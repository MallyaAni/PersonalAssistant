"""Check new operational source bindings and preserve only small local control evidence."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import warnings

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
RESEARCH = REPO / 'docs/research'
SOURCES = RESEARCH / 'sources'
ROOT = Path('/tmp/capacity-package-metadata-head-evidence-20261018-v1')
CAP = 262144
CONTROLS = {
    'prepare-package-metadata-head-v1-2026-10-18.py': '8e9bc16a102cb689dc4184c94af53af9f28791f7ae35ebea0b71a03d4de9e65b',
    'capacity-package-metadata-head-v1-2026-10-18.py': '17617e37bb685c7fb40767c750ceb79c0ff2745a8adf9095fade5ac5f850d0bb',
    'capacity-package-metadata-head-transport-v1-2026-10-18.py': 'e563f027aa601f6860d372e8f875a0e4c9cfbf7db0de92af9e99313b2508eb5b',
    'prepare-package-metadata-head-independent-v1-2026-10-18.py': 'b9c456cf8fac0cdea336dee43cc585dee5f5a9c35e501794cc298d5c4dbae18b',
    'verify-package-metadata-head-v1-2026-10-18.py': '6c17116d9bb1334b7a1e33ebc0ed64867916b56428c24941f077427567ea04ee',
    'package-metadata-head-independent-transport-v1-2026-10-18.py': 'ab334e55fe905bd268bacb5228b27f8922468318ad5bdcfb350202a1eacc508c'
}


# Preserve exact physical fields as decimal strings rather than lossy floating numbers.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Authenticate one small local file through two complete held-descriptor reads and named bookends.
def read(path, expected=None):
    path = path.resolve(strict=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'physical': physical(before)}
        if expected is not None:
            assert row['sha256'] == expected
        return raw, row
    finally:
        os.close(descriptor)


# Verify declared AST reuse and transport terminals, then retain exact bounded evidence copies and sync them.
def main():
    warnings.simplefilter('error')
    trees, controls, purpose = {}, {}, 0
    for name, sha in CONTROLS.items():
        raw, row = read(SOURCES / name, sha)
        tree = ast.parse(raw)
        lines = raw.decode().splitlines()
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert all(lines[min([node.lineno] + [item.lineno for item in node.decorator_list]) - 2].lstrip().startswith('# ')
            for node in functions)
        purpose += len(functions)
        controls[name] = row
        trees[name] = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert purpose == 34
    old_collector = ast.parse((SOURCES / 'capacity-native-package-text-census-v1-2026-10-18.py').read_bytes())
    old_checker = ast.parse((SOURCES / 'verify-native-package-text-census-v1-2026-10-18.py').read_bytes())
    originals = [{node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for tree in (old_collector, old_checker)]
    reused = (('digest', 'save', 'save_json', 'alarm', 'client_limits', 'inspect_source'),
        ('physical', 'read', 'digest', 'save', 'save_json', 'alarm', 'client_limits'))
    names = ('capacity-package-metadata-head-v1-2026-10-18.py', 'verify-package-metadata-head-v1-2026-10-18.py')
    for original, selected, name in zip(originals, reused, names):
        candidate = trees[name]
        assert all(ast.dump(original[key], include_attributes=False) == ast.dump(candidate[key], include_attributes=False)
            for key in selected)
        original['command'].body[0] = candidate['command'].body[0]
        assert ast.dump(original['command'], include_attributes=False) == ast.dump(candidate['command'], include_attributes=False)
    reproduction = Path('/tmp/capacity-package-metadata-head-control-reproduction-20261018-v1')
    for name in (names[0], names[1], 'capacity-package-metadata-head-transport-v1-2026-10-18.py',
            'package-metadata-head-independent-transport-v1-2026-10-18.py'):
        assert read(reproduction / name)[0] == read(SOURCES / name, CONTROLS[name])[0]
    observations = []
    inputs = [(name, SOURCES / name) for name in CONTROLS]
    inputs += [('preserver.py', Path(__file__)),
        ('contract.json', RESEARCH / 'original-loader-package-metadata-head-contract-v1-2026-10-18.json'),
        ('independent.json', RESEARCH / 'original-loader-package-metadata-head-independent-v1-2026-10-18.json')]
    for label, directory in (('primary', '/tmp/capacity-package-metadata-head-transport-20261018-v1'),
            ('independent', '/tmp/capacity-package-metadata-head-independent-transport-20261018-v1')):
        root = Path(directory)
        receipt = json.loads(read(root / 'exit.json')[0])
        assert receipt['exit'] == 0 and receipt['owned_SSH_group_stop'] is None
        assert receipt['failure_class'] is None and receipt['cleanup_failure_class'] is None
        assert read(root / 'stderr')[0] == b''
        observations.append({'label': label, 'exit': 0, 'stderr_bytes': 0, 'owned_stop': None, 'cleanup_failure': None})
        inputs += [(label + '-' + name, root / name) for name in ('stdout', 'stderr', 'exit.json')]
    proof_raw, proof_row = read(RESEARCH / 'original-loader-package-metadata-head-independent-v1-2026-10-18.json',
        '4a30076a7e6b530b7e24ffa1990abeb6d7a817974d96ef3d6f8100b1e7e111ab')
    proof = json.loads(proof_raw)
    assert proof['files'] == 44 and proof['candidate_sha256'] == '42d6171789b08b0b2b9c305a6fe564829982befd752b1779813de4edc4ac64af'
    assert [row['path_metadata']['stat']['size'] for row in proof['path_observations']] == [3031, 78313, 6635, 111517, 62353, 201096]
    assert all(row['path_metadata']['http_status'] == 200 and row['path_metadata']['content_read_authorized'] is False
        for row in proof['path_observations'])
    static = {'schema': 'package-metadata-head-controls-static/1', 'controls': controls,
        'purpose_comments_across_six_dispatch_build_controls': purpose,
        'AST_warnings_as_errors': 'PASS', 'unchanged_reused_function_ASTs': 13,
        'two_command_functions_only_allowlist_assertion_changed': True,
        'four_generated_controls_byte_exact_reproduction': True, 'transports': observations,
        'independent_raw_proof': proof_row,
        'Ruff': 'PREVIOUSLY_UNAVAILABLE_NO_LINT_CLAIM',
        'package_payload_CodeType_import_body_or_old_gate_replay': False,
        'timeout_signal_overflow_owned_stop_crash_branches': 'UNTESTED'}
    static_path = RESEARCH / 'original-loader-package-metadata-head-controls-static-v1-2026-10-18.json'
    raw = json.dumps(static, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= CAP
    with static_path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    inputs.append(('static.json', static_path))
    ROOT.mkdir(mode=0o700, exist_ok=False)
    manifest, total = [], 0
    for name, path in inputs:
        raw, original = read(path)
        destination = ROOT / name
        with destination.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        copied, saved = read(destination)
        assert copied == raw and saved['sha256'] == original['sha256'] and saved['bytes'] == original['bytes']
        manifest.append({'file': name, 'source': str(path), 'original': original, 'copy': saved})
        total += len(raw)
    raw = json.dumps({'schema': 'local-package-metadata-head-evidence/1', 'files': manifest,
        'data_bytes': total, 'file_readback_and_root_resolved_parent_fsync': True,
        'crash_durability_guarantee': False}, sort_keys=True, indent=2).encode() + b'\n'
    assert len(raw) <= CAP
    with (ROOT / 'manifest.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(ROOT / 'manifest.json')[0] == raw
    for directory in (ROOT.resolve(strict=True), ROOT.parent.resolve(strict=True), reproduction.resolve(strict=True)):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for path in reproduction.iterdir():
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    result = {'schema': 'package-metadata-head-local-preservation/1', 'root': str(ROOT),
        'files': len(manifest), 'data_bytes': total, 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'manifest_bytes': len(raw), 'file_readback_root_resolved_parent_fsync': True}
    output = json.dumps(result, sort_keys=True, indent=2).encode() + b'\n'
    with (RESEARCH / 'original-loader-package-metadata-head-preservation-v1-2026-10-18.json').open('xb') as stream:
        stream.write(output); stream.flush(); os.fsync(stream.fileno())
    print(output.decode(), end='')


if __name__ == '__main__':
    main()
