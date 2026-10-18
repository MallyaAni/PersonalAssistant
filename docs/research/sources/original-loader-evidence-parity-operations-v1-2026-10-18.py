"""ROOT pinned-key source transport and separately reviewed finite native/parity calls."""
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import sys
import types

REPO=pathlib.Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
LOCAL=pathlib.Path('/tmp/capacity-evidence-parity-operations-20261018-v1')
TRANSFER='/home/animallya96/scratch/capacity-evidence-parity-transfer-20261018-v1'
PINS={
 'stage.py':('original-loader-evidence-parity-stage-v1-2026-10-18.py','87edc9f50a3a86df08c77c8978cb22d5a809e4cc195fc8b95dd4a96516c64c3f'),
 'verifier.py':('original-loader-evidence-parity-verifier-v1-2026-10-18.py','1b0d23cf5af739fb0e1254cb6bae0b3dd82b10ab0668144e5440ede3fdfbb3bb'),
 'native-audit/bootstrap.py':('original-loader-evidence-native-probe-v1-2026-10-18.py','ac6d0696a658f5da3b219b8eac548831450a9021ec81d4241ee4e01912e4440a'),
 'launch.py':('original-loader-evidence-parity-launch-v1-2026-10-18.py','d1fb58bab1535e0f68815d8a5e790ba3e2511d346bafca05472c53a7f35aff11'),
 'preservation.py':('original-loader-evidence-parity-preservation-v1-2026-10-18.py','928c4af5e3bc23e745ce5e78d76cf2649a74c3f2a19f623625c8494e4f2188ac')}

# Load only the exact old finite transport library and never invoke its old main.
def transport():
    path=pathlib.Path('/tmp/n2_guard_packet_owner_20261018_v3.py');raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='f8e6fcb47bff6c2f190295ddd2bd63308b7384a10734b422daed5e07c300c4db'
    value=types.ModuleType('parity_source_transport');value.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),value.__dict__);value.LOCAL=LOCAL
    return value

# Upload new bounded helper sources, then stage the existing immutable packet once.
def stage(module):
    LOCAL.mkdir(mode=0o700,exist_ok=False)
    files={name:(REPO/'docs/research/sources'/item[0]).read_bytes() for name,item in PINS.items()}
    assert all(module.sha(files[name])==item[1] for name,item in PINS.items())
    files['operations.py']=pathlib.Path(__file__).read_bytes()
    payload=json.dumps({name:raw.hex() for name,raw in files.items()},sort_keys=True).encode();assert len(payload)<=2097152
    command="import hashlib,json,os,pathlib,sys; raw=sys.stdin.buffer.read(2097153); assert len(raw)<=2097152 and hashlib.sha256(raw).hexdigest()=="+repr(module.sha(payload))+"; files=json.loads(raw); root=pathlib.Path("+repr(TRANSFER)+"); assert os.getuid()==1000 and root.parent.resolve(strict=True)==root.parent; root.mkdir(mode=0o700,exist_ok=False)\nfor name,text in files.items():\n p=root/name; assert '..' not in pathlib.PurePosixPath(name).parts and not pathlib.PurePosixPath(name).is_absolute(); p.parent.mkdir(mode=0o700,parents=True,exist_ok=True); body=bytes.fromhex(text); assert len(body)<=262144; f=p.open('xb'); f.write(body); f.flush(); os.fsync(f.fileno()); f.close(); assert p.read_bytes()==body\nfor p in (root/'native-audit',root,root.parent):\n fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY); os.fsync(fd); os.close(fd)\nprint(json.dumps({name:hashlib.sha256(bytes.fromhex(text)).hexdigest() for name,text in files.items()},sort_keys=True))"
    code,raw,error=module.remote('helper-stage',['python3','-I','-S','-B','-c',command],payload)
    assert code==0 and not error and json.loads(raw)=={name:module.sha(body) for name,body in files.items()}
    packet=pathlib.Path('/tmp/capacity-evidence-parity-packet-20261018-v1/packet.json').read_bytes()
    assert len(packet)==356825 and module.sha(packet)=='edac83ca50254771cec2d79bb7e2d562b43bc1578e8fbeaa81730b2b21ad3fd2'
    command=invocation('stage.py',PINS['stage.py'][1],[])
    code,raw,error=module.remote('packet-stage',['python3','-I','-S','-B','-c',command],packet);assert code==0 and not error
    print(raw.decode(),flush=True)

# Build a safely quoted exact self-pinned helper invocation.
def invocation(name,pin,arguments):
    path=TRANSFER+'/'+name
    return "import hashlib,pathlib,sys; p=pathlib.Path("+repr(path)+"); raw=p.read_bytes(); assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()=="+repr(pin)+"; sys.argv=[str(p)]+"+repr(arguments)+"; exec(compile(raw,str(p),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(p)})"

# Run one readonly independent fold without any application or test entry point.
def review(module,route):
    pin=PINS['verifier.py'][1];command=invocation('verifier.py',pin,[route,pin])
    code,raw,error=module.remote('review-'+route,['python3','-I','-S','-B','-c',command]);assert code==0 and not error;print(raw.decode(),flush=True)

# Retrieve one bounded proof without rerunning the body it describes.
def fetch(module,name,path):
    command="import pathlib,sys; p=pathlib.Path("+repr(path)+"); assert p.resolve(strict=True)==p and p.stat().st_size<=262144; raw=p.read_bytes(); assert len(raw)<=262144; sys.stdout.buffer.write(raw)"
    code,raw,error=module.remote('fetch-'+name,['python3','-I','-S','-B','-c',command]);assert code==0 and not error
    print(json.dumps({'sha256':module.sha(raw),'bytes':len(raw),'local':str(LOCAL/('fetch-'+name+'.stdout'))}),flush=True)

# Own one finite190s SSH launch, retaining exact raw outputs and actual exit before propagation.
def launch(module,route,arguments):
    assert module.TRUSTED.read_bytes()==module.KEYS
    pin=PINS['launch.py'][1];command=invocation('launch.py',pin,[route]+arguments+[pin])
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlgorithms=ssh-ed25519','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','GlobalKnownHostsFile=/dev/null','-o','UserKnownHostsFile='+str(module.TRUSTED),'animallya96@172.16.8.3',shlex.join(['python3','-I','-S','-B','-c',command])]
    stdout=(LOCAL/(route+'.stdout')).open('xb');stderr=(LOCAL/(route+'.stderr')).open('xb');process=None;stopped=None
    try:
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,preexec_fn=module.limits);process.wait(timeout=190)
    finally:
        if process is not None and process.poll() is None:
            stopped='TERM';process.terminate()
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:stopped='KILL';process.kill();process.wait(timeout=1)
        for output in (stdout,stderr):output.flush();os.fsync(output.fileno());output.close()
        module.save(LOCAL/(route+'.exit.json'),json.dumps({'pid':None if process is None else str(process.pid),'exit':None if process is None else process.returncode,'owned_stop':stopped,'launch_sha256':pin,'arguments':[route]+arguments+[pin]},sort_keys=True).encode())
    print(json.dumps({'exit':process.returncode,'owned_stop':stopped,'stdout':(LOCAL/(route+'.stdout')).read_text(),'stderr':(LOCAL/(route+'.stderr')).read_text()},sort_keys=True),flush=True)
    assert process.returncode==0 and stopped is None and (LOCAL/(route+'.stderr')).read_bytes()==b''

# Dispatch only explicit source, readonly, native or parity routes with separately reviewed pins.
def main(arguments):
    module=transport()
    if arguments==['stage']:stage(module)
    elif len(arguments)==2 and arguments[0]=='review' and arguments[1] in ('prerequisites','native','terminal'):review(module,arguments[1])
    elif len(arguments)==4 and arguments[0]=='fetch':fetch(module,arguments[1],arguments[2]+'/'+arguments[3])
    elif len(arguments)==2 and arguments[0]=='native':launch(module,'native',arguments[1:])
    elif len(arguments)==3 and arguments[0]=='parity':launch(module,'parity',arguments[1:])
    else:raise SystemExit('NO_PARITY_OPERATION_ROUTE')

if __name__=='__main__':main(sys.argv[1:])
