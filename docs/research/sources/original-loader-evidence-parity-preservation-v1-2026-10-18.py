"""Preserve completed native/parity evidence, then independently read it twice."""
import hashlib
import json
import os
import socket
import sys
import types
from pathlib import Path

BASE=Path('/home/animallya96/scratch')
ROOT=BASE/'capacity-evidence-parity-evidence-20261018-v1'
REVIEW=BASE/'capacity-evidence-parity-evidence-review-20261018-v1'
INPUTS={'source':BASE/'capacity-evidence-parity-source-20261018-v1','run':BASE/'capacity-evidence-parity-20261018-v1','prerequisites':BASE/'capacity-evidence-parity-prerequisites-20261018-v1','terminal':BASE/'capacity-evidence-parity-independent-review-20261018-v1','transfer':BASE/'capacity-evidence-parity-transfer-20261018-v1','native':BASE/'capacity-evidence-native-probe-20261018-v1','native-review':BASE/'capacity-evidence-native-probe-review-20261018-v1'}

# Import only the pinned readonly physical reader, never an old test entry point.
def reader():
    path=BASE/'n2-loader-guard-source-20261018-v2/owner/verifier.py'
    raw=path.read_bytes()
    assert len(raw)<=262144 and hashlib.sha256(raw).hexdigest()=='e0fa867a793c78b8260d935ed0c1518f60caa10ba3ab11e084a51ae249ec92f5'
    value=types.ModuleType('metadata_evidence_reader')
    value.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),value.__dict__)
    return value

# Write one exclusive bounded file and verify durable exact-byte readback.
def save(path,raw):
    assert len(raw)<=262144
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    assert path.parent.resolve(strict=True)==path.parent
    with path.open('xb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    assert path.read_bytes()==raw

# Fsync every created directory from children through its exclusive parent.
def sync(root):
    for path in sorted((p for p in root.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True)+[root,root.parent]:
        descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

# Copy completed source and runtime proofs with two exact original physical reads.
def preserve(value):
    ROOT.mkdir(mode=0o700,exist_ok=False)
    origins={};records={};total=0
    for role,source in INPUTS.items():
        physical,bodies=value.capture(source)
        origins[role]=physical
        for name,raw in bodies.items():
            target=role+'/'+name
            save(ROOT/target,raw)
            records[target]={'sha256':value.sha(raw),'bytes':len(raw)}
            total+=len(raw)
        assert value.capture(source)[0]==physical
    copied,bodies=value.capture(ROOT)
    assert set(copied)==set(records)
    assert all(records[name]=={key:copied[name][key] for key in ('sha256','bytes')} for name in records)
    proof=value.metadata(bodies['terminal/proof.json'])
    assert proof['status']=='VERIFIED_SYNTHETIC_EVIDENCE_PARITY_ONLY' and proof['cases']==80
    manifest={'schema':'capacity-evidence-parity-evidence-manifest/1','files':records,'origins':origins,'files_count':len(records),'bytes':total,'genuine_acceptance':False}
    raw=json.dumps(manifest,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'
    save(ROOT/'manifest.json',raw);sync(ROOT)
    print(json.dumps({'manifest_sha256':value.sha(raw),'manifest_bytes':len(raw),'files':len(records),'bytes':total,'root':str(ROOT)},sort_keys=True))

# Independently authenticate the completed manifest and both full physical read passes.
def verify(value):
    REVIEW.mkdir(mode=0o700,exist_ok=False)
    physical,bodies=value.capture(ROOT)
    manifest=value.metadata(bodies['manifest.json'])
    assert manifest['schema']=='capacity-evidence-parity-evidence-manifest/1' and manifest['genuine_acceptance'] is False
    assert set(physical)==set(manifest['files'])|{'manifest.json'} and manifest['files_count']==len(manifest['files'])
    assert sum(item['bytes'] for item in manifest['files'].values())==manifest['bytes']
    for name,item in manifest['files'].items():assert item=={key:physical[name][key] for key in ('sha256','bytes')}
    for role,source in INPUTS.items():
        before,originals=value.capture(source)
        assert before==manifest['origins'][role]
        for name,raw in originals.items():assert raw==bodies[role+'/'+name]
        assert value.capture(source)[0]==before
    assert value.capture(ROOT)[0]==physical
    result={'schema':'capacity-evidence-parity-evidence-independent-proof/1','status':'VERIFIED_TWO_FULL_READS_EXACT_PHYSICAL_EVIDENCE','manifest_sha256':value.sha(bodies['manifest.json']),'files_count':len(physical),'physical':physical,'genuine_acceptance':False}
    raw=json.dumps(result,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'
    save(REVIEW/'proof.json',raw);sync(REVIEW)
    print(json.dumps({'proof_sha256':value.sha(raw),'proof_bytes':len(raw),'files':len(physical),'root':str(REVIEW)},sort_keys=True))

# Require an exact self pin for exclusive preservation or independent readonly review.
def main(arguments):
    assert len(arguments)==2 and arguments[0] in ('preserve','verify')
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==arguments[1]
    assert os.getuid()==1000 and socket.gethostname()=='animallya-spark1'
    {'preserve':preserve,'verify':verify}[arguments[0]](reader())

if __name__=='__main__':main(sys.argv[1:])
