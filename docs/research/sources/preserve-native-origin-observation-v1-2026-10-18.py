"""Preserve new native-origin observation controls and exact returned historical DATA locally."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPOSITORY = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
RESEARCH = REPOSITORY / 'docs/research'
SOURCES = RESEARCH / 'sources'
ROOT = Path('/tmp/native-origin-observation-evidence-20261018-v1')
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


# Preserve complete local operational evidence and reconstruct only the newly returned raw JSON page.
def main():
    assert __debug__
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(30)
    source_names = ('native-origin-control-bootstrap-v1-2026-10-18.py',
        'native-origin-control-transport-v1-2026-10-18.py', 'observe-retained-native-json-v1-2026-10-18.py',
        'verify-retained-native-json-v1-2026-10-18.py', 'get-native-origin-result-v1-2026-10-18.py',
        'native-origin-result-getter-transport-v1-2026-10-18.py', Path(__file__).name)
    paths = [SOURCES / name for name in source_names]
    paths += [RESEARCH / 'original-loader-native-origin-contract-v1-2026-10-18.json',
        Path('/tmp/native-origin-control-preparation-20261018-v1/packet.json')]
    for phase in ('before-stage', 'stage', 'before-observe', 'observe'):
        paths += [Path('/tmp/native-origin-' + phase + '-transport-20261018-v1') / name
            for name in ('stdout', 'stderr', 'exit.json', 'wire.json')]
    paths += [Path('/tmp/native-origin-result-getter-transport-20261018-v1') / name
        for name in ('stdout', 'stderr', 'exit.json')]
    paths += [Path('/tmp/native-origin-result-getter-drafts-20261018-v1') / name
        for name in ('getter-unrun.py', 'transport-unrun.py', 'reason.txt')]
    bodies, rows = {}, {}
    for path in paths:
        bodies[path], rows[path] = read(path)
    total = sum(row['bytes'] for row in rows.values())
    assert total <= 1048576 and len(paths) == len(set(paths))
    for name in source_names:
        raw = bodies[SOURCES / name]
        tree = ast.parse(raw, filename=name)
        lines = raw.decode().splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                assert lines[first - 2].lstrip().startswith('# ')
        assert b'\x08' not in raw
    terminal = json.loads(bodies[Path('/tmp/native-origin-observe-transport-20261018-v1/stdout')])
    retrieval = json.loads(bodies[Path('/tmp/native-origin-result-getter-transport-20261018-v1/stdout')])
    assert terminal['historical_artifact_only'] is True and terminal['pages'] == 1
    assert retrieval['schema'] == 'native-origin-result-retrieval/1'
    assert retrieval['reader_rerun'] is False and retrieval['independent_fold'] is False
    assert retrieval['native_runtime_admission'] is None
    returned = {name: base64.b64decode(raw, validate=True) for name, raw in retrieval['retained'].items()}
    assert set(returned) == {'summary.json', 'body-0000.json', 'stage.json'}
    for name, body in returned.items():
        remote = ('/home/animallya96/scratch/capacity-native-origin-observer-tools-20261018-v1/' if name == 'stage.json'
            else '/home/animallya96/scratch/capacity-native-origin-observation-20261018-v1/') + name
        assert len(body) == retrieval['inventory'][remote]['bytes'] and sha(body) == retrieval['inventory'][remote]['sha256']
    summary = json.loads(returned['summary.json'])
    assert terminal['summary'] == retrieval['inventory']['/home/animallya96/scratch/capacity-native-origin-observation-20261018-v1/summary.json']
    assert summary['catalog_records'] == 1339 and len(summary['catalog_page_record_counts']) == 21
    assert sum(summary['catalog_page_record_counts']) == 1339 and summary['catalog_payload_bytes_declared_only'] == 24575979
    page = json.loads(returned['body-0000.json'])
    assert page['schema'] == 'retained-native-json-raw-page/1' and page['start'] == 0 and len(page['records']) == 1
    record = page['records'][0]
    raw = base64.b64decode(record['base64'], validate=True)
    assert record['offset'] == 0 and record['bytes'] == len(raw) == summary['native_raw_bytes']
    assert sha(raw) == record['sha256'] == summary['native_raw_sha256']
    assert json.loads(raw) == summary['native_fields']
    assert summary['native_runtime_admission'] is None and summary['genuine_execution_authorized'] is False
    assert summary['historical_string_only_not_executable_path_build_or_runtime_authority'] is True
    originals = summary['input_inventory']
    assert len(originals) == 28
    page_bytes = sum(row['bytes'] for row in summary['raw_pages'])
    assert summary['hash_work_before_summary'] == 2 * sum(row['bytes'] for row in originals.values()) + len(raw) + 3 * page_bytes
    assert terminal['hash_work_final'] == summary['hash_work_before_summary'] + 2 * len(returned['summary.json'])
    assert terminal['output_bytes'] == len(returned['summary.json']) + page_bytes
    ROOT.mkdir(mode=0o700, exist_ok=False)
    retained = {}
    for index, path in enumerate(paths):
        target = ROOT / ('%02d-' % index + path.name)
        retained[str(path)] = {'original': rows[path], 'copy_path': str(target), 'copy': write(target, bodies[path])}
    outputs = {}
    for name, body in {**returned, 'native-raw.json': raw}.items():
        outputs[name] = write(ROOT / name, body)
    report = {'schema': 'native-origin-observation-local-review/1', 'scope': 'RETURNED_RESULT_AND_LOCAL_RECEIPT_REVIEW_NOT_INDEPENDENT_REMOTE_CATALOG_FOLD',
        'primary_terminal': terminal, 'native_fields': summary['native_fields'],
        'catalog_records': summary['catalog_records'], 'catalog_page_counts': summary['catalog_page_record_counts'],
        'raw_bytes': len(raw), 'raw_sha256': summary['native_raw_sha256'], 'returned': outputs,
        'native_runtime_admission': None, 'independent_fold': False, 'genuine_execution_authorized': False}
    report_row = write(ROOT / 'local-review.json', (json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
    for path, row in rows.items():
        read(path, row)
        item = retained[str(path)]
        read(Path(item['copy_path']), item['copy'])
    for name, row in outputs.items():
        read(ROOT / name, row)
    read(ROOT / 'local-review.json', report_row)
    manifest = {'schema': 'native-origin-observation-local-preservation/1', 'files': len(paths),
        'bytes': total, 'inputs': retained, 'returned_outputs': outputs, 'local_review': report_row,
        'local_review_path': str(ROOT / 'local-review.json'), 'file_bound': 262144, 'software_input_bound': 1048576,
        'independent_remote_fold': False, 'kernel_AS_FSIZE_or_crash_durability_claim': False}
    manifest_row = write(ROOT / 'manifest.json', (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n').encode())
    for directory in (ROOT, ROOT.parent.resolve(strict=True), SOURCES):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    signal.alarm(0)
    print(json.dumps({'root': str(ROOT), 'manifest': manifest_row, 'local_review': report_row,
        'input_files': len(paths), 'input_bytes': total, 'hash_work_final': HASH_WORK}, sort_keys=True))


if __name__ == '__main__':
    main()
