"""UNEXECUTED capacity bindings/lifetime proposal; no admitted loader or genuine entry point.

Direct imports and every call still require a future source-pinned pre-import
fence, complete phase manifests and actual host/runtime admission. A reserved
failure FD and a file map do not prove that fence exists. This new owner never
calls a model loader and cannot certify a caller-supplied object's model/type.
"""
import hashlib
import json
import os
import stat
from pathlib import Path

from backend.market import capacity_original_admissions_v1 as admissions
from backend.market import capacity_original_archives_v1 as archives_module
from backend.market import capacity_original_evidence_v1 as evidence
from backend.market import live_model_history_input_auth as byte_auth

SCHEMA = 'capacity-original-admission-binding/1'
BASE_MAP = '503e8d508ebe5fdc82a17c11974ccce5366c60ce8e78fc549c129fc6c6d81e03'
MAX_RESULT_BYTES = 256 * 1024**2
NEW_MODULE_PATHS = {
    'backend/__init__.py', 'backend/market/__init__.py',
    'backend/market/original_history_json.py',
    'backend/market/live_model_history_input_auth.py',
    'backend/market/capacity_original_metadata_v1.py',
    'backend/market/capacity_original_evidence_v1.py',
    'backend/market/capacity_original_archive_adaptations_v1.py',
    'backend/market/capacity_original_archives_v1.py',
    'backend/market/capacity_original_calendar_v1.py',
    'backend/market/capacity_original_admissions_v1.py',
    'backend/market/capacity_original_admission_lifecycle_v1.py',
}


# Hash only canonical finite file-map declarations, separately from runtime call manifests.
def map_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


# Read a distinct capacity wrapper without reinterpreting the original schema2 invocation.
def capacity_binding(path, expected):
    binding = evidence.strict_json(evidence.pinned(path, expected))
    fields = {'schema', 'original_invocation', 'original_invocation_sha256', 'source_root', 'source_host_root', 'source_map', 'source_map_sha256', 'native31', 'native31_sha256'}
    evidence.require(type(binding) is dict and set(binding) == fields and binding['schema'] == SCHEMA, 'EXACT_CAPACITY_BINDING_REQUIRED')
    for name in ('original_invocation', 'source_root', 'source_host_root', 'source_map', 'native31'):
        byte_auth.canonical(binding[name], absolute=True)
    for name in ('original_invocation_sha256', 'source_map_sha256', 'native31_sha256'):
        byte_auth.digest_value(binding[name])
    value = admissions.invocation(binding['original_invocation'], binding['original_invocation_sha256'])
    evidence.require(value['profile'] == 'original-full-27471', 'ORIGINAL_FULL_CAPACITY_PROFILE_REQUIRED')
    root = Path(binding['source_root'])
    evidence.require(root == Path(__file__).resolve().parents[2], 'ACTUAL_CAPACITY_IMPORT_ROOT_REQUIRED')
    source_map = evidence.strict_json(evidence.pinned(binding['source_map'], binding['source_map_sha256']))
    evidence.require(type(source_map) is dict and set(source_map) == {'schema', 'base', 'modules', 'files'} and source_map['schema'] == 'capacity-original-source-map/1', 'EXACT_NEW_CAPACITY_SOURCE_MAP_REQUIRED')
    base, modules, files = source_map['base'], source_map['modules'], source_map['files']
    evidence.require(type(base) is dict and len(base) == 2446 and map_digest(base) == BASE_MAP, 'UNCHANGED_LEGACY2446_MAP_REQUIRED')
    evidence.require(type(modules) is dict and set(modules) == NEW_MODULE_PATHS and type(files) is dict, 'EXACT_CAPACITY_MODULE_SET_REQUIRED')
    for name, digest in modules.items():
        byte_auth.canonical(name, absolute=False)
        byte_auth.digest_value(digest)
        evidence.require(name not in base or base[name] == digest, 'LEGACY_SOURCE_OVERRIDE_FORBIDDEN')
    evidence.require(files == {**base, **modules}, 'EXACT_CAPACITY_MAP_UNION_REQUIRED')
    native = evidence.strict_json(evidence.pinned(binding['native31'], binding['native31_sha256']))
    return binding, value, source_map, native


# Bind the new import root to its externally pinned actual read-only host source mapping.
def root_admission(binding, value):
    row = evidence.strict_json(evidence.pinned(value['runtime'], value['runtime_sha256']))[0]
    mounts = row['Mounts']
    evidence.require(len(mounts) == len({item['Destination'] for item in mounts}), 'UNIQUE_RUNTIME_MOUNT_DESTINATIONS_REQUIRED')
    root = Path(binding['source_root'])
    covering = [item for item in mounts if root == Path(item['Destination']) or Path(item['Destination']) in root.parents]
    evidence.require(bool(covering), 'CAPACITY_ROOT_BIND_REQUIRED')
    chosen = max(covering, key=lambda item: len(Path(item['Destination']).parts))
    evidence.require(chosen['Type'] == 'bind' and chosen['RW'] is False and Path(chosen['Source']) / root.relative_to(chosen['Destination']) == Path(binding['source_host_root']), 'EXACT_READONLY_CAPACITY_HOST_ROOT_REQUIRED')
    return {'source_root': str(root), 'source_host_root': binding['source_host_root'], 'runtime_sha256': value['runtime_sha256'], 'held_root_FD_isolation': False}


# Authenticate every declared new-tree byte separately from the legacy audit-source receipt.
def module_admission(binding, source_map):
    root = Path(binding['source_root'])
    for name, expected in source_map['files'].items():
        byte_auth.canonical(name, absolute=False)
        evidence.authenticate_file(root / name, expected)
    return {'source_map_sha256': binding['source_map_sha256'], 'files': len(source_map['files']), 'base_files': 2446, 'module_files': len(source_map['modules']), 'call_manifest_or_runtime_acceptance': False}


# Sync one exact named directory while its held descriptor and path identities agree.
def sync_directory(path, expected):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid')
        actual = tuple(getattr(before, key) for key in keys)
        evidence.require(stat.S_ISDIR(before.st_mode) and actual == expected and all(getattr(before, key) == getattr(path.stat(follow_symlinks=False), key) for key in keys), 'OWNED_DURABILITY_DIRECTORY_CHANGED')
        os.fsync(descriptor)
        evidence.require(all(getattr(before, key) == getattr(os.fstat(descriptor), key) == getattr(path.stat(follow_symlinks=False), key) for key in keys), 'OWNED_DURABILITY_DIRECTORY_CHANGED')
    finally:
        os.close(descriptor)


# Retain all graphs and source-bound archives until complete candidate bytes are durable.
class CapacityArchiveLeaseV1:
    # Perform ordered metadata/source/calendar/preservation/byte admission without loading a model.
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
        reader = archives_module.CapacitySourceReaderV1(self.binding['source_root'], native)
        self.archives = archives_module.CapacityOriginalArchivesV1(self.value['account'], self.value['completion_sha256'], self.value['initial_sha256'], self.value['manifest'], self.value['manifest_sha256'], source_reader=reader, scratch=self.destination / 'archive-spools', external_inputs=True)
        self.legacy_source = admissions.source_admission(self.value, self.archives)
        self.producer = admissions.producer_admission(self.value)
        self.calendar = admissions.calendar_admission(self.archives, self.value['profile'])
        self.preserved = archives_module.preserved_archives(self.archives, self.value['physical_sha256'], self.value['physical_bytes'])
        self.pins = byte_auth.Pins(self.value['profile'], self.value['completion_sha256'], self.value['manifest_sha256'], self.value['execution_sha256'])
        self.before = self._bytes('input-auth-before')
        self.loaded = self.after = self.serialized = self.encoded = None
        self.phase = 'BEFORE'

    # Keep the unchanged complete two-pass byte-authentication receipt graph alive.
    def _bytes(self, name):
        return byte_auth.authenticate(Path(self.value['account']) / 'completion.json', self.value['manifest'], self.value['execution'], self.pins, external_inputs=True, scratch=self.destination / name)

    # Retain a future separately admitted loader result without certifying its type or model.
    def retain_loaded(self, loaded):
        evidence.require(self.phase == 'BEFORE' and loaded is not None, 'EXACT_LOADED_RETENTION_PHASE_REQUIRED')
        self.loaded = loaded
        self.phase = 'FROZEN_UNVERIFIED_LOADER_OBJECT'

    # Recheck complete inputs, archives and source while every prior graph remains retained.
    def verify_after(self):
        evidence.require(self.phase == 'FROZEN_UNVERIFIED_LOADER_OBJECT', 'AFTER_PHASE_ORDER_REQUIRED')
        self.after = self._bytes('input-auth-after')
        evidence.require(self.before == self.after, 'COMPLETE_BYTE_RECEIPTS_CHANGED')
        evidence.require(archives_module.preserved_archives(self.archives, self.value['physical_sha256'], self.value['physical_bytes']) == self.preserved, 'ORIGINAL_STATE_CHANGED')
        self.archives.unchanged()
        module_admission(self.binding, self.source_map)
        self.phase = 'AFTER'

    # Allocate complete JSON and UTF8 with both receipt graphs and the loaded object retained.
    def serialize(self):
        evidence.require(self.phase == 'AFTER' and self.before == self.after and self.loaded is not None and self.archives is not None, 'COEXISTENCE_ROOTS_REQUIRED')
        result = {'status': 'CAPACITY_ARCHIVE_CANDIDATE_REQUIRES_INDEPENDENT_ACCEPTANCE', 'runtime': self.runtime, 'root': self.root, 'legacy_source': self.legacy_source, 'new_source': self.modules, 'packages': self.packages, 'producer': self.producer, 'calendar': self.calendar, 'input_bytes': self.before, 'publication': 'CLOSED', 'historical_publication_authorized': False, 'genuine_model_type_or_RAM_acceptance': False}
        self.serialized = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
        self.encoded = self.serialized.encode('utf-8')
        evidence.require(len(self.encoded) <= MAX_RESULT_BYTES, 'CAPACITY_RESULT_BOUND_EXCEEDED')
        self.phase = 'ENCODED'
        return self.encoded

    # Persist exact candidate bytes without replacing an old result or deleting any scratch.
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

    # Drop only this lease's RAM references after durable bytes, retaining all evidence files.
    def release(self):
        evidence.require(self.phase == 'DURABLE_CANDIDATE_NOT_ACCEPTANCE', 'RELEASE_BEFORE_DURABILITY_FORBIDDEN')
        self.loaded = self.before = self.after = self.serialized = self.encoded = self.archives = None
        self.phase = 'RELEASED_REFERENCES_ONLY_FILES_RETAINED'


# Refuse a standalone run until a distinct complete source/fence/runtime owner is reviewed.
def execute(*args, **kwargs):
    raise RuntimeError('SOURCE_ONLY_NO_GENUINE_EXECUTOR_OR_MODEL_STRATEGY')


if __name__ == '__main__':
    execute()
