"""Stage source and transport receipts only after completed metadata terminal review."""
import hashlib
import json
import pathlib
import sys
import types

LOCAL=pathlib.Path('/tmp/n2-metadata-tiny-operations-20261018-v1')
REMOTE='/home/animallya96/scratch/n2-metadata-tiny-transfer-20261018-v1'
REPO=pathlib.Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
PIN='2935dcd12302766f85236cb71de801e2e34df231461a84be829281dd04bff8fb'

# Authenticate the existing transport library and retain its finite pinned-key behavior.
def transport():
    path=pathlib.Path('/tmp/n2_guard_packet_owner_20261018_v3.py');raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='f8e6fcb47bff6c2f190295ddd2bd63308b7384a10734b422daed5e07c300c4db'
    module=types.ModuleType('metadata_preservation_transport');module.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__);module.LOCAL=LOCAL
    return module

# Stage exact source and prior transport receipts without overwriting any retained file.
def stage(module):
    files={'preservation.py':(REPO/'docs/research/sources/original-loader-metadata-tiny-preservation-2026-10-18.py').read_bytes(),'operations.py':pathlib.Path('/tmp/n2_metadata_operations_20261018_v1.py').read_bytes(),'evidence-transport.py':pathlib.Path(__file__).read_bytes()}
    assert module.sha(files['preservation.py'])==PIN
    assert json.loads((LOCAL/'launch.exit.json').read_bytes())['exit']==0
    assert json.loads((LOCAL/'terminal-proof.stdout').read_bytes())['status']=='VERIFIED_METADATA_HELPER_PARTIAL31_ONLY'
    for path in LOCAL.iterdir():
        if path.is_file():files['transport-receipts/'+path.name]=path.read_bytes()
    assert all(len(raw)<=262144 for raw in files.values())
    payload=json.dumps({name:raw.hex() for name,raw in files.items()},sort_keys=True).encode();assert len(payload)<=2097152
    command="import hashlib,json,os,pathlib,sys; root=pathlib.Path("+repr(REMOTE)+"); raw=sys.stdin.buffer.read(2097153); assert len(raw)<=2097152 and hashlib.sha256(raw).hexdigest()=="+repr(module.sha(payload))+"; files=json.loads(raw)\nfor name,text in files.items():\n p=root/name; assert '..' not in pathlib.PurePosixPath(name).parts and not pathlib.PurePosixPath(name).is_absolute(); p.parent.mkdir(mode=0o700,parents=True,exist_ok=True); body=bytes.fromhex(text); assert len(body)<=262144; f=p.open('xb'); f.write(body); f.flush(); os.fsync(f.fileno()); f.close(); assert p.read_bytes()==body\nfor p in (root/'transport-receipts',root):\n fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY); os.fsync(fd); os.close(fd)\nprint(json.dumps({name:hashlib.sha256(bytes.fromhex(text)).hexdigest() for name,text in files.items()},sort_keys=True))"
    code,raw,error=module.remote('evidence-source-stage',['python3','-I','-S','-B','-c',command],payload)
    assert code==0 and not error and json.loads(raw)=={name:module.sha(body) for name,body in files.items()}
    print(json.dumps({'files':len(files),'payload_bytes':len(payload),'payload_sha256':module.sha(payload)},sort_keys=True))

# Execute only preservation or its independent readonly full-read verifier.
def fold(module,route):
    command="import hashlib,pathlib,sys; p=pathlib.Path("+repr(REMOTE+'/preservation.py')+"); raw=p.read_bytes(); assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()=="+repr(PIN)+"; sys.argv=[str(p),"+repr(route)+","+repr(PIN)+"]; exec(compile(raw,str(p),'exec',dont_inherit=True),{'__name__':'__main__','__file__':str(p)})"
    code,raw,error=module.remote('evidence-'+route,['python3','-I','-S','-B','-c',command])
    assert code==0 and not error;print(raw.decode(),flush=True)

if __name__=='__main__':
    assert sys.argv[1:] in (['stage'],['preserve'],['verify'])
    module=transport()
    if sys.argv[1]=='stage':stage(module)
    else:fold(module,sys.argv[1])
