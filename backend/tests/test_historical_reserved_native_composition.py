"""New private raw final production/recovery assertions with real native storage.

Synthetic stage/context/policy/resolver inputs surround exact complete-source
producer/settlement/Nightly CodeTypes. Actual native fills, saves, Store commits
and three owned process SIGKILL cuts run; no closed test body is executed.
"""
import ast
from copy import deepcopy
from datetime import UTC, date, datetime
import hashlib
import multiprocessing
import os
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_store as storage
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_synthetic_native_write as writer_module
from backend.tests import synthetic_reserved_stage_fixture as stages
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import test_historical_raw_cycle_nightly as fixture
from backend.tests import test_historical_raw_nightly_metadata as metadata_fixture
from backend.tests import test_historical_raw_settlement_integration as settlement_fixture

ACTUAL_KILL_FILES = []


# Distinguish a deliberately injected boundary stop from a native/runtime failure.
class BoundaryCut(Exception):
    pass



# Save through an explicit source-bound capability; planning/context data remain synthetic.
def synthetic_trade(report, root, session, force, *, client_factory, decision_at, holding_policy, native_save):
    holding_policy.decide()
    state = paper.load_state(root)
    state.start_equity = float('nan')
    entry = paper.snapshot(state, session, 100000, 100000,
        [{'z': 'é' + str(i) + 'x' * 25000, 'a': float('nan')} for i in range(12)])
    if session == '2019-02-28':
        state.pending = [{'client_order_id': 'SYNTHETIC-cycle-bridge', 'symbol': 'AAPL',
            'side': 'buy', 'qty': 8, 'session': session, 'execute_on': '2019-03-01',
            'execution_timing': 'dip_or_close'}]
    native_save(root, state)
    return entry


# Deliberately swallow the first capture failure and try another save to test poisoning.
def catching_trade(report, root, session, force, *, client_factory, decision_at, holding_policy, native_save):
    try:
        return synthetic_trade(report, root, session, force, client_factory=client_factory,
            decision_at=decision_at, holding_policy=holding_policy, native_save=native_save)
    except ValueError:
        native_save(root, paper.load_state(root))
        raise AssertionError('Uncertain capture allowed another save')


# Verify the new reserved composition without executing any closed test body.
class ReservedCompositionTests(unittest.TestCase):
    # Reuse exact source/setup helpers without invoking any earlier test or scenario body.
    def setUp(self):
        self.case = fixture.RawCycleNightlyTests()
        self.case.setUp()
        self.nightly, self.raw = self.case.nightly, self.case.raw
        self.store, self.pins = self.case.store, self.case.pins
        self.context = self.case.context
        self.store_root = self.store.root
        base = self.case.fixture.fixture.fixture
        self.writer = base.writer
        self.pool = writer_module.reserve(self.store.root / "SYNTHETIC-reserved-workspace",
            writer=paper.save_state, writer_source=Path(paper.__file__), identity=base.profile,
            identity_sha256=self.store.identity, slots=8)
        self.nightly.root = self.pool.root / "work"
        self.account = self.nightly.root
        (self.account / "operations").mkdir(mode=0o700)
        self.case.fixture.ns["reserved_io"] = reserved_io
        self.io = reserved_io.SyntheticNativeIO(self.pool, synthetic_trade,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.allocated = {i: (p.stat().st_dev, p.stat().st_ino, p.stat().st_blocks)
            for i in range(8) for p in [self.pool.root / "anchors" / str(i)]}
        self.assertTrue(all(row[2] * 512 >= writer_module.SLOT_BYTES for row in self.allocated.values()))
        path = Path('/audit/backend/market/historical_raw_cycle_final.py')
        tree = ast.parse(path.read_bytes())
        constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id != 'SAVE_STATE'}
        self.producer = settlement_fixture.functions(path,
            ('finalize', 'recover', 'sources', 'guard', 'operation', 'read', 'anchors',
             'current', 'link', 'reservation', 'prepared_receipt', 'result', '_recover', '_finalize'),
            {'deepcopy': deepcopy, 'UTC': UTC, 'date': date, 'datetime': datetime,
             'sha256': hashlib.sha256, 'Path': Path, 'paper': paper, 'codec': codec,
             'legacy': self.case.fixture.legacy, 'storage': storage, 'bridge': self.case.bridge,
             'raw_nightly': SimpleNamespace(__file__=self.case.fixture.ns['__file__'],
                RawNightly=self.case.fixture.ns['RawNightly'], sources=self.case.fixture.ns['sources']),
             'packet': packet, 'native': native, 'digest': codec.digest,
             'Store': Store, 'StorePause': StorePause, 'SAVE_STATE': paper.save_state,
             'reserved_io': reserved_io, **constants})
        self.points = []


    # Keep all evidence and ensure any actual writer lock is released at test completion.
    def tearDown(self):
        self.case.tearDown()


    # Observe actual producer boundaries without replacing any native operation function.
    def trace(self, point):
        if point.startswith('raw_final_'):
            self.points.append(point)


    # Produce only fresh synthetic committed stages and a real post-submission native fill.
    def prepare(self):
        self.client, self.birth = self.nightly._initialize(self.context, raw_checkpoint=self.raw, native_io=self.io)
        self.previous = self.nightly._close(self.context, self.client, '2019-02-28',
            birth=self.birth, previous=self.birth, raw_checkpoint=self.raw, native_io=self.io)
        prior = self.case.fixture.read(self.previous)
        self.lineage = {'schema': 'raw-nightly-cycle-lineage/1', 'birth': self.birth,
            'previous_nightly': self.previous, 'context': prior['context'],
            'context_identity': prior['context_identity']}
        body = fixture.demand.encoded({'scope': 'SYNTHETIC_RAW_FINAL_CONTEXT',
            'window': {'completed_at': '2019-03-01T14:45:00Z'}})
        self.case.cycle_context = {'raw': body.decode(), 'sha256': hashlib.sha256(body).hexdigest()}
        self.case.cycle_sha = hashlib.sha256(b'SYNTHETIC_RAW_FINAL_PRODUCER').hexdigest()
        self.case.lineage, self.case.client = self.lineage, self.client
        stages.ready(self.store, self.case.cycle_sha)
        self.case.commit_operation('DECISION_FROZEN', self.case.receipt(
            {'stage': 'DECISION_FROZEN', 'raw_nightly_lineage': self.lineage}))
        self.client.observe('2019-03-01T14:45:31.200000+00:00', {'AAPL': 100}, True)
        order = self.client.submit_market('AAPL', 5, 'buy', 'SYNTHETIC-cycle-bridge')
        state = paper.load_state(self.account)
        state.pending[0].update({'sent': {'qty': 5, 'at': order['submitted_at']},
            'execution': {'created_at': order['created_at'], 'submitted_at': order['submitted_at']}})
        self.pool.save(state, expected_preimage=self.pool.completed()['state'])
        latch = self.case.cycle['entry_timing'].latch_path(self.account, date(2019, 3, 1))
        latch.parent.mkdir(mode=0o700)
        latch.write_bytes(fixture.demand.encoded({'session': '2019-03-01', 'scope': 'SYNTHETIC_FINAL_LATCH'}))
        entry = self.case.commit_operation('SUBMISSION_CAPTURED', self.case.receipt(
            {'stage': 'SUBMISSION_CAPTURED', 'raw_nightly_lineage': self.lineage}))
        self.submission_head = entry['sha256']
        self.nightly.expected_head = self.submission_head
        self.client.flush('2019-03-01T14:45:33+00:00', {'AAPL': 100})
        self.before_paper = paper.state_path(self.account).read_bytes()
        self.before_broker = codec.encode(self.client, **self.pins)
        self.resolved = {'stage': 'OUTCOME_COMMITTED', 'scope': 'SYNTHETIC_RESOLVER_DECLARATION'}
        self.store.fault = self.trace


    # Run the new exact private producer body with the externally pinned submission head.
    def finish(self):
        return self.producer._finalize(self.nightly, self.client, submission_head=self.submission_head,
            resolved=self.resolved, raw_checkpoint=self.raw, native_io=self.io)


    # Exercise only metadata recovery under the explicitly supplied authoritative head.
    def recover(self):
        return self.producer._recover(self.nightly, submission_head=self.submission_head,
            resolved=self.resolved, raw_checkpoint=self.raw)


    # Read the actual account, broker, checkpoint control and Store head around recovery.
    def state_bytes(self):
        return (paper.state_path(self.account).read_bytes(), codec.encode(self.client, **self.pins),
                (self.raw.root / 'control').read_bytes(), self.store.snapshot())


    # Reopen the real Store and checkpoint only with the independently retained exact head.
    def reopen(self, head):
        self.store.close()
        self.store = Store(self.store_root, self.pins['identity_sha256'], head)
        self.nightly.store = self.case.store = self.case.fixture.store = self.store
        self.raw = physical.PhysicalCheckpoint(self.raw.root,
            identity_sha256=self.pins['identity_sha256'], writer=self.writer)
        self.case.raw = self.case.fixture.raw = self.raw
        self.pool = writer_module.ReservedWriter(self.pool.root, writer=paper.save_state,
            writer_source=Path(paper.__file__), identity_sha256=self.store.identity)
        self.io = reserved_io.SyntheticNativeIO(self.pool, synthetic_trade,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.nightly.expected_head = head
        self.store.fault = self.trace


    # Execute one child producer until an actual SIGKILL at its declared durable boundary.
    def child_finish(self, boundary):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        self.store = Store(self.store_root, self.pins['identity_sha256'], self.submission_head)
        self.nightly.store = self.store
        self.nightly.expected_head = self.submission_head

        # Retain an exact observed cut/head/PID before terminating this owned child.
        def cut(point):
            if point == boundary:
                marker = {'point': point, 'pid': os.getpid(), 'head': self.store.snapshot()['head'],
                    'paper_sha256': hashlib.sha256(paper.state_path(self.account).read_bytes()).hexdigest()}
                self.case.fixture.legacy.write_once(self.account / 'actual-child-cut.json',
                                                    fixture.demand.encoded(marker))
                os.kill(os.getpid(), signal.SIGKILL)

        self.store.fault = cut
        if boundary == 'reserved_native_returned':
            # Kill this owned child after native replace but before writer completion.
            def native_cut(point):
                if point == 'native_returned':
                    cut(boundary)
            self.pool._point = native_cut
        self.finish()
        raise AssertionError('Expected actual child SIGKILL boundary was not reached')


    # Own, bound and reap one actual child before reopening or inspecting its retained state.
    def killed(self, boundary):
        self.store.close()
        process = multiprocessing.get_context('fork').Process(target=self.child_finish, args=(boundary,))
        try:
            watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM}
            old = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                process.start()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
            process.join(timeout=15)
            self.assertFalse(process.is_alive(), 'Owned raw final child did not reach its cut')
            self.assertEqual(process.exitcode, -signal.SIGKILL)
            marker = packet._decode((self.account / 'actual-child-cut.json').read_bytes())
            self.assertEqual(marker['pid'], process.pid)
            self.assertEqual(marker['point'], boundary)
            self.reopen(marker['head'])
            receipt = {'pid': process.pid, 'exitcode': process.exitcode, 'boundary': boundary,
                       'head': marker['head'], 'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}
            self.case.fixture.legacy.write_once(self.account / 'actual-child-exit.json',
                                                fixture.demand.encoded(receipt))
            self.assertEqual(hashlib.sha256(paper.state_path(self.account).read_bytes()).hexdigest(),
                             marker['paper_sha256'])
            ACTUAL_KILL_FILES.append((str(self.account / 'actual-child-cut.json'),
                                      str(self.account / 'actual-child-exit.json')))
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


    # Prove preallocated inode identity and exact native bytes through all private phases.
    def test_reserved_birth_close_final_recovery_and_next_close(self):
        self.prepare()
        result = self.finish()
        self.assertEqual(self.pool.completed()['slot'], 3)
        self.assertEqual(paper.load_state(self.account).journal[-1]['filled_qty'], 5)
        self.assertGreater(len(paper.state_path(self.account).read_bytes()), 262144)
        self.assertIn(b'NaN', paper.state_path(self.account).read_bytes())
        self.reopen(result['head'])
        before = self.state_bytes() + ((self.pool.root / 'control').read_bytes(),)
        self.assertEqual(self.recover(), result)
        self.assertEqual(self.recover(), result)
        self.assertEqual(before, self.state_bytes() + ((self.pool.root / 'control').read_bytes(),))
        next_receipt = self.nightly._close(self.context, self.client, '2019-03-01',
            birth=self.birth, previous=result['receipt_sha256'], raw_checkpoint=self.raw, native_io=self.io)
        self.assertEqual(self.pool.completed()['slot'], 4)
        self.assertEqual(self.context.policy_calls, 2)
        self.assertEqual(self.store.snapshot()['head'], result['head'])
        self.case.fixture.read(next_receipt)
        self.case.fixture.read(self.birth)
        self.case.fixture.read(self.previous)
        for index in range(5):
            anchor = self.pool.root / 'anchors' / str(index)
            self.assertEqual((anchor.stat().st_dev, anchor.stat().st_ino), self.allocated[index][:2])
            expected = physical._fixed_read(self.pool.root / 'receipts' / str(index))['state']
            self.assertEqual(writer_module._image(anchor), expected)
        native_bytes = paper.state_path(self.account).read_bytes()
        self.assertEqual(native_bytes, fixture.lifecycle.json.dumps(paper.load_state(self.account),
            indent=2, default=paper._state_json).encode())

    # Retain OPEN native uncertainty after a real kill following the native replace.
    def test_actual_kill_after_native_replace_never_replays(self):
        self.prepare()
        self.killed('reserved_native_returned')
        control = physical._fixed_read(self.pool.root / 'control')
        self.assertEqual((control['operation'], control['next_slot']), (3, 4))
        self.assertNotEqual(paper.state_path(self.account).read_bytes(), self.before_paper)
        before = self.state_bytes() + ((self.pool.root / 'control').read_bytes(),)
        with self.assertRaises((StorePause, FileNotFoundError)):
            self.recover()
        with self.assertRaises((StorePause, FileNotFoundError)):
            self.finish()
        self.assertEqual(before, self.state_bytes() + ((self.pool.root / 'control').read_bytes(),))

    # Recover only the original result marker after a real committed Store cut.
    def test_actual_kill_after_commit_recovers_original_reserved_result(self):
        self.prepare()
        self.killed('raw_final_outcome_committed')
        before = self.state_bytes() + ((self.pool.root / 'control').read_bytes(),)
        result = self.recover()
        self.assertEqual(self.recover(), result)
        self.assertEqual(before, self.state_bytes() + ((self.pool.root / 'control').read_bytes(),))
        self.assertEqual(self.pool.completed()['slot'], 3)

    # Refuse a reserved operation cut before any native slot is consumed.
    def test_actual_kill_after_reservation_preserves_native_preimage(self):
        self.prepare()
        self.killed('raw_final_reserved')
        self.assertEqual(paper.state_path(self.account).read_bytes(), self.before_paper)
        self.assertEqual(self.pool.completed()['slot'], 2)
        before = self.state_bytes() + ((self.pool.root / 'control').read_bytes(),)
        with self.assertRaises((StorePause, FileNotFoundError)):
            self.finish()
        self.assertEqual(before, self.state_bytes() + ((self.pool.root / 'control').read_bytes(),))

    # Poison save/capture uncertainty even when the synthetic executor catches its error.
    def test_caught_capture_failure_cannot_save_again_or_replay_close(self):
        self.io = reserved_io.SyntheticNativeIO(self.pool, catching_trade,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.client, self.birth = self.nightly._initialize(self.context, raw_checkpoint=self.raw, native_io=self.io)
        original_capture = self.raw.capture

        # Inject failure only after the next real native save has returned.
        def after_native(point):
            if point == 'native_returned':
                self.raw.capture = failed_capture

        # Represent an explicit synthetic checkpoint-recording failure, not native IO failure.
        def failed_capture(*args, **kwargs):
            raise ValueError('SYNTHETIC capture uncertainty')

        self.pool._point = after_native
        with self.assertRaises(ValueError):
            self.nightly._close(self.context, self.client, '2019-02-28', birth=self.birth,
                previous=self.birth, raw_checkpoint=self.raw, native_io=self.io)
        self.raw.capture = original_capture
        self.assertTrue(self.io.failed)
        self.assertEqual(self.pool.completed()['slot'], 1)
        before = self.state_bytes() + ((self.pool.root / 'control').read_bytes(),)
        with self.assertRaises(StorePause):
            self.nightly._close(self.context, self.client, '2019-02-28', birth=self.birth,
                previous=self.birth, raw_checkpoint=self.raw, native_io=self.io)
        self.assertEqual(self.context.policy_calls, 1)
        self.assertEqual(before, self.state_bytes() + ((self.pool.root / 'control').read_bytes(),))

    # Refuse an intervening completed save before any additional native effect.
    def test_intervening_writer_cursor_is_not_adopted(self):
        directory = self.account / 'operations' / 'SYNTHETIC-cursor'
        directory.mkdir(mode=0o700)
        self.io.begin(self.nightly, directory, self.case.fixture.legacy)
        self.pool.save(paper.PaperState(), expected_preimage=None)
        before = (self.pool.root / 'control').read_bytes(), paper.state_path(self.account).read_bytes()
        with self.assertRaisesRegex(ValueError, 'cursor changed'):
            self.io.save(self.account, paper.PaperState())
        self.assertEqual(before, ((self.pool.root / 'control').read_bytes(), paper.state_path(self.account).read_bytes()))

    # Refuse missing reserved-mode metadata rather than downgrading committed recovery.
    def test_missing_auxiliary_cannot_downgrade_final_recovery(self):
        self.prepare()
        result = self.finish()
        self.nightly.expected_head = result['head']
        _, directory = self.producer.operation(self.nightly, self.submission_head)
        (directory / 'reserved-native-save.json').unlink()
        prepared = packet._decode((directory / 'prepared.json').read_bytes())
        prepared.pop('reserved_native_io')
        (directory / 'prepared.json').write_bytes(fixture.demand.encoded(prepared))
        before = self.state_bytes()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.recover()
        self.assertEqual(before, self.state_bytes())

    # Refuse a different function from the same pinned executor source before effects.
    def test_executor_identity_and_existing_account_refuse_before_save(self):
        self.io.trade = catching_trade
        with self.assertRaisesRegex(ValueError, 'executor differs'):
            self.io.guard()
        self.io.trade = synthetic_trade
        path = paper.state_path(self.account)
        path.write_bytes(b'SYNTHETIC existing account must never be adopted')
        before = path.read_bytes(), (self.pool.root / 'control').read_bytes()
        with self.assertRaisesRegex(ValueError, 'preimage'):
            self.nightly._initialize(self.context, raw_checkpoint=self.raw, native_io=self.io)
        self.assertEqual(before, (path.read_bytes(), (self.pool.root / 'control').read_bytes()))
