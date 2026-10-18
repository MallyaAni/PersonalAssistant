# SOURCE ONLY: new upstream identity; no runtime or model admission.
"""Unexecuted directory durability primitive under a new module identity."""
import os
import stat
from backend.market import capacity_original_evidence_v1 as evidence

MAX_RESULT_BYTES = 256 * 1024**2

# Sync one exact named directory while its held descriptor and path identities agree.
def sync_directory(path, expected):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid')
        actual = tuple(getattr(before, key) for key in keys)
        evidence.require(stat.S_ISDIR(before.st_mode) and actual == expected and all(getattr(before, key) == getattr(path.stat(follow_symlinks=False), key) for key in keys), 'OWNED_DURABILITY_DIRECTORY_CHANGED')
        os.fsync(descriptor)
        evidence.require(all(getattr(before, key) == getattr(os.fstat(descriptor), key) == getattr(path.stat(follow_symlinks=False), key) for key in keys), 'OWNED_DURABILITY_DIRECTORY_CHANGED')
    finally:
        os.close(descriptor)
