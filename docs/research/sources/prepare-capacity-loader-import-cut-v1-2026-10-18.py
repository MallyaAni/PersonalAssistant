"""Prepare a distinct inert import cut and inspect exact source graphs, never code bodies."""

import ast
from collections import deque
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-loader-import-cut-source-20261018-v1')
ORIGINAL = '27471b9c61b958f759e9f48b80acaf60cdf75f2e'
MAP_SHA = '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
TARGET = 'backend/market/learned_entry_data.py'
VARIANT = 'sources/capacity-learned-entry-data-import-cut-v1-2026-10-18.py'
NUMERICAL_ROOTS = (
    'backend.market.forward_arithmetic',
    'backend.market.holding_risk_bank',
    'backend.market.conditional_holding_calibration',
    'backend.market.market_conditioned_holding',
    'backend.market.market_conditioned_calibration',
)


# Identify exact bytes without normalizing their source representation.
def digest(raw):
    return sha256(raw).hexdigest()


# Retain only a newly named bounded artifact with fsync and exact readback.
def save(path, raw):
    assert len(raw) <= 262144, str(path)
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


# Encode finite source metadata separately from application or model objects.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Select only bytes matching the immutable composed map, or fail without a substitute.
def read_source(name, pins, cache):
    if name not in cache:
        path = REPO / name
        raw = path.read_bytes() if path.is_file() else b''
        origin = 'matching local source'
        if digest(raw) != pins[name]:
            raw = subprocess.run(
                ['git', 'show', ORIGINAL + ':' + name], cwd=REPO,
                capture_output=True, check=True,
            ).stdout
            origin = 'exact original Git blob'
        assert digest(raw) == pins[name] and len(raw) <= 1048576, name
        cache[name] = (raw, origin)
        assert len(cache) <= 1024 and sum(len(row[0]) for row in cache.values()) <= 32 * 1048576
    return cache[name]


# Map an import name only when the declared source map contains its Python origin.
def module_path(name, pins):
    stem = name.replace('.', '/')
    matches = [path for path in (stem + '.py', stem + '/__init__.py') if path in pins]
    assert len(matches) <= 1, name
    return matches[0] if matches else None


# Inspect imports in module and class execution scopes while excluding callable bodies.
def scope_imports(node, conditional=False):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            yield child, conditional
        else:
            branch = conditional or isinstance(child, (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.Match))
            yield from scope_imports(child, branch)


# Resolve explicit source imports and preserve unresolved external package declarations.
def import_targets(node, current, pins):
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    else:
        base = node.module or ''
        if node.level:
            path = module_path(current, pins)
            package = current if path.endswith('/__init__.py') else current.rsplit('.', 1)[0]
            parts = package.split('.')
            assert node.level <= len(parts), current
            base = '.'.join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
        names = [base]
        names += [base + '.' + alias.name for alias in node.names if alias.name != '*']
    local = {name for name in names if module_path(name, pins)}
    external = {name for name in names[:1] if name and not name.startswith('backend')}
    unresolved = {name for name in names[:1] if name.startswith('backend') and not module_path(name, pins)}
    return sorted(local), sorted(external), sorted(unresolved)


# Follow declared import edges without importing modules or evaluating branch conditions.
def graph(roots, pins, cache, variant=None):
    pending, nodes, edges, externals, unresolved, deferred = deque(roots), {}, [], [], [], []
    while pending:
        name = pending.popleft()
        if name in nodes:
            continue
        path = module_path(name, pins)
        assert path is not None, name
        original_raw, origin = read_source(path, pins, cache)
        raw = variant if variant is not None and path == TARGET else original_raw
        tree = ast.parse(raw, filename=path)
        nodes[name] = {'path': path, 'sha256': digest(raw), 'bytes': len(raw), 'origin': 'separate proposed source variant' if raw != original_raw else origin}
        parts = name.split('.')
        for index in range(1, len(parts)):
            parent = '.'.join(parts[:index])
            if module_path(parent, pins):
                edges.append({'from': name, 'to': parent, 'kind': 'implicit_package', 'line': None, 'conditional': False})
                pending.append(parent)
        imports = list(scope_imports(tree))
        active = {id(node) for node, _ in imports}
        for node, conditional in imports:
            local, external, missing = import_targets(node, name, pins)
            for target in local:
                edges.append({'from': name, 'to': target, 'kind': 'source_import', 'line': node.lineno, 'conditional': conditional})
                pending.append(target)
            for target in external:
                externals.append({'from': name, 'line': node.lineno, 'module': target, 'conditional': conditional})
            for target in missing:
                unresolved.append({'from': name, 'line': node.lineno, 'module': target})
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in active:
                deferred.append({'from': name, 'line': node.lineno, 'statement': ast.unparse(node)})
    return {'roots': list(roots), 'nodes': nodes, 'edges': edges, 'external_declarations': externals, 'unresolved_backend_imports': unresolved, 'callable_scope_import_declarations_not_followed': deferred}


# Keep graph evidence below ordinary file bounds through exclusive paged records.
def pages(label, value):
    records = []
    for section, rows in value.items():
        iterable = [{'name': key, **row} for key, row in sorted(rows.items())] if isinstance(rows, dict) else rows
        records.extend({'section': section, 'value': row} for row in iterable)
    result = []
    for start in range(0, len(records), 64):
        path = DOCS / f'original-loader-import-cut-{label}-page-{start // 64:03d}-2026-10-18.json'
        record = save(path, encoded({'schema': 'capacity-loader-source-graph-page/1', 'records': records[start:start + 64]}))
        record['path'] = path.name
        result.append(record)
    return {'nodes': len(value['nodes']), 'edges': len(value['edges']), 'external_declarations': len(value['external_declarations']), 'deferred_imports': len(value['callable_scope_import_declarations_not_followed']), 'unresolved_backend_imports': value['unresolved_backend_imports'], 'pages': result}


# Locate one qualified declaration and bind its complete AST without compiling it.
def declaration(raw, qualified):
    node = ast.parse(raw)
    for name in qualified.split('.'):
        node = next(child for child in node.body if isinstance(child, (ast.FunctionDef, ast.ClassDef)) and child.name == name)
    return node


# Identify source-coupled calls and allocation operations within selected exact declarations.
def describe(raw, qualified):
    node = declaration(raw, qualified)
    calls = sorted({ast.unparse(child.func) for child in ast.walk(node) if isinstance(child, ast.Call)})
    return {'line': node.lineno, 'end_line': node.end_lineno, 'AST_sha256': digest(ast.dump(node, include_attributes=False).encode()), 'calls': calls}


# Mark only the unchanged guard's broker and account namespace boundaries.
def effect(name):
    return name.startswith('backend.agents.trading.desk') or name in ('backend.market.alpaca_trading', 'backend.market.replay_broker')


# Prepare the single import relocation and a source-only entry closure contract.
def main():
    ROOT.mkdir(exist_ok=False)
    map_raw = (DOCS / 'original-loader-genuine-source-map-2026-10-18.json').read_bytes()
    assert digest(map_raw) == MAP_SHA
    pins, cache = json.loads(map_raw), {}
    assert len(pins) == 2446
    raw, origin = read_source(TARGET, pins, cache)
    old_import = b'from backend.market.fill_timing import session_scale\n'
    signature = b'def prepare(panel, grades, eligible, cubes):\n'
    assert raw.count(old_import) == raw.count(signature) == 1
    variant = raw.replace(old_import, b'').replace(signature, signature + b'    ' + old_import)
    before, after = ast.parse(raw), ast.parse(variant)
    original_import = next(node for node in before.body if isinstance(node, ast.ImportFrom) and node.module == 'backend.market.fill_timing')
    before.body.remove(original_import)
    prepared = next(node for node in after.body if isinstance(node, ast.FunctionDef) and node.name == 'prepare')
    moved = prepared.body.pop(0)
    assert ast.dump(original_import, include_attributes=False) == ast.dump(moved, include_attributes=False)
    assert ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False)
    variant_record = save(DOCS / VARIANT, variant)
    variant_record['path'] = VARIANT
    save(ROOT / 'original-learned-entry-data.py', raw)
    save(ROOT / 'variant.py', variant)
    numerical = graph(NUMERICAL_ROOTS, pins, cache)
    candidate = graph(NUMERICAL_ROOTS, pins, cache, variant)
    loader = graph(('backend.market.live_model_history_audit_inputs',), pins, cache)
    original_effects = sorted(name for name in numerical['nodes'] if effect(name))
    candidate_effects = sorted(name for name in candidate['nodes'] if effect(name))
    assert original_effects and not candidate_effects
    assert all(not value['unresolved_backend_imports'] for value in (numerical, candidate, loader))
    witness = ['backend.market.forward_arithmetic', 'backend.market.direct_daily_arithmetic', 'backend.market.learned_entry_data', 'backend.market.fill_timing', 'backend.agents.trading.desk.paper']
    assert all(any(row['from'] == left and row['to'] == right and not row['conditional'] for row in numerical['edges']) for left, right in zip(witness, witness[1:]))
    selections = {
        'backend/market/live_model_history_audit_inputs.py': ('load', 'daily_prefix', 'economic_paths', 'align_passive', 'reviewed_economics', 'readonly', 'AuditInputs'),
        'backend/cli/market_strategy_continue.py': ('inputs',),
        'backend/cli/market_actual_policy_timing.py': ('load_passive_inputs',),
        'backend/market/holding_risk_bank.py': ('load_bank', '_sources'),
        'backend/market/forward_arithmetic.py': ('load_publication', '_admit'),
        'backend/market/direct_daily_arithmetic.py': ('numeric_head', 'numeric_identity', 'NumericHead.predict', 'predict'),
        'backend/market/learned_retention_models.py': ('completed_features',),
        TARGET: ('_validate_panel', '_daily_context', 'prepare'),
        'backend/market/live_model_history.py': ('FrozenCurrentRiskReader.__init__', 'FrozenCurrentMarketReader.__init__'),
        'backend/market/counterfactual_holding.py': ('CounterfactualRiskReader.__init__',),
        'backend/market/conditional_holding_calibration.py': ('_Calibration._bind',),
        'backend/market/market_conditioned_holding.py': ('_MarketCalibration._bind', '_MarketCalibration._stock_fit'),
        'backend/market/calendar.py': ('reviewed_sessions', 'session_close'),
        'backend/market/panel.py': ('Panel', 'panel_from_histories', 'build_panel'),
        'backend/market/store.py': ('MarketStore.read',),
    }
    facts = {}
    for path, names in selections.items():
        content, _ = read_source(path, pins, cache)
        facts.update({path + ':' + name: describe(content, name) for name in names})
    report = {
        'schema': 'capacity-loader-import-cut-source-review/1',
        'status': 'SOURCE_ONLY_IMPORT_CUT_PROVED_NUMERICAL_AND_GENUINE_BODIES_UNRUN',
        'starting_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, check=True, text=True).stdout.strip(),
        'original_composed_map': {'sha256': MAP_SHA, 'files': 2446, 'unchanged': True},
        'old_capacity2453_map_unchanged': True,
        'variant': {**variant_record, 'original_sha256': pins[TARGET], 'original_origin': origin, 'prospective_origin': '/app/' + TARGET, 'source_identity': 'NEW explicitly changed executor source, never original source identity', 'sole_change': 'Move the exact fill_timing.session_scale import into intraday prepare before its previous first statement.', 'all_other_AST_nodes_identical': True, 'module_global_session_scale_alias_removed': True, 'prepare_CodeType_and_import_order_changed': True, 'old_capacity_binding_accepts_variant': False, 'old_refusal': 'LEGACY_SOURCE_OVERRIDE_FORBIDDEN', 'new_explicit_map_transition_required': True, 'module_and_callable_bodies_executed': False},
        'graphs': {'original_numerical': pages('original-numerical', numerical), 'candidate_numerical': pages('candidate-numerical', candidate), 'original_loader': pages('original-loader', loader)},
        'scope': 'Static explicit imports in module/class scopes including unexecuted branches, plus implicit packages. Callable imports are recorded but not followed. No branch evaluation, import order certificate, dynamic import/native-extension/package-origin or executable-call closure.',
        'original_numerical_effect_imports': original_effects,
        'candidate_numerical_effect_imports_in_declared_graph': candidate_effects,
        'unconditional_original_witness': witness,
        'exact_declarations': facts,
        'entry_bindings_required': [
            'Separate versioned capacity entry/result dataclass, real exact CapacityOriginalArchivesV1, full authenticated original metadata and new source map. No old load entry reroute or public execute change.',
            'Explicit daily loader using original prefix statement order with exact panel/store/yahoo source and pyarrow origin. No continuation CLI import or runtime CodeType/AST masquerading. Original inspect.getsource hash remains original-only evidence; new source needs its own binding.',
            'Explicit economic helper using exact constants, strict pinned evidence, original action/passive functions and full calendar.session_close/REGULAR_OPEN/NEW_YORK. Tiny reviewed_sessions-only capacity calendar cannot supply that interface.',
            'Readonly execution inputs may retain original real module after fresh full-map/fence review; its original calendar import follows panel/store/yahoo. Do not alias the small capacity calendar into original globals.',
            'Explicit capacity risk constructor preserves both complete_features calls, both prediction calls, all original copies and readonly transitions with a declared new reader identity. Inherit unchanged ForwardVolatilityHoldingReader if retaining _Calibration isinstance semantics; exact new-parent check replaces only old FrozenCurrentRiskReader identity.',
            'Retain unchanged original _Calibration._bind and _MarketCalibration._bind at real paths to preserve deepcopy, isinstance ForwardVolatilityHoldingReader, original file/protocol hashes and original market-context selection. No select/distribution/_stock_fit/fit_market_log calls.',
            'Keep holding_risk_bank._sources original self/dependency/calendar file hashes and three actual frozen calendar data files. Authenticate original producer root separately from new executor root; no alias or relabel of changed executor bytes.',
        ],
        'lifetime_requirements': [
            'First completed_features graph lives through first prediction and CloseObservation/bank copies; it may release when CounterfactualRiskReader constructor returns before second completed_features call.',
            'Second completed_features graph and full predictions coexist with all frozen copies until FrozenCurrentRiskReader constructor returns.',
            'Market binding deepcopies the complete parent before freezes/context copy; original parent, its copy, panel/raw arrays, bank/head/receipts and overlay remain live during this binding.',
            'After loader return retain real loaded object, archives/ShaMap/Rows and both complete byte-auth receipt graphs plus full JSON and UTF8 through durable result and actual late peak observation. Source array sizes and synthetic peaks are not combined RAM bounds.',
        ],
        'model_source_path_observation': 'Unchanged load_publication restores non-executable numeric NPZ and numeric_head constructs NumericHead; NumericHead.predict traverses saved numeric trees. No executable estimator restoration is needed by these source bodies. This is not observed runtime/model acceptance or a selected admitted model import strategy.',
        'next_atomic_source_work': 'Review explicit new capacity daily/economic/reader/result entry implementations against these declarations and the sole inert import cut. Preserve pure numerical/calibration modules and original calendar at real paths; construct a NEW immutable executed-map/phase/finder/generated/native-package contract before synthetic proposal or genuine capacity proposal.',
        'unadmitted': {'executed_map': None, 'model_import_strategy': None, 'call_manifest': None, 'generated_manifest': None, 'entrypoint': None, 'launch': None, 'runtime': None, 'admission': None, 'execution_authorized': False},
        'not_run': ['payload import or CodeType compile', 'numerical/application/model bodies', 'tests or old completed gate replay', 'original/account/market data reads', 'SSH/host probes/Docker/jobs'],
        'unchanged': {'original_source_files': True, 'guard_G08_caps': True, 'production': True, 'original_timing': 'FAILED', 'publication': 'CLOSED', 'v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'historical_ordinary_intraday_fill_UI_combinedRAM': 'UNVERIFIED', 'heartbeat': 'ACTIVE'},
    }
    source_book = {name: {'sha256': pins[name], 'bytes': len(value[0]), 'origin': value[1]} for name, value in sorted(cache.items())}
    report['original_source_inventory'] = pages('source-inventory', {'nodes': source_book, 'edges': [], 'external_declarations': [], 'callable_scope_import_declarations_not_followed': [], 'unresolved_backend_imports': [], 'roots': []})
    report_record = save(DOCS / 'original-loader-import-cut-source-review-v1-2026-10-18.json', encoded(report))
    save(ROOT / 'report-pointer.json', encoded(report_record))
    print(json.dumps({'report': report_record, 'variant': variant_record, 'source_files_read': len(cache), 'graphs': {name: {key: value[key] for key in ('nodes', 'edges', 'deferred_imports')} for name, value in report['graphs'].items()}, 'candidate_effect_imports': candidate_effects, 'bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
