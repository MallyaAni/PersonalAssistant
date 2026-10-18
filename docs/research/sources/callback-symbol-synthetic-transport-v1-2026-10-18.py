"""New pinned-key source-only staging or one separately reviewed SYNTHETIC63 invocation."""
import base64
import hashlib
import gzip
import sys
import json
import os
from pathlib import Path
import resource
import shlex
import signal
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
LOCAL = Path('/tmp/callback-symbol-synthetic-' + sys.argv[1] + '-transport-20261018-v1')
TRUSTED = Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
KEYS = b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s\n192.168.100.2 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBUse1bIT4RgPgnmirFkc+tr3tcBTKsLCJpQkbZS9QGm\n'
PINS = {'parse-callback-symbol-data-v1-2026-10-18.py': '6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11', 'fold-callback-symbol-data-v1-2026-10-18.py': 'a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127', 'check-callback-symbol-data-v1-2026-10-18.py': '847127b3a70b7522645e8901c881cb135ca2da5850400c9a282647096a9cd76d', 'run-callback-symbol-checks-v1-2026-10-18.py': '5bbae0ddefe3fe32ce83e163e58d72ea1b5f99d55d682149af35a42f5b6d3f0f'}
BOOTSTRAP = '"""Bounded source staging or one separately reviewed SYNTHETIC63 owner invocation."""\nimport base64\nimport hashlib\nimport json\nimport os\nfrom pathlib import Path\nimport resource\nimport signal\nimport socket\nimport stat\nimport sys\nimport zlib\n\nTOOLS = Path(\'/home/animallya96/scratch/callback-symbol-synthetic-tools-20261018-v1\')\nRUN = Path(\'/home/animallya96/scratch/callback-symbol-synthetic-run-20261018-v1\')\nPINS = {\n    \'parse-callback-symbol-data-v1-2026-10-18.py\': (\'6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11\', 13496),\n    \'fold-callback-symbol-data-v1-2026-10-18.py\': (\'a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127\', 14287),\n    \'check-callback-symbol-data-v1-2026-10-18.py\': (\'847127b3a70b7522645e8901c881cb135ca2da5850400c9a282647096a9cd76d\', 17574),\n    \'run-callback-symbol-checks-v1-2026-10-18.py\': (\'5bbae0ddefe3fe32ce83e163e58d72ea1b5f99d55d682149af35a42f5b6d3f0f\', 9318),\n}\n\n\n# Retain exact decimal physical fields without a floating point representation.\ndef physical(value):\n    return {key: str(getattr(value, key)) for key in (\'st_dev\', \'st_ino\', \'st_mode\',\n        \'st_uid\', \'st_nlink\', \'st_size\', \'st_blocks\', \'st_mtime_ns\', \'st_ctime_ns\')}\n\n\n# Bind two full held reads to the same named regular source or result file.\ndef read(path):\n    assert path.resolve(strict=True) == path\n    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)\n    try:\n        before = os.fstat(descriptor)\n        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1\n        assert 0 <= before.st_size <= 262144\n        raw = os.read(descriptor, 262145)\n        os.lseek(descriptor, 0, os.SEEK_SET)\n        assert os.read(descriptor, 262145) == raw and len(raw) == before.st_size\n        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))\n        return raw, {\'bytes\': len(raw), \'sha256\': hashlib.sha256(raw).hexdigest(), \'physical\': physical(before)}\n    finally:\n        os.close(descriptor)\n\n\n# Sync a finite new root and its resolved parent after exclusive file persistence.\ndef sync(root):\n    for directory in (root, root.resolve(strict=True).parent):\n        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)\n        try:\n            os.fsync(descriptor)\n        finally:\n            os.close(descriptor)\n\n\n# Gate staging or execution on fresh host headroom without claiming a reservation.\ndef resources():\n    available = None\n    for line in Path(\'/proc/meminfo\').read_text().splitlines():\n        fields = line.split()\n        if fields and fields[0] == \'MemAvailable:\':\n            assert len(fields) == 3 and fields[2] == \'kB\'\n            available = int(fields[1]) * 1024\n    assert available is not None and available >= 2147483648\n    filesystems = {}\n    for directory in (TOOLS.parent, Path(\'/tmp\')):\n        value = os.statvfs(directory)\n        free = value.f_bavail * value.f_frsize\n        assert free >= 33554432 and value.f_favail >= 128\n        filesystems[str(directory)] = {\'available_bytes\': str(free), \'available_inodes\': str(value.f_favail)}\n    return {\'MemAvailable_bytes\': str(available), \'filesystems\': filesystems, \'reservation\': False}\n\n\n# Authenticate a finite compressed source envelope and stage or run exactly once by explicit phase.\ndef main():\n    assert __debug__ and sys.platform == \'linux\' and os.getuid() == 1000\n    assert socket.gethostname() == \'animallya-spark1\'\n    assert len(sys.argv) == 3 and sys.argv[1] in (\'stage\', \'run\')\n    phase, stage_sha = sys.argv[1:]\n    assert (phase == \'stage\' and stage_sha == \'NONE\') or (phase == \'run\' and len(stage_sha) == 64 and all(c in \'0123456789abcdef\' for c in stage_sha))\n    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))\n    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))\n    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))\n    signal.alarm(30)\n    os.umask(0o077)\n    raw = sys.stdin.buffer.read(65537)\n    assert len(raw) <= 65536\n    packet = json.loads(raw)\n    assert type(packet) is dict and set(packet) == set(PINS)\n    sources = {}\n    for name, (digest, size) in PINS.items():\n        compressed = base64.b64decode(packet[name], validate=True)\n        assert len(compressed) <= 262144 and size <= 262144\n        decoder = zlib.decompressobj(31)\n        body = decoder.decompress(compressed, size + 1)\n        assert len(body) == size and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail\n        assert hashlib.sha256(body).hexdigest() == digest\n        sources[name] = body\n    assert TOOLS.parent.resolve(strict=True) == TOOLS.parent\n    assert not os.path.lexists(RUN)\n    headroom = resources()\n    inventory = {}\n    if phase == \'stage\':\n        assert not os.path.lexists(TOOLS)\n        TOOLS.mkdir(mode=0o700, exist_ok=False)\n        for name, body in sources.items():\n            with (TOOLS / name).open(\'xb\') as output:\n                output.write(body)\n                output.flush()\n                os.fsync(output.fileno())\n            retained, row = read(TOOLS / name)\n            assert retained == body\n            inventory[name] = row\n        proof = {\'schema\': \'callback-symbol-synthetic-stage/1\', \'scope\': \'SOURCE_ONLY_ALL63_UNRUN\',\n            \'inventory\': inventory, \'resources\': headroom, \'uid\': os.getuid(), \'hostname\': socket.gethostname(),\n            \'python\': sys.version, \'wire_bytes\': len(raw), \'wire_sha256\': hashlib.sha256(raw).hexdigest(),\n            \'source_envelope\': \'exact-size-bounded-single-gzip-member/1\', \'run_root_absent\': True}\n        body = json.dumps(proof, sort_keys=True).encode() + b\'\\n\'\n        with (TOOLS / \'stage.json\').open(\'xb\') as output:\n            output.write(body)\n            output.flush()\n            os.fsync(output.fileno())\n        assert read(TOOLS / \'stage.json\')[0] == body\n        sync(TOOLS)\n        print(body.decode(), end=\'\', flush=True)\n    else:\n        stage_body, stage_row = read(TOOLS / \'stage.json\')\n        assert stage_row[\'sha256\'] == stage_sha\n        stage = json.loads(stage_body)\n        assert stage[\'scope\'] == \'SOURCE_ONLY_ALL63_UNRUN\' and set(stage[\'inventory\']) == set(PINS)\n        for name, body in sources.items():\n            retained, row = read(TOOLS / name)\n            assert retained == body and row == stage[\'inventory\'][name]\n            inventory[name] = row\n        admission = {\'schema\': \'callback-symbol-synthetic-scoped-invocation/1\',\n            \'stage_sha256\': stage_sha, \'resources\': headroom, \'source_inventory\': inventory,\n            \'scope\': \'ONE_NEW_SYNTHETIC63_ONLY\', \'host_python_not_N2_runtime\': True}\n        body = json.dumps(admission, sort_keys=True).encode() + b\'\\n\'\n        with (TOOLS / \'invocation.json\').open(\'xb\') as output:\n            output.write(body)\n            output.flush()\n            os.fsync(output.fileno())\n        assert read(TOOLS / \'invocation.json\')[0] == body\n        sync(TOOLS)\n        signal.alarm(0)\n        name = \'run-callback-symbol-checks-v1-2026-10-18.py\'\n        sys.argv = [str(TOOLS / name)]\n        exec(compile(sources[name], str(TOOLS / name), \'exec\', dont_inherit=True),\n            {\'__name__\': \'__main__\', \'__file__\': str(TOOLS / name)})\n        signal.alarm(30)\n        retained = {}\n        for name in (\'stage.json\', \'invocation.json\'):\n            body, row = read(TOOLS / name)\n            retained[\'tools/\' + name] = dict(row, base64=base64.b64encode(body).decode())\n        for path in sorted(RUN.iterdir()):\n            body, row = read(path)\n            retained[\'run/\' + path.name] = dict(row, base64=base64.b64encode(body).decode())\n        for name, row in inventory.items():\n            assert read(TOOLS / name)[1] == row\n        assert read(TOOLS / \'stage.json\')[1] == stage_row\n        result = json.dumps({\'schema\': \'callback-symbol-synthetic-return/1\', \'retained\': retained}, sort_keys=True).encode()\n        assert len(result) <= 262144\n        print(result.decode(), flush=True)\n    signal.alarm(0)\n\n\nif __name__ == \'__main__\':\n    main()\n'


# Apply the existing finite SSH-log bound and remove the short parent registration signal mask.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})


# Enter finite owned SSH cleanup when an ordinary signal interrupts the transport owner.
def interrupt(signum, frame):
    raise InterruptedError('SOURCE_TRANSPORT_INTERRUPTED')


# Authenticate four compressed operational sources for explicit stage or one reviewed Linux synthetic invocation.
def main():
    assert __debug__ and len(sys.argv) == 3 and sys.argv[1] in ('stage', 'run')
    assert TRUSTED.read_bytes() == KEYS
    packet = {}
    for name, digest in PINS.items():
        body = (REPO / 'docs/research/sources' / name).read_bytes()
        assert len(body) <= 262144 and hashlib.sha256(body).hexdigest() == digest
        packet[name] = base64.b64encode(gzip.compress(body, mtime=0)).decode('ascii')
    raw = json.dumps(packet, sort_keys=True).encode()
    assert len(raw) <= 65536
    LOCAL.mkdir(mode=0o700, exist_ok=False)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UserKnownHostsFile=' + str(TRUSTED),
        'animallya96@172.16.8.3', shlex.join(['python3', '-I', '-S', '-B', '-c', BOOTSTRAP, *sys.argv[1:]])]
    watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous = {signum: signal.signal(signum, interrupt) for signum in watched}
    process, stopped, failure = None, None, None
    stdout, stderr = (LOCAL / 'stdout').open('xb'), (LOCAL / 'stderr').open('xb')
    try:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout,
                stderr=stderr, preexec_fn=limits, start_new_session=True)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        process.communicate(input=raw, timeout=70)
    except BaseException as exc:
        failure = type(exc).__name__
        raise
    finally:
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
        cleanup_failure = None
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
                if process is not None and process.stdin is not None:
                    process.stdin.close()
                for stream in (stdout, stderr):
                    stream.flush()
                    os.fsync(stream.fileno())
                    stream.close()
                receipt = {'pid': None if process is None else str(process.pid),
                    'exit': None if process is None else process.returncode, 'owned_SSH_group_stop': stopped,
                    'failure_class': failure, 'cleanup_failure_class': cleanup_failure,
                    'source_sha256': PINS, 'command': command,
                    'remote_quiescence_inferred_from_SSH_exit': False}
                body = json.dumps(receipt, sort_keys=True, indent=2).encode() + b'\n'
                assert len(body) <= 262144
                with (LOCAL / 'exit.json').open('xb') as stream:
                    stream.write(body); stream.flush(); os.fsync(stream.fileno())
                for directory in (LOCAL, LOCAL.resolve().parent):
                    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    os.fsync(descriptor); os.close(descriptor)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    assert process.returncode == 0 and stopped is None and (LOCAL / 'stderr').stat().st_size == 0
    print((LOCAL / 'stdout').read_text(), end='')


if __name__ == '__main__':
    main()
