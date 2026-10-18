"""Local independent SOURCE/packet preservation check; no remote controls or readers run."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import zlib

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
SOURCE = REPO / 'docs/research/sources'
PREPARED = Path('/tmp/native-origin-control-preparation-20261018-v1')
ROOT = Path('/tmp/native-origin-control-local-independent-20261018-v1')
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
WORK = 0
INPUTS = {}


# Precharge complete local hashes to a separate finite independent verification ledger.
def digest(body):
    global WORK
    assert WORK + len(body) <= 4194304
    WORK += len(body)
    return hashlib.sha256(body).hexdigest()


# Authenticate two complete local held/named reads and their decimal physical identities.
def read(path, pin=None):
    assert len(INPUTS) < 64 or str(path) in INPUTS
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        body = os.read(descriptor, 262145)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert body == os.read(descriptor, 262145) and len(body) == before.st_size
        physical = dict(zip(FIELDS, (str(getattr(before, key)) for key in FIELDS)))
        assert physical == {key: str(getattr(os.fstat(descriptor), key)) for key in FIELDS}
        assert physical == {key: str(getattr(os.lstat(path), key)) for key in FIELDS}
        row = {'bytes': len(body), 'sha256': digest(body), 'physical': physical}
        if pin is not None:
            assert all(row[key] == value for key, value in pin.items())
        if str(path) in INPUTS:
            assert INPUTS[str(path)] == row
        INPUTS[str(path)] = row
        return body, row
    finally:
        os.close(descriptor)


# Stop incomplete local verification on its finite wall clock.
def stop(number, frame):
    raise KeyboardInterrupt('NATIVE_CONTROL_LOCAL_VERIFICATION_SIGNAL_' + str(number))


# Independently fold the prepared packet, exact source ASTs and every retained original/copy.
def main():
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(30)
    own, own_row = read(Path(__file__))
    raw, manifest_row = read(PREPARED / 'manifest.json', {'bytes': 16302,
        'sha256': '0b1fc7f967c36f8546776c700f80a144db120fdb774d0f72777c36b18276f539'})
    manifest = json.loads(raw)
    assert manifest['files'] == 13 and manifest['bytes'] == 210865
    assert len(manifest['inputs']) == 13
    for original, entry in manifest['inputs'].items():
        body, _ = read(Path(original), entry['original'])
        copied, _ = read(Path(entry['copy_path']), entry['copy'])
        assert body == copied
    report_raw, report_row = read(PREPARED / 'source-review.json', manifest['source_review'])
    assert report_row['sha256'] == 'fef8d9681adddae39aee8a2b917cf086a00c48cdaacd4361f9c283555bd89e25'
    report = json.loads(report_raw)
    packet_raw, packet_row = read(PREPARED / 'packet.json', report['base_packet'])
    packet = json.loads(packet_raw)
    assert set(packet) == {'schema', 'files', 'control_source_sha256'} and packet['schema'] == 'native-origin-control-packet/1'
    names = {'observe-retained-native-json-v1-2026-10-18.py', 'origin-contract.json', 'native-proof.json', 'native-inspect.json'}
    assert set(packet['files']) == names and len(packet_raw) == 30745
    original_paths = {
        'observe-retained-native-json-v1-2026-10-18.py': SOURCE / 'observe-retained-native-json-v1-2026-10-18.py',
        'origin-contract.json': REPO / 'docs/research/original-loader-native-origin-contract-v1-2026-10-18.json',
        'native-proof.json': Path('/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-proof.stdout'),
        'native-inspect.json': Path('/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout'),
    }
    decoded_bytes, compressed_bytes = 0, 0
    for name, item in packet['files'].items():
        assert set(item) == {'bytes', 'sha256', 'gzip_bytes', 'gzip_sha256', 'gzip_base64'}
        compressed = base64.b64decode(item['gzip_base64'], validate=True)
        assert len(compressed) == item['gzip_bytes'] <= 65536 and digest(compressed) == item['gzip_sha256']
        inflater = zlib.decompressobj(31)
        body = inflater.decompress(compressed, item['bytes'] + 1)
        assert len(body) == item['bytes'] <= 262144 and inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail
        assert digest(body) == item['sha256'] and body == read(original_paths[name])[0]
        decoded_bytes += len(body)
        compressed_bytes += len(compressed)
    assert decoded_bytes == 95869 and compressed_bytes == 22240
    transport, _ = read(SOURCE / 'native-origin-control-transport-v1-2026-10-18.py',
        {key: report['source_inventory']['transport'][key] for key in ('bytes', 'sha256')})
    control, _ = read(SOURCE / 'native-origin-control-bootstrap-v1-2026-10-18.py',
        {key: report['source_inventory']['bootstrap'][key] for key in ('bytes', 'sha256')})
    tree = ast.parse(transport)
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, (ast.Constant, ast.Dict, ast.Tuple))}
    assert constants['BOOTSTRAP'].encode('utf-8') == control
    assert constants['BOOTSTRAP_SHA'] == digest(control) == packet['control_source_sha256']
    assert constants['PACKET_SHA'] == packet_row['sha256'] and constants['PACKET_BYTES'] == len(packet_raw)
    assert constants['SOURCE_ROWS'] == {name: {key: item[key] for key in ('bytes', 'sha256')} for name, item in packet['files'].items()}
    wire = (json.dumps({'base_packet_base64': base64.b64encode(packet_raw).decode('ascii'),
        'prerequisite_base64': None}, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    assert len(wire) == 41049 <= 65536
    old = ast.parse(read(SOURCE / 'callback-symbol-data-primary-transport-v1-2026-10-18.py')[0])
    for name in ('limits', 'interrupt'):
        first = next(node for node in old.body if isinstance(node, ast.FunctionDef) and node.name == name)
        second = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        assert ast.dump(first, include_attributes=False) == ast.dump(second, include_attributes=False)
    assert sum(row['bytes'] for row in INPUTS.values()) <= 1048576
    ROOT.mkdir(mode=0o700, exist_ok=False)
    with (ROOT / 'source.py').open('xb') as output:
        output.write(own)
        output.flush()
        os.fsync(output.fileno())
    assert read(ROOT / 'source.py', {'bytes': len(own), 'sha256': own_row['sha256']})[0] == own
    for path, pin in list(INPUTS.items()):
        read(Path(path), pin)
    proof = {'schema': 'native-origin-control-local-independent/1', 'scope': 'LOCAL_SOURCE_AND_PACKET_ONLY',
        'inputs': INPUTS, 'originals': 13, 'copies': 13, 'manifest': manifest_row, 'source_review': report_row,
        'packet': packet_row, 'decoded_files': 4, 'decoded_bytes': decoded_bytes, 'compressed_bytes': compressed_bytes,
        'fixed_before_wire_bytes': len(wire), 'complete_source_body_and_physical_bookends_equal': True,
        'remote_controls_and_reader_bodies_UNRUN': True, 'remote_pages_target_native_json_UNREAD': True,
        'actual_prerequisites': None, 'runtime_admission': None, 'hash_work_before_proof': WORK}
    body = (json.dumps(proof, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('ascii')
    assert len(body) <= 262144
    expected = {'bytes': len(body), 'sha256': digest(body)}
    with (ROOT / 'proof.json').open('xb') as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    assert read(ROOT / 'proof.json', expected)[0] == body
    for directory in (ROOT, ROOT.parent.resolve(strict=True)):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'proof': expected, 'root': str(ROOT), 'source': own_row,
        'originals': 13, 'copies': 13, 'bookended_files_before_proof': len(INPUTS) - 1,
        'hash_work_final': WORK, 'remote_controls_UNRUN': True}, sort_keys=True))


if __name__ == '__main__':
    main()
