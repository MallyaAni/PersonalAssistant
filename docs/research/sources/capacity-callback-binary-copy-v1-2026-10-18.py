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



# Identify complete finite source or wire bytes without executing their contents.
def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# Retain a new bounded observation, fsync its bytes and parent, and verify readback.
def save(name, raw):
    assert type(raw) is bytes and len(raw) <= CAP and Path(name).name == name
    path = ROOT / name
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
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
    assert arguments in (('container', 'inspect', CID),) or (
        len(arguments) == 4 and arguments[:2] == ('container', 'cp')
        and arguments[2] in tuple(CID + ':' + path for path in PATHS) and arguments[3] == '-')
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


# Compare every inspect field and complete unique mount records while retaining raw list order separately.
def inspection(raw, baseline_raw):
    item, baseline = inspect_source(raw), inspect_source(baseline_raw)
    assert digest(baseline_raw) == BASELINE
    assert {key: value for key, value in item.items() if key != 'Mounts'} == {key: value for key, value in baseline.items() if key != 'Mounts'}
    current_mounts, baseline_mounts = item['Mounts'], baseline['Mounts']
    assert len({mount['Destination'] for mount in current_mounts}) == len(current_mounts) == 2
    assert len({mount['Destination'] for mount in baseline_mounts}) == len(baseline_mounts) == 2
    assert {mount['Destination']: mount for mount in current_mounts} == {mount['Destination']: mount for mount in baseline_mounts}
    return {'sha256': digest(raw), 'bytes': len(raw), 'raw_bytes_equal': raw == baseline_raw,
        'full_decoded_equal': item == baseline, 'raw_Mounts_list_order_equal': current_mounts == baseline_mounts,
        'all_nonMounts_and_complete_uniqueDestination_mount_records_equal': True}


# Refuse any changed, running, restarted, mounted-over or non-N2 source container.
def inspect_source(raw):
    values = json.loads(raw)
    assert type(values) is list and len(values) == 1
    item = values[0]
    assert item['Id'] == CID and item['Image'] == IMAGE
    state = item['State']
    assert state['Status'] == 'exited' and state['Running'] is False
    assert state['Paused'] is False and state['Restarting'] is False
    assert state['ExitCode'] == 0 and state['OOMKilled'] is False and state['Pid'] == 0
    assert state['FinishedAt'] == '2026-10-18T09:53:55.975021651Z'
    assert item['HostConfig']['ReadonlyRootfs'] is True and item['Config']['User'] == '1000:1000'
    destinations = [mount['Destination'] for mount in item['Mounts']]
    assert len(destinations) == len(set(destinations)) == 2 and set(destinations) == {'/audit', '/out'}
    for path in PATHS:
        assert all(path != target and not path.startswith(target.rstrip('/') + '/') for target in destinations)
    return item



# Validate one plain regular tar member and retain exact binary bytes without filesystem extraction.
def binary_member(raw):
    assert 1024 <= len(raw) <= CAP and len(raw) % 512 == 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        assert len(members) == 1
        member = members[0]
        assert member.name == Path(PATHS[0]).name
        assert member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and member.sparse is None and not member.linkname
        assert not any(key.startswith('GNU.sparse.') for key in member.pax_headers)
        assert member.size == 216280 <= CAP
        with archive.extractfile(member) as stream:
            body = stream.read(CAP + 1)
        assert len(body) == 216280 and digest(body) == BINARY_SHA
        end = member.offset_data + ((member.size + 511) // 512) * 512
        assert end + 1024 <= len(raw) and not any(raw[end:])
        metadata = {'member': member.name, 'size': member.size, 'mode': member.mode,
            'uid': member.uid, 'gid': member.gid, 'pax_headers': member.pax_headers,
            'mtime_representation': repr(member.mtime),
            'identity_scope': 'ARCHIVE_METADATA_NOT_CONTAINER_SOURCE_HELD_FD_OR_IMAGE_ATTESTATION'}
    return body, metadata


# Copy the sole bounded binary twice between complete stopped-container inspection bookends.
def main(arguments):
    assert arguments == ['collect-one-callback-binary'] and __debug__
    assert os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.parent.resolve(strict=True) == ROOT.parent
    space = os.statvfs(ROOT.parent)
    assert space.f_bavail * space.f_frsize >= 1073741824 and space.f_favail >= 512
    memory_raw = Path('/proc/meminfo').read_bytes()
    assert len(memory_raw) <= CAP
    available_fields, = [line.split()[1:] for line in memory_raw.splitlines() if line.startswith(b'MemAvailable:')]
    assert available_fields[1:] == [b'kB']
    available = int(available_fields[0]) * 1024
    assert available >= 2147483648
    ROOT.mkdir(mode=0o700, exist_ok=False)
    previous = {s: signal.signal(s, alarm) for s in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(95)
    try:
        deadline = time.monotonic() + 90
        save_json('prerequisites.json', {'hostname': socket.gethostname(), 'uid': os.getuid(),
            'MemAvailable_bytes': str(available), 'scratch_available_bytes': str(space.f_bavail * space.f_frsize),
            'scratch_available_inodes': str(space.f_favail), 'reservation': False})
        prior_raw, prior_row = read(PRIOR)
        assert digest(prior_raw) == HEAD_SHA and len(prior_raw) == 86271
        prior = json.loads(prior_raw)
        selected, = [r for r in prior['path_observations'] if r['container_path'] == PATHS[0]]
        assert selected['declaration'] == DECLARATION and selected['path_metadata']['http_status'] == 200
        assert selected['path_metadata']['stat']['size'] == 216280 and selected['path_metadata']['stat']['linkTarget'] == ''
        assert prior['status'] == 'VERIFIED_RETAINED_PAIRED_DAEMON_PATH_METADATA_ONLY'
        saved_prior = save('prior-head-proof.json', prior_raw)
        baseline_raw, baseline_row = read(BASELINE_INSPECT)
        assert digest(baseline_raw) == BASELINE and len(baseline_raw) == 9755
        saved_baseline = save('baseline-inspect.json', baseline_raw)
        before_raw = command('inspect-before', ('container', 'inspect', CID), deadline)
        before = inspection(before_raw, baseline_raw)
        bodies, reads = [], []
        for turn in range(2):
            wire = command('binary-read-%d' % turn, ('container', 'cp', CID + ':' + PATHS[0], '-'), deadline)
            body, metadata = binary_member(wire)
            bodies.append(body)
            reads.append({'wire_sha256': digest(wire), 'wire_bytes': len(wire), 'archive': metadata})
        assert bodies[0] == bodies[1]
        retained = save('callback.bin', bodies[0])
        after_raw = command('inspect-after', ('container', 'inspect', CID), deadline)
        after = inspection(after_raw, baseline_raw)
        assert read(PRIOR) == (prior_raw, prior_row) and read(BASELINE_INSPECT) == (baseline_raw, baseline_row)
        pointer = save_json('candidate.json', {'schema': 'stopped-n2-callback-binary-copy/1',
            'status': 'PAIRED_BINARY_BYTES_REQUIRE_INDEPENDENT_REVIEW', 'container': CID, 'image': IMAGE,
            'declaration': DECLARATION, 'retained': retained, 'reads': reads,
            'prior_head_proof': saved_prior, 'prior_head_physical': prior_row,
            'inspection_binding': {'baseline': saved_baseline, 'baseline_physical': baseline_row,
                'before': before, 'after': after, 'raw_before_after_equal': before_raw == after_raw},
            'binary_interpretation_import_or_execution': False, 'native_runtime_or_model_RAM_admission': None})
        print(json.dumps(pointer, sort_keys=True), flush=True)
    finally:
        signal.alarm(0)
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == '__main__':
    main(sys.argv[1:])
