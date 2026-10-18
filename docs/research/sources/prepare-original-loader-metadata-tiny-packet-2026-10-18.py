"""Build one exclusive small source-only metadata packet; never import its payload."""
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
OUT = Path('/tmp/n2-metadata-tiny-packet-20261018-v1')

# Name exact complete payload bytes.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

# Persist a new bounded local source packet with durable readback.
def save(path, raw):
    assert len(raw) <= 2*1024**2
    with path.open('xb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    assert path.read_bytes() == raw

# Read exact original source bytes without importing their application modules.
def original(name, expected):
    raw = (REPO / name).read_bytes()
    if sha(raw) != expected:
        raw = subprocess.run(['git','show','27471b9c61b958f759e9f48b80acaf60cdf75f2e:' + name],cwd=REPO,capture_output=True,check=True).stdout
    assert sha(raw) == expected and len(raw) <= 262144
    return raw

# Assemble31 inert sources and exact bootstrap/owner/caller bytes only once.
def main():
    OUT.mkdir(mode=0o700, exist_ok=False)
    contract = json.loads((DOCS/'original-loader-capacity-contract-2026-10-18.json').read_bytes())
    native = contract['source_recipe']['native31']
    assert len(native) == 31 and sha(json.dumps(native,sort_keys=True,separators=(',',':')).encode()) == '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
    raw_map = (DOCS/'original-loader-genuine-source-map-2026-10-18.json').read_bytes()
    assert len(raw_map) == 279395 and sha(raw_map) == '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
    paths = {
        'audit/bootstrap.py': 'sources/original-loader-metadata-tiny-2026-10-18.py',
        'audit/helper.py': 'sources/original-loader-capacity-metadata-boundary-2026-10-18.py',
        'audit/harness.py': 'sources/original-loader-capacity-harness-v3-2026-10-18.py',
        'owner/controller.py': 'sources/original-loader-guard-controller-v2-2026-10-18.py',
        'owner/metadata-owner.py': 'sources/original-loader-metadata-tiny-owner-2026-10-18.py',
        'owner/caller.py': 'sources/original-loader-metadata-tiny-caller-2026-10-18.py',
    }
    payload = {name:(DOCS/path).read_bytes() for name,path in paths.items()}
    assert sha(payload['audit/helper.py']) == 'd413e748bf2b1eb63f4d267371f22cf6431f6ae650368676c815b07779723135'
    assert sha(payload['audit/harness.py']) == '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
    assert sha(payload['owner/controller.py']) == '2e505205cc8a3793d7b3313a5b5c3b670b00134575982d26c725787b6530df5a'
    payload['audit/full-map.json.gz'] = gzip.compress(raw_map,mtime=0)
    payload['audit/native31.json'] = json.dumps(native,sort_keys=True,indent=2).encode() + b'\n'
    payload['audit/current-paper-source.txt'] = (REPO/'backend/agents/trading/desk/paper.py').read_bytes()
    assert sha(payload['audit/current-paper-source.txt']) == 'a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c'
    payload.update({'audit/fixture/' + name:original(name,expected) for name,expected in native.items()})
    assert len(payload) == 40 and all(len(raw) <= 262144 for raw in payload.values())
    book_names = set(payload) - {'owner/metadata-owner.py','owner/caller.py'}
    book = {'schema':'metadata-tiny-source/1','files':{name:{'sha256':sha(payload[name]),'bytes':len(payload[name])} for name in sorted(book_names)}}
    book_raw = json.dumps(book,sort_keys=True,indent=2).encode() + b'\n'
    packet = {'schema':'metadata-tiny-packet/1','scope':'SYNTHETIC_METADATA_PARTIAL31_ONLY_NOT_GENUINE','files':{name:{'sha256':sha(raw),'bytes':len(raw),'base64':base64.b64encode(raw).decode()} for name,raw in sorted(payload.items())},'source_book':book}
    packet_raw = json.dumps(packet,sort_keys=True,separators=(',',':')).encode() + b'\n'
    save(OUT/'packet.json',packet_raw)
    save(OUT/'source-book.json',book_raw)
    result = {'packet':{'sha256':sha(packet_raw),'bytes':len(packet_raw),'records':len(payload),'decoded_source_bytes':sum(len(raw) for raw in payload.values())},'source_book':{'sha256':sha(book_raw),'bytes':len(book_raw),'records':len(book_names)},'sources':{name:{'sha256':sha(raw),'bytes':len(raw)} for name,raw in payload.items()},'local_root':str(OUT),'remote_staged':False,'admission':None,'test_execution':False}
    save(OUT/'build.json',json.dumps(result,sort_keys=True,indent=2).encode() + b'\n')
    print(json.dumps(result,sort_keys=True))

if __name__ == '__main__':
    main()
