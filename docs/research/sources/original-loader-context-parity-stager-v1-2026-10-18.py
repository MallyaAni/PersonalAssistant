"""UNRUN bounded staging only; no candidate imports, Docker or execution admission."""
import base64
import gzip
import hashlib
import io
import json
import os
import socket
import stat
import sys
from pathlib import Path, PurePosixPath

SOURCE = Path('/home/animallya96/scratch/capacity-context-parity-source-20261018-v1')


# Reject duplicate packet fields before interpreting source identities or path declarations.
def unique(pairs):
    value = {}
    for name, item in pairs:
        assert name not in value
        value[name] = item
    return value


# Write only a new bounded staged source with fsync and full hash readback.
def save(path, raw):
    assert len(raw) <= 262144 and path.parent.resolve(strict=True) == path.parent
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw and path.stat().st_uid == 1000 and path.stat().st_nlink == 1


# Expand one explicitly compressed source within its exact declared ordinary source bound.
def decode(item):
    assert set(item) == {'gzip_base64', 'gzip_sha256', 'gzip_bytes', 'sha256', 'bytes'}
    assert type(item['bytes']) is int and 0 <= item['bytes'] <= 262144
    compressed = base64.b64decode(item['gzip_base64'], validate=True)
    assert len(compressed) == item['gzip_bytes'] <= 262144 and hashlib.sha256(compressed).hexdigest() == item['gzip_sha256']
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(item['bytes'] + 1)
        assert len(raw) == item['bytes'] and stream.read(1) == b''
    assert hashlib.sha256(raw).hexdigest() == item['sha256']
    return raw


# Stage exactly one exclusive new source tree from an externally SHA-bound small envelope.
def main(arguments):
    if len(arguments) != 3 or arguments[0] != '--stage-context-source':
        raise SystemExit('SOURCE_ONLY_NO_CONTEXT_STAGING_ROUTE')
    packet, expected = Path(arguments[1]), arguments[2]
    assert os.getuid() == 1000 and socket.gethostname() == 'animallya-spark1' and not os.path.lexists(SOURCE)
    assert packet.resolve(strict=True) == packet and not packet.is_symlink()
    with packet.open('rb') as source:
        before = os.fstat(source.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and before.st_size <= 2097152
        raw = source.read(2097153)
        keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        assert len(raw) == before.st_size and all(getattr(before, k) == getattr(os.fstat(source.fileno()), k) == getattr(packet.stat(), k) for k in keys)
    assert hashlib.sha256(raw).hexdigest() == expected
    value = json.loads(raw, object_pairs_hook=unique)
    assert set(value) == {'schema', 'files', 'source_book', 'source_book_sha256'} and value['schema'] == 'capacity-context-parity-packet/1'
    assert 1 <= len(value['files']) <= 128
    book_raw = base64.b64decode(value['source_book'], validate=True)
    assert len(book_raw) <= 262144 and hashlib.sha256(book_raw).hexdigest() == value['source_book_sha256']
    book = json.loads(book_raw, object_pairs_hook=unique)
    assert set(book) == {'schema', 'files'} and book['schema'] == 'capacity-context-parity-source/1' and set(book['files']) == set(value['files'])
    decoded = {}
    for name, item in value['files'].items():
        path = PurePosixPath(name)
        assert str(path) == name and not path.is_absolute() and '..' not in path.parts and path.parts[0] in ('audit', 'owner')
        data = decode(item)
        assert book['files'][name] == {'sha256': item['sha256'], 'bytes': len(data)}
        decoded[name] = data
    assert sum(map(len, decoded.values())) <= 8 * 1024**2
    SOURCE.mkdir(mode=0o700)
    for name, data in sorted(decoded.items()):
        path = SOURCE / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        save(path, data)
    save(SOURCE / 'source-book.json', book_raw)
    for path in sorted((p for p in SOURCE.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True) + [SOURCE]:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    print(json.dumps({'schema': 'capacity-context-source-stage/1', 'packet_sha256': expected, 'source_book_sha256': value['source_book_sha256'],
        'files': len(decoded), 'decoded_bytes': sum(map(len, decoded.values())), 'payload_imported': False, 'execution_authorized': False}, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
