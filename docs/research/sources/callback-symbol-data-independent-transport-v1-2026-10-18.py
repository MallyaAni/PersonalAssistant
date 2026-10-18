'One reviewed retained-callback symbol/version DATA invocation; no native loading or old gates.'
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
LOCAL = Path('/tmp/callback-symbol-data-independent-transport-20261018-v1')
TRUSTED = Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
KEYS = b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s\n192.168.100.2 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBUse1bIT4RgPgnmirFkc+tr3tcBTKsLCJpQkbZS9QGm\n'
PINS = {'verify-callback-symbol-retained-v1-2026-10-18.py': '7fc2e4d9e79c26293738ebb7fb86bb9906c9c2b82d92338899a2fe40e98175f8', 'fold-callback-symbol-data-v1-2026-10-18.py': 'a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127'}
BOOTSTRAP = "import base64,hashlib,json,os,pathlib,resource,signal,socket,sys\nassert os.getuid()==1000 and socket.gethostname()=='animallya-spark1' and sys.platform=='linux' and not sys.flags.optimize\nresource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))\nresource.setrlimit(resource.RLIMIT_CPU,(20,20))\nresource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144))\nsignal.alarm(30)\nos.umask(0o077)\nraw=sys.stdin.buffer.read(65537)\nassert len(raw)<=65536\npacket=json.loads(raw)\nexpected={'verify-callback-symbol-retained-v1-2026-10-18.py': '7fc2e4d9e79c26293738ebb7fb86bb9906c9c2b82d92338899a2fe40e98175f8', 'fold-callback-symbol-data-v1-2026-10-18.py': 'a526e85d63313fac8a4de11eb31dc34964ad9eaeed6d93a4a78d25cb5b469127'}\nassert type(packet)is dict and set(packet)==set(expected)\nsources={}\nfor name,digest in expected.items():\n body=base64.b64decode(packet[name],validate=True)\n assert len(body)<=262144 and hashlib.sha256(body).hexdigest()==digest\n sources[name]=body\nroot=pathlib.Path('/home/animallya96/scratch/capacity-callback-symbol-independent-tools-20261018-v1')\nassert root.parent.resolve(strict=True)==root.parent and not os.path.lexists(root)\ntarget=pathlib.Path('/home/animallya96/scratch/capacity-callback-symbol-data-independent-20261018-v1')\nassert not os.path.lexists(target)\navailable=None\nfor line in pathlib.Path('/proc/meminfo').read_text().splitlines():\n fields=line.split()\n if fields and fields[0]=='MemAvailable:':\n  assert len(fields)==3 and fields[2]=='kB'\n  available=int(fields[1])*1024\nassert available is not None and available>=2147483648\nstats=os.statvfs(root.parent)\nassert stats.f_bavail*stats.f_frsize>=33554432 and stats.f_favail>=512\nroot.mkdir(mode=0o700,exist_ok=False)\nfor name,body in sources.items():\n with (root/name).open('xb')as output:\n  output.write(body);output.flush();os.fsync(output.fileno())\n assert (root/name).read_bytes()==body\nproof=json.dumps({'scope':'RETAINED_CALLBACK_SYMBOL_DATA_ONLY','phase':'independent','source_sha256':expected,'MemAvailable_bytes':str(available),'scratch_available_bytes':str(stats.f_bavail*stats.f_frsize),'scratch_available_inodes':str(stats.f_favail),'headroom_is_reservation':False,'python':sys.version,'hostname':socket.gethostname(),'uid':os.getuid()},sort_keys=True).encode()\nwith (root/'stage.json').open('xb')as output:\n output.write(proof);output.flush();os.fsync(output.fileno())\nassert (root/'stage.json').read_bytes()==proof\nfor directory in (root,root.parent):\n fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);os.fsync(fd);os.close(fd)\nprint(proof.decode(),flush=True)\nsignal.alarm(0)\npath=root/'verify-callback-symbol-retained-v1-2026-10-18.py'\nexec(compile(sources[path.name],str(path),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(path)})\n"


# Apply the existing finite SSH-log bound and remove the short parent registration signal mask.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})


# Enter finite owned SSH cleanup when an ordinary signal interrupts the transport owner.
def interrupt(signum, frame):
    raise InterruptedError('SOURCE_TRANSPORT_INTERRUPTED')


# Authenticate two reviewed operational sources and dispatch one retained-binary DATA operation.
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
