"""Unexecuted bounded source census for one exact stopped N2 native-probe container."""
import hashlib
import io
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import socket
import subprocess
import sys
import tarfile
import time

CID = '803718a62e3cbd1f6070abab25a58e1fbc0ee5d04b5444f57c817d7e47b8bf57'
IMAGE = 'sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237'
ROOT = Path('/home/animallya96/scratch/capacity-native-package-text-census-20261018-v1')
DOCKER = ('docker', '--host', 'unix:///var/run/docker.sock')
CAP = 262144
PATHS = ('/usr/local/lib/python3.12/site-packages/pyarrow/_generated_version.py', '/usr/local/lib/python3.12/site-packages/pyarrow/ipc.py', '/usr/local/lib/python3.12/site-packages/pyarrow/types.py', '/usr/local/lib/python3.12/site-packages/pyarrow/util.py', '/usr/local/lib/python3.12/site-packages/pyarrow/compute.py', '/usr/local/lib/python3.12/site-packages/numpy/version.py', '/usr/local/lib/python3.12/site-packages/numpy/_distributor_init.py', '/usr/local/lib/python3.12/site-packages/numpy/_core/__init__.py', '/usr/local/lib/python3.12/site-packages/scipy/version.py', '/usr/local/lib/python3.12/site-packages/scipy/_distributor_init.py', '/usr/local/lib/python3.12/site-packages/scipy/_lib/_ccallback.py', '/usr/local/lib/python3.12/site-packages/sklearn/_config.py', '/usr/local/lib/python3.12/site-packages/sklearn/_distributor_init.py', '/usr/local/lib/python3.12/site-packages/sklearn/base.py', '/usr/local/lib/python3.12/site-packages/sklearn/utils/_show_versions.py')
KNOWN = {}


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


# Decode exactly one regular source member in memory without extracting archive paths.
def source_member(raw, path):
    assert 1024 <= len(raw) <= CAP and len(raw) % 512 == 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        members = archive.getmembers()
        assert len(members) == 1
        member = members[0]
        assert member.name == Path(path).name and member.isfile()
        assert not member.issym() and not member.islnk() and not member.sparse
        assert 0 < member.size <= CAP and not member.linkname
        stream = archive.extractfile(member)
        assert stream is not None
        with stream:
            body = stream.read(CAP + 1)
        assert len(body) == member.size
        end = member.offset_data + ((member.size + 511) // 512) * 512
        assert end + 1024 <= len(raw) and not any(raw[end:])
        body.decode('utf-8', errors='strict')
        metadata = {'member': member.name, 'size': member.size, 'mode': member.mode,
            'uid': member.uid, 'gid': member.gid, 'pax_headers': member.pax_headers,
            'mtime_representation': repr(member.mtime),
            'identity_scope': 'ARCHIVE_METADATA_NOT_HELD_FD_OR_EXACT_PHYSICAL_NS_PROOF'}
    if path in KNOWN:
        assert digest(body) == KNOWN[path]
    return body, metadata


# Propose exact source reads only; collection requires a separately reviewed concrete invocation.
def main(arguments):
    assert arguments == ['collect-new-native-package-texts']
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
        before = inspect_source(command('inspect-before', ('container', 'inspect', CID), deadline))
        sources = []
        for index, path in enumerate(PATHS):
            observations, bodies = [], []
            for turn in range(2):
                wire = command('source-%02d-read-%d' % (index, turn),
                    ('container', 'cp', CID + ':' + path, '-'), deadline)
                body, metadata = source_member(wire, path)
                bodies.append(body)
                observations.append({'wire_sha256': digest(wire), 'wire_bytes': len(wire), 'archive': metadata})
            assert bodies[0] == bodies[1]
            saved = save('source-%02d.py.txt' % index, bodies[0])
            sources.append({'container_path': path, 'retained': saved, 'reads': observations})
        after = inspect_source(command('inspect-after', ('container', 'inspect', CID), deadline))
        assert before == after
        saved = save_json('candidate.json', {'schema': 'stopped-n2-native-package-text-census/1',
            'status': 'PAIRED_FIXED_PATH_SOURCE_READS_ONLY_REQUIRES_INDEPENDENT_REVIEW',
            'container': CID, 'image': IMAGE, 'sources': sources,
            'observed_at_ns': str(time.time_ns()), 'full_container_inspect_bookends_equal': True,
            'physical_source_root_identity': None, 'package_versions_and_native_closure': None,
            'package_import_or_container_start': False, 'model_RAM_acceptance': False})
        print(json.dumps(saved, sort_keys=True), flush=True)
    finally:
        signal.alarm(0)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    main(sys.argv[1:])
