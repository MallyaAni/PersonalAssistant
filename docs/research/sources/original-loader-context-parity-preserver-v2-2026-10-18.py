"""UNRUN v2 complete context/native/prerequisite/tool preservation; raw large packet stays external."""
import hashlib
import json
import os
import resource
import stat
import sys
from pathlib import Path

SCRATCH = Path('/home/animallya96/scratch')
SOURCE = SCRATCH / 'capacity-context-parity-source-20261018-v1'
RUN = SCRATCH / 'capacity-context-parity-20261018-v1'
REVIEW = SCRATCH / 'capacity-context-parity-independent-review-20261018-v1'
TOOLS = SCRATCH / 'capacity-context-parity-tools-source-20261018-v1'
EVIDENCE = SCRATCH / 'capacity-context-parity-evidence-20261018-v1'
COPY_REVIEW = SCRATCH / 'capacity-context-parity-evidence-review-20261018-v1'
TRANSFER = SCRATCH / 'capacity-context-parity-transfer-20261018-v1'
PACKET = TRANSFER / 'packet.json'
ROOTS = {'source': SOURCE, 'run': RUN, 'review': REVIEW, 'tools': TOOLS,
    'prerequisites': SCRATCH / 'capacity-context-parity-prerequisites-20261018-v1',
    'native': SCRATCH / 'capacity-context-native-probe-20261018-v1',
    'native-review': SCRATCH / 'capacity-context-native-probe-review-20261018-v1', 'transfer': TRANSFER}


# Preserve exact physical identity using decimal strings rather than rounded timestamp projections.
def physical(value):
    return {k: str(getattr(value, k)) for k in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Read one ordinary bounded file with named and held identity and exact SHA bookends.
def read(path):
    assert path.resolve(strict=True) == path
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        assert len(raw) == before.st_size and physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Persist only a new bounded evidence file and check its full physical byte readback.
def save(path, raw):
    assert len(raw) <= 262144
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    observed, item = read(path)
    assert observed == raw
    return item


# Encode finite metadata without normalizing opaque native or original account bytes.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Sync completed evidence directories from descendants to the retained parent.
def sync(root):
    for path in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True) + [root]:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


# Freeze the complete source/run/independent-review inventories before a separate evidence copy.
def names():
    result = {}
    for label, root in ROOTS.items():
        assert root.resolve(strict=True) == root
        for path in sorted(root.rglob('*')):
            if not path.is_dir() and path != PACKET:
                result[label + '/' + str(path.relative_to(root))] = path
    assert 1 <= len(result) <= 8192
    return result


# Authenticate the retained external envelope in bounded chunks without copying it into capped evidence roots.
def external_packet():
    assert PACKET.resolve(strict=True) == PACKET
    with PACKET.open('rb') as stream:
        before = os.fstat(stream.fileno())
        assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1 and before.st_size == 903267
        digest, size = hashlib.sha256(), 0
        while block := stream.read(65536):
            size += len(block)
            assert size <= 903267
            digest.update(block)
        assert size == 903267 and physical(before) == physical(os.fstat(stream.fileno())) == physical(PACKET.stat(follow_symlinks=False))
    assert digest.hexdigest() == 'dfd903f31677b5945ae8fceafb25990b237d8780a5060f9469acc064d133f772'
    return {'path': str(PACKET), 'bytes': size, 'sha256': digest.hexdigest(), 'physical': physical(before), 'copied_into_ordinary_evidence_root': False}


# Copy every bounded evidence file with original/copy physical bookends and page manifests below the cap.
def preserve(self_sha, proof_sha):
    assert not os.path.lexists(EVIDENCE) and read(REVIEW / 'proof.json')[1]['sha256'] == proof_sha
    files = names()
    packet_before = external_packet()
    sizes = sum(path.stat().st_size for path in files.values())
    assert sizes <= 2 * 1024**3
    disk = os.statvfs(SCRATCH)
    assert disk.f_bavail * disk.f_frsize >= sizes + 1024**3 and disk.f_favail >= len(files) + 1024
    EVIDENCE.mkdir(mode=0o700)
    records, pages, source_inodes, copy_inodes = {}, [], set(), set()
    for name, original in files.items():
        raw, before = read(original)
        copied = save(EVIDENCE / name, raw)
        assert read(original)[1] == before
        assert copied['sha256'] == before['sha256'] and copied['bytes'] == before['bytes']
        for item, inodes in ((before, source_inodes), (copied, copy_inodes)):
            inode = (item['physical']['st_dev'], item['physical']['st_ino'])
            assert inode not in inodes
            inodes.add(inode)
        records[name] = {'original': before, 'copy': copied}
        if len(records) == 64:
            page = 'manifest-page-' + str(len(pages)).zfill(3) + '.json'
            item = save(EVIDENCE / page, encoded(records))
            pages.append({'path': page, **item})
            records = {}
    if records:
        page = 'manifest-page-' + str(len(pages)).zfill(3) + '.json'
        pages.append({'path': page, **save(EVIDENCE / page, encoded(records))})
    assert set(files) == set(names()) and source_inodes.isdisjoint(copy_inodes)
    sync(EVIDENCE)
    assert external_packet() == packet_before
    manifest = {'schema': 'capacity-context-parity-evidence/1', 'files': len(files), 'bytes': sizes,
        'pages': pages, 'external_packet': packet_before, 'proof_sha256': proof_sha, 'preserver_sha256': self_sha, 'genuine_acceptance': False,
        'scope': 'EXACT_SYNTHETIC73_SOURCE_RUN_REVIEW_COPY_ONLY_NO_GENUINE_OR_CRASH_ACCEPTANCE'}
    item = save(EVIDENCE / 'manifest.json', encoded(manifest))
    sync(EVIDENCE)
    print(json.dumps({'manifest_sha256': item['sha256'], 'files': len(files), 'bytes': sizes, 'genuine_acceptance': False}, sort_keys=True))


# Independently re-read originals, copies and page physical records in a distinct exclusive review root.
def review(self_sha, manifest_sha):
    assert not os.path.lexists(COPY_REVIEW)
    raw, manifest_item = read(EVIDENCE / 'manifest.json')
    assert manifest_item['sha256'] == manifest_sha
    manifest = json.loads(raw)
    assert external_packet() == manifest['external_packet']
    assert manifest['schema'] == 'capacity-context-parity-evidence/1' and manifest['genuine_acceptance'] is False
    files = names()
    seen, total = set(), 0
    for page in manifest['pages']:
        raw, item = read(EVIDENCE / page['path'])
        assert item == {k: v for k, v in page.items() if k != 'path'}
        records = json.loads(raw)
        assert 1 <= len(records) <= 64
        for name, expected in records.items():
            assert name in files and name not in seen
            seen.add(name)
            for _ in range(2):
                original_raw, original = read(files[name])
                copy_raw, copied = read(EVIDENCE / name)
                assert original == expected['original'] and copied == expected['copy'] and original_raw == copy_raw
            total += original['bytes']
    assert seen == set(files) and len(seen) == manifest['files'] and total == manifest['bytes']
    expected_names = seen | {p['path'] for p in manifest['pages']} | {'manifest.json'}
    assert {str(p.relative_to(EVIDENCE)) for p in EVIDENCE.rglob('*') if not p.is_dir()} == expected_names
    assert read(EVIDENCE / 'manifest.json')[1] == manifest_item and external_packet() == manifest['external_packet']
    COPY_REVIEW.mkdir(mode=0o700)
    proof = {'schema': 'capacity-context-parity-evidence-review/1', 'manifest_sha256': manifest_sha,
        'verifier_sha256': self_sha, 'files': len(seen), 'bytes': total, 'two_full_reads': True,
        'exact_original_and_copy_physical_bookends': True, 'genuine_acceptance': False}
    item = save(COPY_REVIEW / 'proof.json', encoded(proof))
    sync(COPY_REVIEW)
    print(json.dumps({'proof_sha256': item['sha256'], 'files': len(seen), 'genuine_acceptance': False}, sort_keys=True))


# Expose only explicit source-pinned evidence-copy or read-only copy-review operations.
def main(arguments):
    if len(arguments) != 3 or arguments[0] not in ('--preserve-context-parity', '--review-context-preservation'):
        raise SystemExit('SOURCE_ONLY_NO_CONTEXT_PRESERVATION_ROUTE')
    mode, self_sha, expected = arguments
    assert os.getuid() == 1000 and read(Path(__file__))[1]['sha256'] == self_sha
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    if mode == '--preserve-context-parity':
        preserve(self_sha, expected)
    else:
        review(self_sha, expected)


if __name__ == '__main__':
    main(sys.argv[1:])
