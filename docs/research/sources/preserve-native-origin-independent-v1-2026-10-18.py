"""Preserve the new independent historical-DATA fold, finite controls and exact local evidence."""
import ast
import base64
import shlex
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPOSITORY = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
RESEARCH = REPOSITORY / 'docs/research'
SOURCES = RESEARCH / 'sources'
ROOT = Path('/tmp/native-origin-independent-evidence-20261018-v1')
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


# Verify returned independent evidence and preserve all new local controls and terminal links without remote replay.
def main():
    assert __debug__
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(30)
    source_names = ('verify-retained-native-json-pinned-v1-2026-10-18.py',
        'native-origin-independent-bootstrap-v1-2026-10-18.py', 'prepare-native-origin-independent-controls-v1-2026-10-18.py',
        'native-origin-independent-transport-v1-2026-10-18.py', 'get-native-origin-independent-result-v1-2026-10-18.py',
        'native-origin-independent-result-getter-transport-v1-2026-10-18.py', Path(__file__).name,
        'verify-retained-native-json-v1-2026-10-18.py')
    preparation = Path('/tmp/native-origin-independent-preparation-20261018-v1')
    prior = Path('/tmp/native-origin-observation-evidence-20261018-v1')
    paths = [SOURCES / name for name in source_names]
    paths += [preparation / name for name in ('packet.json', 'manifest.json', 'source-review.json', 'transport.py', 'bootstrap.py', 'pinned.py')]
    paths += [prior / name for name in ('summary.json', 'native-raw.json', 'body-0000.json', '03-verify-retained-native-json-v1-2026-10-18.py')]
    for phase in ('before-stage', 'stage', 'before-observe', 'observe'):
        paths += [Path('/tmp/native-origin-independent-' + phase + '-transport-20261018-v1') / name
            for name in ('stdout', 'stderr', 'exit.json', 'wire.json')]
    getter_root = Path('/tmp/native-origin-independent-result-getter-transport-20261018-v1')
    paths += [getter_root / name for name in ('stdout', 'stderr', 'exit.json')]
    paths += [Path('/tmp/native-origin-independent-preserver-drafts-20261018-v1') / name
        for name in ('preserver-unrun.py', 'reason.txt')]
    bodies, rows = {}, {}
    for path in paths:
        bodies[path], rows[path] = read(path)
    total = sum(row['bytes'] for row in rows.values())
    assert total <= 1048576 and len(paths) == len(set(paths))
    for name in source_names:
        raw = bodies[SOURCES / name]
        lines = raw.decode().splitlines()
        for node in ast.walk(ast.parse(raw, filename=name)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                assert lines[first - 2].lstrip().startswith('# ')
        assert b'\x08' not in raw
    assert rows[SOURCES / 'verify-retained-native-json-v1-2026-10-18.py']['sha256'] == '094561ab917e774ae04af52dc81cdbc5865db23ae5898f1ae25fd00496867a76'
    transport_tree = ast.parse(bodies[SOURCES / 'native-origin-independent-transport-v1-2026-10-18.py'])
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in transport_tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in
        ('BOOTSTRAP', 'BOOTSTRAP_SHA', 'PACKET_SHA', 'SOURCE_ROWS')}
    phase_proofs, terminal_rows = {}, {}
    prefix = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10',
        '-o', 'ServerAliveCountMax=2', '-o', 'GlobalKnownHostsFile=/dev/null',
        '-o', 'UserKnownHostsFile=/tmp/checkpoint-image-hostkeys-20261017-v1', 'animallya96@172.16.8.3']
    for phase in ('before-stage', 'stage', 'before-observe', 'observe'):
        directory = Path('/tmp/native-origin-independent-' + phase + '-transport-20261018-v1')
        receipt = json.loads(bodies[directory / 'exit.json'])
        assert receipt['exit'] == 0 and not bodies[directory / 'stderr']
        assert all(receipt[key] is None for key in ('failure_class', 'cleanup_failure_class', 'owned_SSH_group_stop'))
        expected = 'NONE' if phase.startswith('before-') else rows[Path('/tmp/native-origin-independent-' +
            ('before-stage' if phase == 'stage' else 'before-observe') + '-transport-20261018-v1/stdout')]['sha256']
        assert receipt['command'][:-1] == prefix
        assert shlex.split(receipt['command'][-1]) == ['python3', '-I', '-S', '-B', '-c',
            constants['BOOTSTRAP'], phase, constants['PACKET_SHA'], expected]
        assert receipt['control_source_sha256'] == constants['BOOTSTRAP_SHA']
        assert receipt['base_packet_sha256'] == constants['PACKET_SHA']
        assert receipt['input_wire'] == rows[directory / 'wire.json']
        wire = json.loads(bodies[directory / 'wire.json'])
        assert base64.b64decode(wire['base_packet_base64'], validate=True) == bodies[preparation / 'packet.json']
        if expected != 'NONE':
            assert sha(base64.b64decode(wire['prerequisite_base64'], validate=True)) == expected
        phase_proofs[phase] = json.loads(bodies[directory / 'stdout'])
        terminal_rows[phase] = {'stdout': rows[directory / 'stdout'], 'exit_receipt': rows[directory / 'exit.json'],
            'wire_bytes': rows[directory / 'wire.json']['bytes'], 'exit': 0}
    getter_terminal = json.loads(bodies[getter_root / 'exit.json'])
    assert getter_terminal['exit'] == 0 and not bodies[getter_root / 'stderr']
    assert all(getter_terminal[key] is None for key in ('failure_class', 'cleanup_failure_class', 'owned_SSH_group_stop'))
    getter_tree = ast.parse(bodies[SOURCES / 'native-origin-independent-result-getter-transport-v1-2026-10-18.py'])
    getter_constants = {node.targets[0].id: ast.literal_eval(node.value) for node in getter_tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('BOOTSTRAP', 'PINS')}
    assert getter_terminal['command'][:-1] == prefix
    assert shlex.split(getter_terminal['command'][-1]) == ['python3', '-I', '-S', '-B', '-c', getter_constants['BOOTSTRAP']]
    assert getter_terminal['source_sha256'] == getter_constants['PINS']
    assert getter_constants['PINS'] == {'get-native-origin-independent-result-v1-2026-10-18.py':
        rows[SOURCES / 'get-native-origin-independent-result-v1-2026-10-18.py']['sha256']}
    retrieval = json.loads(bodies[getter_root / 'stdout'])
    assert retrieval['schema'] == 'native-origin-independent-result-retrieval/1' and retrieval['reader_rerun'] is False
    returned = {name: base64.b64decode(body, validate=True) for name, body in retrieval['retained'].items()}
    assert set(returned) == {'proof.json', 'stage.json'}
    stage_stdout = Path('/tmp/native-origin-independent-stage-transport-20261018-v1/stdout')
    assert returned['stage.json'] == bodies[stage_stdout]
    for name, body in returned.items():
        remote = '/home/animallya96/scratch/capacity-native-origin-independent' + ('-tools' if name == 'stage.json' else '') + '-20261018-v1/' + name
        assert len(body) == retrieval['inventory'][remote]['bytes'] and sha(body) == retrieval['inventory'][remote]['sha256']
    terminal = phase_proofs['observe']
    assert len(returned['proof.json']) == terminal['proof_bytes'] and sha(returned['proof.json']) == terminal['proof_sha256']
    proof = json.loads(returned['proof.json'])
    assert (json.dumps(proof, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii') == returned['proof.json']
    summary = json.loads(bodies[prior / 'summary.json'])
    assert proof['schema'] == 'independent-retained-native-json/1' and proof['status'] == 'HISTORICAL_ARTIFACT_BYTES_ONLY'
    assert proof['complete_raw_equal'] is True and proof['complete_canonical_summary_equal'] is True
    assert proof['native_runtime_admission'] is None and proof['genuine_execution_authorized'] is False
    assert proof['selection'] == summary['selection'] and proof['native_fields'] == summary['native_fields']
    assert proof['raw_pages'] == summary['raw_pages'] and proof['catalog_records'] == summary['catalog_records'] == 1339
    assert {key: proof['input_inventory'][key] for key in summary['input_inventory']} == summary['input_inventory']
    extra = set(proof['input_inventory']) - set(summary['input_inventory'])
    base = '/home/animallya96/scratch/'
    assert extra == {base + 'capacity-native-origin-independent-tools-20261018-v1/verify-retained-native-json-v1-2026-10-18.py',
        base + 'capacity-native-origin-observation-20261018-v1/summary.json',
        base + 'capacity-native-origin-observation-20261018-v1/body-0000.json'}
    assert len(proof['input_inventory']) == 31
    own_source = base + 'capacity-native-origin-independent-tools-20261018-v1/verify-retained-native-json-v1-2026-10-18.py'
    assert proof['input_inventory'][own_source] == phase_proofs['stage']['files']['verify-retained-native-json-v1-2026-10-18.py']
    assert proof['input_inventory'][base + 'capacity-native-origin-observation-20261018-v1/summary.json'] == proof['summary']
    assert proof['input_inventory'][base + 'capacity-native-origin-observation-20261018-v1/body-0000.json'] == {
        key: summary['raw_pages'][0][key] for key in ('bytes', 'sha256', 'physical')}
    raw = bodies[prior / 'native-raw.json']
    assert len(raw) == summary['native_raw_bytes'] == 650 and sha(raw) == summary['native_raw_sha256']
    assert json.loads(raw) == proof['native_fields']
    assert proof['summary']['sha256'] == rows[prior / 'summary.json']['sha256']
    assert proof['hash_work_before_proof'] == 2 * sum(row['bytes'] for row in proof['input_inventory'].values()) + len(raw)
    assert terminal['hash_work_final'] == proof['hash_work_before_proof'] + 2 * len(returned['proof.json'])
    assert proof['primary_hash_work_final'] == summary['hash_work_before_summary'] + 2 * len(bodies[prior / 'summary.json'])
    ROOT.mkdir(mode=0o700, exist_ok=False)
    copies = {}
    for index, path in enumerate(paths):
        target = ROOT / ('%02d-' % index + path.name)
        copies[str(path)] = {'original': rows[path], 'copy_path': str(target), 'copy': write(target, bodies[path])}
    outputs = {name: write(ROOT / name, body) for name, body in returned.items()}
    report = {'schema': 'native-origin-independent-local-review/1', 'scope': 'AUTHENTICATED_RETURNED_INDEPENDENT_DATA_PROOF_AND_LOCAL_TERMINALS',
        'terminals': terminal_rows, 'independent_result': terminal, 'remote_input_count': 31,
        'native_fields': proof['native_fields'], 'primary_summary': proof['summary'], 'selection': proof['selection'],
        'complete_raw_and_canonical_summary_equal': True, 'native_runtime_admission': None,
        'genuine_execution_authorized': False, 'returned': outputs}
    report_row = write(ROOT / 'local-review.json', (json.dumps(report, indent=2, sort_keys=True) + '\n').encode())
    for path, row in rows.items():
        read(path, row)
        item = copies[str(path)]
        read(Path(item['copy_path']), item['copy'])
    for name, row in outputs.items():
        read(ROOT / name, row)
    read(ROOT / 'local-review.json', report_row)
    manifest = {'schema': 'native-origin-independent-local-preservation/1', 'inputs': copies,
        'input_files': len(paths), 'input_bytes': total, 'returned_outputs': outputs,
        'local_review': report_row, 'local_review_path': str(ROOT / 'local-review.json'),
        'software_file_bound': 262144, 'software_input_bound': 1048576, 'kernel_AS_FSIZE_or_crash_durability_claim': False}
    manifest_row = write(ROOT / 'manifest.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
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
