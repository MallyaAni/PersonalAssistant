"""Independently verify retained HEAD observations without repeating path requests."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import quote

ROOT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1')
REVIEW = Path('/home/animallya96/scratch/capacity-package-metadata-head-independent-20261018-v1')
CID = '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
CAP = 262144
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
PATHS = tuple('/usr/local/lib/python3.12/site-packages/' + relative for relative in (
    'pyarrow-25.0.1.dist-info/METADATA', 'pyarrow-25.0.1.dist-info/RECORD',
    'numpy-2.5.3.dist-info/METADATA', 'numpy-2.5.3.dist-info/RECORD',
    'scipy-1.18.1.dist-info/METADATA', 'scipy-1.18.1.dist-info/RECORD'))
CANDIDATE_SHA = '42d6171789b08b0b2b9c305a6fe564829982befd752b1779813de4edc4ac64af'



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


# Independently reconstruct strict path metadata from one stored header-only HTTP response.
def decode(raw, path):
    pieces = raw.split(b'\r\n\r\n')
    assert len(pieces) == 2 and pieces[1] == b'' and 4 <= len(raw) <= CAP
    lines = pieces[0].decode('ascii').split('\r\n')
    protocol, code, reason = lines[0].split(' ', 2)
    assert protocol == 'HTTP/1.1' and code in ('200', '404')
    pairs = [line.split(':', 1) for line in lines[1:]]
    assert all(len(pair) == 2 and pair[0] and pair[0] == pair[0].strip()
        and all(33 <= ord(c) <= 126 for c in pair[0]) for pair in pairs)
    lowered = [pair[0].lower() for pair in pairs]
    assert len(set(lowered)) == len(pairs) and 'transfer-encoding' not in lowered
    headers = dict((key.lower(), value.strip()) for key, value in pairs)
    if code == '404':
        assert 'x-docker-container-path-stat' not in headers
        return {'status': 'REFUSED_MISSING_PATH', 'http_status': 404,
            'content_read_authorized': False, 'stat': None}
    encoded = headers['x-docker-container-path-stat']
    value_raw = base64.b64decode(encoded, validate=True)
    assert base64.b64encode(value_raw).decode() == encoded
    value = json.loads(value_raw)
    assert set(value) == {'name', 'size', 'mode', 'mtime', 'linkTarget'}
    assert value['name'] == path.rsplit('/', 1)[1] and value['linkTarget'] == ''
    assert type(value['size']) is int and value['size'] > 0
    assert type(value['mode']) is int and 0 <= value['mode'] <= 4095
    assert isinstance(value['mtime'], str) and 1 <= len(value['mtime']) <= 128
    return {'status': 'DAEMON_REPORTED_REGULAR_PATH_ONLY', 'http_status': 200, 'stat': value,
        'content_bytes_within_ordinary_cap': value['size'] <= CAP,
        'content_read_authorized': False,
        'container_held_FD_identity_or_baked_image_attestation': False}


# Authenticate every retained request, wire, receipt and exact stopped-container bookend independently.
def main(arguments):
    assert arguments == ['verify-package-metadata-head'] and __debug__ and os.getuid() == 1000
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077); os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.resolve(strict=True) == ROOT and REVIEW.parent.resolve(strict=True) == REVIEW.parent
    candidate_raw, first_candidate = read(ROOT / 'candidate.json')
    assert digest(candidate_raw) == CANDIDATE_SHA
    candidate = json.loads(candidate_raw)
    assert candidate['schema'] == 'stopped-n2-package-metadata-head/1'
    assert candidate['status'] == 'PAIRED_PATH_METADATA_ONLY_REQUIRES_INDEPENDENT_REVIEW'
    assert candidate['container'] == CID and candidate['image'] == IMAGE
    assert candidate['full_inspect_baseline_sha256'] == BASELINE
    assert candidate['package_content_read'] is False and candidate['installed_distribution_version_attested'] is False
    assert candidate['native_package_thread_model_RAM_closure'] is None
    assert candidate['container_start_create_exec_load'] is False and candidate['content_read_authorized'] is False
    assert [row['container_path'] for row in candidate['paths']] == list(PATHS)
    names = {'candidate.json', 'prerequisites.json'}
    for label in ('inspect-before', 'inspect-after'):
        names.update(label + suffix for suffix in ('.stdout', '.stderr', '.exit.json'))
    for index in range(6):
        for turn in range(2):
            names.update('path-%02d-read-%d' % (index, turn) + suffix
                for suffix in ('.request', '.response', '.receipt.json'))
    assert len(names) == 44 and {p.name for p in ROOT.iterdir()} == names
    bodies, inventory = {}, {}
    for name in sorted(names):
        bodies[name], inventory[name] = read(ROOT / name)
    assert bodies['candidate.json'] == candidate_raw and inventory['candidate.json'] == first_candidate
    for label in ('inspect-before', 'inspect-after'):
        receipt = json.loads(bodies[label + '.exit.json'])
        assert receipt['arguments'] == list(DOCKER) + ['container', 'inspect', CID]
        assert receipt['exit'] == 0 and receipt['owned_CLI_group_stop'] is None
        assert receipt['failure_class'] is None and receipt['cleanup_failure_class'] is None
        assert receipt['overflow_first_extra_byte_hex'] == {} and bodies[label + '.stderr'] == b''
        assert digest(bodies[label + '.stdout']) == BASELINE
        for channel in ('stdout', 'stderr'):
            expected = receipt['outputs'][channel]
            assert expected == {'file': label + '.' + channel,
                'bytes': len(bodies[label + '.' + channel]), 'sha256': digest(bodies[label + '.' + channel])}
    observations = []
    for index, path in enumerate(PATHS):
        expected_request = ('HEAD /containers/' + CID + '/archive?path=' + quote(path, safe='')
            + ' HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n').encode('ascii')
        decoded = []
        assert len(candidate['paths'][index]['reads']) == 2
        for turn in range(2):
            label = 'path-%02d-read-%d' % (index, turn)
            assert bodies[label + '.request'] == expected_request
            receipt = json.loads(bodies[label + '.receipt.json'])
            assert receipt['failure_class'] is None and receipt['overflow_first_extra_byte_hex'] is None
            assert receipt['socket'] == '/var/run/docker.sock' and receipt['method'] == 'HEAD'
            assert receipt['container_path'] == path and receipt['response_body_requested'] is False
            assert type(receipt['observed_at_ns']) is str and receipt['observed_at_ns'].isdecimal()
            row = candidate['paths'][index]['reads'][turn]
            for key, suffix in (('request', '.request'), ('response', '.response')):
                actual = {'file': label + suffix, 'bytes': len(bodies[label + suffix]),
                    'sha256': digest(bodies[label + suffix])}
                assert receipt[key] == row[key] == actual
            result = decode(bodies[label + '.response'], path)
            assert row['path_metadata'] == result
            decoded.append(result)
        assert decoded[0] == decoded[1]
        observations.append({'container_path': path, 'path_metadata': decoded[0]})
    prerequisites = json.loads(bodies['prerequisites.json'])
    assert prerequisites['hostname'] == 'animallya-spark1' and prerequisites['uid'] == 1000
    assert prerequisites['source_paths'] == list(PATHS) and prerequisites['reservation'] is False
    assert int(prerequisites['MemAvailable_bytes']) >= 2147483648
    assert int(prerequisites['scratch_available_bytes']) >= 1073741824
    assert int(prerequisites['scratch_available_inodes']) >= 512
    REVIEW.mkdir(mode=0o700, exist_ok=False)
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(10)
    try:
        fresh = command('inspect-fresh', ('container', 'inspect', CID), time.monotonic() + 5)
        assert digest(fresh) == BASELINE and fresh == bodies['inspect-before.stdout'] == bodies['inspect-after.stdout']
        for name in sorted(names):
            raw, row = read(ROOT / name)
            assert raw == bodies[name] and row == inventory[name]
        proof = {'schema': 'stopped-n2-package-metadata-head-independent/1',
            'status': 'VERIFIED_RETAINED_PAIRED_DAEMON_PATH_METADATA_ONLY',
            'candidate_sha256': CANDIDATE_SHA, 'inventory': inventory, 'files': 44,
            'path_observations': observations, 'fresh_stopped_inspect_sha256': digest(fresh),
            'package_content_read_or_path_HEAD_replay': False,
            'installed_distribution_native_thread_model_RAM_admission': None,
            'container_source_held_FD_or_baked_image_attestation': False}
        saved = save_json('proof.json', proof)
        raw, row = read(REVIEW / 'proof.json')
        assert digest(raw) == saved['sha256'] and len(raw) == saved['bytes']
        print(raw.decode(), end='')
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


# Bound the complete independent readback, including all pre-inspection file reads.
def run(arguments):
    previous = {sig: signal.signal(sig, alarm) for sig in (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)}
    signal.alarm(30)
    try:
        main(arguments)
    finally:
        signal.alarm(0)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    run(sys.argv[1:])
