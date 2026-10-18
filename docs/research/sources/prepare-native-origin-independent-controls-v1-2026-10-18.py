"""Prepare one distinct pinned independent SOURCE packet and finite controls without remote dispatch."""
import ast
import base64
import gzip
import zlib
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPOSITORY = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
RESEARCH = REPOSITORY / 'docs/research'
SOURCES = RESEARCH / 'sources'
ROOT = Path('/tmp/native-origin-independent-preparation-20261018-v1')
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


# Replace only explicitly selected top-level assignments without importing either source.
def assignments(text, values):
    lines = text.splitlines(keepends=True)
    changes = []
    for name, expression in values.items():
        nodes = [node for node in ast.parse(text).body if isinstance(node, ast.Assign) and
            len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name]
        assert len(nodes) == 1
        node = nodes[0]
        changes.append((node.lineno - 1, node.end_lineno, name + ' = ' + expression + '\n'))
    for start, end, body in sorted(changes, reverse=True):
        lines[start:end] = [body]
    return ''.join(lines)


# Authenticate the separate two-pin source, build one compressed packet and preserve all preparation inputs.
def main():
    assert __debug__
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(30)
    pinned_name = 'verify-retained-native-json-pinned-v1-2026-10-18.py'
    remote_name = 'verify-retained-native-json-v1-2026-10-18.py'
    bootstrap_name = 'native-origin-independent-bootstrap-v1-2026-10-18.py'
    transport_name = 'native-origin-control-transport-v1-2026-10-18.py'
    summary_path = Path('/tmp/native-origin-observation-evidence-20261018-v1/summary.json')
    pins = {
        SOURCES / pinned_name: {'sha256': '321b8d9c445c615152efd8751223e8fd4985d8c6016ed55e4e51a8bdb4be36d6', 'bytes': 16744},
        SOURCES / bootstrap_name: {'sha256': 'a41b4deea218ad41d282fe0c4068de13ff7ade72579253198e4b38df2ad48ec5', 'bytes': 15283},
        SOURCES / transport_name: {'sha256': 'ce66a5d53a789bcb63f31633b222653f62af1cf59419ce3cfe30154952deb087', 'bytes': 26208},
        SOURCES / remote_name: {'sha256': '094561ab917e774ae04af52dc81cdbc5865db23ae5898f1ae25fd00496867a76', 'bytes': 16701},
        Path('/tmp/native-origin-observation-evidence-20261018-v1/03-' + remote_name):
            {'sha256': '094561ab917e774ae04af52dc81cdbc5865db23ae5898f1ae25fd00496867a76', 'bytes': 16701},
        summary_path: {'sha256': '8402d4238508755502005d8290141e10827494083a6384b46be611b5e962986d', 'bytes': 13430},
        SOURCES / 'native-origin-control-bootstrap-v1-2026-10-18.py':
            {'sha256': '70fb388a8cf1271a4eb0957a9071594490ef26318dc52ab9392b4572a6eacb67', 'bytes': 15611},
    }
    paths = list(pins) + [Path(__file__).resolve(strict=True)]
    bodies, rows = {}, {}
    for path in paths:
        bodies[path], rows[path] = read(path, pins.get(path))
    assert sum(row['bytes'] for row in rows.values()) <= 1048576
    old = bodies[SOURCES / remote_name].decode()
    expected = old.replace("SUMMARY_SHA = 'UNOBSERVED_PRIMARY_RESULT'",
        "SUMMARY_SHA = '8402d4238508755502005d8290141e10827494083a6384b46be611b5e962986d'").replace('SUMMARY_BYTES = 0', 'SUMMARY_BYTES = 13430')
    assert old.count("SUMMARY_SHA = 'UNOBSERVED_PRIMARY_RESULT'") == 1 and old.count('SUMMARY_BYTES = 0') == 1
    source = bodies[SOURCES / pinned_name]
    assert source == expected.encode()
    assert bodies[Path('/tmp/native-origin-observation-evidence-20261018-v1/03-' + remote_name)] == bodies[SOURCES / remote_name]
    bootstrap = bodies[SOURCES / bootstrap_name]
    tree = ast.parse(bootstrap)
    source_rows = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign) and
        isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'PINS'))
    assert source_rows == {remote_name: rows[SOURCES / pinned_name] | {}} or set(source_rows) == {remote_name}
    assert source_rows == {remote_name: {key: rows[SOURCES / pinned_name][key] for key in ('bytes', 'sha256')}}
    compressed = gzip.compress(source, mtime=0)
    inflater = zlib.decompressobj(31)
    assert inflater.decompress(compressed, len(source) + 1) == source and inflater.eof
    assert not inflater.unused_data and not inflater.unconsumed_tail
    record = {'bytes': len(source), 'sha256': sha(source), 'gzip_bytes': len(compressed),
        'gzip_sha256': sha(compressed), 'gzip_base64': base64.b64encode(compressed).decode('ascii')}
    packet = (json.dumps({'schema': 'native-origin-control-packet/1', 'control_source_sha256': sha(bootstrap),
        'files': {remote_name: record}}, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    assert len(packet) <= 65536
    wire = (json.dumps({'base_packet_base64': base64.b64encode(packet).decode('ascii'),
        'prerequisite_base64': None}, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    assert len(wire) <= 65536
    original = bodies[SOURCES / transport_name].decode()
    transport = assignments(original, {
        'LOCAL': "Path('/tmp/native-origin-independent-' + sys.argv[1] + '-transport-20261018-v1')",
        'PINS': repr({remote_name: record['sha256']}),
        'BOOTSTRAP': repr(bootstrap.decode()),
        'PREPARATION': 'Path(' + repr(str(ROOT)) + ')',
        'PACKET_SHA': repr(sha(packet)), 'PACKET_BYTES': repr(len(packet)),
        'BOOTSTRAP_SHA': repr(sha(bootstrap)), 'SOURCE_ROWS': repr(source_rows)})
    old_path = "'/tmp/native-origin-' + phase"
    assert transport.count(old_path) == 1
    transport = transport.replace(old_path, "'/tmp/native-origin-independent-' + phase")
    ast.parse(transport)
    before = {node.name: node for node in ast.parse(original).body if isinstance(node, ast.FunctionDef)}
    after = {node.name: node for node in ast.parse(transport).body if isinstance(node, ast.FunctionDef)}
    assert set(before) == set(after) and len(before) == 5
    for name in before:
        candidate = ast.unparse(after[name]).replace("'/tmp/native-origin-independent-'", "'/tmp/native-origin-'")
        assert ast.dump(ast.parse(candidate).body[0]) == ast.dump(before[name])
    for raw in (source, bootstrap, transport.encode(), bodies[Path(__file__).resolve(strict=True)]):
        lines = raw.decode().splitlines()
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                assert lines[first - 2].lstrip().startswith('# ')
        assert b'\x08' not in raw
    ROOT.mkdir(mode=0o700, exist_ok=False)
    copies = {}
    for index, path in enumerate(paths):
        target = ROOT / ('%02d-' % index + path.name)
        copies[str(path)] = {'original': rows[path], 'copy_path': str(target), 'copy': write(target, bodies[path])}
    outputs = {
        'packet.json': write(ROOT / 'packet.json', packet),
        'transport.py': write(ROOT / 'transport.py', transport.encode()),
        'bootstrap.py': write(ROOT / 'bootstrap.py', bootstrap),
        'pinned.py': write(ROOT / 'pinned.py', source)}
    report = {'schema': 'native-origin-independent-control-source-review/1', 'remote_bodies': 'UNRUN',
        'pinned_source': rows[SOURCES / pinned_name], 'original_draft': rows[SOURCES / remote_name],
        'summary_pin': rows[summary_path], 'source_rows': source_rows, 'outputs': outputs,
        'fixed_wire_bytes': len(wire), 'proof_bearing_wire': 'UNOBSERVED_MUST_FIT_65536_BEFORE_USE',
        'compressed_bytes': len(compressed), 'decoded_bytes': len(source),
        'only_two_independent_assignments_changed': True,
        'five_outer_transport_functions_equal_after_single_prerequisite_path_rebinding': True,
        'native_runtime_admission': None, 'genuine_execution_authorized': False}
    report_row = write(ROOT / 'source-review.json', (json.dumps(report, indent=2, sort_keys=True) + '\n').encode())
    for path, row in rows.items():
        read(path, row)
        item = copies[str(path)]
        read(Path(item['copy_path']), item['copy'])
    for name, row in outputs.items():
        read(ROOT / name, row)
    read(ROOT / 'source-review.json', report_row)
    manifest = {'schema': 'native-origin-independent-control-preparation/1', 'inputs': copies,
        'input_files': len(paths), 'input_bytes': sum(row['bytes'] for row in rows.values()),
        'outputs': outputs, 'source_review': report_row, 'remote_bodies': 'UNRUN',
        'software_file_bound': 262144, 'software_input_bound': 1048576,
        'kernel_AS_FSIZE_or_crash_durability_claim': False}
    manifest_row = write(ROOT / 'manifest.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
    for directory in (ROOT, ROOT.parent.resolve(strict=True), SOURCES):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    signal.alarm(0)
    print(json.dumps({'root': str(ROOT), 'manifest': manifest_row, 'source_review': report_row,
        'outputs': outputs, 'hash_work_final': HASH_WORK}, sort_keys=True))


if __name__ == '__main__':
    main()
