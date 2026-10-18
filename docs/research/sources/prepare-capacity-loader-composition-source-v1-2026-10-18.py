"""Prepare inert source composition and finite declarations; never import payloads."""

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
from textwrap import dedent
import subprocess

REPO = Path('/Users/animallya/.codex/worktrees/learned-live-release-20261006/PersonalAssistant')
DOCS = REPO / 'docs/research'
ROOT = Path('/tmp/capacity-loader-composition-source-20261018-v1')


# Identify exact source and finite metadata without interpreting application objects.
def digest(raw):
    return sha256(raw).hexdigest()


# Persist only new bounded artifacts and check complete readback after fsync.
def save(path, raw, *, metadata=False):
    assert len(raw) <= (16 * 1048576 if metadata else 262144)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    assert path.read_bytes() == raw
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


# Encode only finite source declarations under an explicitly typed metadata bound.
def encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'


# Read a hash-bound source or declaration without importing its application code.
def pinned(path, expected):
    raw = Path(path).read_bytes()
    assert digest(raw) == expected, str(path)
    return raw


# Select complete method source text and keep its separate constructor frame intact.
def method(raw, name):
    tree = ast.parse(raw)
    cls = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == 'CapacityArchiveLeaseV1')
    value = next(item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == name)
    return dedent(''.join(raw.decode().splitlines(keepends=True)[value.lineno - 1:value.end_lineno]))


# Apply only one exact source change rather than silently accepting a missing anchor.
def changed(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


# Preserve new source as inert bytes and record its proposed actual executor path.
def module(filename, proposed, raw):
    tree = ast.parse(raw)
    lines = raw.decode().splitlines()
    functions = [item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef)]
    assert all(lines[min([item.lineno] + [value.lineno for value in item.decorator_list]) - 2].lstrip().startswith('#') for item in functions)
    path = DOCS / 'sources' / filename
    if path.exists():
        assert path.read_bytes() == raw
        record = {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}
    else:
        record = save(path, raw)
    save(ROOT / filename, raw)
    return {**record, 'path': str(path.relative_to(DOCS)), 'proposed_origin': proposed, 'functions': len(functions), 'bodies_run': False}


# Assemble a distinct source lease without invoking its admissions or any numerical body.
def main():
    ROOT.mkdir(exist_ok=False)
    old = pinned(DOCS / 'sources/original-loader-capacity-admission-lifecycle-v1-2026-10-18.py', '3acd8b296b3d14234d7c769e2ce4c5a63c8e381d87d7677476964ea1a5f84b1b')
    old_admissions = pinned(DOCS / 'sources/original-loader-capacity-admissions-v1-2026-10-18.py', 'f7a226b3d90472ac3ebe161e4c46beb2c49245d489ac1de4a78f90ee2af6d0a9')
    binding_path = DOCS / 'sources/original-loader-capacity-loader-binding-v1-2026-10-18.py'
    binding_raw = binding_path.read_bytes()
    bindings = module(binding_path.name, 'backend/market/capacity_original_loader_binding_v1.py', binding_raw)
    constructor = method(old, '__init__')
    constructor = changed(constructor, "reader = archives_module.CapacitySourceReaderV1(self.binding['source_root'], native)", "reader = archives_module.CapacitySourceReaderV1(self.binding['reference_root'], native)")
    constructor = changed(constructor, 'self.legacy_source = admissions.source_admission(self.value, self.archives)', "self.legacy_source = source_admission(self.value, self.archives, self.binding['reference_root'])")
    constructor = changed(constructor, "self.calendar = admissions.calendar_admission(self.archives, self.value['profile'])", "self.calendar = calendar_admission(self.archives, self.value['profile'], self.binding['source_root'])")
    constructor = changed(constructor, "self.loaded = self.after = self.serialized = self.encoded = None", "self.loaded = self.after = self.serialized = self.encoded = self.loaded_binding = None")
    serialize = changed(method(old, 'serialize'), "'input_bytes': self.before", "'loader_type_binding': self.loaded_binding, 'input_bytes': self.before")
    release = changed(method(old, 'release'), 'self.encoded = self.archives = None', 'self.encoded = self.archives = self.loaded_binding = None')
    text = '''"""UNEXECUTED constructor-only loader composition; public execute refuses.

The new binding owns distinct executor/reference roots. Original2431 producer
receipts, full original archive preservation, both complete byte-auth graphs,
loaded context and complete JSON/UTF8 remain live through durable persistence.
No external caller-supplied result retention method or admitted executor exists.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from datetime import UTC, datetime

from backend.market import capacity_original_admissions_v1 as admissions
from backend.market import capacity_original_archives_v1 as archives_module
from backend.market import capacity_original_evidence_v1 as evidence
from backend.market import live_model_history_input_auth as byte_auth
from backend.market.capacity_original_admission_lifecycle_v1 import MAX_RESULT_BYTES, sync_directory
from backend.market.capacity_original_loader_binding_v1 import capacity_binding, root_admission, module_admission, source_admission, calendar_admission, module_origin

SCHEMA = 'capacity-original-loader-lease/1'


# Retain all original admission/serialization roots around exactly one private loader call.
class CapacityLoaderLeaseV1:
'''
    declarations = [
        ('Retain every original admission while binding archives to the separate reference root.', constructor),
        ('Retain the unchanged complete two-pass byte-authentication graph.', method(old, '_bytes')),
    ]
    load = '''def _load_inputs(self):
    evidence.require(self.phase == 'BEFORE', 'EXACT_PRIVATE_LOAD_PHASE_REQUIRED')
    self.phase = 'LOAD'
    from backend.market import capacity_original_inputs_v1 as inputs_module
    from backend.market import forward_arithmetic
    from backend.market.capacity_original_frozen_readers_v1 import CapacityFrozenMarketReaderV1, CapacityFrozenRiskReaderV1
    origins = []
    for name in ('capacity_original_inputs_v1', 'capacity_original_daily_inputs_v1', 'capacity_original_economics_v1', 'capacity_original_frozen_readers_v1', 'forward_arithmetic', 'holding_risk_bank', 'direct_daily_arithmetic', 'learned_retention_models', 'market_conditioned_holding', 'conditional_holding_calibration', 'calendar', 'live_execution_inputs'):
        origins.append(module_origin(self.binding, self.source_map, sys.modules.get('backend.market.' + name)))
    self.observed_at = datetime.now(UTC)
    self.loaded = inputs_module._load_capacity_inputs(self.archives, self.value['market'], observed_at=self.observed_at)
    evidence.require(type(self.loaded) is inputs_module.CapacityAuditInputsV1 and type(self.loaded.raw) is inputs_module.RawExecutionInputs and type(self.loaded.reader) is CapacityFrozenMarketReaderV1 and type(self.loaded.reader._parent) is CapacityFrozenRiskReaderV1 and type(self.loaded.reader._parent.current) is forward_arithmetic.CloseObservation and isinstance(self.loaded.reader._parent, forward_arithmetic.ForwardVolatilityHoldingReader), 'EXACT_NEW_CAPACITY_RESULT_LINEAGE_REQUIRED')
    self.loaded_binding = {'result_type': 'capacity_original_inputs_v1.CapacityAuditInputsV1', 'raw_type': 'live_execution_inputs.RawExecutionInputs', 'reader_type': 'capacity_original_frozen_readers_v1.CapacityFrozenMarketReaderV1', 'parent_type': 'capacity_original_frozen_readers_v1.CapacityFrozenRiskReaderV1', 'module_origins': origins, 'numeric_parity_RAM_or_policy_acceptance': False}
    self.phase = 'FROZEN_UNVERIFIED_LOADER_OBJECT'
'''
    declarations += [
        ('Call only the exact new private input factory and retain its typed result; never adopt a supplied object.', load),
        ('Recheck both full source trees and every original archive/input graph with the result retained.', method(old, 'verify_after')),
        ('Retain full JSON/UTF8 and type-binding metadata with both graphs and loaded context.', serialize),
        ('Fsync exclusive candidate bytes, destination then parent using unchanged durability order.', method(old, 'persist')),
        ('Release only this lease RAM after durable candidate bytes; retain every evidence file.', release),
    ]
    for purpose, declaration in declarations:
        text += '    # ' + purpose + '\n' + '\n'.join('    ' + line if line else '' for line in declaration.splitlines()) + '\n\n'
    text += '''
# Refuse public execution until a complete new finder/fence/phase/native/runtime owner is admitted.
def execute(*args, **kwargs):
    raise RuntimeError('SOURCE_ONLY_NO_ADMITTED_LOADER_COMPOSITION_EXECUTOR')
'''
    lifecycle = module('original-loader-capacity-loader-lifecycle-v1-2026-10-18.py', 'backend/market/capacity_original_loader_lifecycle_v1.py', text.encode())
    entry_raw = pinned(DOCS / 'original-loader-entry-source-map-v1-2026-10-18.json', 'aaa1ad0622f18f35e8f639d4a7a9e78e21d8681e19860c7a7284b0876b043f9c')
    entry = json.loads(entry_raw)
    compositions = {row['proposed_origin']: row['sha256'] for row in (bindings, lifecycle)}
    assert len(entry['files']) == 2457 and not set(compositions) & set(entry['files'])
    source_map = {'schema': 'capacity-original-loader-source-declaration/1', 'entry2457_sha256': digest(entry_raw), 'compositions': compositions, 'files': {**entry['files'], **compositions}}
    assert len(source_map['files']) == 2459
    map_record = save(DOCS / 'original-loader-composition-source-map-v1-2026-10-18.json', encoded(source_map), metadata=True)
    map_record['path'] = Path(map_record['path']).name
    contract = {
        'schema': 'capacity-original-loader-composition-source-contract/1', 'status': 'SOURCE_PREPARED_ALL_NEW_BODIES_UNRUN',
        'starting_revision': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, check=True, text=True).stdout.strip(),
        'modules': {'binding': bindings, 'lifecycle': lifecycle}, 'source_map_declaration': map_record,
        'old_sources': {'lifecycle': {'sha256': digest(old), 'bytes': len(old)}, 'admissions': {'sha256': digest(old_admissions), 'bytes': len(old_admissions)}},
        'map_chain': 'Exact raw9a0 old2446 +a68 old2453 +aaa1 entry2457. Only reviewed original4b0555->variant21adedb2 substitution, four entry additions and two new composition modules. Old maps/binding untouched; new2459 declaration is not an assembled/executed-map/finder or runtime admission.',
        'root_namespaces': ['Executor exact import root/new2459 map/ownROhostbind/externaldecimalrootidentity.', 'Reference audit exactold2446 tree/ownROhostbind/externaldecimalrootidentity; archives source_reader/source_root remain here; no root proxy/global/sys.modules trick.', 'Original2431 producer/account/market/source aliases and complete byte receipts unchanged.'],
        'root_controls': 'Distinct canonical root+host paths; exactRO root binds; no descendant mount overrides/proof path overlap; direct/ancestor sys.path reference overlap refused. Held rootFDs only during each both-map hash pass, per-file opens still path based; not hostile-code or full finder isolation.',
        'admission_changes': 'Old source_admission body changes only explicit reference-root parameter/rebinding and exact archives.source_root guard. Calendar imports real original calendar from executor, preserves all old full-profile checks, additionally hashes source and all3data in executor and reference. Old source/producer/runtime/native/config/economic/preservation/fullcompletion/fullphysical/before+after byte checks retained.',
        'lease_changes': 'New independent class copies old constructor/_bytes/verify_after/serialize/persist/release with declared root/admission/source bindings; removes arbitrary retain_loaded API, adds private single-call exact new factory/type lineage/module-file origin path. Private load obtains datetime.now(UTC) immediately before the actual factory call; no caller-supplied fake or historical clock. loaded+archive+both fullgraphs+JSON+UTF8 retained through exclusive fsync/readback/destinationthenparent sync/release.',
        'typed_result_limitations': 'Exact Python classes/file hashes and12module origins are not numerical/type/alias/deepcopy/readonly/model lineage/RAM acceptance; no live CodeType/global/finder/native closure claimed. Immediate new input factory still relies on unchanged publication/config/numeric factory checks. Inherited strategy/fit methods remain unadmitted.',
        'serialization': {'MAX_RESULT_BYTES': 268435456, 'unchanged_bound': True, 'candidate_status_not_acceptance': True, 'late_combined_peak_actual_measurement': None, 'persist_crash_IO_timeout_acceptance': False},
        'unadmitted': {'wrapper': None, 'model_import_strategy': None, 'entrypoint': None, 'executed_map': None, 'finder': None, 'phase_manifest': None, 'generated_manifest': None, 'native_package_closure': None, 'owner': None, 'caller': None, 'bootstrap': None, 'packet': None, 'runtime': None, 'launch': None, 'admission': None, 'execution_authorized': False},
        'next': 'Independently review exact new binding/class AST/root/map/type/lifetime deltas. SOURCE ONLY complete new finder/guard-contract/model-factory/call+generated+phase/native closure and namespace schema, plus separate source parity/refusal/lifetime obligations, before any new synthetic or genuine runtime proposal. Do not execute any payload or regenerate old gates/packets.',
        'unchanged': {'old_guards_G08_caps': True, 'old_failed_completed_roots': True, 'production_and_original_source_data': True, 'original_timing': 'FAILED', 'publication': 'CLOSED', 'v6': 'OPEN_PAUSED_NO_REPLAY_ADOPTION_NEW_RUN', 'genuine_loader_model_RAM_history_ordinary_intraday_fill_UI': 'UNVERIFIED', 'heartbeat': 'ACTIVE'},
    }
    contract_record = save(DOCS / 'original-loader-composition-source-contract-v1-2026-10-18.json', encoded(contract))
    save(ROOT / 'contract-pointer.json', encoded(contract_record))
    print(json.dumps({'modules': contract['modules'], 'map': map_record, 'contract': contract_record, 'payload_bodies_run': False}, sort_keys=True))


if __name__ == '__main__':
    main()
