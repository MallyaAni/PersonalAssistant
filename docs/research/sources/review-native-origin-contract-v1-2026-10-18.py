"""Independently check a local requirements artifact without running its builder or any payload."""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import sys

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-native-origin-contract-20261018-v1')
OUT = Path('/tmp/capacity-native-origin-contract-review-20261018-v1')
BUILDER = DOCS / 'sources/prepare-native-origin-contract-v1-2026-10-18.py'
BUILDER_SHA = '27dfc52faaa2f9121d451a698ec6e8661e47194623804f03f7f75228413f86fd'


# Preserve all physical identity fields without floating-point conversion.
def identity(item):
    return {name: str(getattr(item, name)) for name in ('st_dev', 'st_ino', 'st_mode',
        'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')}


# Independently read a complete ordinary file twice and compare both held and named identities.
def file_record(path):
    path = path.resolve(strict=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        initial = os.fstat(descriptor)
        assert stat.S_ISREG(initial.st_mode) and initial.st_nlink == 1 and initial.st_size <= 262144
        chunks = []
        remaining = initial.st_size
        while remaining:
            block = os.read(descriptor, min(65536, remaining))
            assert block
            chunks.append(block)
            remaining -= len(block)
        assert os.read(descriptor, 1) == b''
        body = b''.join(chunks)
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, 262145) == body
        assert identity(initial) == identity(os.fstat(descriptor)) == identity(path.stat(follow_symlinks=False))
        return body, {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'physical': identity(initial)}
    finally:
        os.close(descriptor)


# Independently inspect a named assignment inside one top-level function as source AST only.
def fields(source, function_name, assignment_name):
    tree = ast.parse(source)
    function, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name]
    target, = [node.value for node in ast.walk(function) if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == assignment_name for name in node.targets)]
    assert isinstance(target, ast.Dict)
    return function, {key.value: value for key, value in zip(target.keys, target.values, strict=True)}


# Check every external binding and proposed gate while keeping all observers and execution unadmitted.
def main(arguments):
    assert __debug__ and len(arguments) == 1 and len(arguments[0]) == 64
    signal.alarm(30)
    builder_raw, builder_row = file_record(BUILDER)
    assert builder_row['sha256'] == BUILDER_SHA
    tree = ast.parse(builder_raw)
    pins_node, = [node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(name, ast.Name) and name.id == 'PINS' for name in node.targets)]
    pins = ast.literal_eval(pins_node)
    assert len(pins) == 10
    inputs, bodies = {}, {}
    for name, (sha, size) in pins.items():
        path = DOCS / name
        body, row = file_record(path)
        assert row['sha256'] == sha and row['bytes'] == size
        inputs[str(path)] = row
        bodies[name] = body
    assert sum(row['bytes'] for row in inputs.values()) + len(builder_raw) <= 1048576
    raw, contract_row = file_record(ROOT / 'contract.json')
    assert contract_row['sha256'] == arguments[0]
    c = json.loads(raw)
    assert c['schema'] == 'capacity-native-origin-requirements/1'
    assert c['status'] == 'SOURCE_REVIEW_REQUIRED_NO_OBSERVER_OR_RUNTIME_ADMISSION'
    assert c['input_inventory'] == inputs
    assert c['genuine_execution_authorized'] is False
    assert all(c[name] is None for name in ('observation_executor', 'observer_invocation', 'native_runtime_admission'))
    a, af = fields(bodies['sources/original-loader-context-native-probe-v1-2026-10-18.py'], 'main', 'result')
    b, bf = fields(bodies['sources/original-loader-context-parity-preflight-v1-2026-10-18.py'], 'native_fold', 'proof')
    assert isinstance(af['python_executable'], ast.Attribute) and af['python_executable'].attr == 'executable'
    assert isinstance(af['python_executable'].value, ast.Name) and af['python_executable'].value.id == 'sys'
    assert 'python_executable' not in bf
    gap = c['source_omission']
    assert gap['emitted_expression'] == 'sys.executable' and gap['emitted_field'] == 'python_executable'
    assert gap['probe_result_fields'] == list(af) and gap['fold_proof_fields'] == list(bf)
    assert gap['summary_field_absent'] is True and gap['raw_native_json_observed_here'] is False
    assert gap['probe_function_AST_sha256'] == hashlib.sha256(ast.dump(a, include_attributes=False).encode()).hexdigest()
    assert gap['fold_function_AST_sha256'] == hashlib.sha256(ast.dump(b, include_attributes=False).encode()).hexdigest()
    old = json.loads(bodies['/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-proof.stdout'])
    prior = json.loads(bodies['original-loader-context-parity-proof-v1-2026-10-18.json'])
    inspect, = json.loads(bodies['/tmp/capacity-context-parity-operations-20261018-v1/fetch-native-inspect.stdout'])
    manifest = json.loads(bodies['/tmp/capacity-context-parity-operations-20261018-v1/fetch-evidence-manifest.stdout'])
    assert old['cid'] == inspect['Id'] == c['existing_runtime']['cid'] == prior['native']['cid']
    assert old['image'] == inspect['Image'] == c['existing_runtime']['image'] == prior['prerequisites']['image_id']
    assert old['python'] == c['existing_runtime']['python_version_metadata'] == '3.12.14'
    assert 'python_executable' not in old
    assert c['existing_runtime']['Path'] == inspect['Path']
    assert c['existing_runtime']['Args'] == inspect['Args']
    for key in ('WorkingDir', 'Entrypoint', 'Cmd'):
        assert c['existing_runtime'][key] == inspect['Config'][key]
    selection = c['retained_metadata_selection']
    assert selection['evidence_root'] == prior['preservation']['root']
    assert selection['page_inventory'] == manifest['pages'] and len(manifest['pages']) == 21 and manifest['files'] == 1339
    assert selection['top_manifest_sha256'] == pins['/tmp/capacity-context-parity-operations-20261018-v1/fetch-evidence-manifest.stdout'][0]
    assert selection['top_manifest_bytes'] == 10845 and selection['target_SHA_bytes_physical'] is None
    assert selection['target_manifest_key'] == 'native/output/native.json'
    assert selection['target_original'] == '/home/animallya96/scratch/capacity-context-native-probe-20261018-v1/output/native.json'
    assert selection['target_copy'] == selection['evidence_root'] + '/' + selection['target_manifest_key']
    assert c['callback_required_version_declarations'] == [
        {'file_hex': '6c69626d2e736f2e36', 'requirements': [{'name_hex': '474c4942435f322e3137', 'vna_other_decimal': '3', 'auxiliary_array_index': 0}]},
        {'file_hex': '6c6962632e736f2e36', 'requirements': [{'name_hex': '474c4942435f322e3137', 'vna_other_decimal': '2', 'auxiliary_array_index': 0}]}]
    assert [item['gate'] for item in c['later_gates_NOT_implemented']] == [
        'INTERPRETER_FILE_ORIGIN', 'ELF_AND_BUILD', 'LOADER_SEARCH_STATE',
        'PROVIDER_ALIAS_VERSION_TRANSITIVE', 'PYTHON_EXTENSION_BINDING', 'GENUINE_MODEL_RAM']
    assert all(item['observer'] is None for item in c['later_gates_NOT_implemented'])
    for path, row in inputs.items():
        assert file_record(Path(path))[1] == row
    assert file_record(BUILDER)[1] == builder_row and file_record(ROOT / 'contract.json')[1] == contract_row
    proof = {'schema': 'capacity-native-origin-independent-source-review/1',
        'status': 'SOURCE_AND_RETAINED_METADATA_DERIVATION_VERIFIED_NOT_OBSERVER_ACCEPTANCE',
        'builder': builder_row, 'contract': contract_row, 'input_inventory': inputs,
        'source_omission_reconstructed': True, 'full21_page_pointer_inventory_equal_not_page_bodies_read': True,
        'historical_command_fields_equal': True, 'complete_required_version_declarations_equal': True,
        'all_observers_NULL': True, 'genuine_execution_authorized': False,
        'payload_import_compile_or_body_and_remote_operations': 0}
    output = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(output) <= 262144
    OUT.mkdir(mode=0o700, exist_ok=False)
    with (OUT / 'proof.json').open('xb') as stream:
        stream.write(output)
        stream.flush()
        os.fsync(stream.fileno())
    assert file_record(OUT / 'proof.json')[0] == output
    for directory in (OUT, OUT.resolve(strict=True).parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    signal.alarm(0)
    print(json.dumps({'bytes': len(output), 'sha256': hashlib.sha256(output).hexdigest(), 'input_files': len(inputs)}, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
