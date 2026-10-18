"""SOURCE ONLY: one exact externally admitted metadata-owner call; default refuses."""
import hashlib
import json
import os
import sys
import types
from pathlib import Path

SOURCE = Path('/home/animallya96/scratch/n2-metadata-tiny-source-20261018-v1')

# Authenticate a bounded exact script or receipt without accepting another path.
def read(path, expected):
    assert path.resolve(strict=True) == path and path.stat().st_uid == 1000
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        after = os.fstat(descriptor)
        named = path.stat(follow_symlinks=False)
        fields = ('st_dev','st_ino','st_mode','st_uid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
        assert all(getattr(before,key) == getattr(after,key) == getattr(named,key) for key in fields)
        assert len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected
        return raw
    finally:
        os.close(descriptor)

# Invoke only the exact new owner with a separately reviewed fresh scoped admission.
def main(arguments):
    if len(arguments) != 4 or arguments[0] != '--call-admitted-metadata-tiny':
        raise SystemExit('SOURCE_ONLY_NO_METADATA_CALLER_ADMISSION')
    owner_sha, book_sha, admission_sha = arguments[1:]
    for value in (owner_sha, book_sha, admission_sha):
        assert len(value) == 64 and all(char in '0123456789abcdef' for char in value)
    owner_path = SOURCE / 'owner/metadata-owner.py'
    raw = read(owner_path, owner_sha)
    read(SOURCE / 'source-book.json', book_sha)
    read(SOURCE / 'admission/admission.json', admission_sha)
    invocation = {'scope': 'ONE_NEW_SYNTHETIC_METADATA_PARTIAL31_NOT_GENUINE', 'argv': ['--admitted-metadata-tiny', admission_sha, owner_sha, book_sha], 'owner_sha256': owner_sha, 'caller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    receipt = SOURCE / 'owner/caller-invocation.json'
    with receipt.open('x') as output:
        json.dump(invocation, output, sort_keys=True); output.flush(); os.fsync(output.fileno())
    module = types.ModuleType('admitted_metadata_tiny_owner')
    module.__file__ = str(owner_path)
    exec(compile(raw, str(owner_path), 'exec', dont_inherit=True), module.__dict__)
    module.main(invocation['argv'])

if __name__ == '__main__':
    main(sys.argv[1:])
