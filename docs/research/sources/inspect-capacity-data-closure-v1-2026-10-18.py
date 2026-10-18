"""Inspect pinned source imports and call sites without importing or compiling payloads."""
import ast
from collections import deque
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-data-closure-source-20261018-v1')
MAP_SHA = '544fe1859ec11e62f2bf506eff70e9111a6a930d53dff59450d9d4816abaa202'
GUARD_SHA = '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
ORIGINAL = '27471b9c61b958f759e9f48b80acaf60cdf75f2e'
ROOTS = ('backend.market.capacity_original_loader_lifecycle_v2', 'backend.market.capacity_original_inputs_v2')


# Hash exact source bytes without normalizing or evaluating their contents.
def digest(raw):
    return sha256(raw).hexdigest()


# Persist only exclusive bounded source evidence and verify complete file readback.
def save(path, raw):
    assert len(raw) <= 262144, str(path)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


# Encode finite source facts rather than application objects or runtime observations.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Resolve only Python origins explicitly present in the declared executor file map.
def module_path(name, pins):
    prefix = name.replace('.', '/')
    choices = [path for path in (prefix + '.py', prefix + '/__init__.py') if path in pins]
    assert len(choices) <= 1, name
    return choices[0] if choices else None


# Inspect lexical execution scopes while excluding every callable body.
def scope_imports(node, conditional=False):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            yield child, conditional
        else:
            yield from scope_imports(child, conditional or isinstance(child, (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.Match)))


# Resolve declared module imports without assuming imported names are runtime objects.
def targets(node, current, pins):
    if isinstance(node, ast.Import):
        names = [item.name for item in node.names]
        bases = names
    else:
        base = node.module or ''
        if node.level:
            path = module_path(current, pins)
            package = current if path.endswith('/__init__.py') else current.rsplit('.', 1)[0]
            parts = package.split('.')
            assert node.level <= len(parts)
            base = '.'.join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
        names = [base] + [base + '.' + item.name for item in node.names if item.name != '*']
        bases = [base]
    local = sorted({name for name in names if module_path(name, pins)})
    external = sorted({name for name in bases if name and not name.startswith('backend')})
    missing = sorted({name for name in bases if name.startswith('backend') and not module_path(name, pins)})
    return local, external, missing


# Read a source matching the declaration from the checkout, inert source archive or original Git.
def read_source(path, pins, archive, cache):
    if path not in cache:
        local = REPO / path
        raw = local.read_bytes() if local.is_file() else b''
        origin = 'matching checkout bytes'
        if digest(raw) != pins[path]:
            location = archive.get(pins[path])
            if location is not None:
                raw = location.read_bytes()
                origin = str(location.relative_to(REPO))
            else:
                raw = subprocess.run(['git', 'show', ORIGINAL + ':' + path], cwd=REPO, capture_output=True, check=True).stdout
                origin = 'exact original Git blob'
        assert digest(raw) == pins[path] and len(raw) <= 262144, path
        cache[path] = (raw, origin)
        assert len(cache) <= 1024 and sum(len(item[0]) for item in cache.values()) <= 32 * 1048576
    return cache[path]


# Enumerate lexical declarations without treating them as an executed call allowlist.
def declarations(node, prefix=''):
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qualified = prefix + child.name
            yield qualified, child
            next_prefix = qualified + ('.<locals>.' if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else '.')
            yield from declarations(child, next_prefix)


# Enumerate one declaration scope while keeping nested callable bodies separate.
def local_nodes(node):
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from local_nodes(child)


# Retain paged static records without relaxing ordinary source or metadata bounds.
def pages(records):
    result = []
    for index in range(0, len(records), 64):
        path = DOCS / f'original-loader-data-closure-page-{index // 64:03d}-2026-10-18.json'
        row = save(path, encoded({'schema': 'capacity-data-closure-source-page/1', 'records': records[index:index + 64]}))
        row['path'] = path.name
        result.append(row)
    return result


# Inspect the complete lexical graph and expose unresolved callable/native/generated obligations.
def main():
    ROOT.mkdir(exist_ok=False)
    map_raw = (DOCS / 'original-loader-data-composition-source-map-v1-2026-10-18.json').read_bytes()
    guard_raw = (DOCS / 'sources/original-loader-capacity-harness-v3-2026-10-18.py').read_bytes()
    assert digest(map_raw) == MAP_SHA and digest(guard_raw) == GUARD_SHA
    pins = json.loads(map_raw)['files']
    assert len(pins) == 2468
    guard = ast.parse(guard_raw)
    assignments = {target.id: node.value for node in guard.body if isinstance(node, ast.Assign) for target in node.targets if isinstance(target, ast.Name)}
    effect_prefixes = ast.literal_eval(assignments['EFFECT_MODULES'])
    forbidden = ast.literal_eval(assignments['FORBIDDEN_NAMES'].args[0])
    archive = {}
    for path in sorted((DOCS / 'sources').glob('*.py')):
        archive.setdefault(digest(path.read_bytes()), path)
    pending, nodes, records, cache = deque(ROOTS), {}, [], {}
    deferred, external, missing, edges = [], [], [], []
    functions, classes, calls, generated, hazards = [], [], [], [], []
    while pending:
        name = pending.popleft()
        if name in nodes:
            continue
        path = module_path(name, pins)
        assert path is not None, name
        raw, origin = read_source(path, pins, archive, cache)
        tree = ast.parse(raw, filename=path)
        copy = save(ROOT / f'source-{len(nodes):03d}.py.txt', raw)
        nodes[name] = {'path': path, 'sha256': digest(raw), 'bytes': len(raw), 'source_origin': origin, 'inert_copy': copy}
        parts = name.split('.')
        for index in range(1, len(parts)):
            parent = '.'.join(parts[:index])
            if module_path(parent, pins):
                edges.append({'from': name, 'to': parent, 'kind': 'implicit_package', 'line': None, 'conditional': False})
                pending.append(parent)
        active = list(scope_imports(tree))
        immediate = {id(item) for item, _ in active}
        for item, conditional in active:
            local, outside, absent = targets(item, name, pins)
            for target in local:
                edges.append({'from': name, 'to': target, 'kind': 'lexical_import', 'line': item.lineno, 'conditional': conditional})
                pending.append(target)
            external.extend({'module': name, 'line': item.lineno, 'target': target, 'conditional': conditional} for target in outside)
            missing.extend({'module': name, 'line': item.lineno, 'target': target} for target in absent)
        for item in ast.walk(tree):
            if isinstance(item, (ast.Import, ast.ImportFrom)) and id(item) not in immediate:
                local, outside, absent = targets(item, name, pins)
                deferred.append({'module': name, 'line': item.lineno, 'statement': ast.unparse(item), 'backend_targets_not_followed': local, 'external_targets_not_followed': outside, 'unresolved_backend': absent})
        scopes = [('<module>', tree)] + list(declarations(tree))
        for qualified, item in scopes:
            common = {'module': name, 'path': path, 'qualname': qualified, 'line': getattr(item, 'lineno', 1), 'end_line': getattr(item, 'end_lineno', len(raw.splitlines())), 'AST_sha256': digest(ast.dump(item, include_attributes=False).encode())}
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(common)
                if item.name in forbidden:
                    hazards.append({**common, 'reason': 'forbidden_co_name_declaration_NOT_selected_call_proof'})
            elif isinstance(item, ast.ClassDef):
                classes.append({**common, 'bases': [ast.unparse(base) for base in item.bases], 'decorators': [ast.unparse(value) for value in item.decorator_list]})
                if any('dataclass' in ast.unparse(value) for value in item.decorator_list):
                    generated.append({**common, 'kind': 'dataclass_producer_declaration_NOT_generated_CodeType', 'decorators': [ast.unparse(value) for value in item.decorator_list]})
            for child in local_nodes(item):
                if isinstance(child, ast.Call):
                    target = ast.unparse(child.func)
                    terminal = child.func.attr if isinstance(child.func, ast.Attribute) else child.func.id if isinstance(child.func, ast.Name) else None
                    calls.append({'module': name, 'owner': qualified, 'line': child.lineno, 'target_expression': target, 'terminal_name': terminal, 'guard_name_collision_lexical_only': terminal in forbidden, 'resolved_actual_callable_or_phase': None})
                if isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda)):
                    generated.append({'module': name, 'owner': qualified, 'line': child.lineno, 'kind': type(child).__name__, 'AST_sha256': digest(ast.dump(child, include_attributes=False).encode()), 'compiled_CodeType_identity': None})
    effects = sorted(name for name in nodes if name.startswith(effect_prefixes))
    assert not effects and not missing
    for section, values in (('module', [{'module': name, **row} for name, row in sorted(nodes.items())]), ('edge', edges), ('external', external), ('deferred', deferred), ('function', functions), ('class', classes), ('call', calls), ('generated_declaration', generated), ('forbidden_declaration_NOT_execution', hazards)):
        records.extend({'section': section, 'value': row} for row in values)
    manifest = pages(records)
    report = {'schema': 'capacity-data-source-closure-inventory/1', 'status': 'LEXICAL_IMPORT_GRAPH_AND_CALL_SITE_INVENTORY_ONLY_NOT_EXECUTABLE_CLOSURE', 'executor_map_sha256': MAP_SHA, 'guard_sha256': GUARD_SHA, 'roots': ROOTS, 'counts': {'modules': len(nodes), 'edges': len(edges), 'external_import_declarations': len(external), 'deferred_import_declarations': len(deferred), 'function_declarations': len(functions), 'class_declarations': len(classes), 'call_sites': len(calls), 'generated_declarations': len(generated), 'forbidden_name_declarations_not_selected_execution': len(hazards), 'source_bytes': sum(len(value[0]) for value in cache.values()), 'records': len(records)}, 'all_five_guard_effect_prefixes': list(effect_prefixes), 'effect_module_nodes': effects, 'unresolved_lexical_backend_imports': missing, 'pages': manifest,
        'limits': ['Explicit lexical module/class imports plus implicit packages only. Conditional branches not evaluated; runtime import order/defaults/decorators/annotations/dynamic imports/native package origins unverified.', 'Deferred callable imports recorded but not followed. Only explicit input factory module added as separate LOAD root; this is not an entire callable closure.', 'Every function and call site is inventory, never an all-functions phase allowlist. Actual self/type/alias/global/bound callable target and guard phase remain unresolved.', 'Dataclasses/comprehensions/lambdas are source declarations, not actual generated CodeTypes, format2 fingerprints or native runtime acceptance.', 'Forbidden-name declarations and lexical call terminals can lie outside selected path or refer to external APIs; neither establishes an actual guard failure.', 'Before byte authentication currently occurs inside lease constructor under its caller guard phase; lease labels alone do not advance the external guard. Exact outer phase ownership remains absent.', 'Original producer2431/reference2446/executor2468 provenance and all archive/full before-after receipt/JSON/UTF8 allocation lifetimes remain mandatory.'],
        'unadmitted': {key: None for key in ('selected_call_closure', 'source_book', 'finder', 'guard_contract', 'call_manifest', 'generated_manifest', 'phase_manifest', 'native_package_closure', 'entrypoint', 'model_import_strategy', 'runtime', 'admission')}, 'execution_authorized': False, 'payload_import_CodeType_body_test_or_job': False}
    record = save(DOCS / 'original-loader-data-closure-inventory-v1-2026-10-18.json', encoded(report))
    save(ROOT / 'inventory-pointer.json', encoded(record))
    descriptor = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(json.dumps({'report': record, 'counts': report['counts'], 'pages': len(manifest), 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
