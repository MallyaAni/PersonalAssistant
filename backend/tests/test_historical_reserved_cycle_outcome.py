"""NEW reserved resolver/final/Nightly assertions; no closed scenario is executed."""
from copy import deepcopy
import hashlib
import multiprocessing
import os
from pathlib import Path
import signal
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_packet_demand as demand
from backend.market import historical_timing_packet as packet
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import synthetic_reserved_outcome_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


# Verify the complete new private seam on fresh accounts, never restored genuine state.
class ReservedCycleOutcomeTests(unittest.TestCase):
    # Allocate fresh physical pools before any native effect for this assertion.
    def setUp(self):
        self.f = fixture.Fixture(self._testMethodName)

    # Retain complete physical evidence and native globals while closing Store.
    def tearDown(self):
        PHYSICAL_OBSERVATIONS.append({'test': self._testMethodName, 'root': str(self.f.cas.root),
            'fields': ['st_dev', 'st_ino', 'st_size', 'st_blocks'],
            'before': self.f.before, 'after': self.f.inventory()})
        self.f.close()

    # Produce the new actual Stage graph once and retain the original submission head.
    def prepare(self):
        self.f.submitted()
        self.head = self.f.submission['head']

    # Read native/account/Store bytes without including the CAS seal that recovery may finish.
    def state(self):
        f = self.f
        return (paper.state_path(f.nightly.root).read_bytes(), codec.encode(f.client, **f.nightly.pins()),
            (f.writer.root / 'control').read_bytes(), (f.raw.root / 'control').read_bytes(),
            f.store.snapshot(), f.context.policy_calls, len(fixture.CALLS))

    # Reopen only with the original pool and independently observed authoritative head.
    def reopen(self, head):
        f = self.f
        root = f.store.root
        f.store.close()
        f.cas = cas.ReservedCAS(root / 'reserved-blobs', identity=f.identity)
        f.store = Store(root, f.identity, head, blob_reservation=f.cas)
        f.nightly.store, f.nightly.expected_head = f.store, head

    # Execute one owned child until its actual declared SIGKILL boundary.
    def child(self, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Retain actual native broker bytes and source-bound boundary identity before killing.
        def cut(boundary):
            if boundary == point:
                broker = codec.encode(f.client, **f.nightly.pins())
                row = {'pid': os.getpid(), 'point': point, 'head': f.store.snapshot()['head'],
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'broker_raw': broker.decode(), 'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'policy_calls': f.context.policy_calls}
                f.legacy.write_once(f.nightly.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault = cut
        result = f.final._finish(submission_head=self.head, inputs=f.inputs)
        if point == 'reserved_phase_result_written':
            f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
                previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io)
        raise AssertionError('Actual cut was not reached')

    # Bound, reap and authenticate a killed child before inspecting its preserved metadata.
    def killed(self, point):
        self.prepare()
        self.f.store.close()
        child = multiprocessing.get_context('fork').Process(target=self.child, args=(point,))
        try:
            watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM}
            old = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                child.start()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
            child.join(timeout=20)
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode, -signal.SIGKILL)
            row = packet._decode((self.f.nightly.root / 'actual-child-cut.json').read_bytes())
            self.assertEqual((row['pid'], row['point']), (child.pid, point))
            self.assertEqual(hashlib.sha256(row['broker_raw'].encode()).hexdigest(), row['broker_sha256'])
            self.reopen(row['head'])
            end = {'pid': child.pid, 'point': point, 'head': row['head'], 'exitcode': child.exitcode,
                   'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}
            self.f.legacy.write_once(self.f.nightly.root / 'actual-child-exit.json', demand.encoded(end))
            ACTUAL_KILL_FILES.append((str(self.f.nightly.root / 'actual-child-cut.json'),
                                     str(self.f.nightly.root / 'actual-child-exit.json')))
            self.assertEqual(hashlib.sha256(paper.state_path(self.f.nightly.root).read_bytes()).hexdigest(),
                             row['paper_sha256'])
            return row
        finally:
            if child.pid is not None and child.is_alive():
                child.terminate()
                child.join(timeout=1)
                if child.is_alive():
                    child.kill()
                    child.join(timeout=1)
            if child.pid is not None:
                self.assertFalse(child.is_alive())
                child.close()

    # Recover only the original final metadata using its externally observed committed head.
    def recover(self):
        return self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)

    # Pause an interrupted attempt without changing native bytes, broker, head or counters.
    def assert_open(self):
        before = self.state()
        for action in (self.recover, lambda: self.f.final._finish(submission_head=self.head, inputs=self.f.inputs)):
            with self.assertRaises(ValueError):
                action()
            self.assertEqual(self.state(), before)
        self.assertEqual(self.f.cas._control()['groups'][-1]['status'], 'ACTIVE')

    # Prove actual native partial reconciliation, reserved save, commit and same-session Nightly.
    def test_a_full_final_reopen_and_same_session_nightly(self):
        self.prepare()
        f = self.f
        result = f.final._finish(submission_head=self.head, inputs=f.inputs)
        state = paper.load_state(f.nightly.root)
        self.assertEqual(state.pending, [])
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty'],
                          state.journal[0]['status']), (8, 5, 'partial'))
        self.assertEqual(f.client._orders['SYNTHETIC-reserved-outcome']['status'], 'filled')
        self.assertGreater(len(paper.state_path(f.nightly.root).read_bytes()), 262144)
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        self.reopen(result['head'])
        before = self.state()
        self.assertEqual(self.recover(), result)
        self.assertEqual(self.recover(), result)
        self.assertEqual(self.state(), before)
        close = f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io)
        value = f.nightly.read_lifecycle(close, raw_checkpoint=f.raw)['value']
        self.assertEqual((value['previous'], f.context.policy_calls), (result['receipt'], 2))
        self.assertEqual(f.store.snapshot()['head'], result['head'])
        before = self.state()
        self.assertEqual(f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io), close)
        self.assertEqual(self.state(), before)
        self.assertEqual([g['status'] for g in f.cas._control()['groups']], ['COMPLETE'] * 7)

    # A reservation cut occurs before native flush and never grants another attempt.
    def test_b_actual_kill_before_resolution(self):
        row = self.killed('reserved_final_reserved')
        broker = codec.restore(row['broker_raw'].encode(), expected_sha256=row['broker_sha256'],
                               **self.f.nightly.pins())
        self.assertEqual(len(broker._fills), 0)
        self.assert_open()

    # A real post-flush cut retains filled broker evidence without replay or account adoption.
    def test_c_actual_kill_after_resolution(self):
        row = self.killed('reserved_final_resolved')
        broker = codec.restore(row['broker_raw'].encode(), expected_sha256=row['broker_sha256'],
                               **self.f.nightly.pins())
        self.assertEqual(len(broker._fills), 1)
        self.assert_open()

    # Prepared-file tampering must refuse before authoritative OUTCOME commitment.
    def test_d_prepared_tamper_before_commit(self):
        self.prepare()
        f = self.f

        # Change only persisted prepared metadata at the producer's explicit precommit boundary.
        def change(point):
            if point == 'reserved_final_prepared':
                _, directory = f.final_ns['operation'](f.nightly, self.head)
                path = directory / 'prepared.json'
                value = packet._decode(path.read_bytes())
                value['receipt'] = '0' * 64
                path.write_bytes(demand.encoded(value))

        f.store.fault = change
        with self.assertRaisesRegex(ValueError, 'Prepared'):
            f.final._finish(submission_head=self.head, inputs=f.inputs)
        self.assertEqual(f.store.snapshot()['head'], self.head)
        self.assertEqual(f.cas._control()['groups'][-1]['status'], 'PAUSED')

    # Caught post-resolution uncertainty blocks later native saves and evidence.
    def test_e_changed_reservation_after_resolution(self):
        self.prepare()
        f = self.f
        before = paper.state_path(f.nightly.root).read_bytes()

        # Alter the original reservation after the actual broker effect, never a callback prompt.
        def change(point):
            if point == 'reserved_final_resolved':
                _, directory = f.final_ns['operation'](f.nightly, self.head)
                path = directory / 'reservation.json'
                value = packet._decode(path.read_bytes())
                value['declaration']['request']['prices']['AAPL'] = 99
                path.write_bytes(demand.encoded(value))

        f.store.fault = change
        with self.assertRaises(ValueError):
            f.final._finish(submission_head=self.head, inputs=f.inputs)
        self.assertEqual(paper.state_path(f.nightly.root).read_bytes(), before)
        self.assertEqual((len(f.client._fills), f.store.snapshot()['head']), (1, self.head))
        self.assertEqual(f.cas._control()['groups'][-1]['status'], 'PAUSED')
        with self.assertRaises(ValueError):
            f.io.save(f.nightly.root, paper.load_state(f.nightly.root))
        with self.assertRaises(ValueError):
            f.io.evidence()

    # Prepared but uncommitted state cannot authorize a new append or native operation.
    def test_f_actual_kill_after_prepared(self):
        self.killed('reserved_final_prepared')
        self.assert_open()

    # Post-commit recovery finishes only the original missing marker and phase seal.
    def test_g_actual_kill_after_commit(self):
        self.killed('reserved_final_committed')
        before = self.state()
        result = self.recover()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.recover(), result)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.cas._control()['groups'][-1]['status'], 'COMPLETE')

    # Nightly refuses an unsealed original result until metadata-only final recovery seals it.
    def test_h_actual_kill_after_original_result(self):
        self.killed('reserved_final_result_written')
        _, directory = self.f.final_ns['operation'](self.f.nightly, self.head)
        result = packet._decode((directory / 'result.json').read_bytes())
        with self.assertRaises(ValueError):
            self.f.nightly.raw_predecessor(result['receipt'], raw_checkpoint=self.f.raw)
        before = self.state()
        self.assertEqual(self.recover(), result)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.nightly.raw_predecessor(result['receipt'],
            raw_checkpoint=self.f.raw)['phase'], 'RAW_CYCLE_OUTCOME')

    # Same-session Nightly can finish only its original result seal after an actual process cut.
    def test_i_actual_kill_after_nightly_result(self):
        row = self.killed('reserved_phase_result_written')
        self.assertEqual(row['policy_calls'], 2)
        result = self.recover()
        before = self.state()
        close = self.f.nightly._close(self.f.context, self.f.client, '2019-03-01',
            birth=self.f.birth, previous=result['receipt'], raw_checkpoint=self.f.raw,
            native_io=self.f.nightly_io)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.nightly.read_lifecycle(close, raw_checkpoint=self.f.raw)['value']['previous'],
                         result['receipt'])
        self.assertEqual(self.f.cas._control()['groups'][-1]['status'], 'COMPLETE')

    # Public entry, nonfinite inputs and altered original stage metadata refuse before arm.
    def test_j_public_input_and_stage_binding_refusals(self):
        self.prepare()
        f = self.f
        before, groups = self.state(), len(f.cas._control()['groups'])
        with self.assertRaises(StorePause):
            f.final_ns['execute']()
        invalid = deepcopy(f.inputs)
        invalid['prices']['AAPL'] = float('nan')
        with self.assertRaises(ValueError):
            f.final._finish(submission_head=self.head, inputs=invalid)
        path = f.stage._directory('DECISION_FROZEN') / 'prepared.json'
        value = packet._decode(path.read_bytes())
        value['native_io']['effect_binding'] = '0' * 64
        path.write_bytes(demand.encoded(value))
        with self.assertRaises(ValueError):
            f.final._finish(submission_head=self.head, inputs=f.inputs)
        self.assertEqual(self.state(), before)
        self.assertEqual(len(f.cas._control()['groups']), groups)
