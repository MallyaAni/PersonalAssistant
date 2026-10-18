"""Preserve native-origin requirements, source and prior metadata without remote or payload operations."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
ROOT = Path('/tmp/capacity-native-origin-contract-evidence-20261018-v1')
NAMES = (
    "sources/prepare-native-origin-contract-v1-2026-10-18.py",
    "sources/review-native-origin-contract-v1-2026-10-18.py",
    "sources/preserve-native-origin-contract-v1-2026-10-18.py",
    "original-loader-native-origin-contract-v1-2026-10-18.json",
    "original-loader-native-origin-static-v1-2026-10-18.json",
    "original-loader-native-origin-independent-v1-2026-10-18.json",
    "original-loader-callback-symbol-data-proof-v1-2026-10-18.json",
    "original-loader-callback-symbol-data-independent-v1-2026-10-18.json",
    "original-loader-context-parity-proof-v1-2026-10-18.json",
    "original-loader-callback-symbol-requirements-v1-2026-10-18.json",
    "sources/original-loader-context-native-probe-v1-2026-10-18.py",
    "sources/original-loader-context-parity-preflight-v1-2026-10-18.py",
    "sources/original-loader-context-parity-preserver-v2-2026-10-18.py",
    "/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-proof.stdout",
    "/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout",
    "/tmp/capacity-context-parity-operations-20261018-v1/fetch-evidence-manifest.stdout",
)

# Preserve exact local physical identities without a numeric precision conversion.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate two complete no-follow held reads with named and held physical bookends.
def read(path):
    path = path.resolve(strict=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        first = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert first == os.read(descriptor, 262145) and len(first) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        return first, {'sha256': hashlib.sha256(first).hexdigest(), 'bytes': len(first), 'physical': physical(before)}
    finally:
        os.close(descriptor)


# Write one exclusive bounded copy, sync it and verify its complete readback.
def retain(path, raw):
    assert len(raw) <= 262144
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    body, row = read(path)
    assert body == raw
    return row


# Freeze the new requirements and source inputs with complete original and copy bookends.
def main():
    assert __debug__
    signal.alarm(30)
    inputs, total = {}, 0
    for name in NAMES:
        path = REPO / 'docs/research' / name
        raw, row = read(path)
        total += len(raw)
        assert total <= 1048576
        inputs[name] = (path, raw, row)
    ROOT.mkdir(mode=0o700, exist_ok=False)
    records = []
    for index, (name, (path, raw, row)) in enumerate(inputs.items()):
        target = ROOT / (str(index).zfill(3) + '-' + path.name)
        copied = retain(target, raw)
        assert read(path)[1] == row
        records.append({'original': str(path), 'copy': str(target), 'original_identity': row, 'copy_identity': copied})
    for row in records:
        assert read(Path(row['original']))[1] == row['original_identity']
        assert read(Path(row['copy']))[1] == row['copy_identity']
    manifest = json.dumps({'scope': 'NATIVE_ORIGIN_SOURCE_REQUIREMENTS_AND_PRIOR_METADATA_ONLY_NO_OBSERVER_ADMISSION',
        'files': records, 'total_input_bytes': total, 'software_file_bound': 262144,
        'software_total_bound': 1048576, 'Mac_AS_or_kernel_FSIZE_claim': False,
        'crash_durability_guarantee': False}, sort_keys=True, indent=2).encode() + b'\n'
    row = retain(ROOT / 'manifest.json', manifest)
    for directory in (ROOT, ROOT.resolve(strict=True).parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'manifest': row, 'root': str(ROOT), 'files': len(records), 'input_bytes': total}, sort_keys=True))


if __name__ == '__main__':
    main()
