"""Check new explicit source declarations independently; never compile or import payloads."""

import ast
from collections import deque
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ORIGINAL = '27471b9c61b958f759e9f48b80acaf60cdf75f2e'
CONTRACT_SHA = '8ee53eaf913e5ad5639ce874ad3b205e91ba1425634047c63c6b62d0b6cfaaf0'


# Bind complete finite metadata before following any paths or source declarations.
def read_json(path, expected):
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == expected, str(path)
    return json.loads(raw)


# Read only original hash-pinned source bytes, preserving the original source identity.
def original(path, pins):
    candidate = REPO / path
    raw = candidate.read_bytes() if candidate.is_file() else b''
    if sha256(raw).hexdigest() != pins[path]:
        raw = subprocess.run(['git', 'show', ORIGINAL + ':' + path], cwd=REPO, capture_output=True, check=True).stdout
    assert sha256(raw).hexdigest() == pins[path], path
    return raw


# Select a qualified declaration directly from inert source text.
def selected(raw, name):
    value = ast.parse(raw)
    for part in name.split('.'):
        value = next(item for item in value.body if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == part)
    return deepcopy(value)


# Compare complete ASTs while deliberately excluding positions and CodeType claims.
def same(left, right):
    assert ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


# Rebind only explicit original namespace references and declared new local identities.
class Rebind(ast.NodeTransformer):
    # Retain the finite names and module attributes allowed by this source comparison.
    def __init__(self, names=None, attributes=None):
        self.names = names or {}
        self.attributes = attributes or {}

    # Rename declared load-site identifiers without accepting arbitrary source rewrites.
    def visit_Name(self, value):
        return ast.copy_location(ast.Name(id=self.names.get(value.id, value.id), ctx=value.ctx), value)

    # Replace only a declared simple module attribute with its explicit new local binding.
    def visit_Attribute(self, value):
        key = ast.unparse(value)
        if key in self.attributes:
            return ast.copy_location(ast.Name(id=self.attributes[key], ctx=value.ctx), value)
        return self.generic_visit(value)


# Resolve actual Python source origins from the proposed declaration, without importing them.
def origin(module, pins):
    stem = module.replace('.', '/')
    values = [path for path in (stem + '.py', stem + '/__init__.py') if path in pins]
    assert len(values) <= 1, module
    return values[0] if values else None


# Inspect module and class lexical imports while leaving callable bodies unentered.
def module_imports(value):
    result = []
    for child in ast.iter_child_nodes(value):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            result.append(child)
        else:
            result.extend(module_imports(child))
    return result


# Record source import reachability, original origins and deferred seams without executing code.
def graph(pins, overlays, original_pins):
    roots = ['backend.market.capacity_original_inputs_v1']
    pending, nodes, edges, external, deferred = deque(roots), {}, [], [], []
    while pending:
        module = pending.popleft()
        if module in nodes:
            continue
        path = origin(module, pins)
        assert path is not None, module
        raw = overlays[path] if path in overlays else original(path, original_pins)
        assert sha256(raw).hexdigest() == pins[path]
        value = ast.parse(raw)
        nodes[module] = {'path': path, 'sha256': pins[path], 'bytes': len(raw), 'source': 'explicit new capacity/variant source' if path in overlays else 'exact unchanged original source'}
        parts = module.split('.')
        for stop in range(1, len(parts)):
            target = '.'.join(parts[:stop])
            if origin(target, pins):
                edges.append({'from': module, 'to': target, 'line': None, 'kind': 'implicit_package'})
                pending.append(target)
        active = module_imports(value)
        for declaration in active:
            if isinstance(declaration, ast.Import):
                targets = [alias.name for alias in declaration.names]
            else:
                assert declaration.level == 0, module
                base = declaration.module or ''
                targets = [base] + [base + '.' + alias.name for alias in declaration.names if alias.name != '*']
            for target in sorted({name for name in targets if origin(name, pins)}):
                edges.append({'from': module, 'to': target, 'line': declaration.lineno, 'kind': 'source_import'})
                pending.append(target)
            external.extend({'from': module, 'line': declaration.lineno, 'statement': ast.unparse(declaration)} for _ in [0] if not any(name.startswith('backend') for name in targets))
            assert not any(name.startswith('backend') and not origin(name, pins) for name in targets[:1])
        active_ids = {id(item) for item in active}
        deferred.extend({'from': module, 'line': item.lineno, 'statement': ast.unparse(item)} for item in ast.walk(value) if isinstance(item, (ast.Import, ast.ImportFrom)) and id(item) not in active_ids)
    return {'roots': roots, 'nodes': nodes, 'edges': edges, 'external_package_declarations_not_admitted': external, 'callable_scope_imports_not_followed': deferred}


# Validate every declared AST transformation and the new map transition before source review.
def main():
    contract = read_json(DOCS / 'original-loader-entry-source-contract-v1-2026-10-18.json', CONTRACT_SHA)
    old = read_json(DOCS / 'original-loader-genuine-source-map-2026-10-18.json', '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224')
    prior = read_json(DOCS / 'original-loader-admission-source-map-v1-2026-10-18.json', 'a68ebbefb776a93dfdfb56fc6c4893ac35450a224fcf2fa50498cb911bfeda43')
    map_record = contract['map_declaration']
    declared = read_json(DOCS / map_record['path'], map_record['sha256'])
    pins = declared['files']
    assert len(pins) == 2457 and len(prior['files']) == 2453
    assert {path for path in prior['files'] if pins[path] != prior['files'][path]} == {'backend/market/learned_entry_data.py'}
    assert set(pins) - set(prior['files']) == set(declared['new_modules'])
    assert sha256(json.dumps(pins, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == contract['map_compact_files_sha256']
    overlays, new = {}, {}
    for name, record in contract['modules'].items():
        raw = (DOCS / record['path']).read_bytes()
        assert sha256(raw).hexdigest() == record['sha256'] == pins[record['proposed_origin']]
        assert len(raw) == record['bytes'] <= 262144
        overlays[record['proposed_origin']] = raw
        new[name] = raw
    variant = (DOCS / 'sources/capacity-learned-entry-data-import-cut-v1-2026-10-18.py').read_bytes()
    assert sha256(variant).hexdigest() == pins['backend/market/learned_entry_data.py'] == '21adedb2a11ef8fe9802c4be6c2783b684bfd755db17032ae4bbaf0a2e2a693e'
    overlays['backend/market/learned_entry_data.py'] = variant
    old_module_names = {
        'capacity_original_archive_adaptations_v1': 'original-loader-capacity-archive-adaptations-v1-2026-10-18.py',
        'capacity_original_archives_v1': 'original-loader-capacity-archive-context-v1-2026-10-18.py',
        'capacity_original_evidence_v1': 'original-loader-capacity-evidence-v1-2026-10-18.py',
        'capacity_original_metadata_v1': 'original-loader-capacity-metadata-boundary-2026-10-18.py',
    }
    for name, filename in old_module_names.items():
        path = 'backend/market/' + name + '.py'
        raw = (DOCS / 'sources' / filename).read_bytes()
        assert sha256(raw).hexdigest() == pins[path]
        overlays[path] = raw
    originals = {path: original(path, old) for path in contract['original_sources']}
    audit = originals['backend/market/live_model_history_audit_inputs.py']
    econ = originals['backend/cli/market_actual_policy_timing.py']
    historical = originals['backend/market/live_model_history.py']
    predecessor = originals['backend/market/counterfactual_holding.py']
    original_daily = selected(originals['backend/cli/market_strategy_continue.py'], 'inputs')
    cutoff = next(index for index, item in enumerate(original_daily.body) if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'shape' for target in item.targets))
    daily = selected(new['daily-inputs'], 'daily_prefix')
    assert len(daily.body) == cutoff + 1
    for first, second in zip(original_daily.body[:cutoff], daily.body[:-1], strict=True):
        same(first, second)
    same(daily.body[-1], ast.parse('return panel, grades, eligible, factors, actions, sources').body[0])
    checks = ['original_prefix_statements_and_explicit_return']
    for name in ('economic_paths', 'align_passive'):
        same(selected(audit, name), selected(new['economics'], name))
        checks.append(name)
    same(selected(audit, 'readonly'), selected(new['inputs'], 'readonly'))
    checks.append('readonly')
    removed_economics = {'economics.' + name: name for name in ('ECONOMIC_INPUT_PROOF_SHA', 'ACTIONS_SHA', 'ACTION_REVIEW_SHA', 'PASSIVE_ARRAYS_SHA', 'PASSIVE_RECEIPT_SHA', 'load_passive_inputs')}
    same(Rebind(attributes=removed_economics).visit(selected(audit, 'reviewed_economics')), selected(new['economics'], 'reviewed_economics'))
    checks.append('reviewed_economics_explicit_namespace')
    expected = Rebind(names={'plain': '_passive_provenance_plain'}, attributes={'forecasts.evidence': '_passive_evidence'}).visit(selected(econ, 'load_passive_inputs'))
    same(expected, selected(new['economics'], 'load_passive_inputs'))
    checks.append('load_passive_inputs_bindings')
    expected = selected(originals['backend/cli/market_probabilistic_execution.py'], 'evidence')
    expected.name = '_passive_evidence'
    expected = Rebind(names={'sha256': '_file_sha256'}).visit(expected)
    same(expected, selected(new['economics'], '_passive_evidence'))
    expected = selected(originals['backend/cli/market_learned_entry.py'], 'sha256')
    expected.name = '_file_sha256'
    same(expected, selected(new['economics'], '_file_sha256'))
    checks.extend(['passive_evidence_original_semantics', 'file_hash_path_API'])
    expected = selected(originals['backend/market/live_policy_replay.py'], 'plain')
    expected.name = '_passive_provenance_plain'
    expected = Rebind(names={'plain': '_passive_provenance_plain'}).visit(expected)
    branch = expected.body[2]
    assert isinstance(branch, ast.If) and isinstance(branch.body[0].value, ast.IfExp)
    branch.body = ast.parse('require(math.isfinite(value), "FINITE_PASSIVE_PROVENANCE_REQUIRED")\nreturn float(value)').body
    same(expected, selected(new['economics'], '_passive_provenance_plain'))
    checks.append('only_nonfinite_refusal_in_provenance_projection')
    same(selected(predecessor, 'CounterfactualRiskReader.__init__'), selected(new['frozen-readers'], 'CapacityCounterfactualRiskBaseV1.__init__'))
    same(selected(historical, 'FrozenCurrentRiskReader.__init__'), selected(new['frozen-readers'], 'CapacityFrozenRiskReaderV1.__init__'))
    expected = Rebind(names={'FrozenCurrentRiskReader': 'CapacityFrozenRiskReaderV1'}).visit(selected(historical, 'FrozenCurrentMarketReader.__init__'))
    same(expected, selected(new['frozen-readers'], 'CapacityFrozenMarketReaderV1.__init__'))
    bases = {value.name: [ast.unparse(base) for base in value.bases] for value in ast.parse(new['frozen-readers']).body if isinstance(value, ast.ClassDef)}
    assert bases == {'CapacityCounterfactualRiskBaseV1': ['forward_arithmetic.ForwardVolatilityHoldingReader'], 'CapacityFrozenRiskReaderV1': ['CapacityCounterfactualRiskBaseV1'], 'CapacityFrozenMarketReaderV1': ['ForwardMarketConditionedHoldingReader']}
    checks.extend(['base_constructor_separate_frame', 'frozen_constructor_super_then_second_features', 'market_constructor_new_exact_parent', 'real_base_MRO_declaration'])
    expected = selected(audit, 'AuditInputs')
    expected.name = 'CapacityAuditInputsV1'
    expected = Rebind(names={'FrozenCurrentMarketReader': 'CapacityFrozenMarketReaderV1'}).visit(expected)
    same(expected, selected(new['inputs'], 'CapacityAuditInputsV1'))
    checks.append('six_result_fields_new_identity')
    expected = selected(audit, 'load')
    expected.name = '_load_capacity_inputs'
    expected = Rebind(names={'FrozenCurrentMarketReader': 'CapacityFrozenMarketReaderV1', 'FrozenCurrentRiskReader': 'CapacityFrozenRiskReaderV1', 'AuditInputs': 'CapacityAuditInputsV1'}, attributes={'economics.ECONOMIC_INPUT_PROOF_SHA': 'ECONOMIC_INPUT_PROOF_SHA'}).visit(expected)
    actual = selected(new['inputs'], '_load_capacity_inputs')
    first = actual.body.pop(0)
    same(first, ast.parse('require(type(archives) is CapacityOriginalArchivesV1, "EXACT_CAPACITY_ARCHIVE_CONTEXT_REQUIRED")').body[0])
    extra = [item for item in actual.body if isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and ast.unparse(item.value.func) == 'require_factory_head']
    assert len(extra) == 1
    index = actual.body.index(extra[0])
    assert ast.unparse(actual.body[index - 1].value.func) == 'forward_arithmetic.load_publication'
    same(extra[0], ast.parse('require_factory_head(head, model)').body[0])
    actual.body.remove(extra[0])
    same(expected, actual)
    checks.append('private_load_only_declared_two_guards_and_type_namespace_rebindings')
    expected_guard = ast.parse('def require_factory_head(head, model):\n    require(head is None or type(head) is direct_daily_arithmetic.NumericHead, "EXACT_NUMERIC_FACTORY_HEAD_REQUIRED")\n    require((head is not None) == (model["status"] == "fitted"), "NUMERIC_FACTORY_STATUS_REQUIRED")').body[0]
    same(expected_guard, selected(new['inputs'], 'require_factory_head'))
    checks.append('factory_guard_only_type_and_fitted_nonnull_consistency')
    execute = selected(new['inputs'], 'execute')
    same(execute, ast.parse('def execute(*args, **kwargs):\n    raise RuntimeError("CAPACITY_MODEL_ENTRY_UNADMITTED")').body[0])
    checks.append('public_execute_unconditionally_refuses')
    for kind, names in contract['original_constant_assignments'].items():
        before = ast.parse(audit if kind == 'audit' else econ)
        for name in names:
            target = new['economics'] if name in ('ECONOMIC_RECEIPT_SHA256',) or kind == 'economics' else new['inputs']
            old_assignment = next(item for item in before.body if isinstance(item, ast.Assign) and any(isinstance(key, ast.Name) and key.id == name for key in item.targets))
            new_assignment = next(item for item in ast.parse(target).body if isinstance(item, ast.Assign) and any(isinstance(key, ast.Name) and key.id == name for key in item.targets))
            same(old_assignment, new_assignment)
    checks.append('all12_original_constant_assignments')
    imports = graph(pins, overlays, old)
    harness = (DOCS / 'sources/original-loader-capacity-harness-v3-2026-10-18.py').read_bytes()
    assert sha256(harness).hexdigest() == '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
    prefixes = next(ast.literal_eval(item.value) for item in ast.parse(harness).body if isinstance(item, ast.Assign) and any(isinstance(key, ast.Name) and key.id == 'EFFECT_MODULES' for key in item.targets))
    assert len(prefixes) == 5 and not any(name.startswith(prefix) for name in imports['nodes'] for prefix in prefixes)
    assert not any(name.startswith('backend.cli') or name in ('backend.market.live_model_history', 'backend.market.live_policy_replay', 'backend.market.live_model_history_stream_audit') for name in imports['nodes'])
    report = {'schema': 'capacity-original-entry-independent-source-review/1', 'status': 'SOURCE_AST_AND_DECLARED_IMPORT_GRAPH_ONLY_ALL_BODIES_UNRUN', 'contract_sha256': CONTRACT_SHA, 'modules': contract['modules'], 'map_declaration': map_record, 'AST_checks': checks, 'guard_effect_prefixes': list(prefixes), 'candidate_module_count': len(imports['nodes']), 'candidate_edge_count': len(imports['edges']), 'graph': imports, 'scope': 'Lexical explicit module/class imports plus implicit packages only. No branch/default/decorator/annotation evaluation, generated CodeTypes, dynamic/native-extension/callable-body/package/runtime closure or actual import-order proof.', 'new_map_is_declaration_not_execution_admission': True, 'factory_type_status_guard_is_not_provenance_by_itself': True, 'inherited_distribution_and_fit_methods_present_but_unadmitted': True, 'private_provenance_nonfinite_branch_refuses_not_normalizes': True, 'entrypoint_model_strategy_finder_phase_generated_runtime_launch_admission': None, 'application_numpy_model_test_SSH_Docker_account_data_bodies_or_operations': False}
    raw = json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    path = DOCS / 'original-loader-entry-independent-source-review-v1-2026-10-18.json'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    print(json.dumps({'report_sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'AST_checks': len(checks), 'modules': len(imports['nodes']), 'edges': len(imports['edges']), 'deferred_imports': len(imports['callable_scope_imports_not_followed']), 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
