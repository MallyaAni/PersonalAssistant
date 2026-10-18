'One fixed read-only prerequisite or retained-receipt observation; no decoder execution.'
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
LOCAL = Path('/tmp/callback-symbol-primary-receipts-transport-20261018-v1')
TRUSTED = Path('/tmp/checkpoint-image-hostkeys-20261017-v1')
KEYS = b'172.16.8.3 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINHTL/KivuZJ4KwrNAPy+2RnonvooU7mqwOvqA8anY8s\n192.168.100.2 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBUse1bIT4RgPgnmirFkc+tr3tcBTKsLCJpQkbZS9QGm\n'
PINS = {'analyze-callback-symbol-retained-v1-2026-10-18.py': 'b7eadb0166ed9aa21749c5230f19ce466b2430ca95fca0cc6f61948bac5d65c4', 'parse-callback-symbol-data-v1-2026-10-18.py': '6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11'}
BOOTSTRAP = "import base64,hashlib,json,os,pathlib,resource,signal,socket,stat,sys,time\nassert __debug__ and sys.platform=='linux' and os.getuid()==1000 and socket.gethostname()=='animallya-spark1'\nresource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))\nresource.setrlimit(resource.RLIMIT_CPU,(20,20))\nresource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144))\nsignal.alarm(30)\nraw=sys.stdin.buffer.read(65537)\nassert len(raw)<=65536\npacket=json.loads(raw)\nexpected={'analyze-callback-symbol-retained-v1-2026-10-18.py': 'b7eadb0166ed9aa21749c5230f19ce466b2430ca95fca0cc6f61948bac5d65c4', 'parse-callback-symbol-data-v1-2026-10-18.py': '6fe24522e57910ed2f9136762ea4f910f46fd6a6a91afe4f55c80b5e8462bd11'}\nassert type(packet)is dict and set(packet)==set(expected)\nfor name,sha in expected.items():\n body=base64.b64decode(packet[name],validate=True)\n assert len(body)<=262144 and hashlib.sha256(body).hexdigest()==sha\nphase='primary'\nmode='receipts'\ntools=pathlib.Path('/home/animallya96/scratch/capacity-callback-symbol-'+phase+'-tools-20261018-v1')\noutput=pathlib.Path('/home/animallya96/scratch/capacity-callback-symbol-data-'+('analysis' if phase=='primary' else 'independent')+'-20261018-v1')\nassert tools.parent.resolve(strict=True)==tools.parent and output.parent==tools.parent\n\n# Keep original physical fields exact in the retained observation.\ndef physical(value):\n return {key:str(getattr(value,key))for key in ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_blocks','st_mtime_ns','st_ctime_ns')}\n\n# Read a complete bounded regular file twice and bind held and named physical bookends.\ndef read(path):\n assert path.resolve(strict=True)==path\n fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)\n try:\n  before=os.fstat(fd)\n  assert stat.S_ISREG(before.st_mode)and before.st_uid==1000 and before.st_nlink==1 and 0<=before.st_size<=262144\n  body=os.read(fd,262145);os.lseek(fd,0,os.SEEK_SET)\n  assert os.read(fd,262145)==body and len(body)==before.st_size\n  assert physical(before)==physical(os.fstat(fd))==physical(path.stat(follow_symlinks=False))\n  return body,{'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest(),'physical':physical(before)}\n finally:\n  os.close(fd)\n\nproof={'schema':'callback-symbol-DATA-observation/1','phase':phase,'mode':mode,'hostname':socket.gethostname(),'uid':os.getuid(),'python':sys.version,'observed_time_ns':str(time.time_ns()),'proposed_sources':expected,'wire_bytes':len(raw),'wire_sha256':hashlib.sha256(raw).hexdigest(),'reservation':False,'native_runtime_admission':None}\nif mode=='prerequisite':\n assert not os.path.lexists(tools)and not os.path.lexists(output)\n available=None\n for line in pathlib.Path('/proc/meminfo').read_text().splitlines():\n  fields=line.split()\n  if fields and fields[0]=='MemAvailable:':\n   assert len(fields)==3 and fields[2]=='kB'\n   available=int(fields[1])*1024\n assert available is not None and available>=2147483648\n stats=os.statvfs(tools.parent)\n assert stats.f_bavail*stats.f_frsize>=33554432 and stats.f_favail>=512\n proof.update(MemAvailable_bytes=str(available),scratch_available_bytes=str(stats.f_bavail*stats.f_frsize),scratch_available_inodes=str(stats.f_favail),tools_root_absent=True,output_root_absent=True,remote_files_written=0)\nelse:\n assert mode=='receipts'and tools.resolve(strict=True)==tools and output.resolve(strict=True)==output\n observed={};retained={}\n targets=[(tools/'stage.json',True),(output/('summary.json'if phase=='primary'else'proof.json'),True)]+[(tools/name,False)for name in expected]\n for path,include in targets:\n  body,row=read(path)\n  if path.name in expected:\n   assert row['sha256']==expected[path.name]\n  observed[str(path)]=row\n  if include:\n   retained[str(path)]=dict(row,base64=base64.b64encode(body).decode('ascii'))\n for path,row in observed.items():\n  assert read(pathlib.Path(path))[1]==row\n proof.update(input_inventory=observed,retained=retained,all_file_bookends_equal=True)\nbody=json.dumps(proof,sort_keys=True).encode()+b'\\n'\nassert len(body)<=262144\nprint(body.decode(),end='',flush=True)\nsignal.alarm(0)\n"


# Apply the existing finite SSH-log bound and remove the short parent registration signal mask.
def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})


# Enter finite owned SSH cleanup when an ordinary signal interrupts the transport owner.
def interrupt(signum, frame):
    raise InterruptedError('SOURCE_TRANSPORT_INTERRUPTED')


# Observe only fixed prerequisites or retained receipts through a bounded read-only SSH.
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
