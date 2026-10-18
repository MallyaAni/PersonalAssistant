"""Observe only six fixed stopped-N2 metadata paths through bounded HEAD requests."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import quote

CID = '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
BASELINE = 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'
ROOT = Path('/home/animallya96/scratch/capacity-package-metadata-head-20261018-v1')
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
CAP = 262144
PATHS = tuple('/usr/local/lib/python3.12/site-packages/' + relative for relative in (
    'pyarrow-25.0.1.dist-info/METADATA', 'pyarrow-25.0.1.dist-info/RECORD',
    'numpy-2.5.3.dist-info/METADATA', 'numpy-2.5.3.dist-info/RECORD',
    'scipy-1.18.1.dist-info/METADATA', 'scipy-1.18.1.dist-info/RECORD'))



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


# Parse one bounded header-only response and expose only strict daemon-reported path metadata.
def path_stat(raw, path):
    assert type(raw) is bytes and 4 <= len(raw) <= CAP and path in PATHS
    head, separator, remainder = raw.partition(b'\r\n\r\n')
    assert separator and not remainder
    lines = head.split(b'\r\n')
    status = lines[0].decode('ascii').split(' ', 2)
    assert len(status) == 3 and status[0] == 'HTTP/1.1' and status[1] in ('200', '404')
    headers = {}
    for line in lines[1:]:
        key, colon, value = line.partition(b':')
        assert colon and key and key == key.strip() and all(33 <= byte <= 126 for byte in key)
        key = key.decode('ascii').lower()
        assert key not in headers
        headers[key] = value.strip().decode('ascii')
    assert 'transfer-encoding' not in headers
    if status[1] == '404':
        assert 'x-docker-container-path-stat' not in headers
        return {'status': 'REFUSED_MISSING_PATH', 'http_status': 404,
            'content_read_authorized': False, 'stat': None}
    encoded = headers['x-docker-container-path-stat']
    decoded = base64.b64decode(encoded, validate=True)
    assert base64.b64encode(decoded).decode('ascii') == encoded and len(decoded) <= CAP
    value = json.loads(decoded)
    assert type(value) is dict and set(value) == {'name', 'size', 'mode', 'mtime', 'linkTarget'}
    assert value['name'] == Path(path).name and value['linkTarget'] == ''
    assert type(value['mode']) is int and 0 <= value['mode'] <= 0o7777
    assert type(value['size']) is int and value['size'] > 0
    assert type(value['mtime']) is str and 0 < len(value['mtime']) <= 128
    return {'status': 'DAEMON_REPORTED_REGULAR_PATH_ONLY', 'http_status': 200, 'stat': value,
        'content_bytes_within_ordinary_cap': value['size'] <= CAP,
        'content_read_authorized': False,
        'container_held_FD_identity_or_baked_image_attestation': False}


# Send one fixed HEAD over the local Docker socket with a cumulative five-second wire deadline.
def observe(name, path, deadline):
    assert path in PATHS and time.monotonic() < deadline
    request = ('HEAD /containers/' + CID + '/archive?path=' + quote(path, safe='')
        + ' HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n').encode('ascii')
    retained_request = save(name + '.request', request)
    raw, failure, overflow = bytearray(), None, None
    limit = min(deadline, time.monotonic() + 5)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(max(0.001, limit - time.monotonic()))
            connection.connect('/var/run/docker.sock')
            connection.settimeout(max(0.001, limit - time.monotonic()))
            connection.sendall(request)
            while True:
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('HEAD_WIRE_DEADLINE')
                connection.settimeout(remaining)
                block = connection.recv(min(4096, CAP - len(raw) + 1))
                if not block:
                    break
                available = CAP - len(raw)
                raw.extend(block[:available])
                if len(block) > available:
                    overflow = block[available:].hex()
                    raise RuntimeError('HEAD_WIRE_BOUND')
        result = path_stat(bytes(raw), path)
    except BaseException as exc:
        failure = type(exc).__name__
        raise
    finally:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK,
            {signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM})
        try:
            response = save(name + '.response', bytes(raw))
            save_json(name + '.receipt.json', {'request': retained_request, 'response': response,
                'failure_class': failure, 'overflow_first_extra_byte_hex': overflow,
                'socket': '/var/run/docker.sock', 'method': 'HEAD', 'container_path': path,
                'observed_at_ns': str(time.time_ns()), 'response_body_requested': False})
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    return {'request': retained_request, 'response': response, 'path_metadata': result}


# Observe paired path headers between exact stopped-container bookends without reading package content.
def main(arguments):
    assert arguments == ['observe-six-metadata-paths']
    assert not sys.flags.optimize and os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1'
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == set()
    os.umask(0o077)
    os.nice(10)
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 4294967296))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (CAP, CAP))
    assert ROOT.parent.resolve(strict=True) == ROOT.parent
    space = os.statvfs(ROOT.parent)
    assert space.f_bavail * space.f_frsize >= 1073741824 and space.f_favail >= 512
    memory_raw = Path('/proc/meminfo').read_bytes()
    assert len(memory_raw) <= CAP
    memory = {line.split(b':', 1)[0]: line.split(b':', 1)[1].split() for line in memory_raw.splitlines()}
    assert memory[b'MemAvailable'][1:] == [b'kB']
    available = int(memory[b'MemAvailable'][0]) * 1024
    assert available >= 2147483648
    ROOT.mkdir(mode=0o700, exist_ok=False)
    watched = (signal.SIGALRM, signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    previous = {signum: signal.signal(signum, alarm) for signum in watched}
    signal.alarm(95)
    try:
        deadline = time.monotonic() + 90
        save_json('prerequisites.json', {'hostname': socket.gethostname(), 'uid': os.getuid(),
            'observed_at_ns': str(time.time_ns()), 'MemAvailable_bytes': str(available),
            'scratch_available_bytes': str(space.f_bavail * space.f_frsize),
            'scratch_available_inodes': str(space.f_favail), 'reservation': False,
            'helper_AS_soft_bytes': 536870912, 'CLI_AS_bytes': 4294967296,
            'daemon_RAM_bound': None, 'source_paths': list(PATHS)})
        before_raw = command('inspect-before', ('container', 'inspect', CID), deadline)
        before = inspect_source(before_raw)
        assert digest(before_raw) == BASELINE
        paths = []
        for index, path in enumerate(PATHS):
            reads = [observe('path-%02d-read-%d' % (index, turn), path, deadline) for turn in range(2)]
            assert reads[0]['path_metadata'] == reads[1]['path_metadata']
            paths.append({'container_path': path, 'reads': reads})
        after_raw = command('inspect-after', ('container', 'inspect', CID), deadline)
        assert inspect_source(after_raw) == before and digest(after_raw) == BASELINE
        saved = save_json('candidate.json', {'schema': 'stopped-n2-package-metadata-head/1',
            'status': 'PAIRED_PATH_METADATA_ONLY_REQUIRES_INDEPENDENT_REVIEW',
            'container': CID, 'image': IMAGE, 'paths': paths,
            'full_inspect_baseline_sha256': BASELINE, 'observed_at_ns': str(time.time_ns()),
            'package_content_read': False, 'installed_distribution_version_attested': False,
            'native_package_thread_model_RAM_closure': None,
            'container_start_create_exec_load': False, 'content_read_authorized': False})
        print(json.dumps(saved, sort_keys=True), flush=True)
    finally:
        signal.alarm(0)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    main(sys.argv[1:])
