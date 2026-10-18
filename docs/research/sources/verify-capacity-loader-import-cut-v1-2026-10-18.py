"""Independently verify inert source deltas and graph records without importing payloads."""

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ORIGINAL = '27471b9c61b958f759e9f48b80acaf60cdf75f2e'
REPORT_SHA = '3f408ce008e38066a9f54f7aa4b6ebef9e343d2184d52e6079c03384ee53de1d'


# Authenticate complete metadata bytes before interpreting their declared fields.
def read_json(path, expected):
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == expected
    return json.loads(raw)


# Flatten bounded, hash-linked pages without using the source builder's graph routine.
def records(section):
    result = []
    for page in section['pages']:
        path = DOCS / page['path']
        assert path.stat().st_size == page['bytes'] <= 262144
        result.extend(read_json(path, page['sha256'])['records'])
    return result


# Read pinned original bytes independently from the current worktree or original Git.
def original_bytes(path, expected):
    candidate = REPO / path
    raw = candidate.read_bytes() if candidate.is_file() else b''
    if sha256(raw).hexdigest() != expected:
        raw = subprocess.run(['git', 'show', ORIGINAL + ':' + path], cwd=REPO, capture_output=True, check=True).stdout
    assert sha256(raw).hexdigest() == expected
    return raw


# Gather module/class lexical imports while retaining callable imports as a separate seam.
class Imports(ast.NodeVisitor):
    # Start with no source declarations before visiting module or class scopes.
    def __init__(self):
        self.rows = []

    # Stop before callable bodies because this proof admits no application calls.
    def visit_FunctionDef(self, node):
        return None

    # Stop before asynchronous callable bodies for the same source-only boundary.
    def visit_AsyncFunctionDef(self, node):
        return None

    # Retain direct imports with their actual source location.
    def visit_Import(self, node):
        self.rows.append(node)

    # Retain from-imports without treating attributes as automatically imported modules.
    def visit_ImportFrom(self, node):
        self.rows.append(node)


# Resolve backend origins by exact source-map membership rather than importing packages.
def path_of(module, pins):
    stem = module.replace('.', '/')
    candidates = [name for name in (stem + '.py', stem + '/__init__.py') if name in pins]
    assert len(candidates) <= 1
    return candidates[0] if candidates else None


# Reconstruct candidate import destinations from the actual variant and pinned originals.
def expected_edges(module, path, raw, pins):
    visitor = Imports()
    visitor.visit(ast.parse(raw, filename=path))
    targets = set()
    parts = module.split('.')
    for end in range(1, len(parts)):
        parent = '.'.join(parts[:end])
        if path_of(parent, pins):
            targets.add((module, parent, None, 'implicit_package'))
    for node in visitor.rows:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            base = node.module or ''
            if node.level:
                package = module if path.endswith('/__init__.py') else module.rpartition('.')[0]
                package_parts = package.split('.')
                assert node.level <= len(package_parts)
                base = '.'.join(package_parts[:len(package_parts) + 1 - node.level] + ([base] if base else []))
            names = [base] + [base + '.' + alias.name for alias in node.names if alias.name != '*']
        for name in names:
            if path_of(name, pins):
                targets.add((module, name, node.lineno, 'source_import'))
    return targets


# Verify new source metadata, complete candidate edges and all unchanged source pins.
def main():
    report_path = DOCS / 'original-loader-import-cut-source-review-v1-2026-10-18.json'
    report = read_json(report_path, REPORT_SHA)
    pins = read_json(DOCS / 'original-loader-genuine-source-map-2026-10-18.json', report['original_composed_map']['sha256'])
    old_map_path = DOCS / 'original-loader-admission-source-map-v1-2026-10-18.json'
    assert sha256(old_map_path.read_bytes()).hexdigest() == 'a68ebbefb776a93dfdfb56fc6c4893ac35450a224fcf2fa50498cb911bfeda43'
    inventory = records(report['original_source_inventory'])
    originals = {}
    for row in inventory:
        if row['section'] == 'nodes':
            meta = row['value']
            assert pins[meta['name']] == meta['sha256']
            raw = original_bytes(meta['name'], meta['sha256'])
            assert len(raw) == meta['bytes']
            originals[meta['name']] = raw
    assert len(originals) == report['original_source_inventory']['nodes'] == 166
    variant_record = report['variant']
    variant_path = DOCS / variant_record['path']
    variant = variant_path.read_bytes()
    assert len(variant) == variant_record['bytes']
    assert sha256(variant).hexdigest() == variant_record['sha256']
    original = originals['backend/market/learned_entry_data.py']
    first, second = ast.parse(original), ast.parse(variant)
    removed = [node for node in first.body if isinstance(node, ast.ImportFrom) and node.module == 'backend.market.fill_timing']
    assert len(removed) == 1
    first.body.remove(removed[0])
    prepare = next(node for node in second.body if isinstance(node, ast.FunctionDef) and node.name == 'prepare')
    moved = prepare.body.pop(0)
    assert ast.dump(moved, include_attributes=False) == ast.dump(removed[0], include_attributes=False)
    assert ast.dump(first, include_attributes=False) == ast.dump(second, include_attributes=False)
    flattened = records(report['graphs']['candidate_numerical'])
    nodes = {row['value']['name']: row['value'] for row in flattened if row['section'] == 'nodes'}
    actual_edges = {(row['value']['from'], row['value']['to'], row['value']['line'], row['value']['kind']) for row in flattened if row['section'] == 'edges'}
    expected = set()
    for module, record in nodes.items():
        path = record['path']
        raw = variant if path == 'backend/market/learned_entry_data.py' else originals[path]
        assert sha256(raw).hexdigest() == record['sha256']
        expected.update(expected_edges(module, path, raw, pins))
    assert actual_edges == expected and len(nodes) == 20
    assert all(target in nodes for _, target, _, _ in expected)
    reachable = set((
        'backend.market.forward_arithmetic', 'backend.market.holding_risk_bank',
        'backend.market.conditional_holding_calibration', 'backend.market.market_conditioned_holding',
        'backend.market.market_conditioned_calibration',
    ))
    while True:
        following = reachable | {right for left, right, _, _ in expected if left in reachable}
        if following == reachable:
            break
        reachable = following
    assert reachable == set(nodes)
    harness_path = DOCS / 'sources/original-loader-capacity-harness-v3-2026-10-18.py'
    harness_raw = harness_path.read_bytes()
    assert sha256(harness_raw).hexdigest() == '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
    effect_prefixes = next(ast.literal_eval(node.value) for node in ast.parse(harness_raw).body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'EFFECT_MODULES' for target in node.targets))
    assert len(effect_prefixes) == 5
    assert not any(module.startswith(prefix) for module in nodes for prefix in effect_prefixes)
    page_count = 0
    for section in (*report['graphs'].values(), report['original_source_inventory']):
        page_count += len(section['pages'])
        records(section)
    assert page_count == 58
    proof = {
        'schema': 'capacity-loader-import-cut-independent-source-proof/1',
        'status': 'VERIFIED_SOURCE_DELTA_AND_DECLARED_STATIC_GRAPH_ONLY',
        'report_sha256': REPORT_SHA,
        'variant_sha256': variant_record['sha256'],
        'source_files_independently_hashchecked': len(originals),
        'pages_hashchecked': page_count,
        'exact_candidate_nodes': len(nodes),
        'unique_candidate_edges': len(expected),
        'unchanged_harness_effect_prefixes': list(effect_prefixes),
        'candidate_contains_any_of_all5_effect_prefixes': False,
        'original_and_old_capacity_maps_unchanged': True,
        'sole_source_delta': 'Same import removed from module body and inserted first in intraday prepare; every remaining AST node equal.',
        'static_graph_limit': 'Explicit lexical module/class source imports plus implicit packages only; deferred/dynamic imports, evaluated annotations/decorators/class bodies, packages/native extensions, actual import order and runtime are not accepted.',
        'payload_CodeType_compile_import_body_or_tests': False,
        'SSH_Docker_host_model_account_or_original_data_operations': False,
        'new_map_fence_manifest_entry_runtime_model_strategy_admission': None,
        'historical_ordinary_intraday_fill_UI_combined_RAM': 'UNVERIFIED',
    }
    output = DOCS / 'original-loader-import-cut-independent-source-proof-v1-2026-10-18.json'
    raw = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    with output.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert output.read_bytes() == raw
    print(json.dumps({'proof_sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'sources': len(originals), 'pages': page_count, 'candidate_nodes': len(nodes), 'unique_edges': len(expected), 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
