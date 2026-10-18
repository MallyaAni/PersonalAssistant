"""Preserve exact native HEAD controls and small proof without replaying observations."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import warnings

RESEARCH = Path(__file__).resolve().parent.parent
SOURCES = RESEARCH / 'sources'
EVIDENCE = Path('/tmp/capacity-native-path-head-evidence-20261018-v1')
REPRODUCTION = Path('/tmp/capacity-native-path-head-reproduction-20261018-v1')
CAP = 262144
EXPECTED = {
    'prepare-native-path-head-v1-2026-10-18.py': ('71495dd12d1e7d94c84778a4075c37967a377e8fbaf8579e87b59356a4c35e01', 12531),
    'capacity-native-path-head-v1-2026-10-18.py': ('096adba1b0d8163ab1ce7f9e7253dab9033682cc0e49fe9e639d8e6a87b978ce', 28952),
    'verify-native-path-head-v1-2026-10-18.py': ('a1800d2d0625599e676c139c35438969e1924654aebd74e3c975f3359810f473', 30511),
    'native-path-head-primary-transport-v1-2026-10-18.py': ('025ba96b3875366ef81e472b6fb347d9bed7e8c27d9217221e0b65d90a50bbea', 6014),
    'native-path-head-independent-transport-v1-2026-10-18.py': ('d4539e41dbabd2831935f0cb3d5a6c91c65f287e7b13ba47ccc952878c210126', 6015),
}
OLD = {
    'capacity-package-metadata-head-v1-2026-10-18.py': '17617e37bb685c7fb40767c750ceb79c0ff2745a8adf9095fade5ac5f850d0bb',
    'verify-package-metadata-head-v1-2026-10-18.py': '6c17116d9bb1334b7a1e33ebc0ed64867916b56428c24941f077427567ea04ee',
    'capacity-package-metadata-text-census-v2-2026-10-18.py': 'd9cadb938ca5d78d722c4b1974a778130962f4d84d69fcfac43d5f7eaa32960c',
    'capacity-native-package-text-transport-v1-2026-10-18.py': '518ded7394ae1b04db85f32b89e15693086f8e184c231ac2b891391d2f749b08',
}


# Read finite regular controls twice with held and named lossless physical identity.
def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= CAP
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
        physical = {k: str(getattr(before, k)) for k in fields}
        first = os.read(fd, CAP + 1)
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, CAP + 1) == first and len(first) == before.st_size
        assert physical == {k: str(getattr(os.fstat(fd), k)) for k in fields}
        assert physical == {k: str(getattr(path.stat(follow_symlinks=False), k)) for k in fields}
        return first, {'bytes': len(first), 'sha256': hashlib.sha256(first).hexdigest(), 'physical': physical}
    finally:
        os.close(fd)


# Save a fresh bounded artifact with exact readback and file plus directory synchronization.
def write(path, raw):
    assert len(raw) <= CAP
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(path)[0] == raw
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.fsync(fd); os.close(fd)


# Extract exact function ASTs for a declared operational reuse comparison.
def functions(raw):
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        tree = ast.parse(raw)
    result = {}
    lines = raw.decode().splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            assert lines[first - 2].lstrip().startswith('#'), node.name
            result[node.name] = ast.dump(node, include_attributes=False)
    return result


# Verify actual small output, reproduce only new control source, and preserve exclusive local evidence.
def main(arguments):
    assert len(arguments) == 1 and len(arguments[0]) == 64
    raw, proof_row = read(Path('/tmp/capacity-native-path-head-independent-transport-20261018-v1/stdout'))
    assert proof_row['sha256'] == arguments[0]
    proof = json.loads(raw)
    assert proof['status'] == 'VERIFIED_RETAINED_PAIRED_DAEMON_PATH_METADATA_ONLY'
    assert proof['files'] == len(proof['inventory']) == 129 and len(proof['path_observations']) == 20
    assert proof['candidate_sha256'] == '52363e510d61b6d3c3964fef6ab099bb270aeee124c849e1f66ef01a649a7723'
    seam_raw, seam_row = read(RESEARCH / 'original-loader-package-metadata-record-seams-v1-2026-10-18.json')
    assert seam_row['sha256'] == '15f8249875d0aef99b9f48d0e3eb9c1971cf85d23fefc09d27d9ed7538325128'
    declarations = json.loads(seam_raw)['native_filename_declarations']['selected_candidates']
    assert [r['declaration'] for r in proof['path_observations']] == declarations
    for observed in proof['path_observations']:
        meta, declaration = observed['path_metadata'], observed['declaration']
        assert meta['http_status'] == 200 and meta['content_read_authorized'] is False
        assert meta['stat']['linkTarget'] == '' and 0 <= meta['stat']['mode'] <= 4095
        assert meta['stat']['size'] == int(declaration['declared_size_decimal'])
    REPRODUCTION.mkdir(mode=0o700, exist_ok=False)
    reproduced_sources = REPRODUCTION / 'sources'
    reproduced_sources.mkdir(mode=0o700)
    contents, pins, purpose = {}, {}, {}
    for name, expected in EXPECTED.items():
        contents[name], pins[name] = read(SOURCES / name)
        assert (pins[name]['sha256'], pins[name]['bytes']) == expected
        purpose[name] = len(functions(contents[name]))
    for name, sha in OLD.items():
        old_raw, old_row = read(SOURCES / name)
        assert old_row['sha256'] == sha
        write(reproduced_sources / name, old_raw)
    write(REPRODUCTION / 'original-loader-package-metadata-record-seams-v1-2026-10-18.json', seam_raw)
    builder = 'prepare-native-path-head-v1-2026-10-18.py'
    write(reproduced_sources / builder, contents[builder])
    for argv in (['primary'], ['independent', proof['candidate_sha256']]):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(reproduced_sources / builder)] + argv,
            capture_output=True, timeout=10, check=True)
        assert not result.stderr and len(result.stdout) <= CAP
    for name in EXPECTED:
        assert read(reproduced_sources / name)[0] == contents[name]
    primary_ast = functions(contents['capacity-native-path-head-v1-2026-10-18.py'])
    independent_ast = functions(contents['verify-native-path-head-v1-2026-10-18.py'])
    old_primary = functions((SOURCES / 'capacity-package-metadata-head-v1-2026-10-18.py').read_bytes())
    old_independent = functions((SOURCES / 'verify-package-metadata-head-v1-2026-10-18.py').read_bytes())
    compared = []
    for name in ('digest', 'save', 'save_json', 'alarm', 'client_limits', 'command', 'inspect_source'):
        assert primary_ast[name] == old_primary[name]
        compared.append('primary:' + name)
    for name in ('physical', 'read'):
        assert primary_ast[name] == old_independent[name]
        compared.append('primary:' + name)
    for name in ('physical', 'read', 'digest', 'save', 'save_json', 'alarm', 'client_limits', 'command', 'decode'):
        assert independent_ast[name] == old_independent[name]
        compared.append('independent:' + name)
    assert primary_ast['inspection'] == independent_ast['inspection']
    compared.append('shared:inspection')
    observations = {}
    for role in ('primary', 'independent'):
        root = Path('/tmp/capacity-native-path-head-' + role + '-transport-20261018-v1')
        terminal = json.loads(read(root / 'exit.json')[0])
        assert terminal['exit'] == 0 and terminal['failure_class'] is None
        assert terminal['cleanup_failure_class'] is None and terminal['owned_SSH_group_stop'] is None
        assert read(root / 'stderr')[0] == b''
        observations[role] = terminal
    assert json.loads(read(Path('/tmp/capacity-native-path-head-primary-transport-20261018-v1/stdout'))[0])['sha256'] == proof['candidate_sha256']
    evidence = {
        'schema': 'native-path-head-controls-static/1', 'pins': pins, 'purpose_comments': purpose,
        'exact_function_AST_comparisons': compared, 'new_four_outputs_byte_exact_reproduction': True,
        'AST_warnings_as_errors': 'PASS', 'exact20_DECLARATIONS_and_observed_sizes': True,
        'transport_exit0_empty_stderr_no_owned_stop_cleanup_failure': True,
        'old_gates_payloads_tests': 'NOT_RUN', 'timeout_missing_size_type_signal_overflow_crash_branches': 'UNTESTED',
        'Ruff': 'PREVIOUSLY_UNAVAILABLE_NO_LINT_CLAIM',
    }
    static_raw = json.dumps(evidence, sort_keys=True, indent=2).encode() + b'\n'
    write(RESEARCH / 'original-loader-native-path-head-static-v1-2026-10-18.json', static_raw)
    write(RESEARCH / 'original-loader-native-path-head-independent-v1-2026-10-18.json', raw)
    EVIDENCE.mkdir(mode=0o700, exist_ok=False)
    to_copy = [(SOURCES / name, name) for name in EXPECTED]
    to_copy += [(Path(__file__), Path(__file__).name),
        (RESEARCH / 'original-loader-native-path-head-static-v1-2026-10-18.json', 'static.json'),
        (RESEARCH / 'original-loader-native-path-head-independent-v1-2026-10-18.json', 'independent.json'),
        (RESEARCH / 'original-loader-package-metadata-record-seams-v1-2026-10-18.json', 'declaration-seams.json')]
    for role in ('primary', 'independent'):
        root = Path('/tmp/capacity-native-path-head-' + role + '-transport-20261018-v1')
        to_copy.extend((root / name, role + '-' + name) for name in ('stdout', 'stderr', 'exit.json'))
    manifest = []
    for source, name in to_copy:
        body, original = read(source)
        write(EVIDENCE / name, body)
        copied, copy_row = read(EVIDENCE / name)
        assert copied == body and read(source) == (body, original)
        manifest.append({'source': str(source), 'name': name, 'original': original, 'copy': copy_row})
    manifest_raw = json.dumps({'schema': 'native-path-head-local-evidence/1', 'files': manifest},
        sort_keys=True, indent=2).encode() + b'\n'
    write(EVIDENCE / 'manifest.json', manifest_raw)
    for directory in (reproduced_sources, REPRODUCTION, REPRODUCTION.parent.resolve(strict=True),
        EVIDENCE, EVIDENCE.parent.resolve(strict=True)):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(fd); os.close(fd)
    result = {'schema': 'native-path-head-local-preservation/1', 'root': str(EVIDENCE), 'files': len(manifest),
        'data_bytes': sum(r['copy']['bytes'] for r in manifest), 'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(),
        'manifest_bytes': len(manifest_raw), 'files_readbacks_root_resolved_parent_fsync': True,
        'source_reproduction_root': str(REPRODUCTION), 'crash_or_second_full_remote_archive_guarantee': False}
    write(RESEARCH / 'original-loader-native-path-head-preservation-v1-2026-10-18.json',
        json.dumps(result, sort_keys=True, indent=2).encode() + b'\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
