"""Compose inert source identities and namespace recipes; never import application code."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
ROOT = Path('/tmp/original-loader-genuine-composition-20261018-v1')
DOCS = REPO / 'docs/research'
ORIGINAL = '/home/animallya96/scratch/live-model-history-full-20261013-v1'
REVISION = '27471b9c61b958f759e9f48b80acaf60cdf75f2e'
PHASES = ('BOOTSTRAP', 'ADMISSION', 'BEFORE', 'LOAD', 'FROZEN', 'AFTER', 'SERIALIZE', 'DONE')

# Identify complete bytes without interpreting their application semantics.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

# Read one exact small metadata input without selecting a replacement.
def pinned(path, expected):
    raw = Path(path).read_bytes()
    assert sha(raw) == expected, str(path)
    return json.loads(raw)

# Persist only a new finite metadata artifact with durable exact-byte readback.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert path.read_bytes() == raw
    return {'sha256': sha(raw), 'bytes': len(raw)}

# Read matching local source or an exact original Git blob without importing it.
def source(name, expected):
    raw = (REPO / name).read_bytes()
    origin = 'matching local bytes'
    if sha(raw) != expected:
        result = subprocess.run(['git', 'show', REVISION + ':' + name], cwd=REPO, capture_output=True, check=True)
        raw, origin = result.stdout, 'original Git blob at ' + REVISION
    assert sha(raw) == expected and len(raw) <= 1024**2, name
    return raw, origin

# Record AST identities and import declarations without compiling any CodeType.
def record(name, expected):
    raw, origin = source(name, expected)
    tree = ast.parse(raw)
    imports = [{'line': node.lineno, 'statement': ast.unparse(node)} for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    classes = [{'line': node.lineno, 'name': node.name, 'decorators': [ast.unparse(item) for item in node.decorator_list]} for node in tree.body if isinstance(node, ast.ClassDef)]
    return {'source_sha256': expected, 'bytes': len(raw), 'source_origin': origin, 'imports': imports, 'classes': classes}, tree

# Select an exact source AST node for the static incompatibility witness.
def node_record(tree, kind, name):
    node = next(item for item in tree.body if isinstance(item, kind) and item.name == name)
    return {'line': node.lineno, 'end_line': node.end_lineno, 'AST_sha256': sha(ast.dump(node, include_attributes=False).encode())}

# Assemble exact provenance and expose incompatible admission fields as null.
def main():
    contract = pinned(DOCS / 'original-loader-capacity-contract-2026-10-18.json', 'ecc58ad7f6ec65bb42a28ef0c2bea8d116b0e9be5ea59e490388fa0e74dfddc8')
    inputs = {name: pinned(row['path'], row['sha256']) for name, row in contract['source_recipe']['map_inputs'].items()}
    original = inputs['git']['files']
    assert len(original) == 2431 and inputs['git']['revision'] == REVISION
    recipe = {**original, **contract['source_recipe']['frozen_n2_baseline'], **contract['source_recipe']['six_original_audit_overlays'], **contract['source_recipe']['three_binding_reviews']}
    assert len(recipe) == 2446 and sha(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()) == contract['source_recipe']['composed_compact_map_sha256']
    map_artifact = save(DOCS / 'original-loader-genuine-source-map-2026-10-18.json', recipe)
    execution = pinned(ROOT / 'original-execution.json', contract['original_selectors']['execution_sha256'])
    command = execution['command']
    mounts = []
    for index, item in enumerate(command):
        if item == '-v':
            host, target, mode = command[index + 1].split(':')
            assert host.startswith('/home/animallya96/') and target.startswith('/') and mode in ('ro', 'rw')
            mounts.append({'source': host, 'target': target, 'mode': mode})
    assert len(mounts) == 12 and len({item['target'] for item in mounts}) == 12
    assert [item for item in mounts if item['mode'] == 'rw'] == [{'source': ORIGINAL + '/output', 'target': '/results', 'mode': 'rw'}]
    readonly = [item for item in mounts if item['mode'] == 'ro']
    assert readonly[0] == {'source': ORIGINAL + '/source', 'target': '/app', 'mode': 'ro'}
    targets = [dict(item) for item in readonly if item['target'] != '/app']
    aliases = [{'source': item['source'], 'target': item['source'], 'mode': 'ro'} for item in readonly]
    account = {'source': ORIGINAL + '/output/account', 'target': '/original-account', 'mode': 'ro'}
    assert len({item['target'] for item in targets + aliases + [account]}) == 22
    selected = [
        'backend/__init__.py', 'backend/agents/__init__.py',
        'backend/agents/trading/__init__.py', 'backend/agents/trading/desk/__init__.py',
        'backend/cli/audit_original_live_model_history.py',
        'backend/agents/trading/desk/paper.py',
        'backend/agents/trading/desk/execution_evidence.py',
        'backend/agents/trading/desk/planner.py',
        'backend/market/alpaca_trading.py', 'backend/market/replay_broker.py',
        'backend/market/live_model_history.py',
        'backend/market/live_model_history_audit_inputs.py',
    ]
    records, trees = {}, {}
    for name in selected:
        records[name], trees[name] = record(name, recipe[name])
    planner = 'backend/agents/trading/desk/planner.py'
    assert records[planner]['classes'][0]['name'] == 'Order' and records[planner]['classes'][0]['decorators'] == ['dataclass(frozen=True)']
    audit = 'backend/cli/audit_original_live_model_history.py'
    paper = 'backend/agents/trading/desk/paper.py'
    assert any(row['statement'] == 'from backend.agents.trading.desk import paper' for row in records[audit]['imports'])
    assert any(row['statement'] == 'from backend.agents.trading.desk import execution_evidence, planner' for row in records[paper]['imports'])
    harness_path = DOCS / 'sources/original-loader-capacity-harness-v3-2026-10-18.py'
    harness_raw = harness_path.read_bytes()
    assert sha(harness_raw) == '030cb5bb25f89c2785e6acbd55aceff5c99b632a5eb538079ee027362ae6178a'
    harness = ast.parse(harness_raw)
    fence = next(node for node in harness.body if isinstance(node, ast.ClassDef) and node.name == 'CallFence')
    profile = next(node for node in fence.body if isinstance(node, ast.FunctionDef) and node.name == 'profile')
    effect = next(node for node in harness.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'EFFECT_MODULES' for target in node.targets))
    effect_modules = ast.literal_eval(effect.value)
    assert 'backend.agents.trading.desk' in effect_modules
    statements = [ast.unparse(node) for node in profile.body]
    effect_index = next(index for index, text in enumerate(statements) if "self.trip('BROKER_OR_ACCOUNT_FUNCTION'" in text)
    lookup_index = next(index for index, text in enumerate(statements) if text.startswith('registered ='))
    assert effect_index < lookup_index
    prefix = 'backend/market/live_model_history_audit_inputs.py'
    dependencies = next(ast.literal_eval(node.value) for node in trees[prefix].body if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == 'DEPENDENCIES' for item in node.targets))
    assert all(original[name] == recipe[name] for name in dependencies)
    result = {
        'schema': 'original-n2-genuine-capacity-composition/1',
        'status': 'INERT_COMPOSITION_WITH_STATIC_BOOTSTRAP_INCOMPATIBILITY',
        'starting_revision': 'eb670398f67cc8b28d85817cbdf1d1c86a894e8b',
        'contract_sha256': 'ecc58ad7f6ec65bb42a28ef0c2bea8d116b0e9be5ea59e490388fa0e74dfddc8',
        'source_map': {'path': 'original-loader-genuine-source-map-2026-10-18.json', **map_artifact, 'compact_sha256': contract['source_recipe']['composed_compact_map_sha256'], 'files': 2446, 'precedence': contract['source_recipe']['precedence'], 'materialized_source_tree': False, 'native31_compact_sha256': contract['profile']['native31_compact_map_sha256'], 'original_git_map_is_separate': True, 'CURRENT_paper_substituted': False},
        'static_sources': records,
        'execution_receipt': {'sha256': contract['original_selectors']['execution_sha256'], 'bytes': (ROOT / 'original-execution.json').stat().st_size, 'retained_local_root': str(ROOT), 'read_mode': 'One new bounded held-FD SHA-authenticated original metadata read; no Docker/host resource probes, data read or application import.'},
        'namespace_recipe': {'original_readonly_target_mounts_except_original_app': targets, 'original_readonly_absolute_host_aliases': aliases, 'original_account': account, 'excluded_original_writable_results': True, 'original_source_at_original_absolute_host_alias': True, 'composed_app_source': {'source': None, 'target': '/app', 'mode': 'ro', 'requires': 'NEW immutable full2446 source tree authenticated against source_map; never original producer source substituted for composed tree.'}, 'new_audit_and_admission_sources': [{'source': None, 'target': '/audit', 'mode': 'ro'}, {'source': None, 'target': '/admission', 'mode': 'ro'}], 'sole_new_proof': {'source': None, 'target': '/capacity-proof', 'mode': 'rw', 'requires': 'NEW independently admitted UID1000 nonoverlapping root with only preallocated guard-failure.bin before capacity steps.'}, 'exact_actual_mount_inventory': None, 'source_root_paths_are_not_reservations': True},
        'phase_manifest_recipe': {'required_schema': 'n2-capacity-call-manifest/2', 'fingerprint': {'algorithm': 'cpython-code-marshal-format-2-sha256/1', 'marshal_version': 2}, 'required_phase_order': list(PHASES), 'actual_executable_manifest': None, 'calls': None, 'generated': None, 'reason': 'No manifest contents can override the unchanged pre-lookup effect-prefix refusal. Do not publish an all-functions/wildcard phase list or synthetic fixture manifest as a genuine one.', 'phase_intent': {'BOOTSTRAP': 'Only authenticated required imports after active fence/finder; currently blocked.', 'ADMISSION': 'Unchanged invocation/runtime/source/producer/calendar/preservation and real OriginalArchives.', 'BEFORE': 'First complete two-pass input/source authentication receipt retained.', 'LOAD': 'One exact loader call, original daily-prefix transformation, constructor prediction only; stop on return.', 'FROZEN': 'Retained context and alias-aware array inventory; no distribution/select/fit.', 'AFTER': 'Second complete authentication receipt, full graph equality/source and original physical bookends.', 'SERIALIZE': 'Both receipt graphs, archives/context, complete JSON and UTF8 coexist through durable output and final peak metric.', 'DONE': 'Candidate only; independent stopped-runtime/preservation review still required.'}},
        'static_incompatibility': {'status': 'SOURCE_PROVED_UNAVOIDABLE_BACKEND_BOOTSTRAP_FRONTIER_IF_PRIOR_EXTERNAL_IMPORTS_SUCCEED', 'observed_genuine_runtime_failure': False, 'path': [audit, paper, planner], 'planner_Order': node_record(trees[planner], ast.ClassDef, 'Order'), 'next_dataclass_factory_identity': 'backend.agents.trading.desk.planner.__create_fn__', 'profile_effect_branch_before_manifest_lookup': True, 'effect_prefix': 'backend.agents.trading.desk', 'reason': 'BROKER_OR_ACCOUNT_FUNCTION', 'manifest_can_override': False, 'exact_first_runtime_event_certified': False, 'other_reachable_barriers': ['paper and Alpaca generated dataclass factory functions also match effect prefixes.', 'ADMISSION preserved_archives calls paper.state_path, also an effect-prefix function; no call-list entry can admit it.'], 'do_not': ['preload or import before installing guard', 'inject TinySourceBook/fake audit/metric patches into genuine path', 'approve generated rows as if they bypass effect guard', 'change G08 expected refusal or relax effect/source/phase/cap checks']},
        'source_root_dependency_check': {'loader_DEPENDENCIES_all9_match_original_git': True, 'unreviewed_source_root_conflict_asserted': False},
        'runtime_recipe_not_admission': {'image': contract['profile']['auditor_image'], 'uid': '1000:1000', 'network': 'none', 'read_only': True, 'cpu': 1, 'memory_bytes': 2147483648, 'memory_swap_bytes': 2147483648, 'tmpfs': {'/tmp': 'rw,size=64m'}, 'pids_limit_proposed': 32, 'healthcheck': False, 'log_driver': 'none', 'pull_policy': 'never', 'genuine_controller': None, 'runtime_admission': None, 'fresh_headroom': None, 'launch_command': None, 'execution_authorized': False},
        'next': 'Resolve the first static bootstrap incompatibility by a separately source-reviewed capacity-only dependency boundary that does not execute broker/account/planner functions. Review exact declaration needs and preservation helpers before proposing code. Keep existing guard/G08/source/native/config/caps unchanged; no genuine launch or automatic synthetic rerun. A new audited source design or explicit versioned contract is required if immutable recipe cannot provide this separation.',
        'unchanged': {'old_source_roots_admissions': True, 'genuine_loader_not_run': True, 'model_import_load_fit_or_predict': False, 'original_files_changed': False, 'production_changed': False, 'original_timing': 'FAILED', 'publication': 'CLOSED', 'genuine_v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'historical_weekday_intraday_fill_UI': 'UNVERIFIED', 'heartbeat': 'ACTIVE'},
    }
    composition = save(DOCS / 'original-loader-genuine-composition-2026-10-18.json', result)
    print(json.dumps({'source_map': map_artifact, 'composition': composition, 'static_sources': len(records), 'original_target_mounts': len(targets), 'host_aliases': len(aliases), 'genuine_execution': False}, sort_keys=True))

if __name__ == '__main__':
    main()
