"""ROOT exclusive source transport and one separately admitted metadata attempt."""
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import sys
import types

REPO=pathlib.Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
LOCAL=pathlib.Path('/tmp/n2-metadata-tiny-operations-20261018-v1')
TRANSFER='/home/animallya96/scratch/n2-metadata-tiny-transfer-20261018-v1'
SOURCE='/home/animallya96/scratch/n2-metadata-tiny-source-20261018-v1'
VERIFIER='9e3bcdaecc1ecba1901bb7a7bde55aea2903151a34a81bb6e3b40b8bdfd65441'
STAGE='106ae9cfed1c35993554b18ccaaaaed7f0f5c21091cf6a6325b3f4a83925b3fc'
OWNER='d1a73446f79c26e627ac74c5face0ad480e5f62fd9a360bfccf37442a4b5c434'
CALLER='5b2151c4ea45512f1a4bf08ad7299c03f5647d43dba5bddfbfde34c59821f272'
BOOK='dc785f33272b61c4bb79c5c456cce8728aede1ac8ee69880e47817766221ef0f'

# Authenticate the existing finite pinned-key transport without its old entry point.
def transport():
    path=pathlib.Path('/tmp/n2_guard_packet_owner_20261018_v3.py')
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='f8e6fcb47bff6c2f190295ddd2bd63308b7384a10734b422daed5e07c300c4db'
    module=types.ModuleType('metadata_source_transport')
    module.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
    module.LOCAL=LOCAL
    return module

# Stage the exact prior packet with new stager/verifier bytes and no payload execution.
def stage(module):
    LOCAL.mkdir(mode=0o700,exist_ok=False)
    paths={'stage.py':'original-loader-metadata-tiny-stage-2026-10-18.py','verifier.py':'original-loader-metadata-tiny-verifier-2026-10-18.py'}
    files={name:(REPO/'docs/research/sources'/relative).read_bytes() for name,relative in paths.items()}
    assert {name:module.sha(raw) for name,raw in files.items()}=={'stage.py':STAGE,'verifier.py':VERIFIER}
    packet=pathlib.Path('/tmp/n2-metadata-tiny-packet-20261018-v1/packet.json').read_bytes()
    assert module.sha(packet)=='881af8743066e336c4abf021b9c7a5ded1e8b0bb55d3f1df03aac7f0112d0a3e'
    source="import hashlib,os,pathlib; root=pathlib.Path("+repr(TRANSFER)+"); assert os.getuid()==1000 and root.parent.resolve(strict=True)==root.parent; root.mkdir(mode=0o700,exist_ok=False)\n"
    source+="files="+repr(files)+"\nfor name,raw in files.items():\n p=root/name; f=p.open('xb'); f.write(raw); f.flush(); os.fsync(f.fileno()); f.close(); assert p.read_bytes()==raw\n"
    source+="for p in (root,root.parent):\n fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY); os.fsync(fd); os.close(fd)\n"
    source+="p=root/'stage.py'; raw=p.read_bytes(); assert hashlib.sha256(raw).hexdigest()=="+repr(STAGE)+"; exec(compile(raw,str(p),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(p)})"
    code,raw,error=module.remote('stage',['python3','-I','-S','-B','-c',source],packet)
    assert code==0 and error==b''
    print(raw.decode(),flush=True)

# Run only the new independent readonly prerequisite or terminal fold.
def review(module,route):
    command="import hashlib,pathlib,sys; p=pathlib.Path("+repr(TRANSFER+'/verifier.py')+"); raw=p.read_bytes(); assert hashlib.sha256(raw).hexdigest()=="+repr(VERIFIER)+"; sys.argv=[str(p),"+repr(route)+","+repr(VERIFIER)+"]; exec(compile(raw,str(p),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(p)})"
    code,raw,error=module.remote(route,['python3','-I','-S','-B','-c',command])
    assert code==0 and not error
    print(raw.decode(),flush=True)

# Retrieve bounded exact metadata proof bytes without rerunning its observed test.
def fetch(module,route,path):
    command="import pathlib,sys; p=pathlib.Path("+repr(path)+"); assert p.resolve(strict=True)==p and p.stat().st_size<=262144; raw=p.read_bytes(); assert len(raw)<=262144; sys.stdout.buffer.write(raw)"
    code,raw,error=module.remote(route,['python3','-I','-S','-B','-c',command])
    assert code==0 and not error
    print(json.dumps({'bytes':len(raw),'sha256':module.sha(raw),'local':str(LOCAL/(route+'.stdout'))}),flush=True)

# Stage the reviewed launch source without admitting or executing its runtime route.
def stage_launch(module):
    raw=pathlib.Path('/tmp/n2_metadata_launch_20261018_v1.py').read_bytes()
    pin=module.sha(raw)
    command="import hashlib,os,pathlib,sys; p=pathlib.Path("+repr(TRANSFER+'/launch.py')+"); raw=sys.stdin.buffer.read(262145); assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()=="+repr(pin)+"; f=p.open('xb'); f.write(raw); f.flush(); os.fsync(f.fileno()); f.close(); assert p.read_bytes()==raw; fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY); os.fsync(fd); os.close(fd); print(hashlib.sha256(raw).hexdigest())"
    code,result,error=module.remote('launch-source',['python3','-I','-S','-B','-c',command],raw)
    assert code==0 and not error and result.decode().strip()==pin
    print(pin,flush=True)

# Own a finite180s transport for exactly one reviewed150s launch and preserve its exit.
def launch(module,expected):
    assert module.TRUSTED.read_bytes()==module.KEYS
    raw=pathlib.Path('/tmp/n2_metadata_launch_20261018_v1.py').read_bytes()
    assert module.sha(raw)==expected
    script="import hashlib,pathlib,sys; p=pathlib.Path("+repr(TRANSFER+'/launch.py')+"); raw=p.read_bytes(); assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()=="+repr(expected)+"; sys.argv=[str(p),"+repr(expected)+"]; exec(compile(raw,str(p),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(p)})"
    command=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlgorithms=ssh-ed25519','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','GlobalKnownHostsFile=/dev/null','-o','UserKnownHostsFile='+str(module.TRUSTED),'animallya96@172.16.8.3',shlex.join(['python3','-I','-S','-B','-c',script])]
    stdout=(LOCAL/'launch.stdout').open('xb');stderr=(LOCAL/'launch.stderr').open('xb')
    process=None;stopped=None
    try:
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,preexec_fn=module.limits)
        process.wait(timeout=180)
    finally:
        if process is not None and process.poll() is None:
            stopped='TERM';process.terminate()
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:stopped='KILL';process.kill();process.wait(timeout=1)
        for output in (stdout,stderr):output.flush();os.fsync(output.fileno());output.close()
        module.save(LOCAL/'launch.exit.json',json.dumps({'pid':None if process is None else str(process.pid),'exit':None if process is None else process.returncode,'owned_stop':stopped,'launch_sha256':expected},sort_keys=True).encode())
    print(json.dumps({'exit':process.returncode,'owned_stop':stopped,'stdout':(LOCAL/'launch.stdout').read_text(),'stderr':(LOCAL/'launch.stderr').read_text()},sort_keys=True),flush=True)
    assert process.returncode==0 and stopped is None and (LOCAL/'launch.stderr').read_bytes()==b''

# Dispatch source staging and readonly routes; the runtime route is separately pinned.
def main(arguments):
    module=transport()
    if arguments==['stage']:stage(module)
    elif arguments in (['prerequisites'],['terminal']):review(module,arguments[0])
    elif len(arguments)==3 and arguments[0]=='fetch':fetch(module,arguments[1],arguments[2])
    elif arguments==['stage-launch']:stage_launch(module)
    elif len(arguments)==2 and arguments[0]=='launch':launch(module,arguments[1])
    else:raise SystemExit('NO_ADMITTED_RUNTIME_ROUTE')

if __name__=='__main__':main(sys.argv[1:])
