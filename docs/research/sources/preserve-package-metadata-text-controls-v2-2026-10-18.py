"""Validate new operational controls and preserve bounded local failure/success evidence."""
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
ROOT = Path('/tmp/capacity-package-metadata-text-evidence-20261018-v2')
CAP = 262144
PINS = {
    'capacity-package-metadata-text-census-v1-2026-10-18.py': 'a9af8e55fb60b2b950aeada945b7e0ac354fe853a3efeeb6ba4809ba8c226a60',
    'package-metadata-text-transport-v1-2026-10-18.py': '24c8a8f5e57fd0f40908b079ae49126f137218ef12f99387cf14f3eda491cbe5',
    'package-metadata-text-inspect-diagnostic-v1-2026-10-18.py': '13e43d68900d6dc8db90a92bdebceacbf15134d04b7f18fd6548ba41d850ba88',
    'package-metadata-text-diagnostic-transport-v1-2026-10-18.py': '99d256c7b79745a5c4aadc6b1420ba879dff739115abe5c2951b81bcc051bd5d',
    'capacity-package-metadata-text-census-v2-2026-10-18.py': 'd9cadb938ca5d78d722c4b1974a778130962f4d84d69fcfac43d5f7eaa32960c',
    'package-metadata-text-transport-v2-2026-10-18.py': 'abdaf8579552cb3f4f7d2d0e8e7e972dc9f7079b6badb66bc585c9e06df80691',
    'verify-package-metadata-text-census-v2-2026-10-18.py': '4ad058e882c789d4fc9aa7d85d0005775c0cd770c32ca1dc3164d9d4067b6cec',
    'package-metadata-text-independent-transport-v2-2026-10-18.py': '6e09a48d774edee878b744188d64946db7ffafc9550e3f368cc815a6c3912318',
    'prepare-package-metadata-text-v1-2026-10-18.py': 'e9353d70679a000b8956f23aa43dede3b59c240044b85ce79d9585b99db1f58b',
    'prepare-package-metadata-text-v2-2026-10-18.py': '39a1b99fa68ed2ab64470f9b2ecb27a421a3ff315cb2c1589fcdbcd7503c74ea',
    'prepare-package-metadata-text-independent-v2-2026-10-18.py': '8d8db027baf76a6ec46fea50d0acbe43bb4ae7cd36ab90979012025155e5b605'
}


# Encode exact physical identities as lossless decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Read one bounded local evidence file twice using a held descriptor and named physical bookends.
def read(path, sha=None):
    path = path.resolve(strict=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1
        assert 0 <= before.st_size <= CAP
        raw = os.read(descriptor, CAP + 1); os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == before.st_size
        assert physical(before) == physical(os.fstat(descriptor)) == physical(path.stat(follow_symlinks=False))
        row = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': physical(before)}
        if sha is not None:
            assert row['sha256'] == sha
        return raw, row
    finally:
        os.close(descriptor)


# Check declared source reuse and all four transport outcomes, then preserve exact small local evidence.
def main():
    warnings.simplefilter('error')
    trees, controls, purpose = {}, {}, 0
    for name, sha in PINS.items():
        raw, row = read(SOURCES / name, sha)
        text, tree = raw.decode(), ast.parse(raw)
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert all(text.splitlines()[min([node.lineno] + [decorator.lineno for decorator in node.decorator_list]) - 2].lstrip().startswith('# ')
            for node in functions)
        purpose += len(functions)
        controls[name] = row
        trees[name] = {node.name: ast.dump(node, include_attributes=False) for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert purpose == 63
    old = ast.parse((SOURCES / 'capacity-native-package-text-census-v1-2026-10-18.py').read_bytes())
    old_functions = {node.name: ast.dump(node, include_attributes=False) for node in old.body if isinstance(node, ast.FunctionDef)}
    v1 = trees['capacity-package-metadata-text-census-v1-2026-10-18.py']
    v2 = trees['capacity-package-metadata-text-census-v2-2026-10-18.py']
    preserved = ('digest', 'save', 'save_json', 'alarm', 'client_limits', 'command', 'inspect_source')
    assert all(v1[name] == old_functions[name] for name in preserved)
    assert all(v2[name] == body for name, body in v1.items() if name != 'main')
    old_checker = ast.parse((SOURCES / 'verify-native-package-text-census-v1-2026-10-18.py').read_bytes())
    old_checker_functions = {node.name: ast.dump(node, include_attributes=False) for node in old_checker.body if isinstance(node, ast.FunctionDef)}
    checker = trees['verify-package-metadata-text-census-v2-2026-10-18.py']
    inherited = ('physical', 'read', 'digest', 'save', 'save_json', 'alarm', 'client_limits')
    assert all(checker[name] == old_checker_functions[name] for name in inherited)
    assert all(v1[name] == old_checker_functions[name] for name in ('physical', 'read'))
    inputs = [(name, SOURCES / name) for name in PINS]
    inputs.append(('preserver.py', Path(__file__)))
    names = ('original-loader-package-metadata-text-contract-v2-2026-10-18.json',
        'original-loader-package-metadata-text-inspect-diagnostic-v1-2026-10-18.json',
        'original-loader-package-metadata-text-independent-v2-2026-10-18.json')
    for name in names:
        json.loads(read(RESEARCH / name)[0])
        inputs.append((name, RESEARCH / name))
    diagnostic_raw, diagnostic_row = read(RESEARCH / names[1], '7ec16ed395d9b1d75f542a7001e43aede48462accb066e9ae3005561a91cd85f')
    diagnostic = json.loads(diagnostic_raw)
    assert len(diagnostic['failed_root_inventory']) == 5 and len(diagnostic['all_JSON_differences']) == 6
    assert diagnostic['all_nonMounts_fields_equal'] is True and diagnostic['complete_uniqueDestination_mount_records_equal'] is True
    proof_raw, proof_row = read(RESEARCH / names[2], '2b2ca95aaefdf78103e93b2393faa497419270ad0cc4d009f89684314cd046ba')
    proof = json.loads(proof_raw)
    assert proof['source_files'] == 6 and proof['source_bytes'] == 462945 and proof['full_readback_files'] == 53
    assert all(row['raw_bytes_equal'] is True for row in (proof['inspection_binding']['before'], proof['inspection_binding']['after'], proof['fresh_inspection_binding']))
    outcomes = []
    for label, directory, expected in (
        ('failed-v1', '/tmp/capacity-package-metadata-text-transport-20261018-v1', 1),
        ('diagnostic', '/tmp/capacity-package-metadata-text-diagnostic-transport-20261018-v1', 0),
        ('primary-v2', '/tmp/capacity-package-metadata-text-transport-20261018-v2', 0),
        ('independent-v2', '/tmp/capacity-package-metadata-text-independent-transport-20261018-v2', 0)):
        directory = Path(directory)
        terminal = json.loads(read(directory / 'exit.json')[0])
        assert terminal['exit'] == expected and terminal['owned_SSH_group_stop'] is None
        assert terminal['failure_class'] is None and terminal['cleanup_failure_class'] is None
        stderr = read(directory / 'stderr')[0]
        if expected == 0:
            assert stderr == b''
        else:
            assert b'assert digest(before_raw) == BASELINE' in stderr and read(directory / 'stdout')[0] == b''
        outcomes.append({'label': label, 'exit': expected, 'stderr_bytes': len(stderr), 'owned_stop': None, 'cleanup_failure': None})
        inputs += [(label + '-' + name, directory / name) for name in ('stdout', 'stderr', 'exit.json')]
    static = {'schema': 'package-metadata-text-controls-static/2', 'controls': controls,
        'AST_warnings_as_errors': 'PASS', 'purpose_comments_across_eleven_controls': purpose,
        'exact_utility_function_AST_comparisons': 26, 'transport_outcomes': outcomes,
        'diagnostic': diagnostic_row, 'independent': proof_row,
        'v2_reordered_positive_branch': 'SOURCE_REVIEWED_NOT_EXERCISED_BY_SUCCESSFUL_V2',
        'old_package_gate_packet_or_census_replay': False,
        'Ruff': 'PREVIOUSLY_UNAVAILABLE_NO_LINT_CLAIM',
        'timeout_signal_overflow_owned_stop_crash_branches': 'UNTESTED'}
    static_path = RESEARCH / 'original-loader-package-metadata-text-controls-static-v2-2026-10-18.json'
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
        copied, copied_row = read(destination)
        assert copied == raw and copied_row['sha256'] == original['sha256']
        manifest.append({'file': name, 'source': str(path), 'original': original, 'copy': copied_row})
        total += len(raw)
    raw = json.dumps({'schema': 'local-package-metadata-text-evidence/2', 'files': manifest,
        'data_bytes': total, 'file_readback_root_resolved_parent_fsync': True,
        'crash_durability_guarantee': False}, sort_keys=True, indent=2).encode() + b'\n'
    assert len(raw) <= CAP
    with (ROOT / 'manifest.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(ROOT / 'manifest.json')[0] == raw
    for directory in (ROOT.resolve(strict=True), ROOT.parent.resolve(strict=True)):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    result = {'schema': 'package-metadata-text-local-preservation/2', 'root': str(ROOT),
        'files': len(manifest), 'data_bytes': total, 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'manifest_bytes': len(raw), 'files_readback_root_resolved_parent_fsync': True}
    output = json.dumps(result, sort_keys=True, indent=2).encode() + b'\n'
    with (RESEARCH / 'original-loader-package-metadata-text-preservation-v2-2026-10-18.json').open('xb') as stream:
        stream.write(output); stream.flush(); os.fsync(stream.fileno())
    print(output.decode(), end='')


if __name__ == '__main__':
    main()
