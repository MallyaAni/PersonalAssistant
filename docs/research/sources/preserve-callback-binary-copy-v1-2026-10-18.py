"""Preserve new callback binary-copy controls and proof while native bytes stay on Spark."""
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
CAP = 262144
ROOT = Path('/tmp/capacity-callback-binary-evidence-20261018-v1')
REPRODUCTION = Path('/tmp/capacity-callback-binary-reproduction-20261018-v1')
PINS = {
    'prepare-callback-binary-copy-v1-2026-10-18.py': ('3caf6124e1be90c13ae61d7f47d3162ba4a562d64f1fde5ef3f98787a539aee6', None),
    'capacity-callback-binary-copy-v1-2026-10-18.py': ('ed0411890473c979b7219af30530529817388c0897abf4637d77ff91c120bdac', 16057),
    'verify-callback-binary-copy-v1-2026-10-18.py': ('44f5fd350e71bf0d2e0e987eceb3153e0b156127da657464a9688bddb286acd0', 17473),
    'callback-binary-primary-transport-v1-2026-10-18.py': ('975e2ca84e462a3ba0add2039c0d84b85cf54798ff62a7ef79b3bcb21a88f580', 6016),
    'callback-binary-independent-transport-v1-2026-10-18.py': ('91b9b37cf125151029780a275931fb124c12aeae70260c83df446af7851e131a', 6020),
}
INPUTS = {
    'capacity-package-metadata-text-census-v2-2026-10-18.py': 'd9cadb938ca5d78d722c4b1974a778130962f4d84d69fcfac43d5f7eaa32960c',
    'verify-package-metadata-text-census-v2-2026-10-18.py': '4ad058e882c789d4fc9aa7d85d0005775c0cd770c32ca1dc3164d9d4067b6cec',
    'capacity-native-package-text-transport-v1-2026-10-18.py': '518ded7394ae1b04db85f32b89e15693086f8e184c231ac2b891391d2f749b08',
}
DATA = {
    'original-loader-native-path-head-independent-v1-2026-10-18.json': '6f3696b006cb335a06656501446d2976723ec4649117dd33a31cd03c825adaaa',
    'original-loader-package-metadata-record-seams-v1-2026-10-18.json': '15f8249875d0aef99b9f48d0e3eb9c1971cf85d23fefc09d27d9ed7538325128',
}


# Bind a bounded regular local file using two full reads and held plus named decimal physical fields.
def read(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        value = os.fstat(descriptor)
        assert stat.S_ISREG(value.st_mode) and value.st_nlink == 1 and value.st_size <= CAP
        keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
        fields = {key: str(getattr(value, key)) for key in keys}
        raw = os.read(descriptor, CAP + 1)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, CAP + 1) == raw and len(raw) == value.st_size
        assert fields == {key: str(getattr(os.fstat(descriptor), key)) for key in keys}
        assert fields == {key: str(getattr(path.stat(follow_symlinks=False), key)) for key in keys}
        return raw, {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'physical': fields}
    finally:
        os.close(descriptor)


# Save an exclusive bounded artifact with full readback and synchronized file and parent.
def write(path, raw):
    assert len(raw) <= CAP
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    assert read(path)[0] == raw
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.fsync(descriptor); os.close(descriptor)


# Check purpose comments and produce function ASTs without importing operational or native payloads.
def functions(raw):
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        tree = ast.parse(raw)
    lines = raw.decode().splitlines()
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            assert lines[start - 2].lstrip().startswith('#'), node.name
            result[node.name] = ast.dump(node, include_attributes=False)
    return result


# Reproduce only new control source and preserve exact small actual proof without native-body transfer.
def main(arguments):
    assert len(arguments) == 1 and len(arguments[0]) == 64
    transport_root = Path('/tmp/capacity-callback-binary-independent-transport-20261018-v1')
    raw, proof_row = read(transport_root / 'stdout')
    assert proof_row['sha256'] == arguments[0]
    proof = json.loads(raw)
    assert proof['status'] == 'VERIFIED_ONE_BINARY_BYTE_COPY_RECORD_SHA_ONLY_NOT_ELF_OR_RUNTIME'
    assert proof['candidate_sha256'] == '10590bccad71e60b7589a2ef75ff03ed9ea435e26ef6311f57578cc2697506d2'
    assert proof['source_bytes'] == 216280 and proof['full_readback_files'] == 17
    assert proof['binary_hash_matches_RECORD'] is True and max(proof['archive_wire_bytes']) <= CAP
    assert proof['declaration']['declared_hash']['digest_hex'] == '9edf4136653a328edcc88dc97f6d828440ad96550c436cbe087951845c89903b'
    contents, pins, asts = {}, {}, {}
    for name, (sha, size) in PINS.items():
        contents[name], pins[name] = read(SOURCES / name)
        assert pins[name]['sha256'] == sha and (size is None or pins[name]['bytes'] == size)
        asts[name] = functions(contents[name])
    builder = 'prepare-callback-binary-copy-v1-2026-10-18.py'
    REPRODUCTION.mkdir(mode=0o700, exist_ok=False)
    target = REPRODUCTION / 'sources'
    target.mkdir(mode=0o700)
    for name, sha in INPUTS.items():
        old, observed = read(SOURCES / name)
        assert observed['sha256'] == sha
        write(target / name, old)
    for name, sha in DATA.items():
        data, observed = read(RESEARCH / name)
        assert observed['sha256'] == sha
        write(REPRODUCTION / name, data)
    write(target / builder, contents[builder])
    for args in (['primary'], ['independent', proof['candidate_sha256']]):
        completed = subprocess.run([sys.executable, '-I', '-S', '-B', str(target / builder)] + args,
            capture_output=True, timeout=10, check=True)
        assert not completed.stderr and len(completed.stdout) <= CAP
    for name in PINS:
        assert read(target / name)[0] == contents[name]
    old_primary = functions((SOURCES / 'capacity-package-metadata-text-census-v2-2026-10-18.py').read_bytes())
    old_independent = functions((SOURCES / 'verify-package-metadata-text-census-v2-2026-10-18.py').read_bytes())
    comparisons = []
    primary = asts['capacity-callback-binary-copy-v1-2026-10-18.py']
    independent = asts['verify-callback-binary-copy-v1-2026-10-18.py']
    for name in ('digest', 'save', 'save_json', 'alarm', 'client_limits', 'command', 'physical', 'read', 'inspection', 'inspect_source'):
        assert primary[name] == old_primary[name]
        comparisons.append('primary:' + name)
    for name in ('digest', 'save', 'save_json', 'alarm', 'client_limits', 'command', 'physical', 'read', 'inspection'):
        assert independent[name] == old_independent[name]
        comparisons.append('independent:' + name)
    for role in ('primary', 'independent'):
        root = Path('/tmp/capacity-callback-binary-' + role + '-transport-20261018-v1')
        terminal = json.loads(read(root / 'exit.json')[0])
        assert terminal['exit'] == 0 and terminal['failure_class'] is None
        assert terminal['owned_SSH_group_stop'] is None and terminal['cleanup_failure_class'] is None
        assert read(root / 'stderr')[0] == b''
    static = {'schema': 'callback-binary-copy-controls-static/1', 'pins': pins,
        'purpose_comments_five_controls': sum(len(value) for value in asts.values()),
        'exact_function_AST_comparisons': comparisons, 'four_outputs_byte_exact_reproduction': True,
        'AST_warnings_as_errors': 'PASS', 'actual_binary_hash_and_wire_bounds_checked': True,
        'Ruff': 'PREVIOUSLY_UNAVAILABLE_NO_LINT_CLAIM',
        'old_gates_or_model_tests': 'NOT_RUN', 'ELF_parse_native_import_or_execution': False,
        'missing_hash_size_type_sparse_timeout_overflow_signal_crash_branches': 'UNTESTED'}
    write(RESEARCH / 'original-loader-callback-binary-static-v1-2026-10-18.json',
        json.dumps(static, sort_keys=True, indent=2).encode() + b'\n')
    write(RESEARCH / 'original-loader-callback-binary-independent-v1-2026-10-18.json', raw)
    ROOT.mkdir(mode=0o700, exist_ok=False)
    sources = [(SOURCES / name, name) for name in PINS]
    sources += [(Path(__file__), Path(__file__).name),
        (RESEARCH / 'original-loader-callback-binary-static-v1-2026-10-18.json', 'static.json'),
        (RESEARCH / 'original-loader-callback-binary-independent-v1-2026-10-18.json', 'independent.json')]
    for role in ('primary', 'independent'):
        root = Path('/tmp/capacity-callback-binary-' + role + '-transport-20261018-v1')
        sources += [(root / name, role + '-' + name) for name in ('stdout', 'stderr', 'exit.json')]
    manifest = []
    for original, name in sources:
        body, before = read(original)
        write(ROOT / name, body)
        copied, after = read(ROOT / name)
        assert copied == body and read(original) == (body, before)
        manifest.append({'source': str(original), 'name': name, 'original': before, 'copy': after})
    manifest_raw = json.dumps({'schema': 'callback-binary-copy-small-evidence/1', 'files': manifest},
        sort_keys=True, indent=2).encode() + b'\n'
    write(ROOT / 'manifest.json', manifest_raw)
    for directory in (ROOT, ROOT.parent.resolve(strict=True), target, REPRODUCTION, REPRODUCTION.parent.resolve(strict=True)):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(fd); os.close(fd)
    result = {'schema': 'callback-binary-copy-local-preservation/1', 'root': str(ROOT), 'files': len(manifest),
        'data_bytes': sum(row['copy']['bytes'] for row in manifest),
        'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(), 'manifest_bytes': len(manifest_raw),
        'files_readbacks_root_resolved_parent_fsync': True, 'reproduction_root': str(REPRODUCTION),
        'native_binary_and_wires_stay_Spark': True, 'crash_or_second_full_remote_archive_guarantee': False}
    write(RESEARCH / 'original-loader-callback-binary-preservation-v1-2026-10-18.json',
        json.dumps(result, sort_keys=True, indent=2).encode() + b'\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
