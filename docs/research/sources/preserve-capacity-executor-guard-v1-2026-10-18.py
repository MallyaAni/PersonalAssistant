"""Preserve small inert guard sources/reviews locally; never import payload code."""

import hashlib
import json
import os
from pathlib import Path

RESEARCH = Path(__file__).resolve().parents[1]
DEST = Path('/tmp/capacity-executor-guard-source-20261018-v1')
PROOF = RESEARCH / 'original-loader-executor-guard-preservation-v1-2026-10-18.json'
FILES = (
    'sources/capacity-executor-source-guard-v1-2026-10-18.py',
    'sources/prepare-capacity-executor-guard-v1-2026-10-18.py',
    'sources/review-capacity-executor-guard-v1-2026-10-18.py',
    'sources/preserve-capacity-executor-guard-v1-2026-10-18.py',
    'original-loader-executor-guard-contract-v1-2026-10-18.json',
    'original-loader-executor-guard-independent-v1-2026-10-18.json',
    'original-loader-executor-guard-static-v1-2026-10-18.json',
    'original-loader-executor-guard-static-v2-2026-10-18.json',
)


# Keep full physical counters as decimal strings instead of rounded timestamps.
def physical(value):
    return {name: str(getattr(value, name)) for name in (
        'st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size',
        'st_mtime_ns', 'st_ctime_ns',
    )}


# Copy each small source exclusively, fsync it and verify two complete readbacks.
def main():
    assert DEST.is_dir() and (DEST / 'candidate.py').read_bytes() == (RESEARCH / FILES[0]).read_bytes()
    rows = {}
    for name in FILES:
        source, target = RESEARCH / name, DEST / Path(name).name
        raw = source.read_bytes()
        assert len(raw) <= 262144
        before = physical(source.stat())
        with target.open('xb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        first, second = target.read_bytes(), target.read_bytes()
        assert raw == first == second == source.read_bytes() and physical(source.stat()) == before
        rows[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'source_physical': before, 'copy_physical': physical(target.stat())}
    candidate = DEST / 'candidate.py'
    rows['exclusive-builder-reproduction'] = {'sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(), 'bytes': candidate.stat().st_size, 'copy_physical': physical(candidate.stat())}
    manifest = json.dumps({'schema': 'capacity-executor-guard-local-source-preservation/1', 'files': rows}, sort_keys=True, indent=2).encode() + b'\n'
    with (DEST / 'manifest.json').open('xb') as output:
        output.write(manifest)
        output.flush()
        os.fsync(output.fileno())
    assert (DEST / 'manifest.json').read_bytes() == manifest
    for path in (DEST, DEST.resolve().parent):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    proof = {'schema': 'capacity-executor-guard-source-preservation-proof/1', 'root': str(DEST), 'source_review_copies': len(FILES), 'builder_reproduction_files': 1, 'data_bytes': sum(row['bytes'] for row in rows.values()), 'manifest_sha256': hashlib.sha256(manifest).hexdigest(), 'manifest_bytes': len(manifest), 'files_readback_root_resolved_parent_fsynced': True, 'crash_durability_guarantee': False, 'payload_import_CodeType_body': False}
    with PROOF.open('x', encoding='utf-8') as output:
        json.dump(proof, output, sort_keys=True, indent=2)
        output.write('\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
