"""Unexecuted independent readback of the exact stopped-source census, never package code."""
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import tarfile
import time
import sys

ROOT = Path('/home/animallya96/scratch/capacity-package-metadata-text-census-20261018-v2')
REVIEW = Path('/home/animallya96/scratch/capacity-package-metadata-text-independent-20261018-v2')
CID = '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
CAP = 262144
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
PATHS = ('/usr/local/lib/python3.12/site-packages/pyarrow-25.0.1.dist-info/METADATA',
    '/usr/local/lib/python3.12/site-packages/pyarrow-25.0.1.dist-info/RECORD',
    '/usr/local/lib/python3.12/site-packages/numpy-2.5.3.dist-info/METADATA',
    '/usr/local/lib/python3.12/site-packages/numpy-2.5.3.dist-info/RECORD',
    '/usr/local/lib/python3.12/site-packages/scipy-1.18.1.dist-info/METADATA',
    '/usr/local/lib/python3.12/site-packages/scipy-1.18.1.dist-info/RECORD')
SIZES = (3031, 78313, 6635, 111517, 62353, 201096)
PRIOR = Path('/home/animallya96/scratch/capacity-package-metadata-head-independent-20261018-v1/proof.json')
HEAD_SHA = '4a30076a7e6b530b7e24ffa1990abeb6d7a817974d96ef3d6f8100b1e7e111ab'
BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
BASELINE_INSPECT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')
DIAGNOSTIC = Path('/home/animallya96/scratch/capacity-package-metadata-text-inspect-diagnostic-20261018-v1/proof.json')
DIAGNOSTIC_SHA = '7ec16ed395d9b1d75f542a7001e43aede48462accb066e9ae3005561a91cd85f'


# Bind named and held local copy metadata with lossless physical integer strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Independently read one regular copied observation twice without following path links.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        first = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == first and len(first) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return first, {'sha256': hashlib.sha256(first).hexdigest(), 'bytes': len(first), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Identify complete finite source or wire bytes without executing their contents.
def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# Retain a new bounded observation, fsync its bytes and parent, and verify readback.
def save(name, raw):
    assert type(raw) is bytes and len(raw) <= CAP and Path(name).name == name
    path = REVIEW / name
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    descriptor = os.open(REVIEW, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {'file': name, 'bytes': len(raw), 'sha256': digest(raw)}


# Encode only finite plain metadata within the unchanged ordinary file cap.
def save_json(name, value):
    return save(name, json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n')


# Interrupt the host helper while letting its owned CLI cleanup and receipts run.
def alarm(signum, frame):
    raise TimeoutError('SOURCE_CENSUS_WALL_BOUND')


# Give only the owned Go CLI its required virtual address ceiling without a daemon RAM claim.
def client_limits():
    resource.setrlimit(resource.RLIMIT_AS, (4294967296, 4294967296))
    signal.pthread_sigmask(signal.SIG_UNBLOCK,
        {signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM})


# Bound a read-only Docker response and preserve evidence through bounded owned CLI cleanup.
def command(name, arguments, deadline):
    assert arguments == ('container', 'inspect', CID)
    assert time.monotonic() < deadline
    process, selector = None, selectors.DefaultSelector()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    overflow, stopped, failure, cleanup_failure = {}, None, None, None
    try:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK,
            {signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM})
        try:
            process = subprocess.Popen(DOCKER + arguments, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                preexec_fn=client_limits)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        for channel in buffers:
            pipe = getattr(process, channel)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, channel)
        limit = min(deadline, time.monotonic() + 5)
        while selector.get_map():
            remaining = limit - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('DOCKER_SOURCE_READ_DEADLINE')
            for key, events in selector.select(min(remaining, 0.1)):
                channel = key.data
                raw = os.read(key.fd, min(4096, CAP - len(buffers[channel]) + 1))
                if not raw:
                    selector.unregister(key.fileobj)
                    continue
                available = CAP - len(buffers[channel])
                buffers[channel].extend(raw[:available])
                if len(raw) > available:
                    overflow[channel] = raw[available:].hex()
                    raise RuntimeError('DOCKER_SOURCE_RESPONSE_BOUND')
        process.wait(timeout=max(0.001, limit - time.monotonic()))
    except BaseException as exc:
        failure = type(exc).__name__
        raise
    finally:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK,
            {signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM})
        try:
            try:
                if process is not None and process.poll() is None:
                    stopped = 'TERM'
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        stopped = 'KILL'
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=1)
            except BaseException as exc:
                cleanup_failure = type(exc).__name__
                raise
            finally:
                selector.close()
                if process is not None:
                    process.stdout.close()
                    process.stderr.close()
                outputs = {channel: save(name + '.' + channel, bytes(raw)) for channel, raw in buffers.items()}
                save_json(name + '.exit.json', {'arguments': list(DOCKER + arguments),
                    'pid': None if process is None else str(process.pid),
                    'exit': None if process is None else process.returncode,
                    'owned_CLI_group_stop': stopped, 'failure_class': failure,
                    'cleanup_failure_class': cleanup_failure,
                    'outputs': outputs, 'overflow_first_extra_byte_hex': overflow,
                    'overflow_prefix_is_complete_response': False if overflow else None})
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    assert process.returncode == 0 and not stopped and not buffers['stderr'] and not overflow
    return bytes(buffers['stdout'])


# Independently compare complete inspection fields and full mount records, retaining list order observations.
def inspection(raw, baseline_raw):
    records, originals = json.loads(raw), json.loads(baseline_raw)
    assert len(records) == len(originals) == 1 and digest(baseline_raw) == BASELINE
    item, baseline = records[0], originals[0]
    assert set(item) == set(baseline)
    for key in baseline:
        if key != 'Mounts':
            assert item[key] == baseline[key]
    current, original = item['Mounts'], baseline['Mounts']
    destinations = [mount['Destination'] for mount in current]
    original_destinations = [mount['Destination'] for mount in original]
    assert len(destinations) == len(set(destinations)) == len(original_destinations) == len(set(original_destinations)) == 2
    assert set(destinations) == set(original_destinations)
    assert all(next(mount for mount in current if mount['Destination'] == destination)
        == next(mount for mount in original if mount['Destination'] == destination) for destination in destinations)
    return {'sha256': digest(raw), 'bytes': len(raw), 'raw_bytes_equal': raw == baseline_raw,
        'full_decoded_equal': item == baseline, 'raw_Mounts_list_order_equal': current == original,
        'all_nonMounts_and_complete_uniqueDestination_mount_records_equal': True}


# Check copied source bytes, full terminal receipts and a separately observed stopped inspect.
def main():
    assert os.getuid() == 1000 and __debug__
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077)
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.resolve(strict=True) == ROOT and REVIEW.parent.resolve(strict=True) == REVIEW.parent
    REVIEW.mkdir(mode=0o700, exist_ok=False)
    candidate_raw, candidate_row = read(ROOT / 'candidate.json')
    assert candidate_row['sha256'] == '499766ac3c5ea891f508bdab644956a9ee0d438174f9074aae96aa6848ecbf04'
    candidate = json.loads(candidate_raw)
    assert candidate['schema'] == 'stopped-n2-package-metadata-text-census/2'
    assert candidate['status'] == 'PAIRED_FIXED_PATH_SOURCE_READS_ONLY_REQUIRES_INDEPENDENT_REVIEW'
    assert candidate['container'] == CID and candidate['image'] == IMAGE
    assert candidate['package_import_or_container_start'] is False and candidate['model_RAM_acceptance'] is False
    assert candidate['physical_source_root_identity'] is None and candidate['package_versions_and_native_closure'] is None
    assert [row['container_path'] for row in candidate['sources']] == list(PATHS)
    names = {'candidate.json', 'prerequisites.json', 'prior-head-proof.json', 'baseline-inspect.json', 'prior-failure-diagnostic.json'}
    commands = [('inspect-before', ['container', 'inspect', CID]), ('inspect-after', ['container', 'inspect', CID])]
    for index, path in enumerate(PATHS):
        names.add('source-%02d.metadata.txt' % index)
        for turn in range(2):
            commands.append(('source-%02d-read-%d' % (index, turn), ['container', 'cp', CID + ':' + path, '-']))
    for name, arguments in commands:
        names.update(name + ending for ending in ('.stdout', '.stderr', '.exit.json'))
    assert {path.name for path in ROOT.iterdir()} == names and len(names) == 53
    bodies, inventory = {}, {}
    for name in sorted(names):
        bodies[name], inventory[name] = read(ROOT / name)
    assert bodies['candidate.json'] == candidate_raw and inventory['candidate.json'] == candidate_row
    for name, arguments in commands:
        receipt = json.loads(bodies[name + '.exit.json'])
        assert receipt['arguments'] == ['docker', '--host', 'unix:///var/run/docker.sock'] + arguments
        assert receipt['exit'] == 0 and receipt['owned_CLI_group_stop'] is None
        assert type(receipt['pid']) is str and receipt['pid'].isdecimal() and int(receipt['pid']) > 0
        assert receipt['failure_class'] is None and receipt['cleanup_failure_class'] is None
        assert receipt['overflow_first_extra_byte_hex'] == {} and bodies[name + '.stderr'] == b''
        for channel in ('stdout', 'stderr'):
            expected = receipt['outputs'][channel]
            actual = inventory[name + '.' + channel]
            assert expected == {'file': name + '.' + channel, 'bytes': actual['bytes'], 'sha256': actual['sha256']}
    prior_raw, prior_row = read(PRIOR)
    assert digest(prior_raw) == HEAD_SHA and len(prior_raw) == 23927
    assert bodies['prior-head-proof.json'] == prior_raw
    assert candidate['prior_head_proof'] == {'file': 'prior-head-proof.json', 'bytes': len(prior_raw), 'sha256': HEAD_SHA}
    assert candidate['prior_head_physical'] == prior_row
    prior = json.loads(prior_raw)
    assert [row['container_path'] for row in prior['path_observations']] == list(PATHS)
    assert [row['path_metadata']['stat']['size'] for row in prior['path_observations']] == list(SIZES)
    for index, row in enumerate(candidate['sources']):
        name = 'source-%02d.metadata.txt' % index
        assert row['retained'] == {'file': name, 'bytes': inventory[name]['bytes'], 'sha256': inventory[name]['sha256']}
        bodies[name].decode('utf-8', errors='strict')
        assert len(bodies[name]) == SIZES[index] and len(row['reads']) == 2
        for turn in range(2):
            wire = bodies['source-%02d-read-%d.stdout' % (index, turn)]
            observed = row['reads'][turn]
            assert observed['wire_sha256'] == hashlib.sha256(wire).hexdigest() and observed['wire_bytes'] == len(wire)
            with tarfile.open(fileobj=io.BytesIO(wire), mode='r:') as archive:
                members = archive.getmembers()
                assert len(members) == 1
                member = members[0]
                assert member.name == Path(PATHS[index]).name and member.isfile() and not member.sparse and not member.linkname
                assert member.size == SIZES[index] and not member.issym() and not member.islnk()
                assert 1024 <= len(wire) <= CAP and len(wire) % 512 == 0
                assert observed['archive'] == {'member': member.name, 'size': member.size,
                    'mode': member.mode, 'uid': member.uid, 'gid': member.gid,
                    'pax_headers': member.pax_headers, 'mtime_representation': repr(member.mtime),
                    'identity_scope': 'ARCHIVE_METADATA_NOT_HELD_FD_OR_EXACT_PHYSICAL_NS_PROOF'}
                with archive.extractfile(member) as stream:
                    assert stream.read(CAP + 1) == bodies[name]
                end = member.offset_data + ((member.size + 511) // 512) * 512
                assert end + 1024 <= len(wire) and not any(wire[end:])
    baseline_raw, baseline_row = read(BASELINE_INSPECT)
    diagnostic_raw, diagnostic_row = read(DIAGNOSTIC)
    assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755
    assert digest(diagnostic_raw) == DIAGNOSTIC_SHA and len(diagnostic_raw) == 4767
    assert bodies['baseline-inspect.json'] == baseline_raw and bodies['prior-failure-diagnostic.json'] == diagnostic_raw
    binding = candidate['inspection_binding']
    assert candidate['full_container_inspect_bookends_equal'] is None
    assert binding['baseline'] == {'file': 'baseline-inspect.json', 'bytes': len(baseline_raw), 'sha256': BASELINE}
    assert binding['diagnostic'] == {'file': 'prior-failure-diagnostic.json', 'bytes': len(diagnostic_raw), 'sha256': DIAGNOSTIC_SHA}
    assert binding['baseline_physical'] == baseline_row and binding['diagnostic_physical'] == diagnostic_row
    assert binding['before'] == inspection(bodies['inspect-before.stdout'], baseline_raw)
    assert binding['after'] == inspection(bodies['inspect-after.stdout'], baseline_raw)
    assert binding['raw_before_after_equal'] == (bodies['inspect-before.stdout'] == bodies['inspect-after.stdout'])
    assert binding['full_nonMounts_and_uniqueDestination_mount_bookends_equal'] is True
    diagnostic = json.loads(diagnostic_raw)
    assert diagnostic['all_nonMounts_fields_equal'] is True and diagnostic['complete_uniqueDestination_mount_records_equal'] is True
    assert diagnostic['raw_Mounts_list_order_equal'] is False
    before = json.loads(bodies['inspect-before.stdout'])
    assert len(before) == 1
    assert before[0]['Id'] == CID and before[0]['Image'] == IMAGE
    assert before[0]['State']['Running'] is False and before[0]['State']['Status'] == 'exited'
    assert before[0]['State']['ExitCode'] == 0 and before[0]['State']['OOMKilled'] is False
    assert before[0]['State']['FinishedAt'] == '2026-10-18T09:53:55.975021651Z'
    assert before[0]['State']['Pid'] == 0 and before[0]['State']['Paused'] is False and before[0]['State']['Restarting'] is False
    assert before[0]['HostConfig']['ReadonlyRootfs'] is True and before[0]['Config']['User'] == '1000:1000'
    destinations = [mount['Destination'] for mount in before[0]['Mounts']]
    assert len(destinations) == len(set(destinations)) == 2 and set(destinations) == {'/audit', '/out'}
    for path in PATHS:
        assert all(path != target and not path.startswith(target.rstrip('/') + '/') for target in destinations)
    fresh = command('independent-fresh-inspect', ('container', 'inspect', CID), time.monotonic() + 5)
    fresh_row = read(REVIEW / 'independent-fresh-inspect.stdout')[1]
    fresh_binding = inspection(fresh, baseline_raw)
    for name in sorted(names):
        assert read(ROOT / name) == (bodies[name], inventory[name])
    assert read(PRIOR) == (prior_raw, prior_row)
    assert read(BASELINE_INSPECT) == (baseline_raw, baseline_row)
    assert read(DIAGNOSTIC) == (diagnostic_raw, diagnostic_row)
    proof = {'schema': 'stopped-n2-package-metadata-text-census-independent/2',
        'status': 'VERIFIED_SIX_PAIRED_METADATA_TEXT_COPIES_ONLY_NOT_INSTALLED_VERSION_OR_NATIVE_CLOSURE',
        'candidate_sha256': candidate_row['sha256'], 'source_files': 6, 'full_readback_files': 53,
        'source_bytes': sum(inventory['source-%02d.metadata.txt' % index]['bytes'] for index in range(6)),
        'source_inventory': inventory, 'fresh_inspect': fresh_row, 'cli_exit': 0,
        'package_imports_or_container_start': False, 'native_model_RAM_acceptance': False,
        'container_file_physical_identity': None, 'transitive_package_closure': None,
        'prior_head_proof': prior_row, 'inspection_binding': binding, 'fresh_inspection_binding': fresh_binding}
    raw = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= CAP
    with (REVIEW / 'proof.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(REVIEW / 'proof.json')[0] == raw
    descriptor = os.open(REVIEW, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.fsync(descriptor); os.close(descriptor)
    print(raw.decode(), end='')


# Bound all independent file reads as well as the one fresh stopped inspection.
def run(arguments):
    assert arguments == ['verify-six-metadata-texts']
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        main()
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    run(sys.argv[1:])
