"""Unexecuted one-shot pinned-key transport for stopped-container source reads only."""
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import signal
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
HELPER = REPO / 'docs/research/sources/package-metadata-text-inspect-diagnostic-v1-2026-10-18.py'
HELPER_SHA = '13e43d68900d6dc8db90a92bdebceacbf15134d04b7f18fd6548ba41d850ba88'
LOCAL = Path('/tmp/capacity-package-metadata-text-diagnostic-transport-20261018-v1')
TRUSTED = Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
KEYS = b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s\n192.168.100.2 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBUse1bIT4RgPgnmirFkc+tr3tcBTKsLCJpQkbZS9QGm\n'
BOOTSTRAP = """import hashlib,os,pathlib,socket,sys
assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1' and not sys.flags.optimize
raw=sys.stdin.buffer.read(262145)
assert len(raw)==7360 and hashlib.sha256(raw).hexdigest()=='13e43d68900d6dc8db90a92bdebceacbf15134d04b7f18fd6548ba41d850ba88'
os.umask(0o077)
root=pathlib.Path('/home/animallya96/scratch/capacity-package-metadata-text-diagnostic-tools-20261018-v1')
assert root.parent.resolve(strict=True)==root.parent
root.mkdir(mode=0o700,exist_ok=False)
path=root/'helper.py'
with path.open('xb') as out:
 out.write(raw);out.flush();os.fsync(out.fileno())
assert path.read_bytes()==raw
fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
os.fsync(fd);os.close(fd)
sys.argv=[str(path),'compare-retained-inspections']
exec(compile(raw,str(path),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(path)})
"""


# Bound each owned SSH output file without altering any remote service or daemon limit.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})


# Raise through the transport owner so its bounded SSH cleanup and exit receipt run.
def interrupt(signum, frame):
    raise InterruptedError('SOURCE_TRANSPORT_INTERRUPTED')


# Stage one authenticated helper and perform only its reviewed stopped-source invocation.
def main():
    assert TRUSTED.read_bytes() == KEYS
    raw = HELPER.read_bytes()
    assert len(raw) == 7360 and hashlib.sha256(raw).hexdigest() == HELPER_SHA
    LOCAL.mkdir(mode=0o700, exist_ok=False)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UserKnownHostsFile=' + str(TRUSTED),
        'animallya96@172.16.8.3', shlex.join(['python3', '-I', '-S', '-B', '-c', BOOTSTRAP])]
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
        process.communicate(input=raw, timeout=50)
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
                    'helper_sha256': HELPER_SHA, 'command': command,
                    'remote_quiescence_inferred_from_SSH_exit': False}
                body = json.dumps(receipt, sort_keys=True, indent=2).encode() + b'\n'
                assert len(body) <= 262144
                with (LOCAL / 'exit.json').open('xb') as stream:
                    stream.write(body); stream.flush(); os.fsync(stream.fileno())
                descriptor = os.open(LOCAL, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                os.fsync(descriptor); os.close(descriptor)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    assert process.returncode == 0 and stopped is None and (LOCAL / 'stderr').stat().st_size == 0
    print((LOCAL / 'stdout').read_text(), end='')


if __name__ == '__main__':
    main()
