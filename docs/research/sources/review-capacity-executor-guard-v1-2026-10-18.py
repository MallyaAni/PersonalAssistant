"""Check inert guard source using AST and hashes only; never compile its CodeTypes."""

import ast
import hashlib
import json
from pathlib import Path

RESEARCH = Path(__file__).resolve().parents[1]
SOURCES = RESEARCH / 'sources'
OLD = SOURCES / 'original-loader-capacity-harness-v3-2026-10-18.py'
NEW = SOURCES / 'capacity-executor-source-guard-v1-2026-10-18.py'
REPORT = RESEARCH / 'original-loader-executor-guard-static-v2-2026-10-18.json'


# Reduce an AST node to structural content without pretending it is compiled code.
def normalized(node):
    return ast.dump(node, include_attributes=False)


# Select one direct lexical declaration without executing its module or decorators.
def declaration(tree, name):
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name)


# Record a source check only after its condition succeeds.
def checked(checks, name, condition):
    assert condition, name
    checks.append(name)


# Bind exact source bytes and verify declared source deltas without payload execution.
def main():
    old_raw, new_raw = OLD.read_bytes(), NEW.read_bytes()
    assert hashlib.sha256(old_raw).hexdigest() == '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
    old, new = ast.parse(old_raw), ast.parse(new_raw)
    checks = []
    for name in ('require', 'unique_fields', 'nonfinite_token', 'metadata', 'physical', 'directory_fd'):
        checked(checks, 'unchanged_utility_' + name, normalized(declaration(old, name)) == normalized(declaration(new, name)))
    for name in ('PHASES', 'FAILURE_BYTES', 'MAX_PYTHON_BYTES', 'MAX_METADATA_BYTES', 'MAX_CODES_PER_MODULE', 'GENERATED_FINGERPRINT_ALGORITHM', 'FORBIDDEN_NAMES', 'EFFECT_MODULES', 'FORBIDDEN_CLASSES', 'DENIED_AUDIT_EVENTS', 'IMAGE'):
        before = next(node.value for node in old.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
        after = next(node.value for node in new.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
        checked(checks, 'unchanged_constant_' + name, normalized(before) == normalized(after))
    fence_old, fence_new = declaration(old, 'CallFence'), declaration(new, 'CapacityCallFenceV1')
    for name in ('trip', 'audit', 'install', 'advance'):
        checked(checks, 'unchanged_guard_' + name, normalized(declaration(fence_old, name)) == normalized(declaration(fence_new, name)))
    profile_old, profile_new = declaration(fence_old, 'profile'), declaration(fence_new, 'profile')
    old_cut = next(index for index, node in enumerate(profile_old.body) if isinstance(node, ast.If) and normalized(node.test) == normalized(ast.parse("code.co_filename == '<string>'", mode='eval').body))
    new_cut = next(index for index, node in enumerate(profile_new.body) if isinstance(node, ast.If) and normalized(node.test) == normalized(ast.parse("code.co_filename != '<string>'", mode='eval').body))
    checked(checks, 'unchanged_profile_all_refusals_before_dynamic_seam', [normalized(node) for node in profile_old.body[:old_cut]] == [normalized(node) for node in profile_new.body[:new_cut]])
    checked(checks, 'unchanged_profile_exact_generated_record_membership', [normalized(node) for node in profile_old.body[old_cut + 1:]] == [normalized(node) for node in profile_new.body[new_cut + 3:]])
    checked(checks, 'unchanged_register_after_added_source_identity_predicate', [normalized(node) for node in declaration(fence_old, 'register').body] == [normalized(node) for node in declaration(fence_new, 'register').body[1:]])
    checked(checks, 'obsolete_daily_prefix_absent', b'<pinned daily prefix>' not in new_raw and b'40d0d7cf' not in new_raw)
    finder = declaration(new, 'CapacityBackendFinderV1')
    exec_body = declaration(finder, 'exec_module').body
    compiled = next(index for index, node in enumerate(exec_body) if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'compile')
    registered = next(index for index, node in enumerate(exec_body) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'register')
    executed = next(index for index, node in enumerate(exec_body) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'exec')
    checked(checks, 'source_compile_then_register_then_body_order', compiled < registered < executed)
    find_spec = declaration(finder, 'find_spec')
    checked(checks, 'explicit_authenticated_package_search_path', any(isinstance(node, ast.Assign) and any(isinstance(target, ast.Attribute) and target.attr == 'submodule_search_locations' for target in node.targets) for node in ast.walk(find_spec)))
    execute = declaration(new, 'execute')
    checked(checks, 'public_execute_unconditional_refusal', len(execute.body) == 1 and isinstance(execute.body[0], ast.Raise))
    body_calls = [node for node in new.body if isinstance(node, (ast.Expr, ast.If)) and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and type(node.value.value) is str)]
    checked(checks, 'no_top_level_payload_dispatch', not body_calls)
    map_path = RESEARCH / 'original-loader-data-composition-source-map-v1-2026-10-18.json'
    map_raw = map_path.read_bytes()
    pins = json.loads(map_raw)['files']
    literals = {node.targets[0].id: ast.literal_eval(node.value) for node in new.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}
    checked(checks, 'exact_raw2468_and_compact_executor_map', len(pins) == 2468 and hashlib.sha256(map_raw).hexdigest() == literals['EXECUTOR_MAP_SHA256'] and hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == literals['RECIPE_SHA256'])
    checked(checks, 'exact_requirements_contract_binding', hashlib.sha256((RESEARCH / 'original-loader-data-closure-contract-v1-2026-10-18.json').read_bytes()).hexdigest() == literals['CONTRACT_SHA256'])
    prior_raw = (RESEARCH / 'original-loader-stopped-package-source-independent-v1-2026-10-18.json').read_bytes()
    checked(checks, 'exact_dataclasses_source_and_prior_proof', hashlib.sha256(prior_raw).hexdigest() == '6860a76c8a50e4891549ea656ed881cf81518ae1e7d28b02ba65bd32d045c08b' and json.loads(prior_raw)['source_inventory']['source-00.py.txt']['sha256'] == literals['DATACLASSES_SHA256'])
    source_paths = [NEW, Path(__file__), SOURCES / 'prepare-capacity-executor-guard-v1-2026-10-18.py']
    purposes = {}
    for path in source_paths:
        raw = path.read_bytes()
        tree, lines = ast.parse(raw), raw.decode().splitlines()
        nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in nodes:
            first = min([node.lineno] + [value.lineno for value in node.decorator_list])
            assert lines[first - 2].lstrip().startswith('# '), (path, node.name)
        purposes[path.name] = len(nodes)
    checked(checks, 'all_new_function_purpose_comments', True)
    report = {
        'schema': 'capacity-executor-guard-static-review/1', 'status': 'VERIFIED_STATIC_SOURCE_ONLY',
        'checks': checks, 'check_count': len(checks), 'purpose_functions': purposes,
        'files': {str(path.relative_to(RESEARCH)): {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size} for path in source_paths},
        'payload_functions': len([node for node in ast.walk(new) if isinstance(node, ast.FunctionDef)]),
        'payload_bodies': 'UNRUN', 'payload_CodeType_compilation': False, 'runtime_admission': None,
        'limits': 'AST comparisons are source evidence, not behavior, CodeType/global/type/generated producer, finder/runtime or native/RAM acceptance.',
    }
    with REPORT.open('x', encoding='utf-8') as target:
        json.dump(report, target, sort_keys=True, indent=2)
        target.write('\n')
    print(json.dumps({'checks': len(checks), 'purpose_functions': purposes, 'report_sha256': hashlib.sha256(REPORT.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
