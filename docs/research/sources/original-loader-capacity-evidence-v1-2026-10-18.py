"""Unexecuted capacity evidence primitives v1; no admission or model entry point.

This separately named module retains the existing file/JSON primitive bodies.
It is not the original stream audit module and cannot certify original identity,
physical-state digest equality, archive admission, model parity or capacity.
"""

import gzip
import io
import json
import math
import os
import stat
from hashlib import sha256
from pathlib import Path

SCHEMA = "capacity-original-evidence-primitives/1"
MAX_METADATA_BYTES = 16 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024 * 1024


# Reject malformed evidence with the original exception type and reason.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Validate an external content identity without accepting coerced digest values.
def expected_digest(expected):
    require(
        type(expected) is str
        and len(expected) == 64
        and all(char in "0123456789abcdef" for char in expected),
        "External original evidence digest required",
    )


# Identify the same regular file before and after an authenticated read.
def file_identity(value):
    require(stat.S_ISREG(value.st_mode), "Regular original evidence file required")
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


# Reject concurrent replacement or size/content changes while evidence is read.
def stable_file(stream, path, before):
    require(
        file_identity(os.fstat(stream.fileno())) == before
        and file_identity(path.stat()) == before,
        "Original evidence changed during authentication",
    )


# Read small metadata only after its size check, with a bounded growth sentinel.
def pinned(path, expected, *, max_bytes=None):
    expected_digest(expected)
    limit = MAX_METADATA_BYTES if max_bytes is None else max_bytes
    require(type(limit) is int and limit >= 0, "Exact evidence size bound required")
    path = Path(path)
    before = file_identity(path.stat())
    require(before[2] <= limit, "Original metadata size exceeds bound")
    with path.open("rb") as stream:
        require(
            file_identity(os.fstat(stream.fileno())) == before,
            "Original evidence changed before reading",
        )
        raw = stream.read(limit + 1)
        require(len(raw) <= limit, "Original metadata size exceeds bound")
        stable_file(stream, path, before)
    require(sha256(raw).hexdigest() == expected, "Pinned stream input bytes differ")
    return raw


# Authenticate large source/model/input files with fixed-memory digest-only reads.
def authenticate_file(path, expected):
    expected_digest(expected)
    path = Path(path)
    before = file_identity(path.stat())
    value = sha256()
    with path.open("rb") as stream:
        require(
            file_identity(os.fstat(stream.fileno())) == before,
            "Original evidence changed before hashing",
        )
        while chunk := stream.read(HASH_CHUNK_BYTES):
            value.update(chunk)
        stable_file(stream, path, before)
    require(value.hexdigest() == expected, "Pinned stream input bytes differ")
    return value.hexdigest()


# Preserve unique JSON fields instead of silently replacing conflicting evidence.
def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate original pending evidence field")
        result[key] = value
    return result


# Reject nonfinite JSON constants instead of admitting fabricated numeric evidence.
def reject_constant(value):
    raise ValueError("Nonfinite original pending JSON constant: " + value)


# Reject overflowed JSON exponents before any timing receipt comparison.
def finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "Nonfinite original pending JSON number")
    return parsed


# Reject duplicate fields, nonfinite constants and overflow through local validators.
def strict_json(raw):
    require(type(raw) is bytes, "Immutable original JSON bytes required")
    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=reject_constant,
        parse_float=finite_float,
    )


# Reject ordinary mutation of an already admitted nested metadata value.
def _immutable(*args, **kwargs):
    raise TypeError("Admitted original metadata is readonly")


# Retain dict-compatible reads with a new explicitly versioned class identity.
class _ReadOnlyDict(dict):
    __slots__ = ()

    # Populate once during construction, before this mapping is exposed.
    def __new__(cls, value):
        result = dict.__new__(cls)
        dict.update(result, value)
        return result

    # Reinitializing an admitted mapping cannot replace its contents.
    def __init__(self, value):
        pass

    # Immutable nested metadata can be shared safely by detached audit copies.
    def __deepcopy__(self, memo):
        return self

    __setitem__ = __delitem__ = __ior__ = _immutable
    clear = pop = popitem = setdefault = update = _immutable


# Retain list-compatible reads with a new explicitly versioned class identity.
class _ReadOnlyList(list):
    __slots__ = ()

    # Populate once during construction, with already frozen nested values.
    def __new__(cls, value):
        result = list.__new__(cls)
        list.extend(result, value)
        return result

    # Reinitializing an admitted sequence cannot change its records.
    def __init__(self, value):
        pass

    # Immutable session metadata needs no mutable duplicate during audit copying.
    def __deepcopy__(self, memo):
        return self

    __setitem__ = __delitem__ = __iadd__ = __imul__ = _immutable
    append = clear = extend = insert = pop = remove = reverse = sort = _immutable


# Freeze nested metadata without claiming an original class or hostile-code barrier.
def _freeze(value):
    if type(value) is dict:
        return _ReadOnlyDict({name: _freeze(row) for name, row in value.items()})
    if type(value) is list:
        return _ReadOnlyList([_freeze(row) for row in value])
    return value


# Decode bounded gzip bytes using local finite duplicate-free JSON validators.
def archive_value(raw):
    require(
        len(raw) <= MAX_COMPRESSED_BYTES, "Original stream archive too large"
    )
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(MAX_JSON_BYTES + 1)
    require(
        len(expanded) <= MAX_JSON_BYTES, "Original stream expansion too large"
    )
    return strict_json(expanded)
