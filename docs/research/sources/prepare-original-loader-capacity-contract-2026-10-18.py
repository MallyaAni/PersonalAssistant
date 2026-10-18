"""Prepare a local inert contract; never import application code or contact a host."""

import ast
import hashlib
import json
import os
from pathlib import Path

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
OUT = Path('/tmp/original-loader-capacity-contract-20261018-v2')
ORIGINAL = '/home/animallya96/scratch/live-model-history-full-20261013-v1'
MARKET = '/home/animallya96/scratch/live-model-history-20261013-v4/market'
INPUTS = {
    'git': (Path('/tmp/original-history-git-27471b9c-20261017-v1.json'), 'c7abe1641a5510902c9f4ada1bd26faa23681232bdcace74b55a698740080eb0'),
    'baseline': (Path('/tmp/original_streamed_history_baseline_pins_20261017.json'), 'c097f38038e3122d692be442b880492d89b8aff3735174105153ff817c57dc8c'),
    'overlays': (Path('/tmp/original_sha_map_source_pins_20261017.json'), '5958b411d4d96b195292ffba9aa47de4e537bdc7a6dc3ea59a5a50206faf4c48'),
    'identities': (Path('/tmp/historical-current-settlement-cycle-native-20261017-v1/input/identities.json'), 'ea375ba067399da3366bbba4c62e2011244c0f8dfc667e31f3a94b94435022fc'),
}
REVIEWS = {
    'docs/research/trading-source-approval-review-2026-10-17.json': '8b628c76066f62ee724a36d3d07219848786d49d51bb243d73e3e056d7c72bd4',
    'docs/research/trading-numeric-source-review-2026-10-17.json': '2f048a8040532bfdaa49b1101e552457454b526b510b4ee9f2422f3a67a3e5f7',
    'docs/research/settlement-metadata-source-review-2026-10-17.json': '875976f63a530bc14898f3d3121e6177421f82e2275f7a8dabc5cf2b94266ac6',
}
GRAPH_PATHS = (
    'backend/market/live_model_history.py',
    'backend/market/counterfactual_holding.py',
    'backend/market/conditional_holding_calibration.py',
    'backend/market/market_conditioned_holding.py',
    'backend/cli/market_strategy_continue.py',
    'backend/market/learned_retention_models.py',
    'backend/market/direct_daily_arithmetic.py',
    'backend/market/live_execution_inputs.py',
    'backend/cli/market_actual_policy_timing.py',
    'backend/market/panel.py',
    'backend/market/store.py',
)


# Identify bytes without changing their representation.
def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# Encode finite metadata using a stable map ordering.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Pin each small existing manifest before using its declarations.
def admitted(path, expected):
    raw = path.read_bytes()
    assert digest(raw) == expected, str(path)
    return json.loads(raw)


# Preserve only new local metadata and read it back after fsync.
def save(name, value):
    raw = encoded(value)
    with (OUT / name).open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    assert (OUT / name).read_bytes() == raw
    return {'sha256': digest(raw), 'bytes': len(raw)}


# Describe one exact source function without importing or running its module.
def function_record(path, name):
    raw = (REPO / path).read_bytes()
    tree = ast.parse(raw)
    parts = name.split('.')
    selected = tree
    for part in parts:
        selected = next(node for node in selected.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == part)
    return {
        'path': path, 'function': name, 'line': selected.lineno,
        'source_sha256': digest(raw),
        'function_ast_sha256': digest(ast.dump(selected, include_attributes=False).encode()),
        'calls': sorted({ast.unparse(node.func) for node in ast.walk(selected) if isinstance(node, ast.Call)}),
    }


# Assemble a reviewable no-launch contract and evidence for its local source claims.
def main():
    values = {name: admitted(*item) for name, item in INPUTS.items()}
    original, baseline = values['git']['files'], values['baseline']
    overlays = {name: pin for name, pin in values['overlays'].items() if '/tests/' not in name}
    native = values['identities']['N2']['source_sha256']
    assert len(original) == 2431 and len(native) == 31 and len(overlays) == 6
    assert values['git']['revision'] == '27471b9c61b958f759e9f48b80acaf60cdf75f2e'
    assert digest(json.dumps(native, sort_keys=True, separators=(',', ':')).encode()) == '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
    assert all(baseline[name] == pin for name, pin in native.items())
    recipe = {**original, **baseline, **overlays, **REVIEWS}
    checked = {name: recipe[name] for name in set(GRAPH_PATHS) | set(baseline) | set(overlays) | set(REVIEWS)}
    # Main carries CURRENT paper bytes, so native31 is checked against the N2
    # manifest; only explicitly matching local source is read for graph evidence.
    matching = {name: pin for name, pin in checked.items() if (REPO / name).is_file() and digest((REPO / name).read_bytes()) == pin}
    assert all(name in matching for name in GRAPH_PATHS)
    assert all(name in matching for name in overlays)
    assert all(name in matching for name in REVIEWS)
    assert matching['backend/market/live_model_history_audit_inputs.py'] == 'fae5bfc7d7438071094f31f42e884cb48e3709c55f364954e51c28302d3c3e30'
    facts = [function_record(*item) for item in (
        ('backend/market/live_model_history_audit_inputs.py', 'load'),
        ('backend/market/live_model_history_audit_inputs.py', 'daily_prefix'),
        ('backend/market/counterfactual_holding.py', 'CounterfactualRiskReader.__init__'),
        ('backend/market/live_model_history.py', 'FrozenCurrentRiskReader.__init__'),
        ('backend/market/live_model_history.py', 'FrozenCurrentMarketReader.__init__'),
        ('backend/market/conditional_holding_calibration.py', '_Calibration._bind'),
        ('backend/market/market_conditioned_holding.py', '_MarketCalibration._bind'),
        ('backend/market/market_conditioned_holding.py', '_MarketCalibration._stock_fit'),
        ('backend/cli/audit_original_live_model_history.py', 'runtime_admission'),
        ('backend/cli/audit_original_live_model_history.py', 'audit'),
    )]
    assert sum('learned_retention_models.completed_features' in row['calls'] for row in facts) == 2
    assert 'deepcopy' in facts[5]['calls']
    assert 'numerical.fit_market_log' in facts[7]['calls']
    contract = {
        'schema': 'original-n2-loader-capacity-contract/1',
        'status': 'INERT_SOURCE_REVIEW_ONLY_NOT_EXECUTABLE_NOT_ADMITTED',
        'scope': 'Future one-shot original loader plus full authentication-receipt coexistence; no full audit, distribution or account work.',
        'execution_authorized_by_this_contract': False,
        'entrypoint': None,
        'launch_command': None,
        'runtime_admission_document': None,
        'profile': {
            'name': 'original-full-27471',
            'auditor_image': values['identities']['N2']['backend_image'],
            'native31_compact_map_sha256': '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab',
            'numpy': '2.5.3', 'sklearn': '1.9.1',
            'original_config_not_n2_or_current_serving_config': '1a14980a66a1cb5994f0bb82667dd46fce40ec7eb0705728d93e36b18faf5901',
            'n2_serving_config_338e_and_current_config_f96a_forbidden_as_original_selectors': True,
        },
        'source_recipe': {
            'precedence': ['original_git_map', 'frozen_n2_baseline', 'six_original_audit_overlays', 'three_binding_reviews'],
            'map_inputs': {name: {'path': str(path), 'sha256': pin} for name, (path, pin) in INPUTS.items()},
            'original_git_files': len(original),
            'frozen_n2_baseline': baseline,
            'six_original_audit_overlays': overlays,
            'three_binding_reviews': REVIEWS,
            'native31': native,
            'composed_file_count': len(recipe),
            'composed_compact_map_sha256': digest(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()),
            'assembled_tree_exists_or_verified': False,
            'required_before_execution': 'Materialize a NEW immutable exact source tree; authenticate complete composed map and actual import origins before importing numerical modules, with post-run source bookends. No undeclared backend module or ambient host site-packages. Retain original Git-map equality separately; the N2 auditor is not the producer tree.',
            'local_graph_sources_matching_recipe': matching,
            'local_mismatches_not_substituted': sorted(set(checked) - set(matching)),
        },
        'original_selectors': {
            'account_host_path': ORIGINAL + '/output/account',
            'market_host_path': MARKET,
            'namespace_policy': 'Host paths are provenance, not loader argv. Preserve original execution RO target namespaces for OriginalArchives reads, plus original11 RO host namespaces mounted at their own absolute host paths for byte_auth.resolve_input. Mount the composed N2 tree separately at /app; never substitute it into the original producer source host namespace. Derive and pin the full target/host mapping from execution eaa07107 before admission; reject overlaps with the sole proof RW root.',
            'producer_revision': values['git']['revision'],
            'producer_container': '1e8f440a3b5b75dcabd299f5eaba58c7929fb6f96bc822fdb46b641ecf3e598d',
            'producer_image': 'sha256:136ebb46b7912f20472a375a6b29f6efec4cf2fdca13d56cbffb86a1be697db2',
            'producer_inspect_sha256': 'd656d927efc04ae72b1985730f6c4bb470b3e5af862ca37e4dca7c48e45ae8f6',
            'completion': {'bytes': 373782589, 'sha256': 'b9ad0b6c86b287f3557c635a5fca17703adc48a30a75470256084af911c8a3dd'},
            'physical_state': {'bytes': 832110254, 'sha256': 'f334e3a5c691fb4dbcc8ea4e7236f395eb5e26e34bae2f1fd4fac64fc5935130'},
            'initial_sha256': '428d129ba753b833fff909d0a2bae23c7fbba2b2a1f0112fe235407445eeb7b3',
            'source_manifest_sha256': 'd930c0a12574c6b1611a2bc17cabb30c2fd12b8afd899ab0b97a28d583543ae0',
            'execution_sha256': 'eaa07107c2f88e31f6c3eaf1f5eee1bf579bc86fed60db7f578a502859960e96',
            'git_map_sha256': INPUTS['git'][1],
            'bank_receipt': {'relative_path': 'desk/learned-holding/risk/bank.json', 'bytes': 4777209, 'sha256': '79b33d54253001ba0f907ae0b41f49c81ae436800e43e05b75cd5f58bb653cfe'},
            'bank_arrays': {'relative_path': 'desk/learned-holding/risk/bank.npz', 'bytes': 11168202, 'sha256': 'fcb0f04c847a10a2842d26418b872bb1fc758a1d2752727eda72a25c8f122f7a'},
            'head_receipt': {'relative_path': 'desk/learned-holding/model/publication.json', 'bytes': 47641, 'sha256': '858163d5e414ee658f28a10532a934528c72fe98fd1cb685e655d6d3a2c75825'},
            'head_arrays': {'relative_path': 'desk/learned-holding/model/model.npz', 'bytes': 98939, 'sha256': 'e0c42cc2c636db332058424ebe52e153cc364b65eba6b45720e38d900c86cccb'},
            'capture_observation_overlay_economics': 'Derive only through OriginalArchives and exact loader constants/receipt selectors. Authenticate full original manifest2431 and all declared164833 input bytes; never use serving selectors or unreviewed path rewrites.',
            'initial_venue_receipts': None,
        },
        'future_sequence_required': [
            'Fresh exclusive proof root, independently pinned exact source tree, complete invocation and current host/runtime admission; no source/model/account import beforehand.',
            'Call unchanged runtime_admission, enforce exact numerical versions, construct real OriginalArchives(external_inputs=True) with original completion/initial/manifest and fresh spool; no stub archives or synthetic market.',
            'Call unchanged source_admission, producer_admission, calendar_admission and preserved_archives. Full original Git-map2431 equality remains separate from the composed N2 auditor map.',
            'Call unchanged byte_auth.authenticate once for bytes_before (two physical passes); retain its full returned graph and real archives/control/spool objects.',
            'Call exact loader.load once with real archives, original market and real UTC observed_at. Retain returned AuditInputs. Constructor prediction is allowed and reported; it is not a base-model fit.',
            'STOP all model computation at loader return. No select, distribution, calibration fit, StreamAudit construction/verify, initial attempt evaluation, planner, policy, broker, account save/replay or publication.',
            'With loaded context and bytes_before still alive, call unchanged byte_auth.authenticate for bytes_after (two physical passes), compare complete graphs; recheck original physical/source/config selectors and immutable original state.',
            'Retain loaded context, archives and both full receipt graphs through exact final finite JSON serialization of a capacity-only result embedding bytes_before. Exercise Unicode string and encoded UTF8 coexistence if the future writer uses encode. Keep originals unchanged; do not remove fields, lazy-load, truncate or normalize NaNs to fit.',
            'Independently inspect stopped exact owned container, actual mounts/resources/exit/noOOM and full output/source/original physical bookends. No reuse of an old CID/root or inferred success from a live PID.',
        ],
        'allocation_ledger': {
            'measured_archive_array_storage_bytes': {'bank': 29531920, 'head': 104064, 'total': 29635984},
            'measured_receipt_only_peak_kib': 947364,
            'measured_receipt_bytes': 137832798,
            'storage_or_prior_peak_is_not_new_peak_bound': True,
            'allocations_to_account_by_actual_lifetime_not_all_simultaneously': [
                'OriginalArchives immutable metadata, canonical ending-state identity, external164833-pair spool/index and bookkeeping',
                'bytes_before complete authentication graph and temporary second-pass identity/path records',
                'bank JSON bytes/decoded receipt/NPZ bytes/14arrays and load-bank copy/lineage validation temporaries',
                'head receipt/NPZ bytes/196arrays and numeric publication reconstruction copies',
                'daily panel, price arrays, grades, factors, action declarations, passive/observation arrays and reviewed economics',
                'first completed_features full tensor plus parent last-row prediction temporaries',
                'second completed_features full tensor plus full-history prediction temporaries and frozen copies',
                'seven bank field copies, current observation copies, then market-parent deepcopy and market context copy',
                'all loaded AuditInputs and both full authentication receipt graphs; second authentication scratch and file-cache charges',
                'final capacity result references, json.dumps Unicode output, optional UTF8 bytes, write buffers and retained file cache',
                'interpreter/import/native-library/BLAS allocator overhead, tmpfs, filesystem page cache and cgroup kernel charges',
            ],
            'phase_lifetimes': [
                {'phase': 'OriginalArchives admission and first byte authentication', 'live_roots': ['archives and spools', 'authentication current-pass scratch'], 'release': 'Internal parser/decoder lifetimes unchanged; keep archives and returned bytes_before alive.'},
                {'phase': 'bank/head/daily/economic load', 'live_roots': ['archives', 'bytes_before', 'loader locals constructed so far', 'native loader transient bytes/arrays'], 'release': 'Native loader locals and first feature-construction temporaries leave scope normally; do not artificially retain or delete them.'},
                {'phase': 'frozen risk constructor and market binding', 'live_roots': ['archives', 'bytes_before', 'loader original bank/head/panel/raw locals', 'constructed parent reader', 'second feature construction and full prediction temporaries', 'deepcopy destination during _bind'], 'release': 'First completed_features full tensor is not required to coexist with the second once its constructor returns. Preserve unchanged source allocation lifetimes.'},
                {'phase': 'second byte authentication', 'live_roots': ['archives', 'bytes_before', 'returned AuditInputs including detached market parent', 'authentication scratch and growing bytes_after'], 'release': 'Loader locals not reachable from returned context are no longer deliberately retained.'},
                {'phase': 'final capacity-only serialization', 'live_roots': ['archives', 'bytes_before', 'bytes_after', 'loaded AuditInputs', 'result and full JSON Unicode string', 'optional encoded UTF8 bytes and write buffers'], 'release': 'Release only after durable complete capacity receipt and final metrics.'},
            ],
            'deduplicate_views_by_base_allocation': True,
            'numeric_whole_graph_peak_bound_bytes': None,
            'full_distribution_cache_or_horizon_memory': 'NOT_IN_SCOPE_NOT_PROVED',
            'required_phase_measurements': ['monotonic time', 'Linux ru_maxrss KiB', 'VmRSS/VmHWM', 'cgroup memory.current/peak/events and swap.current', 'retained array shapes/dtypes/nbytes with alias-aware inventory', 'proof spool/index/receipt physical allocations'],
        },
        'future_resource_contract_NOT_admission': {
            'host': 'Spark1 only; Spark2 and serving model processes excluded',
            'uid': '1000:1000', 'network': 'none', 'readonly_rootfs': True,
            'nano_cpus': 1000000000, 'memory_bytes': 2147483648, 'memory_swap_total_bytes': 2147483648,
            'tmpfs_exact_existing_guard': {'/tmp': 'rw,size=64m'},
            'pids_limit_proposed': 64, 'cap_add': [], 'devices': [], 'privileged': False,
            'healthcheck': 'disabled', 'log_driver': 'none', 'pull_policy': 'never',
            'docker_socket': 'unix:///var/run/docker.sock; explicit local daemon, independently observed actual container',
            'wall_deadline_seconds_proposed': 1800,
            'fresh_host_headroom_proposed': {'MemAvailable_bytes': 5368709120, 'proof_filesystem_available_bytes': 4294967296, 'available_inodes': 8192},
            'proof_disk_reserved': False, 'headroom_is_not_reservation': True,
            'sole_writable_bind': 'NEW exclusive UID1000 proof root outside all original input/source namespaces; original account and original11 input/source namespaces read-only; never original /results writable',
            'exact_mount_inventory': None,
            'fresh_runtime_and_host_evidence': None,
            'required_controller': 'Source-reviewed finite stdout/stderr/progress limits, monotonic deadlines, owned-CID-only stop/kill/reap and durable nonzero/timeout/OOM receipts. No service stop, blind retry or cleanup of failed evidence. These branches need synthetic validation before any genuine loader admission.',
        },
        'future_acceptance': {
            'required': ['known exact image/source/import origins', 'all authentic admissions complete', 'one loader return', 'zero forbidden calls with independently reviewed pre-import structural guard', 'both complete byte receipts and loaded context coexist through serialization', 'exit0/noOOM/no memory.events OOM or unexplained source/input changes', 'exact original NaN bytes preserved', 'independent terminal/runtime/receipt/preservation check'],
            'possible_claim': 'Loader plus receipt coexistence under one exact bounded N2 invocation only; not numerical/causal/economic correctness, distribution caches, account lifecycle or full horizon.',
            'failure_rule': 'Preserve root/logs/spools/actual terminal state; no automatic retry, cap increase, source substitution, state adoption or fabricated result.',
        },
        'current_verified': ['original header byte/storage inventory', 'original full-byte and two-file consistency checkpoints', 'local AST/source graph observations only in this contract'],
        'current_failed': ['original timing contract'],
        'current_unverified': ['combined loader/receipt peak memory', 'assembled exact N2 source tree', 'capacity harness and forbidden-call guard', 'fresh runtime/host/resources/mount admission', 'full original audit/corrected history/weekday/intraday/fill/UI acceptance'],
        'publication': 'CLOSED', 'genuine_v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_OR_NEW_RUN',
        'actual_two_host': False, 'diagram_impact': 'NONE: inert capacity contract; no implemented component or runtime flow changed',
    }
    OUT.mkdir(mode=0o700, exist_ok=False)
    source = save('source-review.json', {'status': 'LOCAL_SOURCE_AND_AST_ONLY', 'manifest_inputs': contract['source_recipe']['map_inputs'], 'functions': facts, 'module_imports': False, 'network_or_host_runtime': False})
    saved = save('contract.json', contract)
    save('manifest.json', {'contract.json': saved, 'source-review.json': source, 'generator_sha256': digest(Path(__file__).read_bytes())})
    print(json.dumps({'root': str(OUT), 'contract': saved, 'source_review': source, 'composed_file_count': len(recipe), 'local_matching_files': len(matching), 'runtime_executed': False}))


if __name__ == '__main__':
    main()
