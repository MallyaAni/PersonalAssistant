"""Validate and retain bounded local metadata-declaration controls and actual receipts."""
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
ROOT = Path('/tmp/capacity-package-metadata-record-evidence-20261018-v1')
CAP = 262144
PINS = {
    'analyze-package-metadata-records-v1-2026-10-18.py': '3cec8db1f812ae6d44af397ace2cf3637d96e284cdd91f700ded89d8665cc029',
    'verify-package-metadata-records-v1-2026-10-18.py': '8d50d3e16e60fdf28c22239a3fce48d52cfedf695a4778de2737a3b8369e2e06',
    'package-metadata-record-analysis-transport-v1-2026-10-18.py': '26330657173e61a1fba507a43865c0e54f637655d0d3418364f3ed7d3933d366',
    'package-metadata-record-independent-transport-v1-2026-10-18.py': '54d3640b3f350bad9a370d5285bc09161ab1385554f855893e07710a32944262'
}


# Preserve physical metadata with exact decimal strings.
def physical(value):
    return {key: str(getattr(value, key)) for key in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Bind a bounded local file using two full held-descriptor reads and named physical bookends.
def read(path, expected=None):
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
        if expected is not None:
            assert row['sha256'] == expected
        return raw, row
    finally:
        os.close(descriptor)


# Check new source and declaration bindings before preserving small local evidence in an exclusive root.
def main():
    warnings.simplefilter('error')
    names = list(PINS) + ['prepare-metadata-record-transports-v1-2026-10-18.py']
    controls, trees, purposes = {}, {}, 0
    for name in names:
        raw, row = read(SOURCES / name, PINS.get(name))
        text, tree = raw.decode(), ast.parse(raw)
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert all(text.splitlines()[min([n.lineno] + [d.lineno for d in n.decorator_list]) - 2].lstrip().startswith('# ')
            for n in functions)
        purposes += len(functions); controls[name] = row
        trees[name] = {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert purposes == 21
    assert all(trees[names[0]][name] == trees[names[1]][name] for name in ('physical', 'read'))
    original = ast.parse((SOURCES / 'capacity-native-package-text-transport-v1-2026-10-18.py').read_bytes())
    original_functions = {n.name: ast.dump(n, include_attributes=False) for n in original.body if isinstance(n, ast.FunctionDef)}
    assert all(trees[transport][name] == original_functions[name] for transport in names[2:4] for name in ('limits', 'interrupt'))
    summary_name = 'original-loader-package-metadata-record-analysis-v1-2026-10-18.json'
    proof_name = 'original-loader-package-metadata-record-independent-v1-2026-10-18.json'
    seam_name = 'original-loader-package-metadata-record-seams-v1-2026-10-18.json'
    summary_raw, summary_row = read(RESEARCH / summary_name, '180359449b7d1a3085ad2a50a63f027da28b199f6ecb0559861f098920c7f976')
    proof_raw, proof_row = read(RESEARCH / proof_name, 'a5565ba52c801a79dd45cce0d5cb75564d2fe01da0cd85f87aaba7a8e0300362')
    summary, proof, seam = json.loads(summary_raw), json.loads(proof_raw), json.loads(read(RESEARCH / seam_name)[0])
    assert proof['summary']['sha256'] == summary_row['sha256'] and proof['summary']['bytes'] == summary_row['bytes']
    assert summary['total_record_rows'] == proof['total_record_rows'] == 4615
    assert summary['native_filename_declaration_count'] == proof['native_filename_declaration_count'] == 167
    assert len(proof['pages']) == len(summary['pages']) == 73 and len(proof['sources']) == 6
    assert sum(r['bytes'] for r in summary['pages']) == 2633114 and max(r['bytes'] for r in summary['pages']) == 40523
    assert [r['record_count'] for r in summary['packages']] == [860, 1336, 2419]
    assert all(r['metadata_identity_matches_source_literals'] is True for r in summary['packages'])
    assert all(r['RECORD_self_declaration']['declared_hash'] is None and r['RECORD_self_declaration']['declared_size_decimal'] is None for r in summary['packages'])
    declared = {row['fields'][0]: (package, row) for package in summary['packages'] for row in package['native_filename_declarations']}
    selected = seam['native_filename_declarations']['selected_candidates']
    assert len(selected) == 20 and len({r['relative_path'] for r in selected}) == 20
    for row in selected:
        package, source = declared[row['relative_path']]
        assert row['RECORD_source_sha256'] == package['record_source']['sha256']
        assert row['record_index'] == source['record_index'] and row['CSV_end_line'] == source['CSV_end_line']
        assert row['declared_hash'] == source['declared_hash'] and row['declared_size_decimal'] == source['declared_size_decimal']
        assert row['lexical_absolute_path'] == source['lexical_absolute_path'] and row['actual_path_file_hash_ELF_or_load_observed'] is False
    assert seam['native_filename_declarations']['declared_bytes_sum'] == str(sum(int(row['declared_size_decimal'] or 0) for _, row in declared.values())) == '264733848'
    inputs = [(name, SOURCES / name) for name in names] + [('preserver.py', Path(__file__))]
    inputs += [(name, RESEARCH / name) for name in (summary_name, proof_name, seam_name)]
    outcomes = []
    for label in ('analysis', 'independent'):
        directory = Path('/tmp/capacity-package-metadata-record-' + label + '-transport-20261018-v1')
        receipt = json.loads(read(directory / 'exit.json')[0])
        assert receipt['exit'] == 0 and receipt['owned_SSH_group_stop'] is None
        assert receipt['failure_class'] is None and receipt['cleanup_failure_class'] is None
        assert read(directory / 'stderr')[0] == b''
        expected = summary_raw if label == 'analysis' else proof_raw
        assert read(directory / 'stdout')[0] == expected
        outcomes.append({'label': label, 'exit': 0, 'stderr_bytes': 0, 'owned_stop': None, 'cleanup_failure': None})
        inputs += [(label + '-' + name, directory / name) for name in ('stdout', 'stderr', 'exit.json')]
    static = {'schema': 'package-metadata-record-controls-static/1', 'controls': controls,
        'AST_warnings_as_errors': 'PASS', 'purpose_comments_across_five_controls': purposes,
        'exact_utility_AST_comparisons': 6, 'transports': outcomes,
        'summary': summary_row, 'independent': proof_row,
        'all20_selected_native_declarations_exact': True,
        'Ruff': 'PREVIOUSLY_UNAVAILABLE_NO_LINT_CLAIM',
        'timeout_invalid_input_signal_crash_branches': 'UNTESTED',
        'packaging_spec_full_compliance_or_runtime_native_RAM_acceptance': False}
    static_path = RESEARCH / 'original-loader-package-metadata-record-controls-static-v1-2026-10-18.json'
    raw = json.dumps(static, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= CAP
    with static_path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    inputs.append(('static.json', static_path))
    ROOT.mkdir(mode=0o700, exist_ok=False)
    manifest, total = [], 0
    for name, path in inputs:
        raw, original = read(path)
        target = ROOT / name
        with target.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        copied, copy_row = read(target)
        assert copied == raw and copy_row['sha256'] == original['sha256']
        manifest.append({'file': name, 'source': str(path), 'original': original, 'copy': copy_row})
        total += len(raw)
    raw = json.dumps({'schema': 'local-package-metadata-record-evidence/1', 'files': manifest,
        'data_bytes': total, 'files_readback_root_resolved_parent_fsync': True,
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
    observation = {'schema': 'package-metadata-record-local-preservation/1', 'root': str(ROOT),
        'files': len(manifest), 'data_bytes': total, 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'manifest_bytes': len(raw), 'files_readback_root_resolved_parent_fsync': True}
    raw = json.dumps(observation, sort_keys=True, indent=2).encode() + b'\n'
    with (RESEARCH / 'original-loader-package-metadata-record-preservation-v1-2026-10-18.json').open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    print(raw.decode(), end='')


if __name__ == '__main__':
    main()
