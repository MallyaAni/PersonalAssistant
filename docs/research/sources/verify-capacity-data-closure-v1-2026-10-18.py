"""Independently fold preserved source evidence and add explicit missing lambda scopes."""
import ast
from collections import Counter, deque
from hashlib import sha256
import json
import os
from pathlib import Path

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
INVENTORY_SHA = 'a90f578d09edf0c54193156595d8d859e27488b49fac0964caf08558cc128cf1'
ROOT = Path('/tmp/capacity-data-closure-independent-20261018-v1')


# Bind exact source and page bytes with two reads and lossless local physical bookends.
def read(path, expected):
    first = path.stat(follow_symlinks=False)
    raw = path.read_bytes()
    assert len(raw) <= 262144 and sha256(raw).hexdigest() == expected, str(path)
    assert path.read_bytes() == raw
    last = path.stat(follow_symlinks=False)
    keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    assert all(getattr(first, key) == getattr(last, key) for key in keys)
    return raw, {key: str(getattr(first, key)) for key in keys}


# Resolve only the unique backend source origin in the unchanged declaration.
def origin(name, pins):
    prefix = name.replace('.', '/')
    choices = [path for path in (prefix + '.py', prefix + '/__init__.py') if path in pins]
    assert len(choices) <= 1
    return choices[0] if choices else None


# Recompute lexical module and class import scopes without evaluating their branches.
def imports(node, conditional=False):
    for field, value in ast.iter_fields(node):
        children = value if isinstance(value, list) else [value]
        for item in children:
            if not isinstance(item, ast.AST) or isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(item, (ast.Import, ast.ImportFrom)):
                yield item, conditional
            else:
                yield from imports(item, conditional or isinstance(item, (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.Match)))


# Recompute all declared backend targets and retain external package names as unresolved runtime facts.
def targets(item, module, pins):
    if isinstance(item, ast.Import):
        names = [alias.name for alias in item.names]
        bases = names
    else:
        base = item.module or ''
        if item.level:
            package = module if origin(module, pins).endswith('/__init__.py') else module.rsplit('.', 1)[0]
            parts = package.split('.')
            assert item.level <= len(parts)
            base = '.'.join(parts[:len(parts) - item.level + 1] + ([base] if base else []))
        names = [base] + [base + '.' + alias.name for alias in item.names if alias.name != '*']
        bases = [base]
    return sorted({name for name in names if origin(name, pins)}), sorted({name for name in bases if name and not name.startswith('backend')}), sorted({name for name in bases if name.startswith('backend') and not origin(name, pins)})


# Compare complete source records as multisets without hiding duplicate occurrences.
def records_equal(actual, expected):
    assert Counter(json.dumps(row, sort_keys=True) for row in actual) == Counter(json.dumps(row, sort_keys=True) for row in expected)


# Persist one new finite independent proof while preserving all original inventory files.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    assert len(raw) <= 262144
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}


# Verify preserved graph/source facts and explicitly account for every missing lambda call.
def main():
    inventory_raw, inventory_physical = read(DOCS / 'original-loader-data-closure-inventory-v1-2026-10-18.json', INVENTORY_SHA)
    inventory = json.loads(inventory_raw)
    map_path = DOCS / 'original-loader-data-composition-source-map-v1-2026-10-18.json'
    map_raw = map_path.read_bytes()
    assert sha256(map_raw).hexdigest() == inventory['executor_map_sha256'] and len(map_raw) <= 16777216
    assert map_path.read_bytes() == map_raw
    pins = json.loads(map_raw)['files']
    pages, sections, page_physical = [], {}, {}
    for row in inventory['pages']:
        raw, physical = read(DOCS / row['path'], row['sha256'])
        assert len(raw) == row['bytes']
        page = json.loads(raw)
        assert len(page['records']) <= 64
        pages.append(row)
        page_physical[row['path']] = physical
        for entry in page['records']:
            sections.setdefault(entry['section'], []).append(entry['value'])
    assert sum(map(len, sections.values())) == inventory['counts']['records'] == 7120
    modules = {row['module']: row for row in sections['module']}
    assert len(modules) == len(sections['module']) == 35
    trees, source_physical = {}, {}
    full_calls, missing_calls, lambdas = Counter(), [], []
    counts = Counter()
    for module, row in modules.items():
        assert row['path'] == origin(module, pins) and pins[row['path']] == row['sha256']
        raw, physical = read(Path(row['inert_copy']['path']), row['sha256'])
        assert len(raw) == row['bytes'] == row['inert_copy']['bytes']
        assert row['inert_copy']['sha256'] == row['sha256']
        source_physical[module] = physical
        tree = ast.parse(raw)
        trees[module] = tree
        counts['source_bytes'] += len(raw)
        for item in ast.walk(tree):
            if isinstance(item, ast.Call):
                full_calls[(module, item.lineno, ast.unparse(item.func))] += 1
            if isinstance(item, ast.FunctionDef):
                counts['functions'] += 1
            if isinstance(item, ast.ClassDef):
                counts['classes'] += 1
            if isinstance(item, ast.Lambda):
                row = {'module': module, 'line': item.lineno, 'column': item.col_offset, 'end_line': item.end_lineno, 'AST_sha256': sha256(ast.dump(item, include_attributes=False).encode()).hexdigest(), 'source_expression': ast.unparse(item), 'compiled_CodeType_identity': None}
                lambdas.append(row)
                for call in ast.walk(item):
                    if isinstance(call, ast.Call):
                        missing_calls.append({'module': module, 'owner': '<lambda source scope>', 'line': call.lineno, 'target_expression': ast.unparse(call.func), 'actual_callable_phase_and_CodeType': None})
    recorded_calls = Counter((row['module'], row['line'], row['target_expression']) for row in sections['call'])
    supplement_calls = Counter((row['module'], row['line'], row['target_expression']) for row in missing_calls)
    assert len(lambdas) == 5 and len(missing_calls) == 3
    assert full_calls - recorded_calls == supplement_calls and not recorded_calls - full_calls
    assert recorded_calls + supplement_calls == full_calls
    assert sum(recorded_calls.values()) == 5886 and sum(full_calls.values()) == 5889
    assert (counts['functions'], counts['classes'], counts['source_bytes']) == (362, 53, 494189)
    edges, external, deferred, missing = [], [], [], []
    for module, tree in trees.items():
        parts = module.split('.')
        for index in range(1, len(parts)):
            parent = '.'.join(parts[:index])
            if origin(parent, pins):
                edges.append({'from': module, 'to': parent, 'kind': 'implicit_package', 'line': None, 'conditional': False})
        immediate = list(imports(tree))
        active = {id(item) for item, _ in immediate}
        for item, conditional in immediate:
            local, outside, absent = targets(item, module, pins)
            edges.extend({'from': module, 'to': name, 'kind': 'lexical_import', 'line': item.lineno, 'conditional': conditional} for name in local)
            external.extend({'module': module, 'line': item.lineno, 'target': name, 'conditional': conditional} for name in outside)
            missing.extend({'module': module, 'line': item.lineno, 'target': name} for name in absent)
        for item in ast.walk(tree):
            if isinstance(item, (ast.Import, ast.ImportFrom)) and id(item) not in active:
                local, outside, absent = targets(item, module, pins)
                deferred.append({'module': module, 'line': item.lineno, 'statement': ast.unparse(item), 'backend_targets_not_followed': local, 'external_targets_not_followed': outside, 'unresolved_backend': absent})
    assert not missing
    for section, rows in (('edge', edges), ('external', external), ('deferred', deferred)):
        records_equal(rows, sections[section])
    reached, pending = set(), deque(inventory['roots'])
    while pending:
        module = pending.popleft()
        if module not in reached:
            reached.add(module)
            pending.extend(row['to'] for row in edges if row['from'] == module)
    assert reached == set(modules)
    guard_raw, guard_physical = read(DOCS / 'sources/original-loader-capacity-harness-v3-2026-10-18.py', inventory['guard_sha256'])
    guard = ast.parse(guard_raw)
    assignments = {target.id: node.value for node in guard.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
    prefixes = ast.literal_eval(assignments['EFFECT_MODULES'])
    assert len(prefixes) == 5 and list(prefixes) == inventory['all_five_guard_effect_prefixes']
    assert not any(module.startswith(prefixes) for module in modules)
    ROOT.mkdir(exist_ok=False)
    supplement = {'schema': 'capacity-data-closure-lambda-source-supplement/1', 'inventory_sha256': INVENTORY_SHA, 'original_counts_unchanged': inventory['counts'], 'gap': 'Original local scope walk omitted five lambda expressions and three contained calls. Original inventory/pages/source retained, not rewritten or replayed.', 'lambda_source_declarations': lambdas, 'additional_call_sites': missing_calls, 'complete_AST_call_site_count_after_supplement': 5889, 'compiled_generated_call_phase_native_runtime_acceptance': None, 'payload_bodies_run': False}
    supplement_row = save(DOCS / 'original-loader-data-closure-lambda-supplement-v1-2026-10-18.json', supplement)
    proof = {'schema': 'capacity-data-closure-independent-source-proof/1', 'status': 'SOURCE_LEXICAL_GRAPH_VERIFIED_CALL_INVENTORY_EXPLICITLY_SUPPLEMENTED_NOT_RUNTIME_CLOSURE', 'inventory_sha256': INVENTORY_SHA, 'inventory_physical': inventory_physical, 'executor_map_sha256': inventory['executor_map_sha256'], 'guard_sha256': inventory['guard_sha256'], 'guard_physical': guard_physical, 'source_copies': source_physical, 'pages': pages, 'page_physical': page_physical, 'lambda_supplement': supplement_row, 'counts': {'modules': 35, 'edges': len(edges), 'external_declarations': len(external), 'deferred_imports': len(deferred), 'functions': 362, 'classes': 53, 'original_recorded_calls': 5886, 'additional_lambda_calls': 3, 'complete_AST_calls': 5889, 'lambda_scopes': 5, 'source_bytes': 494189}, 'checks': ['two_full_source_and_page_reads_with_exact_SHA_and_local_decimal_physical_bookends', 'independent_exact_lexical_edge_external_and_deferred_multisets', 'exact_root_reachability_35nodes_221edges', 'all_FIVE_unchanged_guard_effect_prefixes_absent_in_lexical_graph', 'full_AST_function_class_sourcebyte_counts', 'all5889_AST_calls_equal_preserved5886_plus_explicit3_lambda_calls', 'no_payload_import_CodeType_body_test_job_or_oldgate_replay'], 'source_copy_authority': 'Exact declared bytes only, not original reference/producer root authority or executable source-book/finder/runtime admission.', 'remaining': ['Actual callable identities/aliases/self/phase bindings unresolved; all-function inventory cannot become a broad call allowlist.', '38 deferred imports and external/native/PyArrow/dataclass/codegen/annotation/default/runtime behavior remain unadmitted.', 'Lease constructor performs complete BEFORE byte authentication under caller guard phase; outer phase ownership still needs explicit source design.', 'No source-book/finder/guard/native/generated/call/phase/runtime/model strategy or admission exists.'], 'execution_authorized': False}
    proof_row = save(DOCS / 'original-loader-data-closure-independent-proof-v1-2026-10-18.json', proof)
    save(ROOT / 'proof-pointer.json', proof_row)
    save(ROOT / 'supplement-pointer.json', supplement_row)
    descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps({'proof': proof_row, 'supplement': supplement_row, 'counts': proof['counts'], 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
