"""UNEXECUTED bootstrap restricted to the new tiny synthetic fixtures.

No generic executor or genuine capacity route is provided. The externally
pinned source record is required before loading any helper. The generated
bundle is a synthetic test pin, never a genuine runtime admission document.
"""

import hashlib
import json
import os
import sys
import types
from pathlib import Path

FINGERPRINT = {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}
HARNESS_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
MANIFEST_SCHEMA = 'n2-capacity-call-manifest/2'

NAMES = {'bootstrap.py', 'fixture.py', 'suite.py', 'harness.py', 'producer-source.txt', 'continuation-source.txt'}


# Verify finite small metadata by its external complete byte digest.
def pinned(path, checksum):
    raw = path.read_bytes()
    assert len(raw) <= 262144 and hashlib.sha256(raw).hexdigest() == checksum
    return json.loads(raw)


# Authenticate all exact mounted helper bytes before importing a helper.
def sources(record):
    assert record['scope'] == 'SOURCE_REVIEWED_SYNTHETIC_ONLY'
    assert record['schema'] == 'n2-guard-source-review/3' and record['guard_manifest_schema'] == MANIFEST_SCHEMA
    assert record['generated_fingerprint'] == FINGERPRINT and record['source_sha256']['harness.py'] == HARNESS_SHA
    assert set(record['source_sha256']) == NAMES
    assert {path.name for path in Path('/audit').iterdir()} == NAMES | {'review.json'}
    for name, checksum in record['source_sha256'].items():
        path = Path('/audit') / name
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert len(raw) <= 262144 and hashlib.sha256(raw).hexdigest() == checksum
    assert not any(name == 'backend' or name.startswith('backend.') for name in sys.modules)


# Execute only held authenticated helper bytes in a non-backend module namespace.
def helper(name, filename, record):
    path = Path('/audit') / filename
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record['source_sha256'][filename]
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0), module.__dict__)
    return module


# Route only preparation, frozen-suite, or exact frozen-child synthetic modes.
def main(arguments):
    assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and not sys.flags.optimize
    assert os.getuid() == 1000
    mode, metadata_path, checksum = arguments[:3]
    path = Path(metadata_path)
    assert path == Path('/audit/review.json') if mode == 'prepare' else path == Path('/fixture/bundle.json')
    record = pinned(path, checksum)
    sources(record)
    fixture = helper('guard_synthetic_fixture', 'fixture.py', record)
    if mode == 'prepare':
        assert len(arguments) == 3
        fixture.prepare(Path('/out/prepared'), Path('/audit/producer-source.txt').read_bytes(), Path('/audit/continuation-source.txt').read_bytes())
        return 0
    assert mode in ('suite', 'child') and record['fixture_path'] == '/fixture'
    prepared = Path('/fixture')
    assert hashlib.sha256((prepared / 'prepared.json').read_bytes()).hexdigest() == record['prepared_sha256']
    suite = helper('guard_synthetic_suite', 'suite.py', record)
    if mode == 'suite':
        assert len(arguments) == 3
        suite.run(Path('/out/suite'), prepared, path, checksum)
        return 0
    assert len(arguments) == 5
    case_id, root = arguments[3:]
    rows = pinned(prepared / 'scenarios.json', record['scenarios_sha256'])
    matches = [row for row in rows if row['id'] == case_id]
    assert len(matches) == 1 and Path(root) == Path('/out/suite') / case_id
    assert Path(root).is_dir() and not Path(root).is_symlink()
    harness = helper('guard_capacity_harness', 'harness.py', record)
    assert record['source_sha256']['harness.py'] == fixture.HARNESS_SHA
    return suite.child_entry(matches[0], Path(root), prepared, harness, fixture)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
