"""Separate pinned-key retained synthetic-data observation with no fixture replay."""
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
LOCAL = Path('/tmp/callback-symbol-synthetic-observe-transport-20261018-v1')
TRUSTED = Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
KEYS = b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s\n192.168.100.2 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBUse1bIT4RgPgnmirFkc+tr3tcBTKsLCJpQkbZS9QGm\n'
PINS = {}
BOOTSTRAP = '"""Independently read retained new synthetic controls and results, without rerunning fixtures."""\nimport base64\nimport hashlib\nimport json\nimport os\nfrom pathlib import Path\nimport resource\nimport signal\nimport socket\nimport stat\nimport sys\n\nTOOLS = Path(\'/home/animallya96/scratch/callback-symbol-synthetic-tools-20261018-v1\')\nRUN = Path(\'/home/animallya96/scratch/callback-symbol-synthetic-run-20261018-v1\')\n\n\n# Preserve exact identity, allocation and nanosecond fields as decimal strings.\ndef physical(value):\n    return {key: str(getattr(value, key)) for key in (\'st_dev\', \'st_ino\', \'st_mode\',\n        \'st_uid\', \'st_nlink\', \'st_size\', \'st_blocks\', \'st_mtime_ns\', \'st_ctime_ns\')}\n\n\n# Read complete bounded file bytes twice and bind their held and named physical identities.\ndef read(path):\n    assert path.resolve(strict=True) == path\n    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)\n    try:\n        before = os.fstat(descriptor)\n        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == 1000\n        assert 0 <= before.st_size <= 262144\n        first = os.read(descriptor, 262145)\n        os.lseek(descriptor, 0, os.SEEK_SET)\n        second = os.read(descriptor, 262145)\n        assert first == second and len(first) == before.st_size\n        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))\n        return first, {\'bytes\': len(first), \'sha256\': hashlib.sha256(first).hexdigest(), \'physical\': physical(before)}\n    finally:\n        os.close(descriptor)\n\n\n# Observe every immediate retained control and run file with a later complete source and result bookend.\ndef main():\n    assert __debug__ and sys.platform == \'linux\' and os.getuid() == 1000 and socket.gethostname() == \'animallya-spark1\'\n    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))\n    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))\n    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))\n    signal.alarm(30)\n    assert sys.argv[1:] == [\'observe\', \'NONE\'] and sys.stdin.buffer.read(3) == b\'{}\'\n    files, inventories, total = {}, {}, 0\n    for label, root in ((\'tools\', TOOLS), (\'run\', RUN)):\n        assert root.resolve(strict=True) == root and root.is_dir()\n        names = sorted(p.name for p in root.iterdir())\n        assert 1 <= len(names) <= 16\n        inventories[label] = names\n        for name in names:\n            raw, row = read(root / name)\n            total += len(raw)\n            assert total <= 131072\n            files[label + \'/\' + name] = dict(row, base64=base64.b64encode(raw).decode())\n    for key, row in files.items():\n        label, name = key.split(\'/\', 1)\n        root = TOOLS if label == \'tools\' else RUN\n        raw, current = read(root / name)\n        assert current == {k: v for k, v in row.items() if k != \'base64\'}\n    for label, root in ((\'tools\', TOOLS), (\'run\', RUN)):\n        assert sorted(p.name for p in root.iterdir()) == inventories[label]\n    body = json.dumps({\'schema\': \'callback-symbol-synthetic-independent-observation/1\',\n        \'scope\': \'RETAINED_DATA_ONLY_NO_FIXTURE_OR_DECODER_REPLAY\', \'files\': files,\n        \'inventories\': inventories, \'full_input_bytes\': total, \'python\': sys.version}, sort_keys=True).encode()\n    assert len(body) <= 262144\n    print(body.decode(), flush=True)\n    signal.alarm(0)\n\n\nif __name__ == \'__main__\':\n    main()\n'


# Apply the existing finite SSH-log bound and remove the short parent registration signal mask.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})


# Enter finite owned SSH cleanup when an ordinary signal interrupts the transport owner.
def interrupt(signum, frame):
    raise InterruptedError('SOURCE_TRANSPORT_INTERRUPTED')


# Observe retained source and result data through one finite read-only SSH without fixture execution.
def main():
    assert __debug__ and len(sys.argv) == 3 and sys.argv[1:] == ['observe', 'NONE']
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
