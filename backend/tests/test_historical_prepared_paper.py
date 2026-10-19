"""NEW owned prepared-paper assertions; no full RAM or genuine admission claim."""
from copy import deepcopy
import hashlib
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_prepared_paper_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS, BASELINE_OBSERVATIONS = [], [], []


PREPARATION_OBSERVATIONS = []

# Exercise pre-callback materialization and original metadata-only recovery.
class PreparedPaperTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        program = {'test_b_binding_mutation': 'tamper_binding_program',
            'test_c_unhanded_state_mutation': 'tamper_state_program',
            'test_e_foreign_object_after_acceptance': 'foreign_save_program',
            'test_f_caught_duplicate_handoff': 'duplicate_load_program'}.get(self._testMethodName, 'stage_program')
        self.f = fixture.Fixture(self._testMethodName, program=program)

    # Retain initialized metadata and actual original directory observations without deleting evidence.
    def tearDown(self):
        f = self.f
        PHYSICAL_OBSERVATIONS.append({'test': self._testMethodName,
            'fields': ['st_dev', 'st_ino', 'st_size', 'st_blocks'],
            'cas_root': str(f.cas.root), 'before': f.before, 'after': f.inventory(),
            'metadata_root': str(f.metadata.root), 'metadata_before': f.metadata_before,
            'metadata_after': f.metadata_inventory(), 'metadata_names': sorted(p.name for p in f.metadata.root.iterdir()),
            'sqlite_root': str(f.sql.directory), 'sqlite_before': f.sql_before,
            'sqlite_after': f.sql_inventory(), 'sqlite_names': sorted(p.name for p in f.sql.directory.iterdir()),
            'directory_root': None if f.binding is None else str(f.binding.root),
            'directory_before': f.directory_before,
            'directory_after': None if f.binding is None else f.directory_inventory(),
            'native_directories_before': f.native_directories_before,
            'native_directories_after': {name: native_directory.directory(f.writer.root if name == '.'
                else f.writer.root / name) for name in native_directory.DIRECTORIES}})
        f.close()

    # Observe native state and published cursors while permitting metadata-only phase sealing.
    def state(self):
        f = self.f
        path = paper.state_path(f.nightly.root)
        client = getattr(f, 'client', None)
        return (path.read_bytes() if path.exists() else None,
            None if client is None else codec.encode(client, **f.nightly.pins()),
            (f.writer.root / 'control').read_bytes(), (f.raw.root / 'control').read_bytes(),
            f.sql._control()['current'], f.context.policy_calls,
            None if f.binding is None else f.binding._control()['cursor'])

    # Reopen only original published Store and directory bindings without restoring an account or broker.
    def reopen(self, head):
        f = self.f
        root = f.store.root
        f.store.close()
        f.sql = sqlbanks.SQLiteBanks(root, identity=f.identity)
        f.cas = cas.ReservedCAS(root / 'reserved-blobs', identity=f.identity)
        f.metadata = protocol.MetadataSlots(root / 'reserved-protocol', identity=f.identity)
        f.binding = native_directory.DirectoryBindings(root, f.writer, identity=f.identity, metadata_pool=f.metadata)
        f.store = Store(root, f.identity, head, blob_reservation=f.cas,
            metadata_reservation=f.metadata, sqlite_reservation=f.sql, directory_binding=f.binding)
        f.nightly.store, f.nightly.expected_head = f.store, head

    # Repeatedly refuse a paused original operation without another native call or cursor advance.
    def paused(self, action):
        before = self.state()
        for _ in range(2):
            with self.assertRaises((ValueError, FileNotFoundError)):
                action()
            self.assertEqual(self.state(), before)

    # Profile only the unchanged native reader while running one bounded action.
    def profiled(self, action):
        calls = []
        code = paper.load_state.__code__
        previous = sys.getprofile()

        # Record actual native reader calls without replacing its function or globals.
        def profile(frame, event, argument):
            if event == 'call' and frame.f_code is code:
                self.assertLess(len(calls), 32)
                calls.append(frame.f_code.co_name)

        sys.setprofile(profile)
        try:
            result = action()
        finally:
            sys.setprofile(previous)
        return result, calls

    # Record one owned submission cut without reconstructing an account or prepared object.
    def child(self, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Preserve exact original binding/native/broker bytes before a protocol-boundary kill.
        def cut(boundary):
            if boundary == point:
                broker = codec.encode(f.client, **f.nightly.pins())
                prepared = f.stage.prepared
                row = {'pid': os.getpid(), 'kind': 'prepared-paper-submission', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(),
                    'directory': {key: f.binding._control()[key] for key in ('cursor', 'pending', 'failed')},
                    'preparation': prepared.binding, 'handed': prepared.handed,
                    'owned_identity': prepared.state is prepared.original}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault = cut
        f.submit_original()
        raise AssertionError('Expected prepared submission cut not reached')

    # Reap the owned child and retain its exact witness before metadata-only original recovery.
    def killed(self, point):
        f = self.f
        f.submitted(submit=False)
        self.head = f.store.snapshot()['head']
        f.store.close()
        process = multiprocessing.get_context('fork').Process(target=self.child, args=(point,))
        watched = {signal.SIGALRM, signal.SIGTERM, signal.SIGINT, signal.SIGHUP}
        try:
            old = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                process.start()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
            process.join(20)
        finally:
            old = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                if process.is_alive():
                    process.terminate()
                    process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join(1)
                pid, exitcode, alive = process.pid, process.exitcode, process.is_alive()
                if not alive:
                    process.close()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
        self.assertFalse(alive)
        self.assertEqual(exitcode, -9)
        row = fixture.packet._decode((f.root / 'actual-child-cut.json').read_bytes())
        self.assertEqual((row['pid'], row['point']), (pid, point))
        self.assertEqual(hashlib.sha256(row['broker_raw'].encode()).hexdigest(), row['broker_sha256'])
        ended = {'pid': pid, 'point': point, 'head': row['head'], 'exitcode': -9,
            'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}
        f.legacy.write_once(f.root / 'actual-child-exit.json', demand.encoded(ended))
        ACTUAL_KILL_FILES.append((str(f.root / 'actual-child-cut.json'), str(f.root / 'actual-child-exit.json')))
        self.reopen(row['head'])
        return row

    # Read the original immutable submission declaration without creating or materializing state.
    def recover_submission(self):
        f = self.f
        original, _ = f.stage._read(f.stage._directory('SUBMISSION_CAPTURED') / 'reservation.json')
        return f.stage._recover('SUBMISSION_CAPTURED', original['declaration'])

    # A preparation failure before the native load durably refuses all later effects and replay.
    def test_a_preparation_failure_before_load(self):
        f = self.f
        f.submitted(submit=False)
        before, callback_count = self.state(), len(fixture.CALLS)

        # Inject a declared product boundary failure without patching the original native reader.
        def fail(point):
            if point == 'reserved_paper_before_load':
                raise ValueError('SYNTHETIC preparation failure')

        f.store.fault = fail
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC preparation failure'):
            self.profiled(f.submit_original)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertEqual(len(fixture.CALLS), callback_count)
        self.assertEqual(f.client._orders, {})
        self.assertTrue(f.binding._control()['failed'])
        self.assertIsNone(f.stage.prepared)
        head = f.store.snapshot()['head']
        self.reopen(head)
        self.paused(f.submit_original)

    # Caught descriptor substitution refuses observation and any subsequent submission.
    def test_b_binding_mutation(self):
        f = self.f
        f.submitted(submit=False)
        before = self.state()
        with self.assertRaises(ValueError):
            f.submit_original()
        self.assertEqual(self.state(), before)
        self.assertEqual(f.client._orders, {})
        self.assertIn('caught_binding', fixture.EVENTS)
        self.assertTrue(fixture.CAPSULES[-1].closed)
        self.assertIsNone(fixture.CAPSULES[-1].state)
        self.paused(f.submit_original)

    # An unhanded object's changed native bytes refuse observation before any broker order.
    def test_c_unhanded_state_mutation(self):
        f = self.f
        f.submitted(submit=False)
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'Unhanded prepared native paper changed'):
            f.submit_original()
        self.assertEqual(self.state(), before)
        self.assertEqual(f.client._orders, {})
        self.assertTrue(fixture.CAPSULES[-1].closed)
        self.assertIsNone(fixture.CAPSULES[-1].state)

    # The real graph loads once before the callback and recovers only original persisted metadata.
    def test_d_full_graph_owned_state_and_profile(self):
        f = self.f
        f.submitted(submit=False)
        _, calls = self.profiled(f.submit_original)
        self.assertEqual(calls, ['load_state'])
        self.assertEqual([r[1] for r in fixture.EVENTS if type(r) is tuple and r[0] == 'owned_load'], [True])
        capsule = fixture.CAPSULES[-1]
        self.assertTrue(capsule.closed)
        self.assertIsNone(capsule.state)
        self.assertIsNone(capsule.original)
        self.assertIsNone(f.stage.prepared)
        original, _ = f.stage._read(f.stage._directory('SUBMISSION_CAPTURED') / 'reservation.json')
        submitted = f.stage._recover('SUBMISSION_CAPTURED', original['declaration'])
        self.assertEqual(submitted['value']['detail']['prepared_paper'], original['prepared_paper'])
        self.assertEqual(original['prepared_paper']['schema'], f.stage_ns['PAPER_SCHEMA'])
        before = self.state()
        _, calls = self.profiled(self.recover_submission)
        self.assertEqual(calls, [])
        self.assertEqual(self.state(), before)
        head = f.store.snapshot()['head']
        result = f.final._finish(submission_head=head, inputs=f.inputs)
        self.reopen(result['head'])
        before = self.state()
        self.assertEqual(f.final._recover(submission_head=head, inputs=f.inputs), result)
        self.assertEqual(self.state(), before)
        close = f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io)
        self.reopen(result['head'])
        before = self.state()
        self.assertEqual(f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io), close)
        self.assertEqual(self.state(), before)
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty']), (8, 5))
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        self.assertGreater(paper.state_path(f.nightly.root).stat().st_size, 262144)
        self.assertEqual(f.context.policy_calls, 2)
        self.assertEqual(len(f.binding._control()['records']), 5)
        PREPARATION_OBSERVATIONS.append({'native_submission_reader_calls': 1,
            'metadata_recovery_reader_calls': 0, 'released_owned_references': True,
            'binding': original['prepared_paper']})

    # Foreign state refusal retains the already accepted order and never saves or replays it.
    def test_e_foreign_object_after_acceptance(self):
        f = self.f
        f.submitted(submit=False)
        before, writer = paper.state_path(f.nightly.root).read_bytes(), f.writer._control()
        head = f.store.snapshot()['head']
        with self.assertRaises(ValueError):
            f.submit_original()
        self.assertEqual([o['qty'] for o in f.client._orders.values()], ['5'])
        self.assertEqual(paper.state_path(f.nightly.root).read_bytes(), before)
        self.assertEqual(f.writer._control(), writer)
        self.assertEqual(f.store.snapshot()['head'], head)
        self.assertIn('caught_foreign', fixture.EVENTS)
        self.assertTrue(fixture.CAPSULES[-1].closed)
        self.paused(f.submit_original)

    # Caught duplicate handoff cannot manufacture a second native state or enable a later save.
    def test_f_caught_duplicate_handoff(self):
        f = self.f
        f.submitted(submit=False)
        before, writer = paper.state_path(f.nightly.root).read_bytes(), f.writer._control()
        with self.assertRaises(ValueError):
            f.submit_original()
        self.assertEqual([o['qty'] for o in f.client._orders.values()], ['5'])
        self.assertEqual(paper.state_path(f.nightly.root).read_bytes(), before)
        self.assertEqual(f.writer._control(), writer)
        self.assertIn('caught_duplicate', fixture.EVENTS)
        self.assertTrue(fixture.CAPSULES[-1].closed)
        self.paused(f.submit_original)

    # Lost pre-effect prepared RAM after reservation never authorizes another materialization or callback.
    def test_g_actual_prepared_before_callback(self):
        row = self.killed('reserved_paper_reserved')
        self.assertFalse(row['handed'])
        self.assertTrue(row['owned_identity'])
        self.assertEqual(row['writer']['next_slot'], 2)
        self.assertEqual(row['head'], self.head)
        before = self.state()
        self.paused(self.recover_submission)
        self.assertEqual(self.state(), before)

    # Accepted-order handoff interruption retains the broker witness and stays paused without replay.
    def test_h_actual_owned_handoff_after_acceptance(self):
        row = self.killed('reserved_paper_handed')
        self.assertTrue(row['handed'])
        self.assertTrue(row['owned_identity'])
        self.assertEqual(row['writer']['next_slot'], 2)
        self.assertEqual(row['head'], self.head)
        self.paused(self.recover_submission)

    # A committed submission creates only its original result/seals with zero native loads on recovery.
    def test_i_actual_committed_original_recovery(self):
        row = self.killed('reserved_cycle_committed_SUBMISSION_CAPTURED')
        self.assertTrue(row['handed'])
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertNotEqual(row['head'], self.head)
        before = self.state()
        result, calls = self.profiled(self.recover_submission)
        self.assertEqual(calls, [])
        self.assertEqual(result['head'], row['head'])
        self.assertEqual(self.state(), before)
        again, calls = self.profiled(self.recover_submission)
        self.assertEqual(calls, [])
        self.assertEqual(again, result)
        self.assertEqual(self.state(), before)
