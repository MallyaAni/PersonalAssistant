"""Copy or verify exactly one binary as inert bytes; no package or ELF execution."""
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time

CID = '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
BASELINE_INSPECT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1/inspect-before.stdout')
PRIOR = Path('/home/animallya96/scratch/capacity-native-path-head-independent-20261018-v1/proof.json')
HEAD_SHA = '6f3696b006cb335a06656501446d2976723ec4649117dd33a31cd03c825adaaa'
ROOT = Path('/home/animallya96/scratch/capacity-callback-binary-copy-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/capacity-callback-binary-independent-20261018-v1')
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
CAP = 262144
DECLARATION = {'CSV_end_line': 220, 'RECORD_source_sha256': 'b4b210e29143fee78ff3abd82e2d308554642129deacfcfec4e7e626c2d4fd68', 'actual_path_file_hash_ELF_or_load_observed': False, 'declared_hash': {'algorithm': 'sha256', 'digest_hex': '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'}, 'declared_size_decimal': '216280', 'lexical_absolute_path': '/usr/local/lib/python3.12/site-packages/scipy/_lib/_ccallback_c.cpython-312-aarch64-linux-gnu.so', 'package': 'scipy', 'record_index': 219, 'relative_path': 'scipy/_lib/_ccallback_c.cpython-312-aarch64-linux-gnu.so'}
PATHS = (DECLARATION['lexical_absolute_path'],)
SIZES = (216280,)
BINARY_SHA = DECLARATION['declared_hash']['digest_hex']
CANDIDATE_SHA = '10590bccad71e60b7589a2ef75ff03ed9ea435e26ef6311f57578cc2697506d2'



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



# Independently validate all retained binary bytes, tar members, terminals and complete stopped state.
def main(arguments):
    assert arguments == ['verify-one-callback-binary'] and __debug__ and os.getuid() == 1000
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.resolve(strict=True) == ROOT and REVIEW.parent.resolve(strict=True) == REVIEW.parent
    previous = {s: signal.signal(s, alarm) for s in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        REVIEW.mkdir(mode=0o700, exist_ok=False)
        first, first_row = read(ROOT / 'candidate.json')
        assert digest(first) == CANDIDATE_SHA
        candidate = json.loads(first)
        assert candidate['schema'] == 'stopped-n2-callback-binary-copy/1'
        assert candidate['status'] == 'PAIRED_BINARY_BYTES_REQUIRE_INDEPENDENT_REVIEW'
        assert candidate['container'] == CID and candidate['image'] == IMAGE
        assert candidate['declaration'] == DECLARATION
        assert candidate['binary_interpretation_import_or_execution'] is False
        assert candidate['native_runtime_or_model_RAM_admission'] is None
        commands = [('inspect-before', ['container', 'inspect', CID]), ('inspect-after', ['container', 'inspect', CID])]
        commands += [('binary-read-%d' % i, ['container', 'cp', CID + ':' + PATHS[0], '-']) for i in range(2)]
        names = {'candidate.json', 'prerequisites.json', 'prior-head-proof.json', 'baseline-inspect.json', 'callback.bin'}
        for label, argv in commands:
            names.update(label + suffix for suffix in ('.stdout', '.stderr', '.exit.json'))
        assert len(names) == 17 and {p.name for p in ROOT.iterdir()} == names
        bodies, inventory = {}, {}
        for n in sorted(names):
            bodies[n], inventory[n] = read(ROOT / n)
        assert bodies['candidate.json'] == first and inventory['candidate.json'] == first_row
        for label, argv in commands:
            terminal = json.loads(bodies[label + '.exit.json'])
            assert terminal['arguments'] == list(DOCKER) + argv
            assert terminal['exit'] == 0 and terminal['owned_CLI_group_stop'] is None
            assert terminal['failure_class'] is None and terminal['cleanup_failure_class'] is None
            assert terminal['overflow_first_extra_byte_hex'] == {} and bodies[label + '.stderr'] == b''
            for channel in ('stdout', 'stderr'):
                value = inventory[label + '.' + channel]
                assert terminal['outputs'][channel] == {'file': label + '.' + channel, 'bytes': value['bytes'], 'sha256': value['sha256']}
        binary = bodies['callback.bin']
        assert len(binary) == 216280 and digest(binary) == BINARY_SHA
        assert candidate['retained'] == {'file': 'callback.bin', 'bytes': 216280, 'sha256': BINARY_SHA}
        assert len(candidate['reads']) == 2
        for i in range(2):
            wire, observed = bodies['binary-read-%d.stdout' % i], candidate['reads'][i]
            assert 1024 <= len(wire) <= CAP and len(wire) % 512 == 0
            assert observed['wire_sha256'] == digest(wire) and observed['wire_bytes'] == len(wire)
            with tarfile.open(fileobj=io.BytesIO(wire), mode='r:') as archive:
                members = archive.getmembers()
                assert len(members) == 1
                member = members[0]
                assert member.name == PATHS[0].rsplit('/', 1)[1] and member.type in (b'0', b'\0')
                assert member.size == 216280 and member.linkname == '' and member.sparse is None
                assert all(not key.startswith('GNU.sparse.') for key in member.pax_headers)
                with archive.extractfile(member) as stream:
                    assert stream.read(CAP + 1) == binary
                end = member.offset_data + ((216280 + 511) // 512) * 512
                assert end + 1024 <= len(wire) and not any(wire[end:])
                assert observed['archive'] == {'member': member.name, 'size': member.size,
                    'mode': member.mode, 'uid': member.uid, 'gid': member.gid,
                    'pax_headers': member.pax_headers, 'mtime_representation': repr(member.mtime),
                    'identity_scope': 'ARCHIVE_METADATA_NOT_CONTAINER_SOURCE_HELD_FD_OR_IMAGE_ATTESTATION'}
        prior_raw, prior_row = read(PRIOR)
        baseline_raw, baseline_row = read(BASELINE_INSPECT)
        assert digest(prior_raw) == HEAD_SHA and len(prior_raw) == 86271 and bodies['prior-head-proof.json'] == prior_raw
        assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755 and bodies['baseline-inspect.json'] == baseline_raw
        assert candidate['prior_head_proof'] == {'file': 'prior-head-proof.json', 'bytes': 86271, 'sha256': HEAD_SHA}
        assert candidate['prior_head_physical'] == prior_row
        selected, = [r for r in json.loads(prior_raw)['path_observations'] if r['container_path'] == PATHS[0]]
        assert selected['declaration'] == DECLARATION and selected['path_metadata']['stat']['size'] == 216280
        binding = candidate['inspection_binding']
        assert binding['baseline'] == {'file': 'baseline-inspect.json', 'bytes': 9755, 'sha256': BASELINE}
        assert binding['baseline_physical'] == baseline_row
        assert binding['before'] == inspection(bodies['inspect-before.stdout'], baseline_raw)
        assert binding['after'] == inspection(bodies['inspect-after.stdout'], baseline_raw)
        assert binding['raw_before_after_equal'] == (bodies['inspect-before.stdout'] == bodies['inspect-after.stdout'])
        prerequisites = json.loads(bodies['prerequisites.json'])
        assert prerequisites['hostname'] == 'animallya-spark1' and prerequisites['uid'] == 1000
        assert prerequisites['reservation'] is False and int(prerequisites['MemAvailable_bytes']) >= 2147483648
        assert int(prerequisites['scratch_available_bytes']) >= 1073741824 and int(prerequisites['scratch_available_inodes']) >= 512
        fresh = command('inspect-fresh', ('container', 'inspect', CID), time.monotonic() + 5)
        fresh_binding = inspection(fresh, baseline_raw)
        for n in sorted(names):
            assert read(ROOT / n) == (bodies[n], inventory[n])
        assert read(PRIOR) == (prior_raw, prior_row) and read(BASELINE_INSPECT) == (baseline_raw, baseline_row)
        saved = save_json('proof.json', {'schema': 'stopped-n2-callback-binary-independent/1',
            'status': 'VERIFIED_ONE_BINARY_BYTE_COPY_RECORD_SHA_ONLY_NOT_ELF_OR_RUNTIME',
            'candidate_sha256': CANDIDATE_SHA, 'declaration': DECLARATION, 'source_bytes': 216280,
            'full_readback_files': 17, 'source_inventory': inventory, 'prior_head_physical': prior_row,
            'original_baseline_physical': baseline_row, 'inspection_binding': binding, 'fresh_inspection_binding': fresh_binding,
            'binary_hash_matches_RECORD': True, 'archive_wire_bytes': [len(bodies['binary-read-%d.stdout' % i]) for i in range(2)],
            'ELF_parse_import_native_load_or_body_execution': False, 'native_model_RAM_admission': None,
            'container_source_held_FD_or_every_file_image_attestation': False})
        raw = read(REVIEW / 'proof.json')[0]
        assert digest(raw) == saved['sha256']
        print(raw.decode(), end='')
    finally:
        signal.alarm(0)
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == '__main__':
    main(sys.argv[1:])
