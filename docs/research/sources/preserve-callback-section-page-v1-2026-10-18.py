"""Preserve bounded local section-page controls, raw transport, DATA and requirements."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
BASE = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-callback-section-page-evidence-20261018-v1')
TRANSPORT = Path('/tmp/callback-section-page-transport-20261018-v1')
FILES = [BASE / 'sources' / name for name in (
    'observe-callback-section-page-v1-2026-10-18.py',
    'prepare-callback-section-page-transport-v1-2026-10-18.py',
    'callback-section-page-transport-v1-2026-10-18.py',
    'prepare-callback-symbol-contract-v1-2026-10-18.py',
    'preserve-callback-section-page-v1-2026-10-18.py')]
FILES += [BASE / name for name in (
    'original-loader-callback-section-page-v1-2026-10-18.json',
    'original-loader-callback-section-page-observation-v1-2026-10-18.json',
    'original-loader-callback-section-page-stage-v1-2026-10-18.json',
    'original-loader-callback-symbol-requirements-v1-2026-10-18.json',
    'original-loader-callback-section-page-static-v1-2026-10-18.json',
    'original-loader-callback-elf-data-independent-v1-2026-10-18.json')]
FILES += [TRANSPORT / name for name in ('stdout', 'stderr', 'exit.json')]
FILES += [Path('/tmp/callback-symbol-requirements-preparation-drafts-20261018-v1') / name for name in (
    'prepare-callback-symbol-contract-v1-2026-10-18.py',
    'original-loader-callback-symbol-requirements-v1-2026-10-18.json',
    'original-loader-callback-section-page-static-v1-2026-10-18.json',
    'manifest.json')]


# Preserve nanosecond and filesystem identity values without a lossy numeric projection.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate a small local file through two complete held reads and named identity bookends.
def read(path, expected=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
        assert 0 <= before.st_size <= 262144
        raw = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, 262145) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        if expected is not None:
            assert row == expected
        return raw, row
    finally:
        os.close(descriptor)


# Abort only this finite local preservation operation when its allowance expires.
def alarm(signum, frame):
    raise TimeoutError('SECTION_PAGE_LOCAL_PRESERVATION_BOUND')


# Retain every fixed small input exclusively and write the manifest after complete original bookends.
def main():
    assert __debug__ and len(FILES) == len(set(FILES)) == 18
    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(30)
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=False)
    rows, total = [], 0
    for index, path in enumerate(FILES):
        raw, original = read(path)
        total += len(raw)
        assert total <= 1048576
        name = '%02d-%s' % (index, path.name)
        target = ROOT / name
        with target.open('xb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        copied, copy = read(target)
        assert copied == raw and copy['sha256'] == original['sha256']
        rows.append({'original_path': str(path), 'copy_file': name, 'original': original, 'copy': copy})
    for row in rows:
        read(Path(row['original_path']), row['original'])
        read(ROOT / row['copy_file'], row['copy'])
    manifest = {'schema': 'callback-section-page-local-preservation/1', 'files': rows,
        'input_bytes': total, 'remote_full_archive_or_crash_durability_claim': False,
        'local_Mac_AS_bound_claim': False}
    body = json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(body) <= 262144
    with (ROOT / 'manifest.json').open('xb') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    assert read(ROOT / 'manifest.json')[0] == body
    for directory in (ROOT, ROOT.resolve().parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'files': len(rows), 'input_bytes': total, 'manifest_bytes': len(body),
        'manifest_sha256': hashlib.sha256(body).hexdigest(), 'root': str(ROOT)}, sort_keys=True))


if __name__ == '__main__':
    main()
