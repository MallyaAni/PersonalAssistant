"""UNRUN exact caller for one separately reviewed synthetic parity admission."""
import hashlib
import json
import os
import stat
import sys
import types
from pathlib import Path

SOURCE=Path('/home/animallya96/scratch/capacity-evidence-parity-source-20261018-v1')

# Authenticate one exact held bounded regular source or admission record.
def read(path,expected):
    assert path.resolve(strict=True)==path
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(descriptor);assert stat.S_ISREG(before.st_mode) and before.st_uid==1000 and before.st_nlink==1 and 0<=before.st_size<=262144
        raw=os.read(descriptor,262145);fields=('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
        assert len(raw)==before.st_size and all(getattr(before,key)==getattr(os.fstat(descriptor),key)==getattr(path.stat(follow_symlinks=False),key) for key in fields)
        assert hashlib.sha256(raw).hexdigest()==expected
        return raw
    finally:os.close(descriptor)

# Preserve the exact caller-to-owner arguments before the single admitted route.
def main(arguments):
    if len(arguments)!=4 or arguments[0]!='--call-admitted-evidence-parity':raise SystemExit('SOURCE_ONLY_NO_EVIDENCE_PARITY_CALLER')
    owner_sha,book_sha,admission_sha=arguments[1:]
    for value in (owner_sha,book_sha,admission_sha):assert len(value)==64 and all(char in '0123456789abcdef' for char in value)
    path=SOURCE/'owner/parity-owner.py';raw=read(path,owner_sha)
    read(SOURCE/'source-book.json',book_sha);read(SOURCE/'admission/admission.json',admission_sha)
    invocation={'scope':'ONE_NEW_SYNTHETIC_EVIDENCE_ARCHIVE_PARITY_ONLY','argv':['--admitted-evidence-parity',admission_sha,owner_sha,book_sha],'owner_sha256':owner_sha,'caller_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (SOURCE/'owner/caller-invocation.json').open('x') as output:json.dump(invocation,output,sort_keys=True);output.flush();os.fsync(output.fileno())
    module=types.ModuleType('admitted_evidence_parity_owner');module.__file__=str(path)
    exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__);module.main(invocation['argv'])

if __name__=='__main__':main(sys.argv[1:])
