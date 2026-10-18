"""Exclusive bounded metadata source staging only; never import packet payloads."""
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath

SOURCE = Path('/home/animallya96/scratch/n2-metadata-tiny-source-20261018-v1')
PACKET = '881af8743066e336c4abf021b9c7a5ded1e8b0bb55d3f1df03aac7f0112d0a3e'
BOOK = 'dc785f33272b61c4bb79c5c456cce8728aede1ac8ee69880e47817766221ef0f'

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

# Stage only the previously pinned40 source records into a new exclusive root.
def main():
    assert os.getuid()==1000 and SOURCE.parent.resolve(strict=True)==SOURCE.parent and not os.path.lexists(SOURCE)
    raw=sys.stdin.buffer.read(2*1024**2+1)
    assert len(raw)==1411906 and hashlib.sha256(raw).hexdigest()==PACKET
    packet=json.loads(raw)
    assert set(packet)=={'schema','scope','files','source_book'} and packet['schema']=='metadata-tiny-packet/1' and packet['scope']=='SYNTHETIC_METADATA_PARTIAL31_ONLY_NOT_GENUINE' and len(packet['files'])==40
    book=packet['source_book']
    book_raw=json.dumps(book,sort_keys=True,indent=2).encode()+b'\n'
    assert len(book['files'])==38 and len(book_raw)==6471 and hashlib.sha256(book_raw).hexdigest()==BOOK
    decoded={}
    for name,item in packet['files'].items():
        path=PurePosixPath(name)
        assert not path.is_absolute() and '..' not in path.parts and str(path)==name and path.parts[0] in ('audit','owner')
        assert set(item)=={'base64','sha256','bytes'}
        body=base64.b64decode(item['base64'],validate=True)
        assert len(body)==item['bytes'] and len(body)<=262144 and hashlib.sha256(body).hexdigest()==item['sha256']
        decoded[name]=body
    assert set(book['files'])==set(decoded)-{'owner/metadata-owner.py','owner/caller.py'}
    for name,item in book['files'].items():
        assert item=={key:packet['files'][name][key] for key in ('sha256','bytes')}
    SOURCE.mkdir(mode=0o700)
    files={name:save(SOURCE/name,body) for name,body in sorted(decoded.items())}
    files['source-book.json']=save(SOURCE/'source-book.json',book_raw)
    assert {str(path.relative_to(SOURCE)) for path in SOURCE.rglob('*') if path.is_file()}==set(files)
    assert {name:read(SOURCE/name) for name in files}==files
    proof={'schema':'metadata-tiny-stage-proof/1','scope':'SOURCE_STAGING_ONLY_NO_PAYLOAD_EXECUTION','packet_sha256':PACKET,'source_book_sha256':BOOK,'files':files}
    result=save(SOURCE/'stage-proof.json',json.dumps(proof,sort_keys=True,indent=2).encode()+b'\n')
    for path in sorted((path for path in SOURCE.rglob('*') if path.is_dir()),key=lambda value:len(value.parts),reverse=True)+[SOURCE,SOURCE.parent]:
        descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    print(json.dumps({'source':str(SOURCE),'stage_proof':result,'files':41,'payload_execution':False},sort_keys=True))

if __name__=='__main__':
    main()
