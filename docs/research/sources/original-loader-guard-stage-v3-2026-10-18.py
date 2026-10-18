"""UNEXECUTED finite source-packet staging proposal, with no network calls.

Only externally SHA-pinned small source bytes can be written to a new root.
Staging is not permission to run containers, import the backend or load models.
"""

import base64
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath

FINGERPRINT = {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}
HARNESS_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
MANIFEST_SCHEMA = 'n2-capacity-call-manifest/2'

NAMES = {'audit/bootstrap.py', 'audit/fixture.py', 'audit/suite.py', 'audit/harness.py',
         'audit/producer-source.txt', 'audit/continuation-source.txt',
         'owner/controller.py', 'owner/verifier.py', 'owner/caller.py', 'stage.py'}


# Encode finite deterministic stage records without lossy timestamp conversions.
def encode(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Reject duplicate packet fields before accepting any path or source byte.
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


# Reject nonfinite metadata at the source-staging boundary.
def nonfinite(value):
    raise ValueError('NONFINITE_SOURCE_PACKET')


# Name complete exact small files without importing them.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Compare stable identity fields while allowing a read to advance access time.
def identity(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Construct only the ten bounded source records for later external SHA pinning.
def packet(sources):
    assert set(sources) == NAMES
    records = {}
    for name, path in sources.items():
        assert path.resolve(strict=True) == path and path.is_file()
        before = path.stat(follow_symlinks=False)
        raw = path.read_bytes()
        assert 0 <= len(raw) == before.st_size <= 262144
        assert identity(path.stat(follow_symlinks=False)) == identity(before)
        records[name] = {'sha256': sha(raw), 'bytes': len(raw), 'base64': base64.b64encode(raw).decode('ascii')}
    assert sum(row['bytes'] for row in records.values()) <= 1024 ** 2
    assert records['audit/harness.py']['sha256'] == HARNESS_SHA
    raw = encode({'schema': 'n2-guard-source-packet/3', 'scope': 'SOURCE_ONLY_SYNTHETIC_NO_RUNTIME_ADMISSION', 'files': records})
    assert len(raw) <= 2 * 1024 ** 2
    return raw


# Create an absent file, fsync it and authenticate held-FD/path readback.
def write(path, raw):
    assert len(raw) <= 2 * 1024 ** 2
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            count = os.write(descriptor, raw[offset:])
            assert count > 0
            offset += count
        os.fsync(descriptor)
        before = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    held = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        assert identity(os.fstat(held)) == identity(before)
        chunks, count = [], 0
        while block := os.read(held, 65536):
            chunks.append(block)
            count += len(block)
            assert count <= len(raw)
        assert b''.join(chunks) == raw and identity(os.fstat(held)) == identity(before)
        named = path.stat(follow_symlinks=False)
        assert named.st_ino == before.st_ino and named.st_dev == before.st_dev and named.st_size == len(raw)
        assert stat.S_ISREG(named.st_mode) and named.st_uid == 1000
    finally:
        os.close(held)
    assert identity(named) == identity(before)
    return identity(named)


# Preserve only ten explicitly named source files and their exact source receipt.
def stage(root, packet_raw, expected_sha):
    assert os.getuid() == 1000 and root.is_absolute() and root.parent.resolve(strict=True) == root.parent
    assert not root.exists() and len(packet_raw) <= 2 * 1024 ** 2 and sha(packet_raw) == expected_sha
    packet = json.loads(packet_raw, object_pairs_hook=unique, parse_constant=nonfinite)
    assert set(packet) == {'schema', 'scope', 'files'} and packet['schema'] == 'n2-guard-source-packet/3'
    assert packet['scope'] == 'SOURCE_ONLY_SYNTHETIC_NO_RUNTIME_ADMISSION' and set(packet['files']) == NAMES
    contents = {}
    for name, record in packet['files'].items():
        assert set(record) == {'sha256', 'bytes', 'base64'}
        relative = PurePosixPath(name)
        assert not relative.is_absolute() and '..' not in relative.parts and str(relative) == name
        raw = base64.b64decode(record['base64'], validate=True)
        assert len(raw) == record['bytes'] <= 262144 and sha(raw) == record['sha256']
        contents[name] = raw
    assert sum(map(len, contents.values())) <= 1024 ** 2
    assert sha(contents['audit/harness.py']) == HARNESS_SHA
    root.mkdir(mode=0o700)
    (root / 'audit').mkdir(mode=0o700)
    (root / 'owner').mkdir(mode=0o700)
    physical = {}
    for name, raw in contents.items():
        physical[name] = write(root / name, raw)
    review = {'schema': 'n2-guard-source-review/3', 'scope': 'SOURCE_REVIEWED_SYNTHETIC_ONLY',
              'guard_manifest_schema': MANIFEST_SCHEMA, 'generated_fingerprint': dict(FINGERPRINT),
              'source_sha256': {name.removeprefix('audit/'): sha(raw) for name, raw in contents.items() if name.startswith('audit/')}}
    review_raw = encode(review)
    physical['audit/review.json'] = write(root / 'audit/review.json', review_raw)
    physical['packet.json'] = write(root / 'packet.json', packet_raw)
    receipt = {'schema': 'n2-guard-source-stage/3', 'status': 'SOURCE_STAGED_NOT_RUNTIME_ADMITTED',
               'packet_sha256': expected_sha, 'review_sha256': sha(review_raw), 'physical': physical,
               'execution_authorized': False, 'genuine_loader': False}
    write(root / 'stage-receipt.json', encode(receipt))
    for directory in (root / 'audit', root / 'owner', root, root.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return receipt


if __name__ == '__main__':
    raise SystemExit('SOURCE_ONLY_NO_STAGING_OR_RUNTIME_ADMISSION')
