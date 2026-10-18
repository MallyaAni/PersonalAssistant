# SOURCE ONLY: separately versioned capacity data interface; all bodies UNRUN.
# This is a new module/type identity, not the original verified reader or receipt.
"""UNEXECUTED source proposal for an explicitly new capacity archive context.

This is neither OriginalArchives nor a full audit entry point. A new executed-map,
invocation/runtime/source/producer/calendar/configuration/preservation admission
and lifecycle contract must precede any genuine use. No sessions/StreamAudit route
or model loader is provided. The parser and physical logical comparison retain
their separately pinned original semantics; no general nonfinite coercion exists.
"""
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from backend.market import capacity_original_archive_adaptations_v2 as adaptations
from backend.market import capacity_original_evidence_v1 as evidence
from backend.market import capacity_original_metadata_v1 as metadata
from backend.market import capacity_original_input_auth_v1 as byte_auth
from backend.market import capacity_original_history_json_v1 as streamed

SCHEMA = 'capacity-original-archive-context/2'
SOURCE_PATHS = (
    'backend/market/live_model_history.py',
    'backend/market/live_policy_replay.py',
    'backend/cli/market_strategy_continue.py',
    'backend/market/replay_broker.py',
    'backend/market/direct_daily_arithmetic.py',
    'backend/market/learned_retention_models.py',
)
ORIGINAL_SOURCES = {
    'backend/market/live_probability_timing.py': '3fc9da7ae628e3fdd98388bbaa0e08bbaf5b8c36da78fb7c0e0efdcab63c1721',
    'backend/cli/market_strategy_continue.py': '14357ed7b87618ee514dd3cd4e4a71e2c27290875c3df257e692773e524cfaaf',
    'backend/agents/trading/desk/intraday_orders.py': 'ca8c236746441e204f36a263e972104d48d442538ea189fd4cad9d4ccf9f0f1c',
    'backend/market/live_policy_replay.py': 'b6ef95f0c5eaa53bd732f0ee5baa55f21ef875d07c69e5abbbb236aafd0586e9',
    'backend/market/entry_timing.py': 'f23d286c0d613d99620ce4a4ea8aa889be88ca224c5fbfc945b4360eae944a88',
}
CATALOG_PATHS = (
    'docs/research/trading-source-approval-review-2026-10-17.json',
    'docs/research/trading-numeric-source-review-2026-10-17.json',
    'docs/research/settlement-metadata-source-review-2026-10-17.json',
)


# Bind exact N2 bytes at real paths without importing any N2 account or policy module.
@dataclass(frozen=True, slots=True)
class CapacitySourceReaderV2:
    root: Path
    pins: dict

    # Authenticate the complete native31 map before exposing this new reader identity.
    def __init__(self, root, pins):
        root = Path(root)
        byte_auth.canonical(str(root), absolute=True)
        evidence.require(root.is_dir(), 'CAPACITY_SOURCE_ROOT_REQUIRED')
        evidence.require(type(pins) is dict, 'EXACT_NATIVE_SOURCE_DICT_REQUIRED')
        object.__setattr__(self, 'root', root)
        object.__setattr__(self, 'pins', evidence._freeze(pins))
        self.authenticate_native()

    # Read only a canonical native-map member using its exact pinned byte identity.
    def read(self, name):
        evidence.require(type(name) is str, 'EXACT_SOURCE_PATH_REQUIRED')
        path = PurePosixPath(name)
        evidence.require(not path.is_absolute() and str(path) == name and name not in ('', '.') and '..' not in path.parts, 'CANONICAL_RELATIVE_NATIVE_SOURCE_REQUIRED')
        evidence.require(name in self.pins, 'NATIVE_SOURCE_MEMBER_REQUIRED')
        return evidence.pinned(self.root / name, self.pins[name])

    # Rehash all31 actual sources through this exact new reader's bound method.
    def authenticate_native(self):
        evidence.require(type(self) is CapacitySourceReaderV2, 'EXACT_CAPACITY_SOURCE_READER_REQUIRED')
        return metadata.native_source_identity(dict(self.pins), self.read)

    # Derive schema and path components from the actual hash-pinned inert paper source.
    def paper_descriptor(self):
        return metadata.paper_descriptor(self.read('backend/agents/trading/desk/paper.py'))


# Retain only the authenticated archive interface needed before a capacity loader returns.
@dataclass(frozen=True, slots=True)
class CapacityOriginalArchivesV2:
    root: Path
    completion_raw: bytes | None
    completion_sha256: str
    completion: dict
    initial_sha256: str
    manifest_path: Path
    manifest_sha256: str
    sources: dict
    ending_state: str
    source_root: Path
    source_reader: CapacitySourceReaderV2
    _consumed_inputs: dict
    unused_inputs: int
    scratch: Path

    # Read the full original completion with explicit owned scratch and sealed map lifetime.
    def __init__(self, root, completion_sha256, initial_sha256, manifest, manifest_sha256, *, source_reader, scratch, external_inputs):
        evidence.require(type(source_reader) is CapacitySourceReaderV2, 'EXACT_CAPACITY_SOURCE_READER_REQUIRED')
        source_reader.authenticate_native()
        evidence.require(type(external_inputs) is bool, 'EXACT_EXTERNAL_INPUT_MODE_REQUIRED')
        root, scratch = Path(root), Path(scratch)
        byte_auth.canonical(str(root), absolute=True)
        byte_auth.canonical(str(scratch), absolute=True)
        scratch.mkdir(mode=0o700, parents=True, exist_ok=False)
        completion = streamed.read(root / 'completion.json', completion_sha256, directory=scratch, external_inputs=external_inputs)
        evidence.require(completion['status'] == 'COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT', 'Genuine completed original account required')
        ending = completion.pop('paper_state')
        try:
            ending_state = adaptations.logical_digest(ending)
        finally:
            streamed.release(ending)
        values = {
            'root': root, 'completion_raw': None,
            'completion_sha256': completion_sha256,
            'completion': evidence._freeze(completion),
            'initial_sha256': initial_sha256,
            'manifest_path': Path(manifest), 'manifest_sha256': manifest_sha256,
            'sources': evidence._freeze(evidence.strict_json(evidence.pinned(manifest, manifest_sha256))['files']),
            'ending_state': ending_state, 'source_root': source_reader.root,
            'source_reader': source_reader, '_consumed_inputs': {},
            'unused_inputs': 0, 'scratch': scratch,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)

    # Expose only the original read-only view of mutable authentication bookkeeping.
    @property
    def consumed_inputs(self):
        return MappingProxyType(self._consumed_inputs)

    # Retain all original source checks with actual native bytes and three pinned catalogs.
    def authenticate_sources(self):
        current = self.source_reader.authenticate_native()
        reviews = tuple(evidence.pinned(self.source_root / name, expected) for name, expected in zip(CATALOG_PATHS, adaptations.CATALOG, strict=True))
        adaptations.reviewed_n2_sources(self.completion['source_sha256'], current, reviews, self.source_reader.read('backend/market/learned_live_holding.py'))
        for name in SOURCE_PATHS:
            evidence.authenticate_file(self.source_root / name, self.sources[name])
        evidence.require({name: self.sources[name] for name in ORIGINAL_SOURCES} == ORIGINAL_SOURCES, 'Exact original legacy producer profile required')

    # Preserve capture/input selection and exact unused-input accounting without data loading.
    def authenticate_inputs(self, market):
        capture_raw = evidence.pinned(Path(market) / 'capture.json', self.completion['capture_sha256'])
        capture = evidence.strict_json(capture_raw)
        self._consumed_inputs.clear()
        self._consumed_inputs.update({str(Path(market) / 'capture.json'): self.completion['capture_sha256']})
        for name, expected in capture['files'].items():
            evidence.require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'Relative original capture path required')
            evidence.authenticate_file(Path(market) / name, expected)
            self._consumed_inputs[str(Path(market) / name)] = expected
        checked = set()
        for name, expected in self.completion['input_sha256'].items():
            if (name.startswith((str(Path(market)) + '/', '/observation/', '/actions/')) or name == '/app/docs/research/actual-policy-action-review-2026-10-04.json'):
                evidence.authenticate_file(name, expected)
                checked.add(name)
                self._consumed_inputs[name] = expected
        object.__setattr__(self, 'unused_inputs', sum(name not in checked for name in self.completion['input_sha256']))
        return capture

    # Read an initial comparison target without using it as account state or seed.
    def initial(self):
        return evidence.archive_value(evidence.pinned(self.root / 'initial.json.gz', self.initial_sha256, max_bytes=evidence.MAX_COMPRESSED_BYTES))

    # Recheck complete sealed input maps, original selectors, consumed bytes and source chain.
    def unchanged(self):
        inputs = self.completion.get('input_sha256')
        if type(inputs) is streamed.ShaMap:
            inputs.authenticate_contents()
        evidence.authenticate_file(self.root / 'completion.json', self.completion_sha256)
        evidence.authenticate_file(self.root / 'initial.json.gz', self.initial_sha256)
        evidence.authenticate_file(self.manifest_path, self.manifest_sha256)
        for path, expected in self._consumed_inputs.items():
            evidence.authenticate_file(path, expected)
        self.authenticate_sources()


# Preserve every archive and exact physical state using only authenticated layout metadata.
def preserved_archives(archives, physical_sha256, physical_bytes):
    evidence.require(type(archives) is CapacityOriginalArchivesV2, 'EXACT_CAPACITY_ARCHIVES_REQUIRED')
    result = {}
    for row in archives.completion['sessions']:
        path = archives.root / 'sessions' / (row['session'] + '.json.gz')
        result[str(path)] = evidence.authenticate_file(path, row['sha256'])
    descriptor = archives.source_reader.paper_descriptor()
    physical = metadata.physical_state_path(archives.root / 'state', descriptor)
    evidence.require(type(physical_bytes) is int and physical_bytes >= 0 and physical.stat().st_size == physical_bytes, 'EXTERNAL_PHYSICAL_SIZE_DIFFERS')
    raw_sha256 = byte_auth.stream_file(physical, physical_sha256)['sha256']
    with tempfile.TemporaryDirectory(prefix='physical-history-', dir=archives.scratch) as directory:
        value = streamed.read(physical, raw_sha256, directory=directory, physical=True)
        try:
            evidence.require(type(value) is dict and set(value) == set(descriptor['physical_state_fields']), 'EXACT_ORIGINAL_PHYSICAL_STATE_SCHEMA_REQUIRED')
            evidence.require(adaptations.logical_digest(value) == archives.ending_state, 'FINAL_PHYSICAL_STATE_DIFFERS_FROM_COMPLETION')
        finally:
            streamed.release(value)
    result[str(physical)] = raw_sha256
    return result
