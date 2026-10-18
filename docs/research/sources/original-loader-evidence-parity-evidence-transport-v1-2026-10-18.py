"""Preserve small transport observations, then run exact evidence-only preservation routes."""
import hashlib
import json
import pathlib
import sys
import types

OPERATIONS=pathlib.Path('/tmp/evidence_parity_operations_20261018_v1.py')
LOCAL=pathlib.Path('/tmp/capacity-evidence-parity-operations-20261018-v1')
TRANSFER='/home/animallya96/scratch/capacity-evidence-parity-transfer-20261018-v1'
PRESERVER='928c4af5e3bc23e745ce5e78d76cf2649a74c3f2a19f623625c8494e4f2188ac'

# Bind only the authenticated finite transport library without invoking a runtime route.
def library():
    raw=OPERATIONS.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='3cfdc1c75ae331ccbb87a234bd8f4f5043a8810a0c6a2252d7329f2b313ebc17'
    value=types.ModuleType('evidence_transport_operations');value.__file__=str(OPERATIONS)
    exec(compile(raw,str(OPERATIONS),'exec',dont_inherit=True),value.__dict__)
    return value,value.transport()

# Copy only existing bounded local observations into a new exclusive remote directory.
def stage(operations,transport):
    files={path.name:path.read_bytes() for path in LOCAL.iterdir() if path.is_file()}
    files['evidence-transport.py']=pathlib.Path(__file__).read_bytes()
    assert files and all(len(raw)<=262144 for raw in files.values())
    payload=json.dumps({name:raw.hex() for name,raw in files.items()},sort_keys=True).encode()
    assert len(payload)<=2097152
    root=TRANSFER+'/transport-observations'
    command="import hashlib,json,os,pathlib,sys; raw=sys.stdin.buffer.read(2097153); assert len(raw)<=2097152 and hashlib.sha256(raw).hexdigest()=="+repr(hashlib.sha256(payload).hexdigest())+"; files=json.loads(raw); root=pathlib.Path("+repr(root)+"); assert os.getuid()==1000 and root.parent.resolve(strict=True)==root.parent; root.mkdir(mode=0o700,exist_ok=False)\nfor name,text in files.items():\n assert pathlib.PurePosixPath(name).name==name; body=bytes.fromhex(text); assert len(body)<=262144; p=root/name; f=p.open('xb'); f.write(body); f.flush(); os.fsync(f.fileno()); f.close(); assert p.read_bytes()==body\nfor p in (root,root.parent):\n fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY); os.fsync(fd); os.close(fd)\nprint(json.dumps({name:hashlib.sha256(bytes.fromhex(text)).hexdigest() for name,text in files.items()},sort_keys=True))"
    code,raw,error=transport.remote('evidence-observations-stage',['python3','-I','-S','-B','-c',command],payload)
    assert code==0 and not error and json.loads(raw)=={name:hashlib.sha256(body).hexdigest() for name,body in files.items()}
    print(json.dumps({'files':len(files),'bytes':sum(map(len,files.values())),'root':root}),flush=True)

# Invoke the pinned preserver or its distinct independent readback without any test body.
def review(operations,transport,route):
    command=operations.invocation('preservation.py',PRESERVER,[route,PRESERVER])
    code,raw,error=transport.remote('evidence-'+route,['python3','-I','-S','-B','-c',command])
    assert code==0 and not error
    print(raw.decode(),flush=True)

# Expose only exclusive observation copying and completed-evidence preservation routes.
def main(arguments):
    assert len(arguments)==1 and arguments[0] in ('stage','preserve','verify')
    operations,transport=library()
    if arguments==['stage']:stage(operations,transport)
    else:review(operations,transport,arguments[0])

if __name__=='__main__':main(sys.argv[1:])
