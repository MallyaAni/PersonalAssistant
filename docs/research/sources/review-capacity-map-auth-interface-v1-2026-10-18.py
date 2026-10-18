"""Independently inspect the new pure-data interface as source, without payload imports."""

import ast
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
CONTRACT_SHA = 'be1f4037e000f158b77a3cf085d77f2c3de23663b863bcb8b81de14a2674899b'
MAP_SHA = 'd78058068ee9fb03722971917a32dcb6589dcf43fa2320fa51d4c998e8c695f0'
GUARD_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'


# Read exact source bytes without importing their modules or running their functions.
def pinned(path, expected):
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == expected, str(path)
    return raw


# Select a complete declaration for comparison while preserving all nested statements.
def selected(tree, qualified):
    for name in qualified.split('.'):
        tree = next(node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == name)
    return tree


# Compare complete syntax trees without claiming executable identity or behavioral parity.
def same(first, second):
    assert ast.dump(first, include_attributes=False) == ast.dump(second, include_attributes=False)


# Undo only one declared module import and require the original source shape exactly.
def restore_import(tree, before, after):
    matches = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == 'backend.market' and len(node.names) == 1 and node.names[0].name == after]
    assert len(matches) == 1, (before, after)
    matches[0].names[0].name = before


# Restore one explicit schema assignment after checking its exact proposed value.
def restore_schema(tree, before, after):
    rows = [node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'SCHEMA' for target in node.targets)]
    assert len(rows) == 1 and ast.literal_eval(rows[0].value) == after
    rows[0].value = ast.Constant(before)


# Record every function declaration as static source rather than a compiled call allowlist.
def declarations(tree, prefix=''):
    result = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = prefix + node.name
            if isinstance(node, ast.FunctionDef):
                result.append({'qualname': name, 'line': node.lineno, 'end_line': node.end_lineno, 'AST_sha256': sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()})
            result.extend(declarations(node, name + '.'))
    return result


# Fold exact source deltas, original guard ordering and uncomposed new identity boundaries.
def main():
    contract = json.loads(pinned(DOCS / 'original-loader-map-auth-interface-source-contract-v1-2026-10-18.json', CONTRACT_SHA))
    original = {key: pinned(REPO / row['path'], row['sha256']) for key, row in contract['original_sources'].items()}
    candidate = {key: pinned(DOCS / row['path'], row['sha256']) for key, row in contract['modules'].items()}
    assert all(len(raw) <= 262144 for raw in candidate.values())
    old_trees = {key: ast.parse(raw) for key, raw in original.items()}
    trees = {key: ast.parse(raw) for key, raw in candidate.items()}
    normalized = deepcopy(trees)
    changed = []
    method = selected(normalized['parser'], 'ShaMap.authenticate_contents')
    method.name = 'verify'
    renamed_calls = []
    for kind in ('parser', 'input_auth', 'archives'):
        rows = [node for node in ast.walk(normalized[kind]) if isinstance(node, ast.Attribute) and node.attr == 'authenticate_contents']
        assert len(rows) == 1, kind
        renamed_calls.append({'module': kind, 'line': rows[0].lineno, 'receiver': ast.unparse(rows[0].value)})
        rows[0].attr = 'verify'
    changed.extend(['exact_ShaMap_method_declaration_rename', 'exact3_direct_acceptance_calls_renamed'])
    for kind in ('input_auth', 'adaptations', 'archives'):
        restore_import(normalized[kind], 'original_history_json', 'capacity_original_history_json_v1')
    restore_import(normalized['archives'], 'live_model_history_input_auth', 'capacity_original_input_auth_v1')
    restore_import(normalized['archives'], 'capacity_original_archive_adaptations_v1', 'capacity_original_archive_adaptations_v2')
    restore_schema(normalized['adaptations'], 'capacity-original-archive-adaptations/1', 'capacity-original-archive-adaptations/2')
    restore_schema(normalized['archives'], 'capacity-original-archive-context/1', 'capacity-original-archive-context/2')
    names = {'CapacityOriginalArchivesV2': 'CapacityOriginalArchivesV1', 'CapacitySourceReaderV2': 'CapacitySourceReaderV1'}
    seen = set()
    for node in ast.walk(normalized['archives']):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names:
            seen.add(node.name)
            node.name = names[node.name]
        elif isinstance(node, ast.Name) and node.id in names:
            seen.add(node.id)
            node.id = names[node.id]
    assert seen == set(names)
    changed.extend(['exact5_explicit_import_rebindings', 'exact2_schema_assignments', 'exact2_archive_class_names_and_references'])
    for kind in trees:
        same(old_trees[kind], normalized[kind])
        changed.append(kind + '_FULL_MODULE_AST_after_only_declared_deltas')
    old_rows = [selected(old_trees['parser'], 'Cursor.sha_map'), selected(old_trees['input_auth'], 'verify_sha_map'), selected(old_trees['archives'], 'CapacityOriginalArchivesV1.unchanged')]
    assert all(sum(isinstance(node, ast.Attribute) and node.attr == 'verify' for node in ast.walk(row)) == 1 for row in old_rows)
    assert sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'verify_sha_map' for node in ast.walk(selected(old_trees['input_auth'], 'authenticate'))) == 3
    assert all(not any(isinstance(node, ast.FunctionDef) and node.name == 'verify' or isinstance(node, ast.Attribute) and node.attr == 'verify' for node in ast.walk(tree)) for tree in trees.values())
    assert any(isinstance(node, ast.Call) and ast.unparse(node.func) == 'streamed.read' for node in ast.walk(selected(old_trees['archives'], 'CapacityOriginalArchivesV1.__init__')))
    changed.append('all_selected_direct_verify_sites_and_three_byte_auth_edges_accounted')
    guard = ast.parse(pinned(DOCS / contract['guard']['path'], GUARD_SHA))
    forbidden = next(node.value for node in guard.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'FORBIDDEN_NAMES' for target in node.targets))
    assert 'verify' in ast.literal_eval(forbidden.args[0]) and 'authenticate_contents' not in ast.literal_eval(forbidden.args[0])
    profile = selected(guard, 'CallFence.profile')
    deny = next(node for node in profile.body if isinstance(node, ast.If) and any(isinstance(call, ast.Call) and ast.unparse(call.func) == 'self.trip' and call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == 'FORBIDDEN_FUNCTION' for call in ast.walk(node)))
    lookup = next(node for node in profile.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'registered' for target in node.targets))
    assert deny.lineno < lookup.lineno
    changed.append('unchanged_guard_forbidden_name_precedes_manifest_lookup')
    declaration = json.loads(pinned(DOCS / 'original-loader-map-auth-interface-source-map-v1-2026-10-18.json', MAP_SHA))
    base = json.loads(pinned(DOCS / 'original-loader-composition-source-map-v1-2026-10-18.json', declaration['base2459_sha256']))
    assert len(base['files']) == 2459 and len(declaration['files']) == 2463
    additions = {row['proposed_origin']: row['sha256'] for row in contract['modules'].values()}
    assert declaration['additions'] == additions and not set(additions) & set(base['files'])
    assert declaration['files'] == {**base['files'], **additions}
    assert all(value is None for value in contract['unadmitted'].values()) and contract['execution_authorized'] is False
    changed.append('exact4_additions_no_old2459_source_substitution_or_admission')
    inventories = {key: declarations(tree) for key, tree in trees.items()}
    assert sum(map(len, inventories.values())) == 79
    for kind, tree in trees.items():
        lines = candidate[kind].decode().splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                first = min([node.lineno] + [item.lineno for item in node.decorator_list])
                assert lines[first - 2].lstrip().startswith('#')
    report = {'schema': 'capacity-map-auth-interface-independent-source-review/1', 'status': 'SOURCE_AST_ONLY_ALL79_PAYLOAD_FUNCTIONS_UNRUN', 'contract_sha256': CONTRACT_SHA, 'map_sha256': MAP_SHA, 'guard_sha256': GUARD_SHA, 'checks': changed, 'renamed_direct_sites': renamed_calls, 'guard_forbidden_line': deny.lineno, 'guard_registered_lookup_line': lookup.lineno, 'modules': contract['modules'], 'static_declarations_NOT_compiled_allowlist': inventories, 'upstream_composition_and_all_runtime_acceptance': None, 'limits': ['Complete normalized AST equality is source evidence only; new module globals/class/type identities and method CodeTypes differ.', 'New reader/input-auth/context/adaptations must be selected consistently; old V1 exact-type input guard and lifecycle Pins/authenticate are not composed with them.', 'The new method name is absent from forbidden names; no full import/call/native/generated/phase/finder or model guard compatibility claim.', 'Original guard/sources/data/receipts and all failed/completed roots unchanged; no old receipt relabel, generic NaN normalization or gate replay.']}
    raw = json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    path = DOCS / 'original-loader-map-auth-interface-independent-source-review-v1-2026-10-18.json'
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw
    print(json.dumps({'report_sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'checks': len(changed), 'payload_functions': 79, 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
