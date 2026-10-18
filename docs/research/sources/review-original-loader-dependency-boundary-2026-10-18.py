"""Record exact declaration dependencies without importing or compiling application code."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
SELECTED = {
    'backend/cli/audit_original_live_model_history.py': ('invocation', 'runtime_admission', 'source_admission', 'producer_admission', 'calendar_admission', 'preserved_archives'),
    'backend/market/live_model_history_stream_audit.py': ('OriginalArchives.__init__', 'OriginalArchives.authenticate_sources', 'OriginalArchives.authenticate_inputs'),
    'backend/market/live_model_history_audit_inputs.py': ('load', 'daily_prefix'),
    'backend/market/live_model_history.py': ('FrozenCurrentRiskReader.__init__', 'FrozenCurrentMarketReader.__init__'),
    'backend/market/counterfactual_holding.py': ('CounterfactualRiskReader.__init__',),
    'backend/market/conditional_holding_calibration.py': ('_Calibration._bind',),
    'backend/market/market_conditioned_holding.py': ('_MarketCalibration._bind',),
    'backend/market/learned_live_holding.py': ('source_identity',),
    'backend/agents/trading/desk/paper.py': ('state_path', 'PaperState'),
    'backend/cli/market_strategy_continue.py': ('inputs',),
    'backend/cli/market_actual_policy_timing.py': ('load_passive_inputs',),
    'backend/market/live_model_history_binding.py': ('reviewed_sources', 'review_catalog', 'guard_extension'),
}

# Identify bytes using the same complete hash algorithm as source admission.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()

# Read exact source provenance without substituting CURRENT for original N2.
def source(name, pin):
    raw = (REPO / name).read_bytes()
    origin = 'matching local source'
    if sha(raw) != pin:
        raw = subprocess.run(['git', 'show', '27471b9c61b958f759e9f48b80acaf60cdf75f2e:' + name], cwd=REPO, capture_output=True, check=True).stdout
        origin = 'original27471 Git blob'
    assert sha(raw) == pin
    return raw, origin

# Select one original declaration and retain all of its method or function body.
def selected(tree, qualified):
    node = tree
    for name in qualified.split('.'):
        node = next(item for item in node.body if isinstance(item, (ast.ClassDef, ast.FunctionDef)) and item.name == name)
    return node

# Preserve only a newly named finite static report and byte-identical readback.
def save(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    with path.open('xb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    assert path.read_bytes() == raw
    return {'sha256': sha(raw), 'bytes': len(raw)}

# Describe source coupling and a narrow unexecuted metadata boundary proposal.
def main():
    map_path = DOCS / 'original-loader-genuine-source-map-2026-10-18.json'
    assert sha(map_path.read_bytes()) == '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
    pins = json.loads(map_path.read_bytes())
    facts, source_records, trees = {}, {}, {}
    for name, declarations in SELECTED.items():
        raw, origin = source(name, pins[name])
        tree = ast.parse(raw)
        trees[name] = tree
        source_records[name] = {'sha256': pins[name], 'bytes': len(raw), 'origin': origin}
        for qualified in declarations:
            node = selected(tree, qualified)
            facts[name + ':' + qualified] = {
                'line': node.lineno, 'end_line': node.end_lineno,
                'AST_sha256': sha(ast.dump(node, include_attributes=False).encode()),
                'calls': sorted({ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)}),
                'source_file_accesses': sorted({ast.unparse(item) for item in ast.walk(node) if isinstance(item, ast.Call) and (ast.unparse(item.func).endswith(('read_bytes', 'getsource')) or ast.unparse(item) == 'Path(__file__)')}),
            }
    paper = trees['backend/agents/trading/desk/paper.py']
    state = selected(paper, 'PaperState')
    fields = [item.target.id for item in state.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)]
    kind = next(item.value.value for item in paper.body if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'PAPER_KIND' for target in item.targets))
    assert len(fields) == len(set(fields)) == 17 and kind == 'paper'
    contract = json.loads((DOCS / 'original-loader-capacity-contract-2026-10-18.json').read_bytes())
    native = contract['source_recipe']['native31']
    assert len(native) == 31 and sha(json.dumps(native, sort_keys=True, separators=(',', ':')).encode()) == '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab'
    helper = DOCS / 'sources/original-loader-capacity-metadata-boundary-2026-10-18.py'
    helper_raw = helper.read_bytes()
    helper_tree = ast.parse(helper_raw)
    assert {item.name for item in helper_tree.body if isinstance(item, ast.FunctionDef)} == {'require', 'paper_descriptor', 'physical_state_path', 'native_source_identity'}
    imports = [ast.unparse(item) for item in helper_tree.body if isinstance(item, (ast.Import, ast.ImportFrom))]
    assert imports == ['import ast', 'import hashlib', 'import json', 'from pathlib import Path']
    result = {
        'schema': 'original-loader-dependency-boundary-review/1',
        'status': 'SOURCE_REVIEWED_METADATA_CUT_PROPOSED_UNEXECUTED_MODEL_BOUNDARY_OPEN',
        'starting_revision': 'e50b81c6eb893c5d43310a3c30747eaa15da0776',
        'source_records': source_records, 'exact_declarations': facts,
        'metadata_cut': {
            'paper_source_sha256': pins['backend/agents/trading/desk/paper.py'],
            'PaperState_fields': fields, 'PAPER_KIND': kind,
            'relative_state_components': ['paper', 'state.json'],
            'PaperState_AST_sha256': facts['backend/agents/trading/desk/paper.py:PaperState']['AST_sha256'],
            'state_path_AST_sha256': facts['backend/agents/trading/desk/paper.py:state_path']['AST_sha256'],
            'native31_pins': native, 'native31_compact_sha256': '99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab',
            'helper': {'path': 'sources/original-loader-capacity-metadata-boundary-2026-10-18.py', 'sha256': sha(helper_raw), 'bytes': len(helper_raw), 'imports': imports, 'functions': 4, 'body_import_compile_exec_or_test': False},
            'scope': 'Read-only declaration metadata, no fake paper/planner/broker modules, class instances, function replacements or authority to access an account.',
            'standalone_source_admission': False,
            'future_reader_binding': 'A new exact caller/contract must require the real authenticated complete SourceBook and bind read_source to its unchanged held-FD read. Callable injection is not genuine acceptance.',
        },
        'model_boundary_findings': [
            'Audit, OriginalArchives, continuation and economics modules import effect modules even when only read-only helpers are requested.',
            'FrozenCurrentRiskReader and CounterfactualRiskReader need numerical constructor bodies; their module files also define policy classes whose base classes import joint funded policy.',
            'Existing full-source identities and self-file hashes must remain explicit: _Calibration._bind and _MarketCalibration._bind hash their own/dependency __file__ bytes, and daily_prefix uses inspect.getsource on the original inputs function.',
            'Moving or cloning numeric bodies into a new file can change receipt identities; selected-AST compilation can change CodeTypes. AST equality alone is not numerical, identity, lifetime or memory parity.',
            'A declaration metadata helper alone does not remove any existing module import. The unchanged genuine bootstrap remains blocked regardless of manifest contents.',
        ],
        'selected_design': {
            'first_atomic_cut': 'Explicit source-bound read-only metadata helper, separately versioned and outside all effect namespaces; future preservation/admission code may consume its exact data only after parity tests and fresh source admission.',
            'model_import_strategy': None,
            'genuine_capacity_execution_ready': False,
            'required_new_contract': 'No old2446/ecc/030c public route silently changed. Any new capacity module/overlay/projection must carry its own complete executed-source map, original-source map, exact full-compilation code identities, source/runtime binding and independently reviewed phase manifest.',
            'preserve_source_identity': 'Authenticate original31 and all original2431 input source bytes independently, retain existing review chain, and publish any new capacity-executor source identity separately. Never relabel changed executor bytes as old original identity.',
            'rejected_shortcuts': ['preload account/planner imports before fence', 'broaden EFFECT_MODULES or generated allowlist to override G08', 'fake paper or broker globals/fixtures as genuine modules', 'move __file__ to make changed source look unchanged', 'copy numeric helpers and claim parity from AST alone', 'launch any old or new genuine account/model/loader run'],
        },
        'required_tiny_acceptance_before_integration': [
            'Prepare new exact packet/proposal/caller and fresh independent synthetic-only actual source/image/UID/jobs/resource/invocation admission; no reuse or full65+4 replay.',
            'N2 exact original paper descriptor and state_path parity, exact17 fields and all31 actual retained source hashes with source reader bookends; original paper module stays unimported in candidate.',
            'Changed source byte, CURRENT paper substitution, wrong descriptor fields/kind/path/AST/schema, incomplete31 map, wrong pin/source bytes and wrong reader binding must refuse at exact boundaries.',
            'Any original state_path or source_identity reference comparison must be explicitly isolated and labelled as a synthetic control, never run under a genuine account or represent it as an unguarded capacity path.',
            'No native state normalization, asdict construction or PaperState object; retain exact original raw physical hashes and the existing separately explicit logical comparison.',
        ],
        'current_runtime': {'application_or_numerical_import': False, 'CodeType_compile': False, 'helper_import_or_execution': False, 'SSH_host_probe_Docker_or_new_job': False, 'old_gate_or_body_replay': False, 'launch': None, 'admission': None, 'genuine_model_RAM_acceptance': False},
        'next': 'Independently review the unexecuted metadata helper, then prepare its narrow source-pinned tiny proposal and fail-closed controls. In parallel source-review a concrete numeric import closure without self-source identity or allocation-lifetime drift; do not declare a model boundary selected or genuine execution ready.',
        'unchanged': {'original_timing': 'FAILED', 'publication': 'CLOSED', 'genuine_v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'historical_weekday_intraday_fill_UI_combined_RAM': 'UNVERIFIED', 'heartbeat': 'ACTIVE'},
    }
    print(json.dumps({'report': save(DOCS / 'original-loader-dependency-boundary-review-2026-10-18.json', result), 'source_files': len(source_records), 'declarations': len(facts), 'helper': result['metadata_cut']['helper']}, sort_keys=True))

if __name__ == '__main__':
    main()
