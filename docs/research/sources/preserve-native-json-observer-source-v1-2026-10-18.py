"""Local stdlib SOURCE-only review and preservation; never imports either proposed reader."""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPOSITORY = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
RESEARCH = REPOSITORY / 'docs/research'
SOURCES = RESEARCH / 'sources'
ROOT = Path('/tmp/capacity-native-origin-observer-source-evidence-20261018-v1')
SOURCE_NAMES = ('observe-retained-native-json-v1-2026-10-18.py', 'verify-retained-native-json-v1-2026-10-18.py',
    'preserve-native-json-observer-source-v1-2026-10-18.py')
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
HASH_WORK = 0
READS = 0


# Retain exact physical identities without rounding nanosecond values.
def physical(info):
    return {name: str(getattr(info, name)) for name in FIELDS}


# Bound all local hashing before the digest begins.
def sha(raw):
    global HASH_WORK
    assert HASH_WORK + len(raw) <= 4194304
    HASH_WORK += len(raw)
    return hashlib.sha256(raw).hexdigest()


# Read two full held and named copies of one bounded local evidence input.
def read(path, expected=None):
    global READS
    assert READS < 1024
    READS += 1
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(fd, 262145)
        os.lseek(fd, 0, os.SEEK_SET)
        assert raw == os.read(fd, 262145) and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(fd)) == physical(os.lstat(path))
        row = {'bytes': len(raw), 'sha256': sha(raw), 'physical': physical(before)}
        if expected is not None:
            assert all(row[name] == value for name, value in expected.items())
        return raw, row
    finally:
        os.close(fd)


# Write an exclusive complete file and authenticate its full fsynced readback.
def write(path, raw):
    assert len(raw) <= 262144
    expected = {'bytes': len(raw), 'sha256': sha(raw)}
    with path.open('xb') as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    observed, row = read(path, expected)
    assert observed == raw
    return row


# Stop local preparation on a deadline without labelling partial files complete.
def stop(number, frame):
    raise KeyboardInterrupt('LOCAL_SOURCE_PRESERVATION_SIGNAL_' + str(number))


# Check only source ASTs and preserve exact local inputs with later original and copy bookends.
def main():
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(30)
    paths = [SOURCES / name for name in SOURCE_NAMES]
    pins = {
        Path('/tmp/capacity-native-origin-observer-source-drafts-20261018-v1/reason.json'):
            {'sha256': '1a328b4b04ac398cae0da1a34a48bddf44f8a0cfc230b31d0176bccaff4e2522', 'bytes': 325},
        Path('/tmp/capacity-native-origin-observer-source-drafts-20261018-v1/preserver-unrun.py'):
            {'sha256': 'ff974a21903f1b9815c46513f8b121a7a2e8f71d8a8bd185f9afd6b7400b9d3a', 'bytes': 8855},
        SOURCES / 'original-loader-context-native-probe-v1-2026-10-18.py':
            {'sha256': '6a9e82a33291466c7ef7abc57554c90b26f56c9253bbc1ff4969c49515f0105f', 'bytes': 1878},
        RESEARCH / 'original-loader-native-origin-contract-v1-2026-10-18.json':
            {'sha256': '4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5', 'bytes': 24905},
        RESEARCH / 'original-loader-native-origin-contract-proof-v1-2026-10-18.json':
            {'sha256': '07e5943049cd3b88411737ab11a30f1598d29d1e4ad4c20aa9c9ec51f967cb9d', 'bytes': 11169},
        Path('/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-proof.stdout'):
            {'sha256': '1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7', 'bytes': 46814},
        Path('/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout'):
            {'sha256': 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2', 'bytes': 9755},
        Path('/tmp/capacity-context-parity-operations-20261018-v1/fetch-evidence-manifest.stdout'):
            {'sha256': 'd2378ddf7f0e5cf9eac724ff1f7c8f3f5d3cff70c0ba39f45cd2ca18546fd9f9', 'bytes': 10845},
    }
    paths.extend(pins)
    bodies, inventory, trees, functions = {}, {}, {}, {}
    for path in paths:
        bodies[path], inventory[path] = read(path, pins.get(path))
    assert sum(row['bytes'] for row in inventory.values()) <= 1048576
    for name in SOURCE_NAMES:
        path = SOURCES / name
        raw = bodies[path]
        tree = ast.parse(raw, filename=str(path))
        trees[name] = tree
        lines = raw.decode('utf-8').splitlines()
        declarations = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in declarations:
            first = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
            assert lines[first - 2].lstrip().startswith('# ')
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
            node.func.id in {'compile', 'exec', 'eval', '__import__'} for node in ast.walk(tree))
        functions[name] = [{'name': node.name, 'line': node.lineno,
            'AST_sha256': sha(ast.dump(node, include_attributes=False).encode('utf-8'))} for node in declarations]
    independent = trees[SOURCE_NAMES[1]]
    assignments = {node.targets[0].id: ast.literal_eval(node.value) for node in independent.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)}
    assert assignments['PRIMARY_SHA'] == inventory[SOURCES / SOURCE_NAMES[0]]['sha256']
    assert assignments['SUMMARY_SHA'] == 'UNOBSERVED_PRIMARY_RESULT' and assignments['SUMMARY_BYTES'] == 0
    primary_imports = [node for node in ast.walk(independent) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all('observe-retained' not in ast.unparse(node) for node in primary_imports)
    main_node = next(node for node in independent.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    assert isinstance(main_node.body[1], ast.Assert) and 'SUMMARY_BYTES' in ast.unparse(main_node.body[1])
    contract = json.loads(bodies[RESEARCH / 'original-loader-native-origin-contract-v1-2026-10-18.json'])
    pages = contract['retained_metadata_selection']['page_inventory']
    assert len(pages) == 21 and sum(page['bytes'] for page in pages) == 1289452
    assert [page['path'] for page in pages] == ['manifest-page-%03d.json' % index for index in range(21)]
    report = {'schema': 'retained-native-json-observer-SOURCE-review/1', 'scope': 'LOCAL_AST_JSON_SHA_ONLY',
        'function_inventory': functions, 'payload_functions_UNRUN': sum(len(functions[name]) for name in SOURCE_NAMES[:2]),
        'primary_independent_source_hash_pinned': True, 'independent_summary_unobserved_fail_closed': True,
        'contract_pages': 21, 'contract_page_bytes': 1289452, 'all_remote_pages_target_and_native_json_UNREAD_here': True,
        'observer_invocation': None, 'independent_invocation': None, 'staging_transport': None,
        'actual_prerequisites': None, 'execution_admission': None, 'native_runtime_admission': None,
        'genuine_execution_authorized': False}
    ROOT.mkdir(mode=0o700, exist_ok=False)
    retained = {}
    for index, path in enumerate(paths):
        name = '%02d-%s' % (index, path.name)
        retained[str(path)] = {'original': inventory[path], 'copy_path': str(ROOT / name), 'copy': write(ROOT / name, bodies[path])}
    report_raw = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    report_row = write(ROOT / 'source-review.json', report_raw)
    for path, row in inventory.items():
        read(path, row)
        copy = retained[str(path)]
        read(Path(copy['copy_path']), copy['copy'])
    read(ROOT / 'source-review.json', report_row)
    manifest = {'schema': 'retained-native-json-observer-source-preservation/1', 'files': len(paths),
        'bytes': sum(row['bytes'] for row in inventory.values()), 'inputs': retained, 'source_review': report_row,
        'source_review_path': str(ROOT / 'source-review.json'), 'software_input_bound': 1048576,
        'file_bound': 262144, 'payload_bodies_UNRUN': True, 'remote_observation_UNRUN': True,
        'kernel_AS_FSIZE_or_crash_durability_claim': False}
    manifest_raw = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    manifest_row = write(ROOT / 'manifest.json', manifest_raw)
    for directory in (ROOT, ROOT.parent.resolve(strict=True)):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    signal.alarm(0)
    print(json.dumps({'root': str(ROOT), 'manifest': manifest_row, 'source_review': report_row,
        'files': len(paths), 'bytes': manifest['bytes'], 'hash_work_final': HASH_WORK, 'payload_bodies_UNRUN': True}, sort_keys=True))


if __name__ == '__main__':
    main()
