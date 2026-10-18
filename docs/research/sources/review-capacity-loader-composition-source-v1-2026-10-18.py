"""Review new source composition as AST/data only, without importing any payload."""

import ast
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
CONTRACT_SHA = 'a69aa1b659dfe9a33053d798592ea8e41856e70f87431c69f5d2b414ffeca2d3'


# Authenticate source/declaration bytes without importing their modules or builders.
def pinned(path, expected):
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == expected, str(path)
    return raw


# Select one complete declaration and detach its AST for comparison only.
def selected(raw, qualified):
    node = ast.parse(raw)
    for name in qualified.split('.'):
        node = next(item for item in node.body if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == name)
    return deepcopy(node)


# Compare full AST declarations without equating runtime CodeTypes or allocation behavior.
def same(first, second):
    assert ast.dump(first, include_attributes=False) == ast.dump(second, include_attributes=False)


# Select exact static statements without compiling the supplied source into executable code.
def statement(text):
    return ast.parse(text).body[0]


# Describe every call in source while leaving its arguments and callable body unevaluated.
def calls(node):
    return sorted({ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)})


# Check explicit source-map, root and lifecycle deltas while every payload body stays unrun.
def main():
    contract = json.loads(pinned(DOCS / 'original-loader-composition-source-contract-v1-2026-10-18.json', CONTRACT_SHA))
    modules = {}
    for name, record in contract['modules'].items():
        modules[name] = pinned(DOCS / record['path'], record['sha256'])
        assert len(modules[name]) == record['bytes'] <= 262144
    old = pinned(DOCS / 'sources/original-loader-capacity-admission-lifecycle-v1-2026-10-18.py', '3acd8b296b3d14234d7c769e2ce4c5a63c8e381d87d7677476964ea1a5f84b1b')
    admissions = pinned(DOCS / 'sources/original-loader-capacity-admissions-v1-2026-10-18.py', 'f7a226b3d90472ac3ebe161e4c46beb2c49245d489ac1de4a78f90ee2af6d0a9')
    reference = json.loads(pinned(DOCS / 'original-loader-genuine-source-map-2026-10-18.json', '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'))
    prior = json.loads(pinned(DOCS / 'original-loader-admission-source-map-v1-2026-10-18.json', 'a68ebbefb776a93dfdfb56fc6c4893ac35450a224fcf2fa50498cb911bfeda43'))
    entry = json.loads(pinned(DOCS / 'original-loader-entry-source-map-v1-2026-10-18.json', 'aaa1ad0622f18f35e8f639d4a7a9e78e21d8681e19860c7a7284b0876b043f9c'))
    proposed = json.loads(pinned(DOCS / contract['source_map_declaration']['path'], contract['source_map_declaration']['sha256']))
    assert len(reference) == 2446 and len(prior['files']) == 2453 and len(entry['files']) == 2457 and len(proposed['files']) == 2459
    assert proposed['files'] == {**entry['files'], **proposed['compositions']}
    assert proposed['compositions'] == {row['proposed_origin']: row['sha256'] for row in contract['modules'].values()}
    assert {path for path in prior['files'] if proposed['files'][path] != prior['files'][path]} == {'backend/market/learned_entry_data.py'}
    binding_tree = ast.parse(modules['binding'])
    assignment = {target.id: item.value for item in binding_tree.body if isinstance(item, ast.Assign) for target in item.targets if isinstance(target, ast.Name)}
    expected_constants = {'REFERENCE_MAP_SHA256': '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224', 'REFERENCE_COMPACT_SHA256': '503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03', 'PRIOR_MAP_SHA256': 'a68ebbefb776a93dfdfb56fc6c4893ac35450a224fcf2fa50498cb911bfeda43', 'ENTRY_MAP_SHA256': 'aaa1ad0622f18f35e8f639d4a7a9e78e21d8681e19860c7a7284b0876b043f9c', 'ORIGINAL_SHA256': '4b0555a6fd929c8a73a9063ef933fde22ce581fa85f37badb37fe611a9123365', 'VARIANT_SHA256': '21adedb2a11ef8fe9802c4be6c2783b684bfd755db17032ae4bbaf0a2e2a693e', 'NATIVE_COMPACT_SHA256': '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'}
    assert all(ast.literal_eval(assignment[key]) == value for key, value in expected_constants.items())
    assert ast.literal_eval(assignment['ENTRY_MODULES']) == entry['new_modules']
    assert ast.literal_eval(assignment['COMPOSITION_PATHS']) == set(proposed['compositions'])
    checks = ['exact_map_chain_and_sole_transition_plus4plus2', 'exact7_digest_constants_and_module_sets']
    before = selected(admissions, 'source_admission')
    after = selected(modules['binding'], 'source_admission')
    assert after.args.args[-1].arg == 'reference_root'
    after.args.args.pop()
    same(after.body.pop(1), statement("require(root == archives.source_root, 'EXACT_REFERENCE_ARCHIVE_ROOT_REQUIRED')"))
    same(after.body[0], statement('root = Path(reference_root)'))
    after.body[0] = before.body[0]
    same(before, after)
    checks.append('complete_legacy_source_Git2431_body_only_explicit_root_and_guard')
    before = selected(admissions, 'calendar_admission')
    after = selected(modules['binding'], 'calendar_admission')
    assert after.args.args[-1].arg == 'executor_root'
    after.args.args.pop()
    same(after.body[1], statement('from backend.market import calendar'))
    after.body[1] = before.body[1]
    same(after.body[2], statement('require(Path(calendar.__file__).resolve().parents[2] == Path(executor_root), "EXACT_ORIGINAL_CALENDAR_EXECUTOR_ROOT_REQUIRED")'))
    after.body[2] = before.body[2]
    same(after.body.pop(3), statement("for path in (Path(calendar.__file__), archives.source_root / 'backend/market/calendar.py'):\n    authenticate_file(path, archives.sources['backend/market/calendar.py'])"))
    data_loop = next(item for item in after.body if isinstance(item, ast.For) and isinstance(item.iter, ast.Tuple) and len(item.iter.elts) == 3)
    assert len(data_loop.body) == 3
    same(data_loop.body[0], statement('relative = str(path.relative_to(executor_root))'))
    data_loop.body[0] = statement('relative = str(path.relative_to(archives.source_root))')
    same(data_loop.body.pop(), statement('authenticate_file(archives.source_root / relative, archives.sources[relative])'))
    same(before, after)
    checks.append('complete_calendar_profile_body_and_both_source_3data_copies')
    name = 'CapacityLoaderLeaseV1'
    cls = selected(modules['lifecycle'], name)
    assert not cls.bases
    assert {item.name for item in cls.body if isinstance(item, ast.FunctionDef)} == {'__init__', '_bytes', '_load_inputs', 'verify_after', 'serialize', 'persist', 'release'}
    before = selected(old, 'CapacityArchiveLeaseV1.__init__')
    after = selected(modules['lifecycle'], name + '.__init__')
    edited = deepcopy(before)
    changes = {
        "reader = archives_module.CapacitySourceReaderV1(self.binding['source_root'], native)": "reader = archives_module.CapacitySourceReaderV1(self.binding['reference_root'], native)",
        'self.legacy_source = admissions.source_admission(self.value, self.archives)': "self.legacy_source = source_admission(self.value, self.archives, self.binding['reference_root'])",
        "self.calendar = admissions.calendar_admission(self.archives, self.value['profile'])": "self.calendar = calendar_admission(self.archives, self.value['profile'], self.binding['source_root'])",
        'self.loaded = self.after = self.serialized = self.encoded = None': 'self.loaded = self.after = self.serialized = self.encoded = self.loaded_binding = None',
    }
    for first, second in changes.items():
        matches = [index for index, item in enumerate(edited.body) if ast.dump(item, include_attributes=False) == ast.dump(statement(first), include_attributes=False)]
        assert len(matches) == 1
        edited.body[matches[0]] = statement(second)
    same(edited, after)
    checks.append('complete_constructor_only4_declared_root_admission_metadata_changes')
    for method in ('_bytes', 'verify_after', 'persist'):
        same(selected(old, 'CapacityArchiveLeaseV1.' + method), selected(modules['lifecycle'], name + '.' + method))
        checks.append(method + '_full_AST_same_new_declared_binding_globals')
    before = selected(old, 'CapacityArchiveLeaseV1.serialize')
    after = selected(modules['lifecycle'], name + '.serialize')
    output = next(item.value for item in after.body if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'result' for target in item.targets))
    index = next(index for index, key in enumerate(output.keys) if isinstance(key, ast.Constant) and key.value == 'loader_type_binding')
    assert ast.unparse(output.values[index]) == 'self.loaded_binding'
    output.keys.pop(index)
    output.values.pop(index)
    same(before, after)
    checks.append('serialize_only_extra_type_metadata_complete_JSON_UTF8_retention')
    before = selected(old, 'CapacityArchiveLeaseV1.release')
    after = selected(modules['lifecycle'], name + '.release')
    row = next(item for item in after.body if isinstance(item, ast.Assign) and len(item.targets) > 1)
    assert ast.unparse(row.targets[-1]) == 'self.loaded_binding'
    row.targets.pop()
    same(before, after)
    checks.append('release_only_extra_metadata_reference_after_durable_bytes')
    load = selected(modules['lifecycle'], name + '._load_inputs')
    call_nodes = [item for item in ast.walk(load) if isinstance(item, ast.Call) and ast.unparse(item.func) == 'inputs_module._load_capacity_inputs']
    assert len(call_nodes) == 1
    actual_factory = next(index for index, item in enumerate(load.body) if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call) and ast.unparse(item.value.func) == 'inputs_module._load_capacity_inputs')
    same(load.body[actual_factory - 1], statement('self.observed_at = datetime.now(UTC)'))
    assert not any(isinstance(item, ast.arg) and item.arg == 'observed_at' for item in ast.walk(cls))
    original_phase_check = "evidence.require(self.phase == 'BEFORE', 'EXACT_PRIVATE_LOAD_PHASE_REQUIRED')"
    same(load.body[0], statement(original_phase_check))
    checks.append('one_private_factory_call_after_real_UTC_clock_no_supplied_result_or_clock')
    module_loop = next(item for item in load.body if isinstance(item, ast.For))
    module_names = ast.literal_eval(module_loop.iter)
    assert len(module_names) == len(set(module_names)) == 12
    assert all('backend/market/' + module + '.py' in proposed['files'] for module in module_names)
    checks.append('exact12_proposed_module_origin_members')
    for kind in ('binding', 'lifecycle'):
        execute = selected(modules[kind], 'execute')
        assert len(execute.body) == 1 and isinstance(execute.body[0], ast.Raise)
    checks.append('both_public_execute_bodies_unconditional_refusal')
    assert 'LEGACY_SOURCE_OVERRIDE_FORBIDDEN' in old.decode()
    data = {'schema': 'capacity-original-loader-composition-independent-source-review/1', 'status': 'SOURCE_AST_MAP_ROOT_AND_LIFETIME_DESIGN_ONLY_ALL_BODIES_UNRUN', 'contract_sha256': CONTRACT_SHA, 'source_map': contract['source_map_declaration'], 'AST_checks': checks, 'module_origin_members': list(module_names), 'source_modules': contract['modules'], 'static_functions': {kind: {item.name: {'line': item.lineno, 'end_line': item.end_lineno, 'AST_sha256': sha256(ast.dump(item, include_attributes=False).encode()).hexdigest(), 'calls': calls(item)} for item in ast.walk(ast.parse(raw)) if isinstance(item, ast.FunctionDef)} for kind, raw in modules.items()}, 'limitations': ['No payload import, executable CodeType compilation, body, test or previous completed gate replay.', 'Map declaration only; full physical source assembly/SourceBook/finder/native/generated/call/phase/runtime/admission absent.', 'Both rootFDs held during map hashing only; per-file opens path based, no hostile kernel/native isolation.', 'Module class/file/spec origin and exact result lineage are not live CodeType/global/factory provenance or numerical/type/parity/RAM acceptance.', 'Reference sys.path overlap refusal is not full meta_path/finder exclusion proof.', 'Original2431 producer source, reference2446 and new2459 executor roles stay distinct; old2453 binding still refuses transition.'], 'entrypoint_modelstrategy_wrapper_finder_manifests_runtime_admission': None, 'production_original_files_guard_G08_caps': 'UNCHANGED'}
    raw = json.dumps(data, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    path = DOCS / 'original-loader-composition-independent-source-review-v1-2026-10-18.json'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    print(json.dumps({'report_sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'AST_checks': len(checks), 'functions': sum(len(value) for value in data['static_functions'].values()), 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
