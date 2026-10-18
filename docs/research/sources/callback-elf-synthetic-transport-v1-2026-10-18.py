"""One new pinned-key Linux invocation of synthetic-only ELF control checks."""
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import signal
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
LOCAL = Path('/tmp/callback-elf-synthetic-transport-20261018-v1')
TRUSTED = Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
KEYS = b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s\n192.168.100.2 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBUse1bIT4RgPgnmirFkc+tr3tcBTKsLCJpQkbZS9QGm\n'
PINS = {
    'parse-callback-elf-data-v1-2026-10-18.py': 'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf',
    'fold-callback-elf-data-v1-2026-10-18.py': 'f302196006bc47e3dd7c1a31aa9477d5119e6c18ac0cad015aa5efb302a34dc1',
    'check-callback-elf-data-v1-2026-10-18.py': 'e4b2ace819e5a09f26bad354b69f9faa5d474601fd78f69af417a00b514fcb22',
    'run-callback-elf-checks-v1-2026-10-18.py': '1ccc1797c6ae95f589c375a5e093495620b7a01f5ed3c24ed3e56e278437ce2c',
}
BOOTSTRAP = """import base64,hashlib,json,os,pathlib,resource,signal,socket,sys
assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1' and sys.platform=='linux' and not sys.flags.optimize
resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))
resource.setrlimit(resource.RLIMIT_CPU,(20,20))
resource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144))
signal.alarm(30)
os.umask(0o077)
raw=sys.stdin.buffer.read(65537)
assert len(raw)<=65536
packet=json.loads(raw)
expected={
'parse-callback-elf-data-v1-2026-10-18.py':'e5c8040315f3b471a4d35d2c90a82778a78954659d4b66e494d5b18abdf9edaf',
'fold-callback-elf-data-v1-2026-10-18.py':'f302196006bc47e3dd7c1a31aa9477d5119e6c18ac0cad015aa5efb302a34dc1',
'check-callback-elf-data-v1-2026-10-18.py':'e4b2ace819e5a09f26bad354b69f9faa5d474601fd78f69af417a00b514fcb22',
'run-callback-elf-checks-v1-2026-10-18.py':'1ccc1797c6ae95f589c375a5e093495620b7a01f5ed3c24ed3e56e278437ce2c'}
assert type(packet)is dict and set(packet)==set(expected)
sources={}
for name,digest in expected.items():
 body=base64.b64decode(packet[name],validate=True)
 assert len(body)<=262144 and hashlib.sha256(body).hexdigest()==digest
 sources[name]=body
root=pathlib.Path('/home/animallya96/scratch/callback-elf-synthetic-tools-20261018-v1')
assert root.parent.resolve(strict=True)==root.parent and not root.exists() and not root.is_symlink()
assert not os.path.lexists('/tmp/callback-elf-synthetic-20261018-v1')
available=None
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
 fields=line.split()
 if fields and fields[0]=='MemAvailable:':
  assert len(fields)==3 and fields[2]=='kB'
  available=int(fields[1])*1024
assert available is not None and available>=2147483648
for directory in (root.parent,pathlib.Path('/tmp')):
 stats=os.statvfs(directory)
 assert stats.f_bavail*stats.f_frsize>=33554432 and stats.f_favail>=128
root.mkdir(mode=0o700,exist_ok=False)
for name,body in sources.items():
 with (root/name).open('xb')as output:
  output.write(body);output.flush();os.fsync(output.fileno())
 assert (root/name).read_bytes()==body
proof=json.dumps({'scope':'NEW_SYNTHETIC_ONLY','source_sha256':expected,'MemAvailable_bytes':str(available),'headroom_is_reservation':False,'python':sys.version,'hostname':socket.gethostname(),'uid':os.getuid()},sort_keys=True).encode()
with (root/'stage.json').open('xb')as output:
 output.write(proof);output.flush();os.fsync(output.fileno())
assert (root/'stage.json').read_bytes()==proof
for directory in (root,root.parent):
 fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);os.fsync(fd);os.close(fd)
signal.alarm(0)
path=root/'run-callback-elf-checks-v1-2026-10-18.py'
exec(compile(sources[path.name],str(path),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(path)})
retained={}
for label,path in (('stage',root/'stage.json'),('result',pathlib.Path('/tmp/callback-elf-synthetic-20261018-v1/stdout.json')),('owner',pathlib.Path('/tmp/callback-elf-synthetic-20261018-v1/exit.json'))):
 assert path.stat().st_size<=262144
 body=path.read_bytes()
 assert path.read_bytes()==body
 retained[label]={'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'base64':base64.b64encode(body).decode('ascii')}
body=json.dumps({'retained':retained,'scope':'SYNTHETIC_ONLY_NO_PHYSICAL_IDENTITY_FOLD'},sort_keys=True)
assert len(body.encode())<=131072
print(body)
"""


# Apply the existing finite SSH-log bound and remove the short parent registration signal mask.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})


# Enter finite owned SSH cleanup when an ordinary signal interrupts the transport owner.
def interrupt(signum, frame):
    raise InterruptedError('SOURCE_TRANSPORT_INTERRUPTED')


# Authenticate four operational sources and dispatch one synthetic-only Linux attempt without retries.
def main():
    assert __debug__ and TRUSTED.read_bytes() == KEYS
    packet = {}
    for name, digest in PINS.items():
        body = (REPO / 'docs/research/sources' / name).read_bytes()
        assert len(body) <= 262144 and hashlib.sha256(body).hexdigest() == digest
        packet[name] = base64.b64encode(body).decode('ascii')
    raw = json.dumps(packet, sort_keys=True).encode()
    assert len(raw) <= 65536
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
