"""Preserve this new retained-ELF DATA evidence set locally; no remote operations."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
ROOT = Path('/tmp/capacity-callback-elf-data-evidence-20261018-v1')
NAMES = ('analyze-callback-elf-retained', 'verify-callback-elf-retained',
    'callback-elf-data-primary-transport', 'callback-elf-data-independent-transport',
    'prepare-callback-elf-data-transports', 'preserve-callback-elf-retained',
    'parse-callback-elf-data', 'fold-callback-elf-data')


# Represent every observed physical field as an exact decimal string.
def physical(value):
    return {name: str(getattr(value, name)) for name in ('st_dev', 'st_ino', 'st_mode',
        'st_nlink', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_blocks')}


# Read one small regular file twice through a held nonfollowing descriptor and bind its named identity.
def read_bound(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 262144:
            raise ValueError('SMALL_EVIDENCE_FILE_BOUND')
        body = source.read(262145)
        source.seek(0)
        again = source.read(262145)
        after = os.fstat(source.fileno())
        named = os.stat(path, follow_symlinks=False)
        if body != again or len(body) != before.st_size or not (
                physical(before) == physical(after) == physical(named)):
            raise ValueError('SMALL_EVIDENCE_PHYSICAL_BINDING')
    return body, physical(before)


# Create and fsync a new file, then verify its full bytes through the same bounded reader.
def retain(path, body):
    with path.open('xb') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    copied, identity = read_bound(path)
    if copied != body:
        raise ValueError('SMALL_EVIDENCE_COPY_READBACK')
    return identity


# Copy the fixed new controls, observations and receipts, recheck originals, then freeze a manifest last.
def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
    signal.alarm(30)
    sources = [REPO / 'docs/research/sources' / (name + '-v1-2026-10-18.py') for name in NAMES]
    sources += [REPO / 'docs/research' / name for name in (
        'original-loader-callback-elf-data-primary-stage-v1-2026-10-18.json',
        'original-loader-callback-elf-data-primary-observation-v1-2026-10-18.json',
        'original-loader-callback-elf-data-independent-stage-v1-2026-10-18.json',
        'original-loader-callback-elf-data-independent-v1-2026-10-18.json',
        'original-loader-callback-elf-data-next-requirements-v1-2026-10-18.json',
        'original-loader-callback-elf-data-static-v1-2026-10-18.json')]
    for phase in ('primary', 'independent'):
        transport = Path('/tmp/callback-elf-data-' + phase + '-transport-20261018-v1')
        sources += [transport / name for name in ('stdout', 'stderr', 'exit.json')]
    sources += [Path('/tmp/callback-elf-data-independent-preparation-drafts-20261018-v1/verify-callback-elf-retained-v1-2026-10-18.py')]
    ROOT.mkdir(mode=0o700)
    entries = []
    total = 0
    for index, path in enumerate(sources):
        body, identity = read_bound(path)
        total += len(body)
        if total > 1048576:
            raise ValueError('SMALL_EVIDENCE_TOTAL_BOUND')
        target = ROOT / (str(index).zfill(2) + '-' + path.name)
        copy_identity = retain(target, body)
        entries.append({'source': str(path), 'copy': str(target), 'bytes': len(body),
            'sha256': hashlib.sha256(body).hexdigest(), 'source_physical': identity,
            'copy_physical': copy_identity})
    for entry in entries:
        body, identity = read_bound(Path(entry['source']))
        if identity != entry['source_physical'] or hashlib.sha256(body).hexdigest() != entry['sha256']:
            raise ValueError('SMALL_EVIDENCE_LATER_BOOKEND')
    manifest = json.dumps({'schema': 'retained-callback-elf-small-evidence/1', 'files': entries,
        'total_bytes': total, 'second_complete_remote_archive': False,
        'crash_or_native_runtime_acceptance': False}, sort_keys=True, indent=2).encode() + b'\n'
    retain(ROOT / 'manifest.json', manifest)
    for directory in (ROOT, ROOT.resolve().parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    signal.alarm(0)
    print(json.dumps({'root': str(ROOT), 'files': len(entries), 'bytes': total,
        'manifest_sha256': hashlib.sha256(manifest).hexdigest(), 'manifest_bytes': len(manifest)}))


if __name__ == '__main__':
    main()
