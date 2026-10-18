"""Synthetic raw metadata continuation with real native paper and Store commits.

Nightly/observer CodeTypes use isolated startup, broker/policy and source-manifest
globals. No complete Nightly constructor, model or genuine operation is admitted.
Previously closed tests are imported for fixtures only; none are executed here.
"""
import builtins
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from threading import Lock, get_ident
import types
from types import SimpleNamespace
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_native_metadata as metadata
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry
from backend.market import historical_physical_checkpoint as physical
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import test_historical_paper_component_integration as fixture


# Reuse exact pure stage fixtures without importing pytest or any closed test bodies.
def stage_namespace():
    path = Path('/audit/backend/tests/test_historical_packet_store.py')
    compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
    codes = {item.co_name: item for item in compiled.co_consts if isinstance(item, types.CodeType)}
    result = {'hashlib': hashlib, 'demand': demand, 'registry': registry}
    for name in ('sha', 'mapping', 'paused', 'ready'):
        result[name] = types.FunctionType(codes[name], result)
    result['paused'].__defaults__ = (False,)
    return SimpleNamespace(**result)


# Return synthetic decisions only, never a fitted policy or inference invocation.
class SyntheticPolicy:
    # Preserve the supplied synthetic native-domain values without conversion.
    def decide(self, value):
        return value['targets'], value['receipt']


# Make any attempted broker effect observable before it can occur.
class SyntheticBroker:
    # Refuse an unexpected invocation rather than simulating a successful order.
    def _submit(self, *args, **kwargs):
        raise AssertionError('Unexpected broker effect')


# Instantiate exact full-source methods with explicit synthetic outer bindings.
def namespace():
    result = fixture.boundary_namespace('historical_conditional_nightly')
    path = Path(result['__file__'])
    compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
    codes = {item.co_name: item for item in compiled.co_consts if isinstance(item, types.CodeType)}
    result.update({'datetime': datetime, 'UTC': UTC, 'get_ident': get_ident,
        'LOCK': Lock(), 'SAVE_STATE': paper.save_state, 'SUBMIT': SyntheticBroker._submit,
        'native': SimpleNamespace(ReplayBroker=SyntheticBroker),
        'FrozenCurrentGradePolicy': SyntheticPolicy,
        'sources': synthetic_sources, 'Store': Store})
    for name in ('sync_directory', 'write_once'):
        result[name] = types.FunctionType(codes[name], result)
    result['NativeCapture'] = builtins.__build_class__(
        types.FunctionType(codes['NativeCapture'], result), 'NativeCapture')
    return result


# Bind the actual edited source while declaring that full source admission is absent.
def synthetic_sources():
    path = Path('/audit/backend/market/historical_conditional_nightly.py')
    return {'SYNTHETIC_SOURCE_MANIFEST_ONLY': hashlib.sha256(path.read_bytes()).hexdigest()}


# Exercise only the new metadata and durable continuation acceptance boundary.
class RawNightlyMetadataTests(unittest.TestCase):
    # Reuse actual Store/checkpoint setup without loading any previously closed suite.
    def setUp(self):
        fixture.PaperComponentIntegrationTests.setUpClass()
        self.fixture = fixture.PaperComponentIntegrationTests()
        self.fixture.setUp()
        self.store, self.raw, self.account = self.fixture.store, self.fixture.raw, self.fixture.account
        self.raw = physical.reserve(self.fixture.root / 'metadata-checkpoint',
            identity=self.fixture.profile, identity_sha256=self.fixture.pin,
            writer=self.fixture.writer, limits={
                'span_bytes': 512 * 1024, 'raw_bytes': 1024 * 1024, 'history_rows': 32,
                'body_slots': 8, 'page_slots': 12, 'directory_headroom_bytes': 65536})
        self.ns = namespace()
        self.producer = hashlib.sha256(Path(self.ns['__file__']).read_bytes()).hexdigest()
        self.nightly = object.__new__(self.ns['Nightly'])
        self.nightly.store, self.nightly.root = self.store, self.account
        self.nightly.expected_head = None
        (self.account / 'operations').mkdir(mode=0o700)

    # Keep all evidence files and release the actual SQLite writer lock.
    def tearDown(self):
        self.store.close()

    # Capture the actual native snapshot return and its independently native-saved state.
    def scenario(self):
        self.state = paper.PaperState(start_equity=float('nan'))
        self.entry = paper.snapshot(self.state, '2019-03-01', 100000, 95000,
            [{'z': 'é' + str(index) + 'x' * 25000, 'a': float('nan')}
             for index in range(12)])
        self.original = paper.save_state(self.account, self.state).read_bytes()
        refs = self.ns['components'](self.store, 'SYNTHETIC_BROKER', self.account,
                                    self.fixture.pins, raw_checkpoint=self.raw)
        self.decision = {'targets': {'z': float('nan'), 'a': 0.5},
                         'receipt': {'order': ['z', 'a'], 'text': 'q' * 270000}}
        entry = metadata.capture(self.store, self.entry, kind='nightly-entry',
                                 producer_sha256=self.producer)
        decision = metadata.capture(self.store, self.decision, kind='holding-decision',
                                    producer_sha256=self.producer)
        context = self.ns['put'](self.store, b'SYNTHETIC_CONTEXT_NO_MODEL')
        self.value = {'phase': 'NIGHTLY_CLOSE', 'session': '2019-03-01',
                      'context': context, 'birth': hashlib.sha256(b'SYNTHETIC_BIRTH').hexdigest(),
                      'components': refs, 'entry': entry, 'decisions': [decision]}
        return self.value

    # Publish a finite raw result under its original exclusive reservation.
    def complete(self):
        directory, reservation = self.nightly.reserve('NIGHTLY_CLOSE', '2019-03-01',
            self.value['context'], self.value['birth'], self.value['components'])
        reference = self.nightly.complete_raw(directory, reservation, self.value,
                                              raw_checkpoint=self.raw)
        return reference, directory

    # Compare standalone native encoding, recover repeatedly and restore opaque paper.
    def test_native_snapshot_completion_reopen_and_exact_restore(self):
        self.scenario()
        reference, directory = self.complete()
        self.assertGreater(len(self.original), 262144)
        self.assertIn(b'NaN', self.original)
        self.store.close()
        self.store = Store(self.fixture.root / 'store', self.fixture.pin, None)
        self.nightly.store = self.store
        self.raw = physical.PhysicalCheckpoint(self.raw.root,
            identity_sha256=self.fixture.pin, writer=self.fixture.writer)
        record = self.nightly.read_raw(reference, raw_checkpoint=self.raw)
        for value, key, kind in ((self.entry, 'entry', 'nightly-entry'),
                                 (self.decision, 'decisions', 'holding-decision')):
            expected = json.dumps(value, indent=2, default=paper._state_json).encode()
            descriptor = record[key][0] if key == 'decisions' else record[key]
            actual = metadata.read_bytes(self.store, descriptor, kind=kind,
                                         producer_sha256=self.producer)
            self.assertGreater(len(actual), 262144)
            self.assertEqual(actual, expected)
            self.assertFalse(actual.endswith(b'\n'))
            self.assertIn(b'NaN', actual)
        before = (directory / 'result.json').read_bytes()
        for _ in range(2):
            self.assertEqual(self.nightly.recover_raw('NIGHTLY_CLOSE', '2019-03-01',
                context_sha256=self.value['context'], birth=self.value['birth'],
                raw_checkpoint=self.raw), reference)
        self.assertEqual((directory / 'result.json').read_bytes(), before)
        from backend.market import historical_paper_component as component
        target = self.fixture.root / 'fresh-native.json'
        component.restore(record['components']['paper'], self.raw, target,
                          expected_identity=self.fixture.pin)
        self.assertEqual(target.read_bytes(), self.original)
        self.assertFalse(record['native_operation_committed'])
        self.assertIsNone(self.store.snapshot()['head'])

    # Commit the raw receipt through a real reserved decision stage and reopen its head.
    def test_actual_store_reserved_stage_commit_readback(self):
        cycle = hashlib.sha256(b'SYNTHETIC_RAW_METADATA_CYCLE').hexdigest()
        stage_namespace().ready(self.store, cycle)
        pre = self.store.snapshot()['head']
        self.nightly.expected_head = pre
        operation = hashlib.sha256(b'SYNTHETIC_RAW_METADATA_OPERATION').hexdigest()
        self.store.reserve_operation(operation=operation, expected_head=pre, cycle=cycle,
            stage='DECISION_FROZEN', inputs=hashlib.sha256(b'SYNTHETIC_INPUT_DECLARATION').hexdigest())
        self.scenario()
        reference, _ = self.complete()
        entry = self.store.complete_operation(operation, reference)
        head = self.store.snapshot()['head']
        self.assertEqual(head, entry['sha256'])
        self.assertNotEqual(head, pre)
        self.assertEqual(entry['stage'], 'DECISION_FROZEN')
        self.assertEqual(entry['receipt_sha256'], reference)
        self.store.close()
        self.store = Store(self.fixture.root / 'store', self.fixture.pin, head)
        self.nightly.store = self.store
        self.assertEqual(self.store.recover_operation(operation), entry)
        self.assertEqual(self.nightly.read_raw(reference, raw_checkpoint=self.raw)['entry'],
                         self.value['entry'])
        self.assertFalse(self.nightly.read_raw(reference, raw_checkpoint=self.raw)
                         ['durable_simulator_adoption'])

    # Preserve the first boundary after missing completion rather than replaying work.
    def test_interrupted_and_conflicting_recovery_stays_paused(self):
        self.scenario()
        self.nightly.reserve('NIGHTLY_CLOSE', '2019-03-01', self.value['context'],
                             self.value['birth'], self.value['components'])
        with self.assertRaisesRegex(StorePause, 'never re-execute'):
            self.nightly.recover_raw('NIGHTLY_CLOSE', '2019-03-01',
                context_sha256=self.value['context'], birth=self.value['birth'], raw_checkpoint=self.raw)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.nightly.recover_raw('NIGHTLY_CLOSE', '2019-03-01',
                context_sha256='0' * 64, birth=self.value['birth'], raw_checkpoint=self.raw)
        self.assertIsNone(self.store.snapshot()['head'])

    # Reject changed source, kind, identity, order and lengths without normalizing bytes.
    def test_metadata_tamper_and_storage_mode_refusals(self):
        self.scenario()
        valid = self.value['entry']
        changes = {'kind': 'holding-decision', 'identity_sha256': '0' * 64,
            'producer_sha256': '0' * 64, 'encoder_sha256': '0' * 64,
            'adapter_sha256': '0' * 64, 'raw_sha256': '0' * 64,
            'raw_bytes': True, 'native_operation_committed': True,
            'chunks': list(reversed(valid['chunks']))}
        for key, value in changes.items():
            with self.subTest(field=key), self.assertRaises((ValueError, StorePause)):
                metadata.read_bytes(self.store, {**valid, key: value}, kind='nightly-entry',
                                    producer_sha256=self.producer)
        reference, directory = self.complete()
        with self.assertRaisesRegex(ValueError, 'standalone nightly'):
            self.nightly.read_original(reference)
        with self.assertRaisesRegex(ValueError, 'not admitted'):
            self.nightly.complete(directory, '0' * 64, self.value)

    # Enforce aggregate entry plus decision size before publishing any raw result.
    def test_receipt_aggregate_bound_and_reservation_tamper(self):
        self.scenario()
        directory, reservation = self.nightly.reserve('NIGHTLY_CLOSE', '2019-03-01',
            self.value['context'], self.value['birth'], self.value['components'])
        changed = {**self.value, 'decisions': self.value['decisions'] * 80}
        with self.assertRaisesRegex(ValueError, 'aggregate bound'):
            self.nightly.complete_raw(directory, reservation, changed, raw_checkpoint=self.raw)
        self.assertFalse((directory / 'result.json').exists())
        with self.assertRaisesRegex(ValueError, 'lineage'):
            self.nightly.complete_raw(directory, '0' * 64, self.value, raw_checkpoint=self.raw)
        self.assertFalse((directory / 'result.json').exists())

    # Exercise the edited observer's decision hook and raw finish without model execution.
    def test_observer_raw_decision_and_recording_failure_retention(self):
        self.scenario()
        self.assertTrue(self.ns['LOCK'].acquire(blocking=False))
        client, policy = SyntheticBroker(), SyntheticPolicy()
        observer = self.ns['NativeCapture'](self.store, self.account, client, policy,
                                             raw_checkpoint=self.raw)
        try:
            with observer:
                targets, receipt = policy.decide(self.decision)
                self.assertIs(targets, self.decision['targets'])
                self.assertIs(receipt, self.decision['receipt'])
                with self.assertRaisesRegex(ValueError, 'PAUSED before submit'):
                    client._submit('SYNTHETIC')
            references = observer.finish()
            self.assertEqual(metadata.read_bytes(self.store, references[0],
                kind='holding-decision', producer_sha256=self.producer),
                json.dumps(self.decision, indent=2, default=paper._state_json).encode())
            observer.recording_failures.append('SYNTHETIC earlier uncertainty')
            before = set((self.store.root / 'blobs').iterdir())
            with self.assertRaisesRegex(StorePause, 'earlier uncertainty'):
                observer.finish()
            self.assertEqual(observer.recording_failures, ['SYNTHETIC earlier uncertainty'])
            self.assertEqual(set((self.store.root / 'blobs').iterdir()), before)
        finally:
            self.ns['LOCK'].release()
        self.assertIs(paper.save_state, self.ns['SAVE_STATE'])

    # Refuse one oversized metadata value at the existing limit without a receipt.
    def test_metadata_local_bound_shape_and_finite_descriptor(self):
        with self.assertRaisesRegex(ValueError, 'aggregate bound'):
            metadata.capture(self.store, {'text': 'x' * metadata.LIMIT},
                             kind='nightly-entry', producer_sha256=self.producer)
        with self.assertRaisesRegex(ValueError, 'shape'):
            metadata.capture(self.store, {'targets': {}}, kind='holding-decision',
                             producer_sha256=self.producer)
        with self.assertRaisesRegex(ValueError, 'aggregate bound'):
            metadata.capture(self.store, {'text': 'x' * 100}, kind='nightly-entry',
                             producer_sha256=self.producer, byte_limit=16)
        descriptor = metadata.capture(self.store, None, kind='nightly-entry',
                                      producer_sha256=self.producer)
        self.assertEqual(metadata.read_bytes(self.store, descriptor, kind='nightly-entry',
                         producer_sha256=self.producer), b'null')
        self.assertLess(len(demand.encoded(descriptor)), 262144)

    # A changed physical result marker cannot authenticate an otherwise valid CAS object.
    def test_result_marker_tamper_is_not_recovered(self):
        self.scenario()
        reference, directory = self.complete()
        (directory / 'result.json').write_bytes(demand.encoded(
            {'schema': 'raw-nightly-result/1', 'receipt': '0' * 64}))
        with self.assertRaisesRegex(ValueError, 'lineage'):
            self.nightly.read_raw(reference, raw_checkpoint=self.raw)
