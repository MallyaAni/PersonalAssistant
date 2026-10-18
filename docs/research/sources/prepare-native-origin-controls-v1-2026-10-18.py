"""Local SOURCE-only packet/transport preparation and preservation; no remote control body runs."""
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import stat

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
HERE = REPO / 'docs/research/sources'
ROOT = Path('/tmp/native-origin-control-preparation-20261018-v1')
BOOTSTRAP_SHA = '70fb388a8cf1271a4eb0957a9071594490ef26318dc52ab9392b4572a6eacb67'
FRAGMENT_SHA = 'c6802e3fb9e8dd28736263698f3af2191a777023635f6742774c3823a86e2ddf'
OLD_SHA = '78253bcf66db3e449b4247749b1912c640ea809e941fb820d975e739bed19617'
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
WORK = 0


# Preserve exact physical metadata for local controls and their new copies.
def physical(value):
    return {name: str(getattr(value, name)) for name in FIELDS}


# Precharge every local digest while keeping the source-only hash work finite.
def sha(raw):
    global WORK
    assert len(raw) <= 4194304 - WORK
    WORK += len(raw)
    return hashlib.sha256(raw).hexdigest()


# Authenticate two full held and named reads of one bounded local source or artifact.
def read(path, pin=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= 262144
        raw = os.read(fd, 262145)
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 262145) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(fd)) == physical(os.lstat(path))
        row = {'bytes': len(raw), 'sha256': sha(raw), 'physical': physical(before)}
        if pin is not None:
            assert all(row[key] == value for key, value in pin.items())
        return raw, row
    finally:
        os.close(fd)


# Create one exclusive bounded local artifact and check its fsynced full readback.
def write(path, raw):
    assert len(raw) <= 262144
    expected = {'bytes': len(raw), 'sha256': sha(raw)}
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    observed, row = read(path, expected)
    assert observed == raw
    return row


# Refuse ambiguous scripted source edits before generating an inert proposed transport.
def replace_once(source, old, new):
    assert source.count(old) == 1
    return source.replace(old, new)


# Abort partial local preparation without accepting an incomplete root.
def stop(number, frame):
    raise KeyboardInterrupt('NATIVE_CONTROL_PREPARATION_SIGNAL_' + str(number))


# Build a bounded packet and inert transport from exact sources, then preserve every local input.
def main():
    signal.signal(signal.SIGALRM, stop)
    signal.alarm(30)
    payload_paths = {
        'observe-retained-native-json-v1-2026-10-18.py': HERE / 'observe-retained-native-json-v1-2026-10-18.py',
        'origin-contract.json': REPO / 'docs/research/original-loader-native-origin-contract-v1-2026-10-18.json',
        'native-proof.json': Path('/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-proof.stdout'),
        'native-inspect.json': Path('/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout'),
    }
    pins = {
        'observe-retained-native-json-v1-2026-10-18.py': {'bytes': 14395, 'sha256': 'b7f6ffb0b968c08caa0b6133c0d2aa20d75c54f87b0abc80326c28c9096a6e5b'},
        'origin-contract.json': {'bytes': 24905, 'sha256': '4a6ef7b722e4b4eb5e77df8de1be7b3fd2ca604d555985d8048409b5748180f5'},
        'native-proof.json': {'bytes': 46814, 'sha256': '1355771ff667f81e02dbe07885914dd5be8bf5cf395a3e74ef3bfdfd4988c6f7'},
        'native-inspect.json': {'bytes': 9755, 'sha256': 'd5265be87b979e83e396e18d1d9d4571cc6e1db5aa09239200004a2809bd90d2'},
    }
    paths = {path: pins[name] for name, path in payload_paths.items()}
    paths.update({
        HERE / 'callback-symbol-data-primary-transport-v1-2026-10-18.py': {'bytes': 8385, 'sha256': OLD_SHA},
        HERE / 'native-origin-control-bootstrap-v1-2026-10-18.py': {'sha256': BOOTSTRAP_SHA},
        HERE / 'native-origin-transport-prelude-v1-2026-10-18.py': {'sha256': FRAGMENT_SHA},
        Path(__file__): None,
        Path('/tmp/native-origin-control-bootstrap-drafts-20261018-v1/bootstrap-unrun.py'): {'bytes': 14858, 'sha256': '2fe7eada6ad9447762f01101702a29c2fbc7bd98c5a158dbd4a24b93fa037407'},
        Path('/tmp/native-origin-control-bootstrap-drafts-20261018-v1/reason.json'): {'bytes': 508, 'sha256': '0ac157d24f9121ed004ef934a272d4eef2062c69e005461e81bbacff68c728e0'},
        Path('/tmp/native-origin-control-preparation-patch-refusal-20261018-v1.json'): None,
    })
    bodies, inputs = {}, {}
    for path, pin in paths.items():
        bodies[path], inputs[path] = read(path, pin)
    assert sum(row['bytes'] for row in inputs.values()) <= 1048576
    bootstrap = bodies[HERE / 'native-origin-control-bootstrap-v1-2026-10-18.py'].decode('utf-8')
    boot_tree = ast.parse(bootstrap)
    declaration = next(node.value for node in boot_tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PINS' for target in node.targets))
    keys = [ast.Constant('observe-retained-native-json-v1-2026-10-18.py') if isinstance(key, ast.Name) and key.id == 'READER' else key for key in declaration.keys]
    assert ast.literal_eval(ast.Dict(keys=keys, values=declaration.values)) == pins
    files = {}
    for name, path in payload_paths.items():
        compressed = gzip.compress(bodies[path], mtime=0)
        assert len(compressed) <= 65536
        files[name] = dict(pins[name], gzip_bytes=len(compressed), gzip_sha256=sha(compressed), gzip_base64=base64.b64encode(compressed).decode('ascii'))
    packet_raw = (json.dumps({'schema': 'native-origin-control-packet/1', 'control_source_sha256': BOOTSTRAP_SHA,
        'files': files}, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
    assert len(packet_raw) <= 65536
    packet_sha = sha(packet_raw)
    old_raw = bodies[HERE / 'callback-symbol-data-primary-transport-v1-2026-10-18.py']
    source, old_tree = old_raw.decode('utf-8'), ast.parse(old_raw)
    edits = []
    for node in old_tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == 'BOOTSTRAP':
                value = 'BOOTSTRAP = ' + repr(bootstrap)
            elif name == 'PINS':
                value = 'PINS = ' + repr({name: row['sha256'] for name, row in pins.items()})
            elif name == 'LOCAL':
                value = "LOCAL = Path('/tmp/native-origin-' + sys.argv[1] + '-transport-20261018-v1')"
            else:
                continue
            edits.append((node.lineno, node.end_lineno, value))
    assert len(edits) == 3
    lines = source.splitlines(keepends=True)
    for start, end, value in sorted(edits, reverse=True):
        lines[start - 1:end] = [value + '\n']
    source = ''.join(lines)
    source = replace_once(source, 'import subprocess\n', 'import subprocess\nimport stat\nimport sys\nimport time\n')
    source = replace_once(source, "'One reviewed retained-callback symbol/version DATA invocation; no native loading or old gates.'", repr('UNRUN native-origin stage/prerequisite/observation transport; no dispatch admitted.'))
    constants = '\nPREPARATION = Path(' + repr(str(ROOT)) + ')\nPACKET_SHA = ' + repr(packet_sha) + '\nPACKET_BYTES = ' + str(len(packet_raw)) + '\nBOOTSTRAP_SHA = ' + repr(BOOTSTRAP_SHA) + '\nSOURCE_ROWS = ' + repr(pins) + '\nFIELDS = ' + repr(FIELDS) + '\nLOCAL_INPUTS = {}\n'
    fragment = bodies[HERE / 'native-origin-transport-prelude-v1-2026-10-18.py'].decode('utf-8')
    source = replace_once(source, '\n\n# Apply the existing finite SSH-log bound', constants + '\n' + fragment + '\n\n# Apply the existing finite SSH-log bound')
    prologue = "    packet = {}\n    for name, digest in PINS.items():\n        body = (REPO / 'docs/research/sources' / name).read_bytes()\n        assert len(body) <= 262144 and hashlib.sha256(body).hexdigest() == digest\n        packet[name] = base64.b64encode(body).decode('ascii')\n    raw = json.dumps(packet, sort_keys=True).encode()\n    assert len(raw) <= 65536\n"
    source = replace_once(source, prologue, '    raw = prepare()\n')
    source = replace_once(source, '    assert __debug__ and TRUSTED.read_bytes() == KEYS', "    assert __debug__ and len(sys.argv) in (2, 3) and sys.argv[1] in ('before-stage', 'stage', 'before-observe', 'observe')\n    assert len(sys.argv) == (2 if sys.argv[1].startswith('before-') else 3)\n    assert TRUSTED.read_bytes() == KEYS")
    source = replace_once(source, "shlex.join(['python3', '-I', '-S', '-B', '-c', BOOTSTRAP])]", "shlex.join(['python3', '-I', '-S', '-B', '-c', BOOTSTRAP, sys.argv[1], PACKET_SHA, 'NONE' if len(sys.argv) == 2 else sys.argv[2]])]")
    source = replace_once(source, '    LOCAL.mkdir(mode=0o700, exist_ok=False)\n', "    LOCAL.mkdir(mode=0o700, exist_ok=False)\n    with (LOCAL / 'wire.json').open('xb') as retained:\n        retained.write(raw); retained.flush(); os.fsync(retained.fileno())\n    _, wire_row = local_read(LOCAL / 'wire.json', {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, record=False)\n")
    source = replace_once(source, "'source_sha256': PINS, 'command': command,", "'source_sha256': PINS, 'command': command,\n                    'input_wire': wire_row, 'base_packet_sha256': PACKET_SHA,\n                    'control_source_sha256': BOOTSTRAP_SHA, 'local_input_inventory': LOCAL_INPUTS,")
    source = replace_once(source, '# Authenticate two reviewed operational sources and dispatch one retained-binary DATA operation.', '# Dispatch one explicit phase after pinned local prerequisite checks without retries.')
    proposed = source.encode('utf-8')
    tree = ast.parse(proposed)
    for name in ('limits', 'interrupt'):
        old = next(node for node in old_tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        new = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        assert ast.dump(old, include_attributes=False) == ast.dump(new, include_attributes=False)
    old_main = next(node for node in old_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    new_main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    old_try = next(node for node in old_main.body if isinstance(node, ast.Try))
    new_try = copy.deepcopy(next(node for node in new_main.body if isinstance(node, ast.Try)))
    for node in ast.walk(new_try):
        if isinstance(node, ast.Dict):
            indexes = [index for index, key in enumerate(node.keys) if isinstance(key, ast.Constant) and key.value in ('input_wire', 'base_packet_sha256', 'control_source_sha256', 'local_input_inventory')]
            for index in reversed(indexes):
                del node.keys[index]
                del node.values[index]
    assert ast.dump(old_try, include_attributes=False) == ast.dump(new_try, include_attributes=False)
    inventory = {}
    for label, raw in (('bootstrap', bootstrap.encode()), ('prelude', fragment.encode()), ('transport', proposed), ('builder', bodies[Path(__file__)])):
        parsed, lines = ast.parse(raw), raw.decode().splitlines()
        functions = [node for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)]
        assert all(lines[min([node.lineno] + [decorator.lineno for decorator in node.decorator_list]) - 2].lstrip().startswith('# ') for node in functions)
        inventory[label] = {'bytes': len(raw), 'sha256': sha(raw), 'purpose_functions': len(functions)}
    fixed_wire = (json.dumps({'base_packet_base64': base64.b64encode(packet_raw).decode('ascii'), 'prerequisite_base64': None}, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    assert len(fixed_wire) <= 65536
    report = {'schema': 'native-origin-controls-SOURCE-review/1', 'source_inventory': inventory,
        'base_packet': {'bytes': len(packet_raw), 'sha256': packet_sha}, 'fixed_before_wire_bytes': len(fixed_wire),
        'decoded_files': 4, 'decoded_bytes': sum(len(bodies[path]) for path in payload_paths.values()),
        'compressed_bytes': sum(item['gzip_bytes'] for item in files.values()),
        'old_limits_and_interrupt_AST_equal': True, 'owned_transport_try_AST_equal_except_four_receipt_fields': True,
        'all_remote_controls_and_reader_bodies_UNRUN': True, 'staging_runtime': None, 'observation_runtime': None,
        'actual_prerequisites': None, 'admission': None, 'native_runtime_admission': None}
    ROOT.mkdir(mode=0o700, exist_ok=False)
    generated = {}
    generated[ROOT / 'packet.json'] = write(ROOT / 'packet.json', packet_raw)
    destination = HERE / 'native-origin-control-transport-v1-2026-10-18.py'
    generated[destination] = write(destination, proposed)
    for path, row in list(generated.items()):
        bodies[path], inputs[path] = read(path, row)
    assert sum(row['bytes'] for row in inputs.values()) <= 1048576
    retained = {}
    for index, (path, raw) in enumerate(bodies.items()):
        target = ROOT / ('input-%02d-' % index + path.name)
        retained[str(path)] = {'original': inputs[path], 'copy_path': str(target), 'copy': write(target, raw)}
    report_raw = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('ascii')
    report_row = write(ROOT / 'source-review.json', report_raw)
    for path, row in inputs.items():
        read(path, row)
        item = retained[str(path)]
        read(Path(item['copy_path']), item['copy'])
    read(ROOT / 'source-review.json', report_row)
    manifest = {'schema': 'native-origin-control-local-preservation/1', 'files': len(inputs),
        'bytes': sum(row['bytes'] for row in inputs.values()), 'inputs': retained, 'source_review': report_row,
        'all_remote_controls_UNRUN': True, 'remote_page_target_native_json_UNREAD': True,
        'software_file_bound': 262144, 'software_input_bound': 1048576, 'software_hash_work_bound': 4194304,
        'Mac_AS_kernel_FSIZE_crash_durability_claim': False}
    manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('ascii')
    manifest_row = write(ROOT / 'manifest.json', manifest_raw)
    for directory in (ROOT, ROOT.parent.resolve(strict=True), HERE):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'root': str(ROOT), 'source_review': report_row, 'manifest': manifest_row,
        'files': len(inputs), 'bytes': manifest['bytes'], 'report': report, 'hash_work_final': WORK}, sort_keys=True))


if __name__ == '__main__':
    main()
