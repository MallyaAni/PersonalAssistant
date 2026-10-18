"""Build explicit inert capacity source modules; do not import or compile payload code."""

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from textwrap import dedent

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-loader-entry-source-20261018-v1')
ORIGINAL = '27471b9c61b958f759e9f48b80acaf60cdf75f2e'
MAP_SHA = '9a0bfbeb59e0a63072453a6ac0e930e65a89684efd90bc705febf9b1bdbe6224'
PINS = {}
CACHE = {}


# Hash exact source or finite metadata bytes without interpreting payload objects.
def digest(raw):
    return sha256(raw).hexdigest()


# Preserve only a new artifact and verify exact bytes after fsync.
def save(path, raw, *, metadata=False):
    assert len(raw) <= (16 * 1048576 if metadata else 262144), str(path)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


# Encode finite provenance without serializing any application or model state.
def json_bytes(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Read exact original-map source bytes through local files or the original Git revision.
def source(path):
    if path not in CACHE:
        current = REPO / path
        raw = current.read_bytes() if current.is_file() else b''
        origin = 'matching local source'
        if digest(raw) != PINS[path]:
            raw = subprocess.run(['git', 'show', ORIGINAL + ':' + path], cwd=REPO, capture_output=True, check=True).stdout
            origin = 'exact original Git blob'
        assert digest(raw) == PINS[path] and len(raw) <= 1048576, path
        CACHE[path] = {'raw': raw, 'tree': ast.parse(raw), 'origin': origin}
    return CACHE[path]


# Select one complete original declaration without executing its decorators or body.
def node(path, qualified):
    value = source(path)['tree']
    for name in qualified.split('.'):
        value = next(item for item in value.body if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name == name)
    return value


# Copy source text including a declaration's decorators while retaining its original body.
def segment(path, qualified):
    value = node(path, qualified)
    start = min([value.lineno] + [item.lineno for item in value.decorator_list]) - 1
    lines = source(path)['raw'].decode().splitlines(keepends=True)
    return dedent(''.join(lines[start:value.end_lineno]))


# Select exact original constants without importing their source module.
def constants(path, names):
    values = []
    for name in names:
        value = next(item for item in source(path)['tree'].body if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in item.targets))
        values.append(ast.get_source_segment(source(path)['raw'].decode(), value) + '\n')
    return '\n'.join(values)


# Rename only explicitly declared source tokens with exact occurrence assertions.
def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


# Persist an explicitly new source identity at its proposed real application origin.
def module(name, text):
    raw = text.encode()
    tree = ast.parse(raw, filename=name)
    lines = text.splitlines()
    functions = [item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert all(lines[min([item.lineno] + [decorator.lineno for decorator in item.decorator_list]) - 2].lstrip().startswith('#') for item in functions)
    target = DOCS / ('sources/original-loader-capacity-' + name + '-v1-2026-10-18.py')
    record = save(target, raw)
    record['path'] = str(target.relative_to(DOCS))
    record['proposed_origin'] = 'backend/market/capacity_original_' + name.replace('-', '_') + '_v1.py'
    record['functions'] = len(functions)
    record['bodies_run'] = False
    save(ROOT / target.name, raw)
    return record


# Keep every fresh source body inert while preparing its declared dependencies and comparisons.
def main():
    ROOT.mkdir(exist_ok=False)
    map_raw = (DOCS / 'original-loader-genuine-source-map-2026-10-18.json').read_bytes()
    assert digest(map_raw) == MAP_SHA
    PINS.update(json.loads(map_raw))
    audit = 'backend/market/live_model_history_audit_inputs.py'
    continuation = 'backend/cli/market_strategy_continue.py'
    economics = 'backend/cli/market_actual_policy_timing.py'
    historical = 'backend/market/live_model_history.py'
    counterfactual = 'backend/market/counterfactual_holding.py'
    original_daily = segment(continuation, 'inputs')
    assert digest(original_daily.encode()) == '40d0d7cf482591ba28e6426ca87d23d3ed1b1cf42e31fd74a24a1287129221d9'
    daily_node = node(continuation, 'inputs')
    stops = [item for item in daily_node.body if isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'shape' for target in item.targets)]
    assert len(stops) == 1
    daily_lines = source(continuation)['raw'].decode().splitlines(keepends=True)
    daily_body = ''.join(daily_lines[daily_node.body[0].lineno - 1:stops[0].lineno - 1])
    daily_text = '''"""UNEXECUTED explicit daily-prefix capacity source; never the original CLI identity."""
import json
from hashlib import sha256

import numpy as np

from backend.market.panel import build_panel
from backend.market.store import MarketStore

SCHEMA = 'capacity-original-daily-inputs/1'
ORIGINAL_FUNCTION_SHA256 = '40d0d7cf482591ba28e6426ca87d23d3ed1b1cf42e31fd74a24a1287129221d9'


# Build the exact original pre-grid daily statements under a distinct source identity.
def daily_prefix(market, original, through):
''' + daily_body + '    return panel, grades, eligible, factors, actions, sources\n'
    modules = {'daily-inputs': module('daily-inputs', daily_text)}
    economic_constants = ('SNAPSHOT_SHA', 'ACTIONS_SHA', 'ACTION_REVIEW_SHA', 'ECONOMIC_INPUT_PROOF_SHA', 'PASSIVE_ARRAYS_SHA', 'PASSIVE_RECEIPT_SHA')
    evidence_body = segment('backend/cli/market_probabilistic_execution.py', 'evidence')
    evidence_body = replace_once(evidence_body, 'def evidence(', 'def _passive_evidence(')
    evidence_body = replace_once(evidence_body, 'sha256(path)', '_file_sha256(path)')
    file_hash = replace_once(segment('backend/cli/market_learned_entry.py', 'sha256'), 'def sha256(', 'def _file_sha256(')
    passive_plain = segment('backend/market/live_policy_replay.py', 'plain')
    assert passive_plain.count('plain(') == 3
    passive_plain = passive_plain.replace('plain(', '_passive_provenance_plain(')
    passive_plain = replace_once(passive_plain, 'return float(value) if math.isfinite(value) else None', 'require(math.isfinite(value), "FINITE_PASSIVE_PROVENANCE_REQUIRED")\n        return float(value)')
    passive_loader = segment(economics, 'load_passive_inputs').replace('forecasts.evidence(', '_passive_evidence(')
    passive_loader = replace_once(passive_loader, 'plain(passive.provenance)', '_passive_provenance_plain(passive.provenance)')
    reviewed = segment(audit, 'reviewed_economics')
    assert reviewed.count('economics.') == 6
    reviewed = reviewed.replace('economics.', '')
    economic_text = '''"""UNEXECUTED explicit capacity economics; no study, replay or account imports.

The private provenance projection refuses nonfinite scalars instead of converting
them to null. Its only caller compares the actual prepare_passive provenance;
it is not a generic native/account normalizer. That narrower domain needs parity.
Original evidence helper leaf-symlink, two-read and json.loads semantics remain.
"""
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.market.capacity_original_evidence_v1 import authenticate_file, pinned, require, strict_json
from backend.market.live_execution_inputs import PassiveMarks, _actions, _dates_by_name, _inherited_actions, prepare_passive, review_action_export

SCHEMA = 'capacity-original-economics/1'

''' + constants(audit, ('ECONOMIC_RECEIPT_SHA256',)) + '\n' + constants(economics, economic_constants)
    for purpose, text in (
        ('Hash only an explicitly supplied passive evidence path with the original chunked helper.', file_hash),
        ('Retain original passive evidence Path-versus-JSON, leaf-link and hash behavior.', evidence_body),
        ('Project only derived finite passive provenance, refusing rather than normalizing nonfinite values.', passive_plain),
        ('Retain exact passive NPZ coordinates, fields, source receipts and derived readonly provenance.', passive_loader),
        ('Select every original economic receipt path without importing a study CLI.', segment(audit, 'economic_paths')),
        ('Preserve missing later passive marks and original array allocation order.', segment(audit, 'align_passive')),
        ('Retain all reviewed economic and inherited action checks with explicit new helper bindings.', reviewed),
    ):
        economic_text += '\n\n# ' + purpose + '\n' + text
    modules['economics'] = module('economics', economic_text)
    base_init = segment(counterfactual, 'CounterfactualRiskReader.__init__')
    frozen_init = segment(historical, 'FrozenCurrentRiskReader.__init__')
    market_init = replace_once(segment(historical, 'FrozenCurrentMarketReader.__init__'), 'type(parent) is not FrozenCurrentRiskReader', 'type(parent) is not CapacityFrozenRiskReaderV1')
    reader_text = '''"""UNEXECUTED capacity reader identities; constructors only, no policy admission.

Two constructor frames preserve the first feature graph's release boundary.
Inherited select/distribution/clock and calibration methods are NOT admitted;
the future exact phase fence must exclude every such call. No model is fitted.
"""
from copy import deepcopy

import numpy as np

from backend.market import direct_daily_arithmetic, forward_arithmetic, learned_retention_models
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.market_conditioned_holding import ForwardMarketConditionedHoldingReader

SCHEMA = 'capacity-original-frozen-readers/1'


# Retain original counterfactual constructor allocations in a separate returning frame.
class CapacityCounterfactualRiskBaseV1(forward_arithmetic.ForwardVolatilityHoldingReader):
'''
    for purpose, declaration_text in [('Preserve first features, first prediction, current observation and original bank copies.', base_init)]:
        reader_text += '    # ' + purpose + '\n' + '\n'.join('    ' + line if line else '' for line in declaration_text.splitlines()) + '\n'
    reader_text += '\n\n# Freeze the second complete feature graph only after the first constructor returns.\nclass CapacityFrozenRiskReaderV1(CapacityCounterfactualRiskBaseV1):\n    # Preserve the second prediction, frozen copies, readonly flags and original numeric receipt.\n'
    reader_text += '\n'.join('    ' + line if line else '' for line in frozen_init.splitlines()) + '\n'
    reader_text += '\n\n# Preserve real market-calibration MRO, deepcopy and self-file identities under a new type.\nclass CapacityFrozenMarketReaderV1(ForwardMarketConditionedHoldingReader):\n    # Accept only the exact new capacity parent before unchanged original market binding.\n'
    reader_text += '\n'.join('    ' + line if line else '' for line in market_init.splitlines()) + '\n'
    modules['frozen-readers'] = module('frozen-readers', reader_text)
    loaded = segment(audit, 'load')
    loaded = replace_once(loaded, 'def load(', 'def _load_capacity_inputs(')
    loaded = replace_once(loaded, '    market = Path(market)', '    require(type(archives) is CapacityOriginalArchivesV1, "EXACT_CAPACITY_ARCHIVE_CONTEXT_REQUIRED")\n    market = Path(market)')
    loaded = replace_once(loaded, '    panel, grades, eligible, factors, events, sources = daily_prefix(', '    require_factory_head(head, model)\n    panel, grades, eligible, factors, events, sources = daily_prefix(')
    for old, new in (('FrozenCurrentMarketReader(', 'CapacityFrozenMarketReaderV1('), ('FrozenCurrentRiskReader(', 'CapacityFrozenRiskReaderV1('), ('return AuditInputs(', 'return CapacityAuditInputsV1('), ('economics.ECONOMIC_INPUT_PROOF_SHA', 'ECONOMIC_INPUT_PROOF_SHA')):
        loaded = replace_once(loaded, old, new)
    result = segment(audit, 'AuditInputs')
    result = replace_once(result, 'class AuditInputs:', 'class CapacityAuditInputsV1:')
    result = replace_once(result, 'reader: FrozenCurrentMarketReader', 'reader: CapacityFrozenMarketReaderV1')
    entry_text = '''"""UNEXECUTED private capacity input source; public execute always refuses.

This private load prototype is not an admitted capacity entrypoint. It must be
bound to a NEW map transition/finder/generated/phase/native-runtime contract,
all original archive/configuration/economic/calendar/producer admissions and
full before/after byte receipts before any scoped synthetic or genuine call.
It retains a new class identity; original model/source receipts stay distinct.
"""
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from backend.market import direct_daily_arithmetic, forward_arithmetic, holding_risk_bank
from backend.market.capacity_original_archives_v1 import CapacityOriginalArchivesV1
from backend.market.capacity_original_daily_inputs_v1 import daily_prefix
from backend.market.capacity_original_economics_v1 import ECONOMIC_INPUT_PROOF_SHA, economic_paths, reviewed_economics
from backend.market.capacity_original_evidence_v1 import authenticate_file, pinned, require, strict_json
from backend.market.capacity_original_frozen_readers_v1 import CapacityFrozenMarketReaderV1, CapacityFrozenRiskReaderV1
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.live_execution_inputs import DAILY_BASIS, RawExecutionInputs

SCHEMA = 'capacity-original-inputs/1'

''' + constants(audit, ('OBSERVATION_METADATA_SHA256', 'OBSERVATION_ARRAYS_SHA256', 'ORIGINAL_CONFIG_SHA256', 'OVERLAY_SHA256', 'DEPENDENCIES'))
    entry_text += '\n\n# Retain all six original loaded fields under a separate capacity result type.\n' + result
    entry_text += '''

# Reject arbitrary predictor objects without replacing the original numeric factory or copying arrays.
def require_factory_head(head, model):
    require(head is None or type(head) is direct_daily_arithmetic.NumericHead, "EXACT_NUMERIC_FACTORY_HEAD_REQUIRED")
    require((head is not None) == (model["status"] == "fitted"), "NUMERIC_FACTORY_STATUS_REQUIRED")


# Preserve the original readonly transitions after constructing raw execution inputs.
''' + segment(audit, 'readonly') + '\n\n# Retain original load statement order with explicit capacity identities and exact factory path.\n' + loaded
    entry_text += '''

# Refuse public execution until a distinct complete source, phase and runtime contract is admitted.
def execute(*args, **kwargs):
    raise RuntimeError("CAPACITY_MODEL_ENTRY_UNADMITTED")
'''
    modules['inputs'] = module('inputs', entry_text)
    prior_path = DOCS / 'original-loader-admission-source-map-v1-2026-10-18.json'
    prior_raw = prior_path.read_bytes()
    assert digest(prior_raw) == 'a68ebbefb776a93dfdfb56fc6c4893ac35450a224fcf2fa50498cb911bfeda43'
    prior = json.loads(prior_raw)
    proposed = dict(prior['files'])
    assert len(proposed) == 2453
    variant_raw = (DOCS / 'sources/capacity-learned-entry-data-import-cut-v1-2026-10-18.py').read_bytes()
    assert digest(variant_raw) == '21adedb2a11ef8fe9802c4be6c2783b684bfd755db17032ae4bbaf0a2e2a693e'
    target = 'backend/market/learned_entry_data.py'
    assert proposed[target] == PINS[target]
    proposed[target] = digest(variant_raw)
    for record in modules.values():
        assert record['proposed_origin'] not in proposed
        proposed[record['proposed_origin']] = record['sha256']
    assert len(proposed) == 2457
    source_map = {'schema': 'capacity-original-entry-source-declaration/1', 'status': 'UNASSEMBLED_UNEXECUTED_DECLARATION_ONLY', 'prior2453_sha256': digest(prior_raw), 'explicit_legacy_path_transition': {target: {'original_sha256': PINS[target], 'new_sha256': digest(variant_raw), 'scope': 'Only reviewed module import relocation into intraday prepare; old lifecycle binding remains rejecting.'}}, 'new_modules': {record['proposed_origin']: record['sha256'] for record in modules.values()}, 'files': proposed}
    map_record = save(DOCS / 'original-loader-entry-source-map-v1-2026-10-18.json', json_bytes(source_map), metadata=True)
    map_record['path'] = Path(map_record['path']).name
    comparisons = {
        'daily_prefix_statement_body': 'Original inputs prefix before unique shape assignment, explicit six-value return, new function/source identity; no runtime AST/inspect projection.',
        'economic_paths_align_passive_readonly': 'Exact original function ASTs; globals explicitly new evidence/economic helper bindings.',
        'load_passive_inputs': 'Only forecasts.evidence -> _passive_evidence and plain -> _passive_provenance_plain rebindings.',
        'passive_evidence_file_hash': 'Original full helper ASTs apart from declared local function/call names; original leaf-symlink, Path-or-JSON and second-read semantics, no added held-FD claim.',
        'passive_provenance_projection': 'Only original nonfinite-to-None float return replaced by finite refusal then float. Actual prepare_passive._freeze rejects nonfinite input; no generic native/account normalization. Narrower domain requires new positive/refusal parity.',
        'reviewed_economics': 'Only economics.<six constants/functions> qualification removed; explicit original constant assignments and copied load_passive_inputs.',
        'two_risk_initializers': 'Complete original AST bodies/arguments, same super call, distinct new class names/base chain and two returning frames. Neither original policy module imported.',
        'market_initializer': 'Only exact parent identity changes to CapacityFrozenRiskReaderV1; unchanged real ForwardMarketConditionedHoldingReader base/MRO/_bind.',
        'private_load': 'Original load statement order; exact archives type and post-factory head/status checks inserted; only explicit new reader/result/economic identities rebound.',
    }
    selected = {audit: ('load', 'readonly', 'economic_paths', 'align_passive', 'reviewed_economics', 'AuditInputs'), continuation: ('inputs',), economics: ('load_passive_inputs',), historical: ('FrozenCurrentRiskReader.__init__', 'FrozenCurrentMarketReader.__init__'), counterfactual: ('CounterfactualRiskReader.__init__',), 'backend/cli/market_probabilistic_execution.py': ('evidence',), 'backend/cli/market_learned_entry.py': ('sha256',), 'backend/market/live_policy_replay.py': ('plain',), 'backend/market/live_execution_inputs.py': ('prepare_passive', '_freeze')}
    facts = {}
    for path, names in selected.items():
        for name in names:
            value = node(path, name)
            facts[path + ':' + name] = {'AST_sha256': digest(ast.dump(value, include_attributes=False).encode()), 'line': value.lineno, 'end_line': value.end_lineno}
    contract = {
        'schema': 'capacity-original-entry-source-contract/1', 'status': 'SOURCE_PREPARED_ALL_MODULE_AND_FUNCTION_BODIES_UNRUN',
        'starting_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, check=True, text=True).stdout.strip(),
        'modules': modules, 'map_declaration': map_record, 'map_compact_files_sha256': digest(json.dumps(proposed, sort_keys=True, separators=(',', ':')).encode()),
        'original_sources': {path: {'sha256': PINS[path], 'bytes': len(row['raw']), 'origin': row['origin']} for path, row in sorted(CACHE.items())}, 'original_declarations': facts, 'declared_AST_rebindings': comparisons,
        'original_constant_assignments': {'audit': ['OBSERVATION_METADATA_SHA256', 'OBSERVATION_ARRAYS_SHA256', 'ORIGINAL_CONFIG_SHA256', 'OVERLAY_SHA256', 'DEPENDENCIES', 'ECONOMIC_RECEIPT_SHA256'], 'economics': list(economic_constants)},
        'factory_chain': 'Exact unchanged load_publication->_admit->numeric_head produces NumericHead/None; entry accepts exact head type+status only immediately after that call. The type/status helper alone does NOT prove factory provenance or reject a forged exact-type object; full source/fence/call binding remains mandatory.',
        'original_inheritance_and_receipts': 'Keep actual original forward/calibration/calendar files and __file__/protocol/data paths, ForwardVolatility ancestry, original _bind deepcopy, original numeric identity dicts; new Python class/module/result identities explicit, not original-policy instances.',
        'lifetimes': 'Distinct returning base/frozen constructor frames retain original first-feature release before second RHS allocation; both predictions/copies, original bank/head, market deepcopy and raw/panel/archive/receipt/JSON/UTF8 coexistence obligations unchanged. AST source equality is not lifetime/RAM proof.',
        'old_map_and_binding': 'Original2446/old2453 declarations and capacity_binding unchanged, deliberately refuse legacy-path override. New2457 typed16MiB metadata declaration is not a SourceBook/finder/import/physical tree/executed-map/runtime admission.',
        'remaining_source_seams': ['Independent exact source/delta/import-closure review and scope-specific numeric/type/readonly/alias/deepcopy/finite-provenance proposal.', 'New map-transition admission/lifecycle wrapper rather than altering old legacy-source refusal.', 'Complete new finder/native-package/generated/call/phase manifest; full real runtime/source/original archive/producer/calendar/config/economic/preservation/before-after byte receipts.', 'Private _load prototype is not a genuine executor: no owner/caller/stager/bootstrap/packet/launch or admitted model strategy; public execute refuses.'],
        'unadmitted': {'model_import_strategy': None, 'entrypoint': None, 'executed_map': None, 'finder': None, 'phase_manifest': None, 'generated_manifest': None, 'runtime': None, 'launch': None, 'admission': None, 'execution_authorized': False},
        'not_run': ['payload import/CodeType compile/body', 'numerical/model/array/load/fit/predict', 'tests or old completed gate/body replay', 'SSH/hostprobe/Docker/jobs', 'original/account/market data reads'],
        'unchanged': {'original_source_maps_and_data': True, 'production': True, 'G08_guard_caps': True, 'original_timing': 'FAILED', 'publication': 'CLOSED', 'v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'genuine_loader_model_RAM_history_ordinary_intraday_fill_UI': 'UNVERIFIED', 'heartbeat': 'ACTIVE'},
    }
    contract_record = save(DOCS / 'original-loader-entry-source-contract-v1-2026-10-18.json', json_bytes(contract))
    save(ROOT / 'contract-pointer.json', json_bytes(contract_record))
    print(json.dumps({'modules': modules, 'contract': contract_record, 'map': map_record, 'original_sources': len(CACHE), 'original_declarations': len(facts), 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
