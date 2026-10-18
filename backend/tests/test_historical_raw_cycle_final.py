"""New private raw final production/recovery assertions with real native storage.

Synthetic stage/context/policy/resolver inputs surround exact complete-source
producer/settlement/Nightly CodeTypes. Actual native fills, saves, Store commits
and four owned process SIGKILL cuts run; no closed test body is executed.
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


# Verify only this new final-producer seam over independently created synthetic accounts.
class RawCycleFinalTests(unittest.TestCase):
    # Reuse exact source/setup helpers without invoking any earlier test or scenario body.
    def setUp(self):
        self.case = fixture.RawCycleNightlyTests()
        self.case.setUp()
        self.nightly, self.raw = self.case.nightly, self.case.raw
        self.store, self.pins = self.case.store, self.case.pins
        self.context = self.case.context
        self.store_root, self.account = self.store.root, self.nightly.root
        self.writer = self.case.fixture.fixture.fixture.writer
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
        self.client, self.birth = self.case.fixture.birth()
        self.previous = self.case.fixture.close(self.client, '2019-02-28', self.birth, self.birth)
        prior = self.case.fixture.read(self.previous)
        self.lineage = {'schema': 'raw-nightly-cycle-lineage/1', 'birth': self.birth,
            'previous_nightly': self.previous, 'context': prior['context'],
            'context_identity': prior['context_identity']}
        body = fixture.demand.encoded({'scope': 'SYNTHETIC_RAW_FINAL_CONTEXT',
            'window': {'completed_at': '2019-03-01T14:45:00Z'}})
        self.case.cycle_context = {'raw': body.decode(), 'sha256': hashlib.sha256(body).hexdigest()}
        self.case.cycle_sha = hashlib.sha256(b'SYNTHETIC_RAW_FINAL_PRODUCER').hexdigest()
        self.case.lineage, self.case.client = self.lineage, self.client
        metadata_fixture.stage_namespace().ready(self.store, self.case.cycle_sha)
        self.case.commit_operation('DECISION_FROZEN', self.case.receipt(
            {'stage': 'DECISION_FROZEN', 'raw_nightly_lineage': self.lineage}))
        self.client.observe('2019-03-01T14:45:31.200000+00:00', {'AAPL': 100}, True)
        order = self.client.submit_market('AAPL', 5, 'buy', 'SYNTHETIC-cycle-bridge')
        state = paper.load_state(self.account)
        state.pending[0].update({'sent': {'qty': 5, 'at': order['submitted_at']},
            'execution': {'created_at': order['created_at'], 'submitted_at': order['submitted_at']}})
        paper.save_state(self.account, state)
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
            resolved=self.resolved, raw_checkpoint=self.raw)

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
        self.nightly.expected_head = head
        self.store.fault = self.trace

    # Complete actual native fold/save/Store commit, reopen and recover without more work.
    def test_private_producer_commit_reopen_and_same_session_nightly(self):
        self.prepare()
        produced = self.finish()
        state = paper.load_state(self.account)
        self.assertEqual(state.pending, [])
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty'],
                          state.journal[0]['status']), (8, 5, 'partial'))
        self.assertIn(b'NaN', paper.state_path(self.account).read_bytes())
        self.assertGreater(len(paper.state_path(self.account).read_bytes()), 262144)
        self.assertEqual(codec.encode(self.client, **self.pins), self.before_broker)
        self.assertEqual(self.points, ['raw_final_reserved', 'raw_final_reconciled',
            'raw_final_native_saved', 'raw_final_prepared', 'raw_final_outcome_committed'])
        self.reopen(produced['head'])
        before = self.state_bytes()
        self.assertEqual(self.recover(), produced)
        self.assertEqual(self.recover(), produced)
        self.assertEqual(self.state_bytes(), before)
        self.assertEqual(len(self.points), 5)
        final = self.case.bridge.read_final(self.store, produced['receipt_sha256'], self.pins,
            expected_head=produced['head'], raw_checkpoint=self.raw)
        self.assertEqual(final['receipt']['raw_final_operation']['reservation_sha256'],
                         produced['reservation_sha256'])
        self.case.fixture.legacy.market_daily.paper_trade = fixture.lifecycle.synthetic_trade
        close = self.case.fixture.close(self.client, '2019-03-01', self.birth, produced['receipt_sha256'])
        self.assertEqual(self.case.fixture.read(close)['previous'], produced['receipt_sha256'])
        self.assertEqual(self.store.snapshot()['head'], produced['head'])
        self.assertEqual(self.context.policy_calls, 2)

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

    # A killed reservation before fold preserves native bytes and cannot authorize replay.
    def test_actual_kill_after_reservation_stays_open_without_native_replay(self):
        self.prepare()
        self.killed('raw_final_reserved')
        self.assertEqual(paper.state_path(self.account).read_bytes(), self.before_paper)
        before = self.state_bytes()
        with self.assertRaisesRegex(StorePause, 'never re-execute'):
            self.recover()
        with self.assertRaisesRegex(StorePause, 'never re-execute'):
            self.finish()
        self.assertEqual(self.state_bytes(), before)
        self.assertEqual(self.context.policy_calls, 1)

    # A killed native save retains changed NaN bytes but no prepared result or new head.
    def test_actual_kill_after_native_save_never_repeats_fold_or_save(self):
        self.prepare()
        self.killed('raw_final_native_saved')
        self.assertNotEqual(paper.state_path(self.account).read_bytes(), self.before_paper)
        self.assertEqual(paper.load_state(self.account).pending, [])
        before = self.state_bytes()
        with self.assertRaisesRegex(StorePause, 'never re-execute'):
            self.finish()
        self.assertEqual(self.state_bytes(), before)
        self.assertEqual(self.store.snapshot()['head'], self.submission_head)

    # A prepared but uncommitted final is uncertain and may never append during recovery.
    def test_actual_kill_after_prepared_refuses_uncommitted_recovery(self):
        self.prepare()
        self.killed('raw_final_prepared')
        before = self.state_bytes()
        with self.assertRaisesRegex(StorePause, 'committed raw Cycle head'):
            self.recover()
        with self.assertRaisesRegex(StorePause, 'committed raw Cycle head'):
            self.finish()
        self.assertEqual(self.state_bytes(), before)
        self.assertEqual(self.store.snapshot()['head'], self.submission_head)

    # Only an exact committed outcome may finish a missing result marker after actual kill.
    def test_actual_kill_after_commit_recovers_only_original_result_marker(self):
        self.prepare()
        self.killed('raw_final_outcome_committed')
        _, directory = self.producer.operation(self.nightly, self.submission_head)
        self.assertFalse((directory / 'result.json').exists())
        before = self.state_bytes()
        result = self.recover()
        self.assertTrue((directory / 'result.json').exists())
        self.assertEqual(self.recover(), result)
        self.assertEqual(self.finish(), result)
        self.assertEqual(self.state_bytes(), before)
        self.assertNotEqual(result['head'], self.submission_head)
        self.assertIs(result['native_operation_committed'], False)
        self.assertIs(result['durable_simulator_adoption'], False)
        self.assertEqual(self.context.policy_calls, 1)

    # Public calls and invalid live inputs refuse before a producer reservation is created.
    def test_public_and_pre_reservation_component_guards(self):
        self.prepare()
        before = self.state_bytes()
        with self.assertRaisesRegex(StorePause, 'before effects'):
            self.producer.finalize(self.nightly, self.client)
        with self.assertRaisesRegex(StorePause, 'before effects'):
            self.producer.recover(self.nightly)
        self.assertEqual(self.state_bytes(), before)
        self.resolved['value'] = float('nan')
        with self.assertRaises(ValueError):
            self.finish()
        self.resolved.pop('value')
        state = paper.load_state(self.account)
        state.history[-1]['cash'] = -1
        paper.save_state(self.account, state)
        with self.assertRaisesRegex(ValueError, 'submission paper differs'):
            self.finish()
        _, directory = self.producer.operation(self.nightly, self.submission_head)
        self.assertFalse(directory.exists())
        self.assertEqual(self.points, [])

    # A post-preparation native mutation prevents the OUTCOME commit and remains paused.
    def test_post_prepared_component_change_stops_commit(self):
        self.prepare()

        # Inject a new native write at the defined boundary without altering producer code.
        def change(point):
            self.trace(point)
            if point == 'raw_final_prepared':
                state = paper.load_state(self.account)
                state.history[-1]['cash'] = -2
                paper.save_state(self.account, state)

        self.store.fault = change
        with self.assertRaisesRegex(StorePause, 'components changed before commit'):
            self.finish()
        self.assertEqual(self.store.snapshot()['head'], self.submission_head)
        before = self.state_bytes()
        with self.assertRaisesRegex(StorePause, 'committed raw Cycle head'):
            self.recover()
        self.assertEqual(self.state_bytes(), before)

    # Changed declarations cannot create a second operation or reinterpret a killed save.
    def test_conflicting_open_reservation_and_prepared_tamper_refuse(self):
        self.prepare()

        # Retain an injected prepared-boundary stop as an explicitly non-crash control.
        def stop(point):
            if point == 'raw_final_prepared':
                raise BoundaryCut('SYNTHETIC injected prepared cut')

        self.store.fault = stop
        with self.assertRaises(BoundaryCut):
            self.finish()
        before = self.state_bytes()
        self.resolved['scope'] = 'DIFFERENT_DECLARATION'
        with self.assertRaisesRegex(ValueError, 'reservation differs'):
            self.finish()
        self.resolved['scope'] = 'SYNTHETIC_RESOLVER_DECLARATION'
        _, directory = self.producer.operation(self.nightly, self.submission_head)
        prepared = packet._decode((directory / 'prepared.json').read_bytes())
        prepared['reservation_sha256'] = '0' * 64
        (directory / 'prepared.json').write_bytes(fixture.demand.encoded(prepared))
        with self.assertRaisesRegex(ValueError, 'prepared marker differs'):
            self.recover()
        self.assertEqual(self.state_bytes(), before)
