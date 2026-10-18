"""Compare complete upstream ASTs after explicit data identity/map/receipt changes only."""
import ast
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
CONTRACT_SHA = '3a2b5faf0904a89d6c95ca967f4eb1d7af867f0678fba1e934cd7bc1e7bb8f6e'
REVERSE = {'capacity_original_input_auth_v1': 'live_model_history_input_auth', 'capacity_original_admissions_v2': 'capacity_original_admissions_v1', 'capacity_original_archives_v2': 'capacity_original_archives_v1', 'capacity_original_archive_adaptations_v2': 'capacity_original_archive_adaptations_v1', 'capacity_original_loader_binding_v2': 'capacity_original_loader_binding_v1', 'capacity_original_durability_v1': 'capacity_original_admission_lifecycle_v1', 'capacity_original_inputs_v2': 'capacity_original_inputs_v1'}
TYPES = {'CapacityOriginalArchivesV2': 'CapacityOriginalArchivesV1', 'CapacitySourceReaderV2': 'CapacitySourceReaderV1', 'CapacityAuditInputsV2': 'CapacityAuditInputsV1', 'CapacityLoaderLeaseV2': 'CapacityLoaderLeaseV1'}


# Authenticate exact bytes without importing application modules or their builders.
def pinned(path, expected):
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == expected, str(path)
    return raw


# Compare complete syntax trees without claiming executable or numerical equivalence.
def same(first, second):
    assert ast.dump(first, include_attributes=False) == ast.dump(second, include_attributes=False)


# Select one exact declaration within an otherwise unevaluated source tree.
def selected(tree, qualified):
    for name in qualified.split('.'):
        tree = next(node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == name)
    return tree


# Restore only declared new module/type identifiers in a detached comparison tree.
def restore_identifiers(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parts = node.module.split('.')
            node.module = '.'.join(REVERSE.get(part, part) for part in parts)
            for alias in node.names:
                alias.name = TYPES.get(alias.name, REVERSE.get(alias.name, alias.name))
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            node.name = TYPES.get(node.name, node.name)
        elif isinstance(node, ast.Name):
            node.id = TYPES.get(node.id, node.id)
        elif isinstance(node, ast.Attribute):
            node.attr = TYPES.get(node.attr, node.attr)
        elif isinstance(node, ast.Constant) and type(node.value) is str:
            node.value = {'capacity_original_inputs_v2.CapacityAuditInputsV2': 'capacity_original_inputs_v1.CapacityAuditInputsV1', 'capacity_original_inputs_v2': 'capacity_original_inputs_v1'}.get(node.value, node.value)


# Remove exactly one declared schema/implementation field from a result metadata dictionary.
def remove_key(node, key, expected):
    index = next(index for index, item in enumerate(node.keys) if isinstance(item, ast.Constant) and item.value == key)
    assert ast.unparse(node.values[index]) == expected
    node.keys.pop(index)
    node.values.pop(index)


# Check full identity/root/lifetime deltas and the exact immutable map union as source only.
def main():
    contract = json.loads(pinned(DOCS / 'original-loader-data-composition-source-contract-v1-2026-10-18.json', CONTRACT_SHA))
    old = {key: ast.parse(pinned(DOCS / row['path'], row['sha256'])) for key, row in contract['original_sources'].items()}
    raw = {key: pinned(DOCS / row['path'], row['sha256']) for key, row in contract['modules'].items()}
    trees = {key: ast.parse(value) for key, value in raw.items()}
    candidate = deepcopy(trees)
    for tree in candidate.values():
        restore_identifiers(tree)
    for key in ('inputs', 'binding', 'lifecycle'):
        before = next(node for node in old[key].body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'SCHEMA' for target in node.targets))
        after = next(node for node in candidate[key].body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'SCHEMA' for target in node.targets))
        assert ast.literal_eval(after.value) == ast.literal_eval(before.value).removesuffix('/1') + '/2'
        after.value = deepcopy(before.value)
    same(old['admissions'], candidate['admissions'])
    same(old['inputs'], candidate['inputs'])
    checks = ['admissions_COMPLETE_AST_only_two_dependency_import_changes', 'inputs_COMPLETE_AST_only_new_archive_result_module_schema_identities']
    same(selected(old['durability'], 'sync_directory'), selected(candidate['durability'], 'sync_directory'))
    bound = next(node for node in candidate['durability'].body if isinstance(node, ast.Assign))
    original_bound = next(node for node in old['durability'].body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'MAX_RESULT_BYTES' for target in node.targets))
    same(bound, original_bound)
    assert sum(isinstance(node, ast.FunctionDef) for node in candidate['durability'].body) == 1
    checks.append('durability_exact_sync_body_bound_no_old_lifecycle_import')
    lifecycle = selected(candidate['lifecycle'], 'CapacityLoaderLeaseV1')
    constructor = selected(candidate['lifecycle'], 'CapacityLoaderLeaseV1.__init__')
    additions = [node for node in constructor.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Attribute) and target.attr == 'interfaces' for target in node.targets)]
    assert len(additions) == 1 and ast.unparse(additions[0].value) == "{'data_modules': dict(self.source_map['data_interfaces']), 'upstream_modules': dict(self.source_map['compositions']), 'original_byte_receipt_adopted': False}"
    constructor.body.remove(additions[0])
    load = selected(candidate['lifecycle'], 'CapacityLoaderLeaseV1._load_inputs')
    origin_loop = next(node for node in load.body if isinstance(node, ast.For))
    original_loop = next(node for node in selected(old['lifecycle'], 'CapacityLoaderLeaseV1._load_inputs').body if isinstance(node, ast.For))
    assert ast.literal_eval(origin_loop.iter)[-4:] == ('capacity_original_history_json_v1', 'capacity_original_input_auth_v1', 'capacity_original_archive_adaptations_v2', 'capacity_original_archives_v2')
    assert len(ast.literal_eval(origin_loop.iter)) == 16
    origin_loop.iter.elts = origin_loop.iter.elts[:-4]
    same(origin_loop.iter, original_loop.iter)
    serialize = selected(candidate['lifecycle'], 'CapacityLoaderLeaseV1.serialize')
    result = next(node.value for node in serialize.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'result' for target in node.targets))
    remove_key(result, 'schema', "'capacity-loader-data-candidate/1'")
    remove_key(result, 'implementation_binding', 'self.interfaces')
    same(old['lifecycle'], candidate['lifecycle'])
    checks.append('lifecycle_COMPLETE_AST_only_declared_types_imports_16origins_and_receipt_metadata')
    binding = candidate['binding']
    inserted = {'COMPOSITION_MAP_SHA256', 'DATA_MAP_SHA256', 'DATA_INTERFACES', 'UPSTREAM_PATHS'}
    constants = {target.id: node.value for node in binding.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
    assert ast.literal_eval(constants['DATA_MAP_SHA256']) == contract['data_map_sha256']
    assert ast.literal_eval(constants['COMPOSITION_MAP_SHA256']) == contract['composition_map_sha256']
    data = json.loads(pinned(DOCS / 'original-loader-map-auth-interface-source-map-v1-2026-10-18.json', contract['data_map_sha256']))
    assert ast.literal_eval(constants['DATA_INTERFACES']) == data['additions']
    binding.body = [node for node in binding.body if not (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in inserted for target in node.targets))]
    method = selected(binding, 'capacity_binding')
    for variable, removed in (('path_fields', {'composition_map', 'data_map'}), ('digest_fields', {'composition_map_sha256', 'data_map_sha256'})):
        row = next(node for node in method.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets))
        assert removed <= {ast.literal_eval(item) for item in row.value.elts}
        row.value.elts = [item for item in row.value.elts if ast.literal_eval(item) not in removed]
    exact = [node for node in method.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and len(node.value.args) == 2 and isinstance(node.value.args[1], ast.Constant) and node.value.args[1].value == 'EXACT_DATA_COMPOSITION_CHAIN_REQUIRED']
    assert len(exact) == 1
    method.body.remove(exact[0])
    start = next(index for index, node in enumerate(method.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'data_map' for target in node.targets))
    end = next(index for index, node in enumerate(method.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'native' for target in node.targets))
    extra = method.body[start:end]
    reasons = [node.value.args[1].value for node in extra if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and len(node.value.args) == 2 and isinstance(node.value.args[1], ast.Constant)]
    assert reasons == ['EXACT_DATA_INTERFACE_SCHEMA_REQUIRED', 'EXACT_FOUR_NEW_DATA_INTERFACES_REQUIRED', 'EXACT2463_DATA_UNION_REQUIRED', 'EXACT_UPSTREAM_COMPOSITION_SCHEMA_REQUIRED', 'EXACT_FIVE_UPSTREAM_ADDITIONS_REQUIRED', 'EXACT2468_UPSTREAM_UNION_REQUIRED']
    del method.body[start:end]
    for node in ast.walk(method):
        if isinstance(node, ast.Name) and node.id == 'composition_map':
            node.id = 'source_map'
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'binding' and isinstance(node.slice, ast.Constant) and node.slice.value == 'composition_map':
            node.slice.value = 'source_map'
    composition_assignment = next(node for node in method.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'source_map' for target in node.targets))
    pinned_call = next(node for node in ast.walk(composition_assignment) if isinstance(node, ast.Call) and ast.unparse(node.func) == 'evidence.pinned')
    assert ast.unparse(pinned_call.args[1]) == 'COMPOSITION_MAP_SHA256'
    pinned_call.args[1] = ast.parse("binding['source_map_sha256']", mode='eval').body
    returned = next(node for node in method.body if isinstance(node, ast.Return)).value.elts[2]
    remove_key(returned, 'data_interfaces', 'DATA_INTERFACES')
    assert ast.unparse(returned.values[-1]) == 'upstreams'
    returned.values[-1] = ast.Name(id='compositions', ctx=ast.Load())
    module_return = next(node for node in selected(binding, 'module_admission').body if isinstance(node, ast.Return)).value
    position = next(index for index, key in enumerate(module_return.keys) if isinstance(key, ast.Constant) and key.value == 'executor_files')
    assert ast.literal_eval(module_return.values[position]) == 2468
    module_return.values[position] = ast.Constant(2459)
    same(old['binding'], binding)
    checks.append('binding_COMPLETE_AST_retains_all_old_root_source_calendar_and_map_checks')
    declaration_row = contract['source_map_declaration']
    declaration = json.loads(pinned(DOCS / declaration_row['path'], declaration_row['sha256']))
    upstreams = {row['proposed_origin']: row['sha256'] for row in contract['modules'].values()}
    assert set(upstreams) == ast.literal_eval(constants['UPSTREAM_PATHS']) and declaration['upstreams'] == upstreams
    assert len(data['files']) == 2463 and len(declaration['files']) == 2468 and not set(data['files']) & set(upstreams)
    assert declaration['files'] == {**data['files'], **upstreams}
    assert all(value is None for value in contract['unadmitted'].values()) and contract['execution_authorized'] is False
    checks.append('exact2463_plus5_union_all_runtime_fields_NULL')
    source_functions = sum(sum(isinstance(node, ast.FunctionDef) for node in ast.walk(tree)) for tree in trees.values())
    forbidden_old_dependencies = {'live_model_history_input_auth', 'original_history_json', 'capacity_original_archives_v1', 'capacity_original_inputs_v1', 'capacity_original_admission_lifecycle_v1'}
    for key, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not set(node.module.split('.')) & forbidden_old_dependencies
                assert not {alias.name for alias in node.names} & forbidden_old_dependencies
        if key in ('inputs', 'binding', 'lifecycle'):
            execute = selected(tree, 'execute')
            assert len(execute.body) == 1 and isinstance(execute.body[0], ast.Raise)
    checks.append('direct_imports_no_old_data_binding_and_public_execute_refuses')
    report = {'schema': 'capacity-data-upstream-independent-source-review/1', 'status': 'SOURCE_AST_MAP_IDENTITY_ONLY_ALL_BODIES_UNRUN', 'contract_sha256': CONTRACT_SHA, 'checks': checks, 'payload_functions': source_functions, 'module_files': contract['modules'], 'new_map': declaration_row, 'binding_added_guards': reasons, 'full_module_AST_comparisons': ['admissions', 'inputs', 'binding', 'lifecycle'], 'durability_exact_function': True, 'module_origin_members': 16, 'scope': 'Complete AST correspondence after declared deltas and direct-import checks only. Not transitive module/call/native/generated/finder/phase closure or runtime/type/numeric/parity/RAM admission.', 'execution_authorized': False}
    value = json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(value) <= 262144
    path = DOCS / 'original-loader-data-composition-independent-source-review-v1-2026-10-18.json'
    with path.open('xb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == value
    print(json.dumps({'report_sha256': sha256(value).hexdigest(), 'bytes': len(value), 'checks': len(checks), 'payload_functions': source_functions, 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
