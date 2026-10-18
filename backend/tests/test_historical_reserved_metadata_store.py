"""New finite reserved metadata/CAS assertions over an explicitly synthetic account.

Whole private Nightly CodeTypes, native paper/broker/checkpoint and SQLite Store
execute. Context, policy, trade orchestration and source-manifest globals are
synthetic; no closed test body, genuine constructor, model or provider executes.
"""
from copy import deepcopy
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_native_metadata as metadata
from backend.market import historical_packet_demand as demand
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_synthetic_native_write as writer_module
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import synthetic_reserved_stage_fixture as stages
from backend.tests import test_historical_raw_nightly_lifecycle as fixture

ACTUAL_KILL_FILES = []


# Declare only the actual source bytes used by an otherwise unused Cycle reader seam.
def bridge_sources():
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
        '/audit/backend/market/historical_raw_cycle.py',
        '/audit/backend/market/historical_conditional_cycle.py')}


# Produce real native NaN/Unicode history through the explicit reserved save capability.
def synthetic_trade(report, root, session, force, *, client_factory, decision_at, holding_policy, native_save):
    holding_policy.decide()
    state = paper.load_state(root)
    state.start_equity = float('nan')
    entry = paper.snapshot(state, session, 100000, 100000,
        [{'z': 'é' + str(i) + 'x' * 25000, 'a': float('nan')} for i in range(12)])
    native_save(root, state)
    return entry


# Exercise the new reservation boundary without running any previously closed scenario.
class ReservedMetadataStoreTests(unittest.TestCase):
    # Reuse fixture setup only, then reserve all new native/CAS extents before account birth.
    def setUp(self):
        self.case = fixture.RawNightlyLifecycleTests()
        self.case.setUp()
        self.store, self.raw, self.nightly = self.case.store, self.case.raw, self.case.nightly
        self.context, self.legacy = self.case.context, self.case.legacy
        self.case.ns['raw_cycle'] = SimpleNamespace(sources=bridge_sources)
        base = self.case.fixture.fixture
        self.pins = base.pins
        self.cas = cas.reserve(self.store)
        self.store.bind_reserved_blobs(self.cas)
        self.writer = writer_module.reserve(self.store.root / 'SYNTHETIC-reserved-workspace',
            writer=paper.save_state, writer_source=Path(paper.__file__), identity=base.profile,
            identity_sha256=self.store.identity, slots=8)
        self.nightly.root = self.writer.root / 'work'
        (self.nightly.root / 'operations').mkdir(mode=0o700)
        self.io = reserved_io.SyntheticNativeIO(self.writer, synthetic_trade,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.initial = self.inventory()

    # Release the actual Store lock while retaining every allocated/evidence file.
    def tearDown(self):
        self.case.tearDown()

    # Record exact allocated inode identities and unchanged file sizes, excluding mtime.
    def inventory(self):
        return {name: tuple(str(getattr((self.cas.root / name).stat(), key)) for key in
            ('st_dev', 'st_ino', 'st_size', 'st_blocks')) for name in self.cas.inodes}

    # Drive one private birth with explicit native and CAS reservations already bound.
    def birth(self):
        return self.nightly._initialize(self.context, raw_checkpoint=self.raw, native_io=self.io)

    # Drive one private prior-close with a separately reserved phase before its effects.
    def close(self, client, birth):
        return self.nightly._close(self.context, client, '2019-02-28', birth=birth,
            previous=birth, raw_checkpoint=self.raw, native_io=self.io)

    # Read the complete authenticated result while preserving its original metadata lease.
    def value(self, reference):
        return self.nightly.read_lifecycle(reference, raw_checkpoint=self.raw)['value']

    # Reopen only the exact original pool and explicitly persisted Store mode/head.
    def reopen(self, head=None):
        root, identity = self.store.root, self.store.identity
        self.store.close()
        self.cas = cas.ReservedCAS(root / 'reserved-blobs', identity=identity)
        self.store = Store(root, identity, head, blob_reservation=self.cas)
        self.nightly.store = self.case.store = self.store

    # Arm one explicit synthetic storage-only producer, separate from native lifecycle leases.
    def arm(self, name):
        return self.cas.arm(operation=hashlib.sha256(name.encode()).hexdigest(),
                            head=self.store.snapshot()['head'])

    # Persist one whole blob through the real Store public storage API.
    def put(self, body):
        return self.store.put_stream(io.BytesIO(body), limit=len(body),
            expected_sha256=hashlib.sha256(body).hexdigest())[0]

    # Verify exact native entry/decision bytes, old references and same-inode physical extents.
    def test_native_metadata_bytes_reopen_and_original_recovery(self):
        client, birth = self.birth()
        result = self.close(client, birth)
        value = self.value(result)
        state = paper.load_state(self.nightly.root)
        expected = json.dumps(state.history[-1], indent=2, default=paper._state_json).encode()
        entry = value['entry']
        producer = hashlib.sha256(Path(self.case.ns['__file__']).read_bytes()).hexdigest()
        self.assertEqual(entry['schema'], 'native-json-metadata/2')
        self.assertGreater(entry['raw_bytes'], 262144)
        self.assertIn(b'NaN', expected)
        self.assertEqual(metadata.read_bytes(self.store, entry, kind='nightly-entry', producer_sha256=producer), expected)
        decision = value['decisions'][0]
        decision_source = hashlib.sha256(Path(self.legacy.__file__).read_bytes()).hexdigest()
        expected_decision = json.dumps({'targets': {'AAPL': float('nan')},
            'receipt': {'text': 'q' * 270000, 'scope': 'SYNTHETIC_POLICY'}}, indent=2,
            default=paper._state_json).encode()
        self.assertEqual(metadata.read_bytes(self.store, decision, kind='holding-decision',
            producer_sha256=decision_source), expected_decision)
        self.assertEqual(self.inventory(), self.initial)
        self.assertEqual(list((self.store.root / 'blobs').iterdir()), [])
        self.assertEqual(list((self.store.root / 'incoming').iterdir()), [])
        self.reopen()
        before = (paper.state_path(self.nightly.root).read_bytes(), (self.raw.root / 'control').read_bytes(),
                  (self.writer.root / 'control').read_bytes(), self.store.snapshot(), (self.cas.root / 'control').read_bytes())
        self.assertEqual(self.close(client, birth), result)
        self.assertEqual(self.close(client, birth), result)
        self.assertEqual(self.value(birth)['entry']['raw_sha256'], hashlib.sha256(b'null').hexdigest())
        self.assertEqual(metadata.read_bytes(self.store, entry, kind='nightly-entry', producer_sha256=producer), expected)
        self.assertEqual(before, (paper.state_path(self.nightly.root).read_bytes(), (self.raw.root / 'control').read_bytes(),
            (self.writer.root / 'control').read_bytes(), self.store.snapshot(), (self.cas.root / 'control').read_bytes()))
        self.assertEqual(self.context.policy_calls, 1)

    # Commit an actual reserved Store decision and verify its authoritative reopened entry.
    def test_actual_store_stage_commit_uses_original_reserved_receipt(self):
        client, birth = self.birth()
        result = self.close(client, birth)
        lease = self.arm('SYNTHETIC_STAGE_PRODUCER')
        cycle = stages.sha('SYNTHETIC_RESERVED_METADATA_STAGE')
        stages.ready(self.store, cycle)
        operation = stages.sha('SYNTHETIC_RESERVED_DECISION_OPERATION')
        self.store.reserve_operation(operation=operation, expected_head=self.store.snapshot()['head'],
            cycle=cycle, stage='DECISION_FROZEN', inputs=stages.sha('SYNTHETIC_INPUTS'))
        entry = self.store.complete_operation(operation, result)
        self.cas.complete(lease, result)
        self.reopen(entry['sha256'])
        self.assertEqual(self.store.recover_operation(operation), entry)
        self.assertEqual(self.store.snapshot()['head'], entry['sha256'])
        self.assertEqual(self.value(result)['birth'], birth)
        self.assertEqual(self.inventory(), self.initial)

    # Preserve whole multi-slot blobs, empty bodies and exact duplicate charges with no names added.
    def test_whole_blob_empty_duplicate_and_descriptor_tamper(self):
        lease = self.arm('SYNTHETIC_WHOLE_BLOB')
        raw = b'z' * (3 * cas.CHUNK + 17)
        reference = self.put(raw)
        self.assertEqual(self.put(raw), reference)
        empty = self.put(b'')
        self.assertEqual(self.store.read_blob(reference, limit=len(raw)), raw)
        self.assertEqual(self.store.read_blob(empty, limit=0), b'')
        _, group = self.cas.group(lease)
        self.assertEqual((group['calls'], group['slots'], group['bytes']), (3, 4, 2 * len(raw)))
        producer = stages.sha('SYNTHETIC_METADATA_PRODUCER')
        ref = metadata.capture(self.store, None, kind='nightly-entry', producer_sha256=producer)
        bad = deepcopy(ref)
        bad['reserved_cas']['index'] = True
        with self.assertRaises(ValueError):
            metadata.read_bytes(self.store, bad, kind='nightly-entry', producer_sha256=producer)
        bad = deepcopy(ref)
        bad['raw_bytes'] += 1
        with self.assertRaises(ValueError):
            metadata.read_bytes(self.store, bad, kind='nightly-entry', producer_sha256=producer)
        for unused in range(cas.METADATA_ITEMS - 1):
            metadata.capture(self.store, None, kind='nightly-entry', producer_sha256=producer)
        with self.assertRaisesRegex(ValueError, 'metadata count'):
            metadata.capture(self.store, None, kind='nightly-entry', producer_sha256=producer)
        self.assertEqual(len(self.cas.group(lease)[1]['metadata']), cas.METADATA_ITEMS)
        self.cas.complete(lease, reference)
        before = (self.cas.root / 'control').read_bytes()
        with self.assertRaises(ValueError):
            metadata.capture(self.store, None, kind='nightly-entry', producer_sha256=producer)
        self.assertEqual((self.cas.root / 'control').read_bytes(), before)
        self.assertEqual(self.store.read_blob(reference, limit=len(raw)), raw)
        bad = deepcopy(ref)
        bad['schema'] = 'native-json-metadata/1'
        with self.assertRaisesRegex(ValueError, 'no downgrade'):
            metadata.read_bytes(self.store, bad, kind='nightly-entry', producer_sha256=producer)
        directory = self.nightly.root / 'operations' / 'SYNTHETIC_PENDING_METADATA'
        directory.mkdir(mode=0o700)
        self.io.begin(self.nightly, directory, self.legacy)

        # Interrupt after metadata claim persistence but before the claimant receives its lease.
        def cut(point):
            if point == 'reserved_metadata_pending':
                raise ValueError('SYNTHETIC metadata claim interruption')
        self.cas._point = cut
        try:
            with self.assertRaisesRegex(ValueError, 'claim interruption'):
                metadata.capture(self.store, None, kind='nightly-entry', producer_sha256=producer)
        finally:
            del self.cas._point
        before = (self.writer.root / 'control').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Uncertain metadata'):
            self.io.save(self.nightly.root, paper.PaperState())
        self.assertEqual((self.writer.root / 'control').read_bytes(), before)
        self.assertFalse(paper.state_path(self.nightly.root).exists())
        self.assertEqual(self.store.read_blob(reference, limit=len(raw)), raw)
        self.assertEqual(self.inventory(), self.initial)

    # Persist caught metadata encoding uncertainty and refuse all later writes/evidence completion.
    def test_metadata_bound_failure_poisons_phase_and_retains_original_bytes(self):
        client, birth = self.birth()
        directory = self.nightly.root / 'operations' / 'SYNTHETIC_METADATA_OVERFLOW'
        directory.mkdir(mode=0o700)
        self.io.begin(self.nightly, directory, self.legacy)
        lease = self.io.reserved_cas
        old = self.put(b'original')
        producer = stages.sha('SYNTHETIC_OVERFLOW_PRODUCER')
        ref = metadata.capture(self.store, {'text': 'x' * 1400000}, kind='nightly-entry',
                               producer_sha256=producer)
        self.assertGreater(ref['raw_bytes'], 1024 * 1024)
        with self.assertRaisesRegex(ValueError, 'aggregate bound'):
            metadata.capture(self.store, {'text': 'y' * 800000}, kind='nightly-entry',
                             producer_sha256=producer)
        native_before = (paper.state_path(self.nightly.root).read_bytes(), (self.writer.root / 'control').read_bytes())
        with self.assertRaises(ValueError):
            self.io.save(self.nightly.root, paper.load_state(self.nightly.root))
        with self.assertRaises(ValueError):
            self.io.evidence()
        self.assertEqual(native_before, (paper.state_path(self.nightly.root).read_bytes(), (self.writer.root / 'control').read_bytes()))
        self.reopen()
        self.assertIsNone(self.value(birth)['birth'])
        self.assertEqual(self.store.read_blob(old, limit=8), b'original')
        self.assertEqual(self.cas.group(lease)[1]['status'], 'PAUSED')
        with self.assertRaises(ValueError):
            self.put(b'next')
        with self.assertRaises(ValueError):
            self.cas.complete(lease, old)
        with self.assertRaises(ValueError):
            self.arm('SYNTHETIC_NO_RETRY')

    # Exhaust declared phase capacity and prove birth refuses before any native/account effect.
    def test_phase_exhaustion_precedes_native_birth_and_public_entry_refuses(self):
        with self.assertRaisesRegex(StorePause, 'before effects'):
            self.nightly.initialize(self.context, raw_checkpoint=self.raw)
        for index in range(cas.GROUPS):
            lease = self.arm('SYNTHETIC_CAPACITY_' + str(index))
            self.cas.complete(lease, self.put(b'result'))
        before = (self.writer.root / 'control').read_bytes()
        with self.assertRaisesRegex(ValueError, 'capacity exhausted before native work'):
            self.birth()
        self.assertFalse(paper.state_path(self.nightly.root).exists())
        self.assertEqual((self.writer.root / 'control').read_bytes(), before)
        self.assertEqual(self.context.policy_calls, 0)
        self.assertEqual(self.inventory(), self.initial)

    # Require persisted reserved mode even when the pool is removed, and refuse legacy/spool downgrade.
    def test_persisted_pool_binding_refuses_missing_removed_or_changed_pool(self):
        root, identity = self.store.root, self.store.identity
        self.store.close()
        with self.assertRaisesRegex(StorePause, 'no downgrade'):
            Store(root, identity, None)
        moved = root / 'retained-reserved-blobs'
        self.cas.root.rename(moved)
        try:
            with self.assertRaisesRegex(StorePause, 'no downgrade'):
                Store(root, identity, None)
        finally:
            moved.rename(self.cas.root)
        self.reopen()
        with self.assertRaises(ValueError):
            self.store.adopt_spool(None, None, expected_sha256='0' * 64, length=0)
        header = deepcopy(self.cas.header)
        header['native_operation_adopted'] = 0
        fixture.physical._fixed_write(self.cas.root / 'header', header)
        with self.assertRaises(ValueError):
            cas.ReservedCAS(self.cas.root, identity=identity)

    # Reopen one owned child and kill exactly after its declared fsynced protocol boundary.
    def child(self, point, mode, birth):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        self.reopen()

        # Retain the observed boundary before SIGKILL, without claiming power-loss durability.
        def cut(name):
            if name == point:
                path = paper.state_path(self.nightly.root)
                value = {'pid': os.getpid(), 'point': name, 'head': self.store.snapshot()['head'],
                    'paper_sha256': None if not path.exists() else hashlib.sha256(path.read_bytes()).hexdigest(),
                    'policy_calls': self.context.policy_calls}
                self.legacy.write_once(self.nightly.root / 'actual-child-cut.json', demand.encoded(value))
                os.kill(os.getpid(), signal.SIGKILL)
        if mode == 'blob':
            self.cas._point = cut
            self.put(b'orphan' * 20000)
        else:
            self.store.fault = cut
            self.close(self.client, birth)
        raise AssertionError('Actual cut not reached')

    # Bound/reap actual children and retain independently readable original cut/exit witnesses.
    def killed(self, point, mode, birth=None):
        self.store.close()
        process = multiprocessing.get_context('fork').Process(target=self.child, args=(point, mode, birth))
        try:
            watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM}
            old = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                process.start()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
            process.join(timeout=15)
            self.assertFalse(process.is_alive(), 'Owned metadata/CAS child missed its cut')
            self.assertEqual(process.exitcode, -signal.SIGKILL)
            marker = json.loads((self.nightly.root / 'actual-child-cut.json').read_bytes())
            self.assertEqual(marker['pid'], process.pid)
            self.assertEqual(marker['point'], point)
            self.reopen(marker['head'])
            ended = {'pid': process.pid, 'exitcode': process.exitcode, 'boundary': point,
                'head': marker['head'], 'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}
            self.legacy.write_once(self.nightly.root / 'actual-child-exit.json', demand.encoded(ended))
            ACTUAL_KILL_FILES.append((str(self.nightly.root / 'actual-child-cut.json'),
                                     str(self.nightly.root / 'actual-child-exit.json')))
            return marker
        finally:
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
            if process.pid is not None:
                self.assertFalse(process.is_alive())
                process.close()

    # Keep an interrupted indexed blob unreadable while older committed blobs remain readable.
    def test_actual_sigkill_after_catalog_before_control_stays_pending_no_replay(self):
        lease = self.arm('SYNTHETIC_INTERRUPTED_CAS')
        old = self.put(b'committed')
        self.killed('reserved_cas_index_fsynced', 'blob')
        self.assertEqual(self.store.read_blob(old, limit=9), b'committed')
        orphan = hashlib.sha256(b'orphan' * 20000).hexdigest()
        with self.assertRaisesRegex(ValueError, 'Uncommitted'):
            self.store.read_blob(orphan, limit=120000)
        self.assertIsNotNone(self.cas._control()['pending'])
        with self.assertRaises(ValueError):
            self.put(b'retry')
        with self.assertRaises(ValueError):
            self.cas.complete(lease, old)
        self.assertEqual(self.inventory(), self.initial)

    # Recover only the original result's missing CAS seal after an actual process interruption.
    def test_actual_sigkill_after_result_recovers_only_original_phase_seal(self):
        self.client, birth = self.birth()
        marker = self.killed('reserved_phase_result_written', 'nightly', birth)
        self.assertEqual(marker['policy_calls'], 1)
        self.assertEqual(self.cas._control()['groups'][-1]['status'], 'ACTIVE')
        directory = self.nightly.operation('NIGHTLY_CLOSE', '2019-02-28')
        result = json.loads((directory / 'result.json').read_bytes())['receipt']
        before = (paper.state_path(self.nightly.root).read_bytes(), (self.raw.root / 'control').read_bytes(),
                  (self.writer.root / 'control').read_bytes(), self.store.snapshot())
        self.assertEqual(self.close(self.client, birth), result)
        self.assertEqual(self.cas._control()['groups'][-1]['status'], 'COMPLETE')
        self.assertEqual(self.close(self.client, birth), result)
        self.assertEqual(before, (paper.state_path(self.nightly.root).read_bytes(), (self.raw.root / 'control').read_bytes(),
            (self.writer.root / 'control').read_bytes(), self.store.snapshot()))
        self.assertEqual(self.context.policy_calls, 0)
        self.assertEqual(self.inventory(), self.initial)
