"""Derive a new source-only preservation control without running old preservation jobs."""
import ast
import hashlib
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent


# Replace exactly one declared literal in the retained operational source template.
def change(text, before, after):
    assert text.count(before) == 1
    return text.replace(before, after)


# Freeze a separately named preserver with seventeen fixed small source and review inputs.
def main():
    source = (BASE / 'preserve-callback-section-page-v1-2026-10-18.py').read_bytes()
    assert hashlib.sha256(source).hexdigest() == 'a837cf43e50d54075a931fe7faa92a5c0e23b069c5e9562a8f40aa617676ba2a'
    text = source.decode()
    beginning = text.index('# Preserve nanosecond and filesystem identity values')
    tail = text[beginning:]
    tail = change(tail, 'len(set(FILES)) == 18', 'len(set(FILES)) == 17')
    tail = change(tail, 'SECTION_PAGE_LOCAL_PRESERVATION_BOUND', 'SYMBOL_SOURCE_LOCAL_PRESERVATION_BOUND')
    tail = change(tail, 'callback-section-page-local-preservation/1', 'callback-symbol-source-local-preservation/1')
    header = '''"""Preserve new UNRUN symbol/version sources and bounded static evidence only."""
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
BASE = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-callback-symbol-source-evidence-20261018-v1')
FILES = [BASE / 'sources' / name for name in (
    'parse-callback-symbol-data-v1-2026-10-18.py',
    'fold-callback-symbol-data-v1-2026-10-18.py',
    'check-callback-symbol-data-v1-2026-10-18.py',
    'prepare-callback-symbol-preserver-v1-2026-10-18.py',
    'preserve-callback-symbol-sources-v1-2026-10-18.py')]
FILES += [BASE / name for name in (
    'original-loader-callback-symbol-source-contract-v1-2026-10-18.json',
    'original-loader-callback-symbol-source-static-v1-2026-10-18.json',
    'original-loader-callback-symbol-requirements-v1-2026-10-18.json',
    'original-loader-callback-section-page-v1-2026-10-18.json',
    'original-loader-callback-section-page-proof-v1-2026-10-18.json')]
FILES += [Path('/tmp/callback-symbol-source-preparation-drafts-20261018-v1') / name for name in (
    'parse-callback-symbol-data-v1-2026-10-18.py',
    'fold-callback-symbol-data-v1-2026-10-18.py',
    'manifest.json')]
FILES += [Path('/tmp/callback-symbol-fanout-preparation-drafts-20261018-v1') / name for name in (
    'parse-callback-symbol-data-v1-2026-10-18.py',
    'fold-callback-symbol-data-v1-2026-10-18.py',
    'check-callback-symbol-data-v1-2026-10-18.py',
    'manifest.json')]


'''
    result = (header + tail).encode()
    tree = ast.parse(result)
    assert len([n for n in tree.body if isinstance(n, ast.FunctionDef)]) == 4
    output = BASE / 'preserve-callback-symbol-sources-v1-2026-10-18.py'
    with output.open('xb') as stream:
        stream.write(result)
        stream.flush()
        os.fsync(stream.fileno())
    assert output.read_bytes() == result
    descriptor = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps({'source_sha256': hashlib.sha256(result).hexdigest(), 'bytes': len(result),
        'old_preserver_executed': False, 'payloads_executed': False}, sort_keys=True))


if __name__ == '__main__':
    main()
