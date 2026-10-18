"""UNEXECUTED constructor-only loader composition; public execute refuses.

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
    # Retain every original admission while binding archives to the separate reference root.
    def __init__(self, wrapper_path, wrapper_sha256, guard_fd):
        self.phase = 'ADMISSION'
        self.binding, self.value, self.source_map, native = capacity_binding(wrapper_path, wrapper_sha256)
        self.runtime = admissions.runtime_admission(self.value)
        self.root = root_admission(self.binding, self.value)
        self.modules = module_admission(self.binding, self.source_map)
        self.packages = admissions.native_packages()
        parent = byte_auth.physical(self.value['proof_parent'])
        evidence.require(parent.is_dir() and parent.stat().st_uid == 1000 and {p.name for p in parent.iterdir()} == {'guard-failure.bin'}, 'OWNED_PROOF_ROOT_RESERVED_SLOT_ONLY_REQUIRED')
        self.proof_parent = parent
        self.parent_identity = tuple(getattr(parent.stat(follow_symlinks=False), key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid'))
        evidence.require(type(guard_fd) is int and guard_fd >= 0, 'OWNED_GUARD_FD_REQUIRED')
        actual, named = os.fstat(guard_fd), (parent / 'guard-failure.bin').stat(follow_symlinks=False)
        keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_blocks', 'st_mtime_ns', 'st_ctime_ns')
        evidence.require(stat.S_ISREG(actual.st_mode) and actual.st_uid == 1000 and actual.st_nlink == 1 and actual.st_size == 65536 and actual.st_blocks == 128 and all(getattr(actual, key) == getattr(named, key) for key in keys), 'EXACT_RESERVED_GUARD_SLOT_REQUIRED')
        self.destination = parent / 'capacity-archive-context'
        self.destination.mkdir(mode=0o700, exist_ok=False)
        self.destination_identity = tuple(getattr(self.destination.stat(follow_symlinks=False), key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid'))
        evidence.require((Path(self.value['account']) / 'completion.json').stat().st_size == admissions.FULL_COMPLETION_BYTES, 'EXACT_ORIGINAL_FULL_COMPLETION_SIZE_REQUIRED')
        reader = archives_module.CapacitySourceReaderV1(self.binding['reference_root'], native)
        self.archives = archives_module.CapacityOriginalArchivesV1(self.value['account'], self.value['completion_sha256'], self.value['initial_sha256'], self.value['manifest'], self.value['manifest_sha256'], source_reader=reader, scratch=self.destination / 'archive-spools', external_inputs=True)
        self.legacy_source = source_admission(self.value, self.archives, self.binding['reference_root'])
        self.producer = admissions.producer_admission(self.value)
        self.calendar = calendar_admission(self.archives, self.value['profile'], self.binding['source_root'])
        self.preserved = archives_module.preserved_archives(self.archives, self.value['physical_sha256'], self.value['physical_bytes'])
        self.pins = byte_auth.Pins(self.value['profile'], self.value['completion_sha256'], self.value['manifest_sha256'], self.value['execution_sha256'])
        self.before = self._bytes('input-auth-before')
        self.loaded = self.after = self.serialized = self.encoded = self.loaded_binding = None
        self.phase = 'BEFORE'

    # Retain the unchanged complete two-pass byte-authentication graph.
    def _bytes(self, name):
        return byte_auth.authenticate(Path(self.value['account']) / 'completion.json', self.value['manifest'], self.value['execution'], self.pins, external_inputs=True, scratch=self.destination / name)

    # Call only the exact new private input factory and retain its typed result; never adopt a supplied object.
    def _load_inputs(self):
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

    # Recheck both full source trees and every original archive/input graph with the result retained.
    def verify_after(self):
        evidence.require(self.phase == 'FROZEN_UNVERIFIED_LOADER_OBJECT', 'AFTER_PHASE_ORDER_REQUIRED')
        self.after = self._bytes('input-auth-after')
        evidence.require(self.before == self.after, 'COMPLETE_BYTE_RECEIPTS_CHANGED')
        evidence.require(archives_module.preserved_archives(self.archives, self.value['physical_sha256'], self.value['physical_bytes']) == self.preserved, 'ORIGINAL_STATE_CHANGED')
        self.archives.unchanged()
        module_admission(self.binding, self.source_map)
        self.phase = 'AFTER'

    # Retain full JSON/UTF8 and type-binding metadata with both graphs and loaded context.
    def serialize(self):
        evidence.require(self.phase == 'AFTER' and self.before == self.after and self.loaded is not None and self.archives is not None, 'COEXISTENCE_ROOTS_REQUIRED')
        result = {'status': 'CAPACITY_ARCHIVE_CANDIDATE_REQUIRES_INDEPENDENT_ACCEPTANCE', 'runtime': self.runtime, 'root': self.root, 'legacy_source': self.legacy_source, 'new_source': self.modules, 'packages': self.packages, 'producer': self.producer, 'calendar': self.calendar, 'loader_type_binding': self.loaded_binding, 'input_bytes': self.before, 'publication': 'CLOSED', 'historical_publication_authorized': False, 'genuine_model_type_or_RAM_acceptance': False}
        self.serialized = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
        self.encoded = self.serialized.encode('utf-8')
        evidence.require(len(self.encoded) <= MAX_RESULT_BYTES, 'CAPACITY_RESULT_BOUND_EXCEEDED')
        self.phase = 'ENCODED'
        return self.encoded

    # Fsync exclusive candidate bytes, destination then parent using unchanged durability order.
    def persist(self):
        evidence.require(self.phase == 'ENCODED' and self.encoded is not None, 'DURABLE_CANDIDATE_PHASE_REQUIRED')
        path = self.destination / 'candidate.json'
        with path.open('xb') as output:
            output.write(self.encoded)
            output.flush()
            os.fsync(output.fileno())
        expected = hashlib.sha256(self.encoded).hexdigest()
        evidence.authenticate_file(path, expected)
        sync_directory(self.destination, self.destination_identity)
        sync_directory(self.proof_parent, self.parent_identity)
        self.phase = 'DURABLE_CANDIDATE_NOT_ACCEPTANCE'
        return {'path': str(path), 'sha256': expected, 'bytes': len(self.encoded), 'publication': 'CLOSED'}

    # Release only this lease RAM after durable candidate bytes; retain every evidence file.
    def release(self):
        evidence.require(self.phase == 'DURABLE_CANDIDATE_NOT_ACCEPTANCE', 'RELEASE_BEFORE_DURABILITY_FORBIDDEN')
        self.loaded = self.before = self.after = self.serialized = self.encoded = self.archives = self.loaded_binding = None
        self.phase = 'RELEASED_REFERENCES_ONLY_FILES_RETAINED'


# Refuse public execution until a complete new finder/fence/phase/native/runtime owner is admitted.
def execute(*args, **kwargs):
    raise RuntimeError('SOURCE_ONLY_NO_ADMITTED_LOADER_COMPOSITION_EXECUTOR')
