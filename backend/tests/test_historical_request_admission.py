"""NEW pre-resolution request admission assertions with an actual unchanged late-failure baseline."""
from copy import deepcopy
import hashlib
import copy
from dataclasses import asdict
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
from backend.market import historical_prepared_transition as transition
from backend.market import historical_request_admission as request_admission
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_request_admission_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


ADMISSION_OBSERVATIONS, UNIT_OBSERVATIONS = [], []

# Exercise pre-callback materialization and original metadata-only recovery.
class RequestAdmissionTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        bad = self._testMethodName in ('test_a_baseline_late_identity_failure', 'test_b_before_flush_identity_refusal')
        self.f = fixture.Fixture(self._testMethodName, baseline=self._testMethodName.startswith('test_a_'),
            program='stage_duplicate_journal' if bad else 'stage_program')


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
            None if f.binding is None else f.binding._control()['cursor'],
            f.metadata.read_latch('2019-03-01'))

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
    # Finish only the original submitted graph and supplied finite resolution declaration.
    def finish(self):
        return self.f.final._finish(submission_head=self.head, inputs=self.f.inputs)

    # Record native load and whole-input deepcopy timing without replacing original functions.
    def profiled(self, action):
        trace, resolved = [], [False]
        compile_events = []
        load_code = paper.load_state.__code__
        flush_code = fixture.native.ReplayBroker.flush.__code__
        copy_code, asdict_code = copy.deepcopy.__code__, asdict.__code__
        previous = sys.getprofile()

        # Observe the direct reconciliation order copy separately from nested broker-validation copies.
        def profile(frame, event, argument):
            if event == 'c_call' and argument is compile and frame.f_code is transition._certificate.__code__:
                compile_events.append(resolved[0])
            if event != 'call':
                return
            kind = None
            if frame.f_code is load_code:
                kind = 'load'
            elif frame.f_code is flush_code:
                kind = 'flush'
                resolved[0] = True
            elif frame.f_code is copy_code and type(frame.f_locals.get('x')) is paper.PaperState:
                kind = 'input_copy'
            elif frame.f_code is asdict_code and type(frame.f_locals.get('obj')) is paper.PaperState:
                kind = 'native_asdict'
            if frame.f_code is self.f.settlement._unique.__code__:
                kind = 'request_unique'
            elif frame.f_code is paper.apply_settlements.__code__:
                kind = 'native_apply'
            elif frame.f_code is transition._apply_owned_tail.__code__:
                kind = 'derived_tail'
            elif frame.f_code is copy_code:
                rows = frame.f_locals.get('x')
                if (frame.f_back is not None and frame.f_back.f_code is self.f.settlement.reconcile_raw.__code__
                        and type(rows) is list):
                    kind = 'orders_copy'
            if kind is not None:
                self.assertLess(len(trace), 64)
                trace.append([kind, resolved[0]])

        sys.setprofile(profile)
        try:
            result = action()
        finally:
            sys.setprofile(previous)
            self.trace = trace
            self.compile_events = compile_events
        return result, trace

    # Prepare one actual accepted submission, retaining its original authoritative parent head.
    def submitted(self):
        self.f.submitted()
        self.head = self.f.store.snapshot()['head']

    # Capture exact owned-input/native/broker metadata before an actual child process cut.
    def child(self, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Retain the full broker witness and original ownership without copying account state.
        def cut(boundary):
            if boundary == point:
                broker = codec.encode(f.client, **f.nightly.pins())
                owned = f.final.request_admission
                row = {'pid': os.getpid(), 'kind': 'request-admission', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'admission': owned.binding, 'used': owned.used,
                    'owned_prior': not owned.closed and owned.prior is owned.original_prior,
                    'released': owned.closed and owned.prior is None and owned.original_prior is None}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault = cut
        self.finish()
        raise AssertionError('Expected prepared-transition cut not reached')

    # Reap one owned process and reopen only its published Store bank for original recovery.
    def killed(self, point):
        self.submitted()
        f = self.f
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

    # Return only the original final result without another native state or input copy.
    def recover(self):
        return self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)

    # Reproduce the original late check using an authentic malformed journal saved by the synthetic producer.
    def test_a_baseline_late_identity_failure(self):
        self.submitted()
        f, before = self.f, self.state()
        with self.assertRaisesRegex(ValueError, 'Original unique paper request identities'):
            self.profiled(self.finish)
        self.assertTrue(any(row == ['flush', True] for row in self.trace))
        self.assertEqual([row['filled_qty'] for row in f.client._orders.values()], ['5'])
        self.assertEqual(f.store.snapshot()['head'], self.head)
        self.assertEqual(self.state()[0], before[0])
        self.assertEqual(f.writer._control()['next_slot'], 3)
        self.assertTrue(f.io.failed)
        UNIT_OBSERVATIONS.append({'scope': 'ACTUAL_UNCHANGED_FINAL4_NEGATIVE_BASELINE_NOT_ACCEPTANCE',
            'real_flush': True, 'filled_qty': '5', 'save_advance': False, 'trace': self.trace})
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertFalse(any(row[0] in ('load', 'flush', 'native_asdict', 'derived_tail', 'request_unique') for row in trace))

    # Refuse the same original duplicate identities before resolution or native output materialization.
    def test_b_before_flush_identity_refusal(self):
        self.submitted()
        f, before = self.f, self.state()
        with self.assertRaisesRegex(ValueError, 'Original unique paper request identities'):
            self.profiled(self.finish)
        self.assertEqual(self.state(), before)
        self.assertEqual([row['status'] for row in f.client._orders.values()], ['accepted'])
        self.assertEqual([row['filled_qty'] for row in f.client._orders.values()], ['0'])
        self.assertEqual([row for row in self.trace if row[0] == 'request_unique'],
                         [['request_unique', False], ['request_unique', False]])
        self.assertFalse(any(row[0] in ('flush', 'native_asdict', 'derived_tail', 'orders_copy') for row in self.trace))
        self.assertTrue(f.io.failed and f.binding._control()['failed'])
        self.assertIsNone(f.final.prepared_input)
        self.assertIsNone(f.final.request_admission)
        with self.assertRaises((ValueError, FileNotFoundError)):
            f.io.evidence()
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Keep finite metadata/type/ownership negative units distinct from whole Cycle admission.
    def test_c_typed_input_units(self):
        unique, scope = self.f.settlement._unique, 'SYNTHETIC_UNITS_NOT_CYCLE_ADMISSION'
        bad = [('pending', None), ('pending', [1]), ('pending', [{'client_order_id': ''}]),
               ('pending', [{'client_order_id': True}]),
               ('journal', [{'client_order_id': 'x'}, {'client_order_id': 'x'}])]
        for field, rows in bad:
            with self.subTest(field=field, rows=rows):
                prior = paper.PaperState()
                setattr(prior, field, rows)
                binding = self.unit_binding(prior, scope)
                with self.assertRaises(ValueError):
                    unique(rows)
                with self.assertRaises(ValueError):
                    request_admission.RequestAdmission(prior, binding, unique)
        prior = paper.PaperState(pending=[{'client_order_id': 'original'}])
        binding = self.unit_binding(prior, scope)
        admission = request_admission.RequestAdmission(prior, binding, unique)
        descriptor = deepcopy(admission.binding)
        wrong = deepcopy(descriptor)
        wrong['counts']['pending'] = True
        with self.assertRaises(ValueError):
            request_admission.read_descriptor(wrong, request_admission.base(binding, unique), unique)
        wrong = deepcopy(descriptor)
        wrong['head'] = 'f' * 64
        with self.assertRaises(ValueError):
            admission.check(prior, binding, wrong)
        with self.assertRaises(ValueError):
            admission.check(deepcopy(prior), binding, descriptor)
        admission.consume(prior, binding, descriptor)
        with self.assertRaises(ValueError):
            admission.consume(prior, binding, descriptor)
        admission.close()
        admission.check_released(binding, descriptor)
        self.assertIsNone(admission.prior)
        huge = paper.PaperState(pending=[{'client_order_id': 'x' * 262144}])
        with self.assertRaisesRegex(ValueError, 'bounded request admission'):
            request_admission.RequestAdmission(huge, self.unit_binding(huge, scope), unique)
        UNIT_OBSERVATIONS.append({'scope': scope, 'predicate_refusals': len(bad),
            'strict_bool_head_foreign_ownership_once_only_and_payload_bound': True})

    # Bind finite negative units to explicit input metadata without pretending they are armed producer phases.
    def unit_binding(self, prior, scope):
        return {'identity': self.f.identity, 'account': str(self.f.nightly.root), 'phase': 'OUTCOME_COMMITTED',
            'head': 'b' * 64, 'native_io_sha256': 'c' * 64, 'native_bytes': transition.native_bytes(prior, 1048576),
            'scope': scope, 'raw_limit': 1048576}

    # Complete the real private graph while observing only original input checks before actual resolution.
    def test_d_full_graph_original_admission(self):
        self.submitted()
        f, descriptors, owners = self.f, [], []

        # Observe a persisted original admission before consume and released ownership before native save.
        def observe(point):
            if point == 'reserved_final_requests_ready':
                owned = f.final.request_admission
                self.assertIs(owned.prior, f.final.prepared_input.prior)
                self.assertFalse(owned.used)
                self.assertEqual(owned.binding['counts'], {'pending': 1, 'journal': 0})
                self.assertEqual(owned.binding['head'], self.head)
                self.assertEqual(owned.binding['native_io_sha256'], f.io.evidence()['reservation_sha256'])
                descriptors.append(deepcopy(owned.binding))
                owners.append(owned)
            if point == 'reserved_final_input_released':
                self.assertTrue(f.final.request_admission.closed and f.final.request_admission.used)
                self.assertIsNone(f.final.request_admission.prior)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual([row for row in trace if row[0] == 'request_unique'],
            [['request_unique', False], ['request_unique', False], ['request_unique', True], ['request_unique', True]])
        self.assertEqual([row for row in trace if row[0] == 'orders_copy'], [['orders_copy', True]])
        self.assertTrue(owners[0].closed and owners[0].used)
        self.assertIsNone(f.final.request_admission)
        self.reopen(result['head'])
        before = self.state()
        again, recovered = self.profiled(self.recover)
        self.assertEqual(again, result)
        self.assertEqual(recovered, [])
        self.assertEqual(self.state(), before)
        close = f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io)
        self.reopen(result['head'])
        before = self.state()
        again, historical = self.profiled(self.recover)
        self.assertEqual((again, historical), (result, []))
        self.assertEqual(f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io), close)
        self.assertEqual(self.state(), before)
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty']), (8, 5))
        self.assertEqual(f.context.policy_calls, 2)
        self.assertEqual(len(f.binding._control()['records']), 5)
        self.assertGreater(len(paper.state_path(f.nightly.root).read_bytes()), 262144)
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        ADMISSION_OBSERVATIONS.append({'trace': trace, 'recovery_trace': recovered,
            'historical_recovery_trace': historical, 'descriptor': descriptors[0],
            'native_results_presnapshotted': False, 'full_ram_admitted': False})

    # A caught premature duplicate consumption cannot authorize the original later flush.
    def test_e_caught_duplicate_consumption(self):
        self.submitted()
        f, before, caught = self.f, self.state(), []

        # Consume the original input admission early, catch a duplicate, then let the real pre-flush check refuse.
        def consume(point):
            if point == 'reserved_final_requests_ready':
                owned, original = f.final.request_admission, f.final.prepared_input
                owned.consume(original.prior, original.binding, owned.binding)
                try:
                    owned.consume(original.prior, original.binding, owned.binding)
                except ValueError:
                    caught.append(True)

        f.store.fault = consume
        with self.assertRaisesRegex(ValueError, 'unused request admission ownership'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(caught, [True])
        self.assertEqual(self.state(), before)
        self.assertFalse(any(row[0] == 'flush' for row in self.trace))
        self.assertTrue(f.io.failed)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after persisted identity admission cannot rerun the original predicate or resolution on recovery.
    def test_f_cut_before_resolution(self):
        row = self.killed('reserved_final_requests_ready')
        self.assertFalse(row['used'])
        self.assertTrue(row['owned_prior'])
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after real resolution retains actual broker results and never reuses the original consumed admission.
    def test_g_cut_after_resolution(self):
        row = self.killed('reserved_final_resolved')
        self.assertTrue(row['used'] and row['owned_prior'])
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Authoritative commitment recovers only the original missing result and seals after input ownership releases.
    def test_h_cut_committed_original(self):
        row = self.killed('reserved_final_committed')
        self.assertTrue(row['used'] and row['released'])
        self.assertEqual(row['writer']['next_slot'], 4)
        before = self.state()
        result, trace = self.profiled(self.recover)
        self.assertEqual(trace, [])
        self.assertEqual(result['head'], row['head'])
        self.assertEqual(self.state(), before)
        again, trace = self.profiled(self.recover)
        self.assertEqual((again, trace), (result, []))
        self.assertEqual(self.state(), before)

    # Recheck the original frozen admission after its interruption hook and before real broker resolution.
    def test_i_consumed_descriptor_drift(self):
        self.submitted()
        f, before = self.f, self.state()

        # Mutate only held metadata after consume, retaining valid paper and the original persisted reservation.
        def mutate(point):
            if point == 'reserved_final_requests_consumed':
                f.final.request_admission.binding['counts']['pending'] = True

        f.store.fault = mutate
        with self.assertRaisesRegex(ValueError, 'unused request admission ownership'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertFalse(any(row[0] == 'flush' for row in self.trace))
        self.assertTrue(f.io.failed)
        self.assertIsNone(f.final.request_admission)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

