"""UNRUN caller: new synthetic73 route only; no admission or transport prepared."""
import hashlib
import json
import os
import stat
import sys
import types
from pathlib import Path

SOURCE = Path('/home/animallya96/scratch/capacity-context-parity-source-20261018-v1')


# Authenticate exact bounded regular source or admission bytes with physical bookends.
def read(path, expected):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        assert len(raw) == before.st_size and all(getattr(before, k) == getattr(os.fstat(descriptor), k) == getattr(path.stat(follow_symlinks=False), k) for k in keys)
        assert hashlib.sha256(raw).hexdigest() == expected
        return raw
    finally:
        os.close(descriptor)


# Preserve the exact new caller/owner arguments before consuming its single source-bound admission.
def main(arguments):
    if len(arguments) != 4 or arguments[0] != '--call-admitted-context-parity':
        raise SystemExit('SOURCE_ONLY_NO_CONTEXT_PARITY_CALLER')
    owner_sha, book_sha, admission_sha = arguments[1:]
    for value in (owner_sha, book_sha, admission_sha):
        assert len(value) == 64 and all(c in '0123456789abcdef' for c in value)
    path = SOURCE / 'owner/context-owner.py'
    raw = read(path, owner_sha)
    read(SOURCE / 'source-book.json', book_sha)
    read(SOURCE / 'admission/admission.json', admission_sha)
    invocation = {'scope': 'ONE_NEW_SYNTHETIC73_CONTEXT_CALENDAR_EXPLICIT_UNITS_ONLY',
        'argv': ['--admitted-context-parity', admission_sha, owner_sha, book_sha], 'owner_sha256': owner_sha,
        'caller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (SOURCE / 'owner/caller-invocation.json').open('x') as output:
        json.dump(invocation, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    module = types.ModuleType('new_admitted_context_parity_owner')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
    module.main(invocation['argv'])


if __name__ == '__main__':
    main(sys.argv[1:])
