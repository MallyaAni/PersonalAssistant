"""Exclusive bounded evidence parity staging; never import packet payloads."""
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath

SOURCE = Path('/home/animallya96/scratch/capacity-evidence-parity-source-20261018-v1')
PACKET = 'edac83ca50254771cec2d79bb7e2d562b43bc1578e8fbeaa81730b2b21ad3fd2'
BOOK = '9cffe5361488307afd63123a4a79ef8b92ec2da53f629c1521734c2d3217b502'

# Preserve exact physical identities without rounding nanosecond timestamps.
def physical(value):
    return {key:str(getattr(value,key)) for key in ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_blocks','st_mtime_ns','st_ctime_ns')}

# Authenticate one regular no-follow file across held and named source bookends.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid==1000 and before.st_nlink==1 and 0<=before.st_size<=262144
        blocks=[]; size=0
        while block:=os.read(descriptor,65536):
            size+=len(block); assert size<=262144; blocks.append(block)
        raw=b''.join(blocks)
        assert len(raw)==before.st_size and physical(before)==physical(os.fstat(descriptor))==physical(path.stat(follow_symlinks=False))
        return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'physical':physical(before)}
    finally:
        os.close(descriptor)

# Write only a new regular bounded source and verify its exact bytes durably.
def save(path,raw):
    assert len(raw)<=262144
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    assert path.parent.resolve(strict=True)==path.parent
    with path.open('xb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())
    result=read(path)
    assert result['sha256']==hashlib.sha256(raw).hexdigest() and result['bytes']==len(raw)
    return result

# Stage only the previously pinned22 source records into a new exclusive root.
def main():
    assert os.getuid()==1000 and SOURCE.parent.resolve(strict=True)==SOURCE.parent and not os.path.lexists(SOURCE)
    raw=sys.stdin.buffer.read(2*1024**2+1)
    assert len(raw)==356825 and hashlib.sha256(raw).hexdigest()==PACKET
    packet=json.loads(raw)
    assert set(packet)=={'schema','scope','files','source_book'} and packet['schema']=='capacity-evidence-parity-packet/1' and packet['scope']=='SYNTHETIC_NEW_MODULE_PARITY_ONLY' and len(packet['files'])==22
    book=packet['source_book']
    book_raw=json.dumps(book,sort_keys=True,indent=2).encode()+b'\n'
    assert len(book['files'])==22 and len(book_raw)==3764 and hashlib.sha256(book_raw).hexdigest()==BOOK
    decoded={}
    for name,item in packet['files'].items():
        path=PurePosixPath(name)
        assert not path.is_absolute() and '..' not in path.parts and str(path)==name and path.parts[0] in ('audit','owner')
        assert set(item)=={'base64','sha256','bytes'}
        body=base64.b64decode(item['base64'],validate=True)
        assert len(body)==item['bytes'] and len(body)<=262144 and hashlib.sha256(body).hexdigest()==item['sha256']
        decoded[name]=body
    assert set(book['files'])==set(decoded)
    for name,item in book['files'].items():
        assert item=={key:packet['files'][name][key] for key in ('sha256','bytes')}
    SOURCE.mkdir(mode=0o700)
    files={name:save(SOURCE/name,body) for name,body in sorted(decoded.items())}
    files['source-book.json']=save(SOURCE/'source-book.json',book_raw)
    assert {str(path.relative_to(SOURCE)) for path in SOURCE.rglob('*') if path.is_file()}==set(files)
    assert {name:read(SOURCE/name) for name in files}==files
    proof={'schema':'capacity-evidence-parity-stage-proof/1','scope':'SOURCE_STAGING_ONLY_NO_PAYLOAD_EXECUTION','packet_sha256':PACKET,'source_book_sha256':BOOK,'files':files}
    result=save(SOURCE/'stage-proof.json',json.dumps(proof,sort_keys=True,indent=2).encode()+b'\n')
    for path in sorted((path for path in SOURCE.rglob('*') if path.is_dir()),key=lambda value:len(value.parts),reverse=True)+[SOURCE,SOURCE.parent]:
        descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    print(json.dumps({'source':str(SOURCE),'stage_proof':result,'files':23,'payload_execution':False},sort_keys=True))

if __name__=='__main__':
    main()
