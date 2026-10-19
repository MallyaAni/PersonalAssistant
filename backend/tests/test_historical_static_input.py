"""NEW private static-input admission assertions; actual broker results are never precomputed."""
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
from backend.market import historical_static_request_admission as static_admission
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_static_input_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


STATIC_OBSERVATIONS, STATIC_UNITS = [], []

# Exercise pre-callback materialization and original metadata-only recovery.
class StaticInputTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        bad = self._testMethodName in ('test_a_old_final5_late_static_failure', 'test_b_static_refusal_before_flush')
        self.f = fixture.Fixture(self._testMethodName, baseline=self._testMethodName.startswith('test_a_'),
            program='stage_bad_future_qty' if bad else 'stage_program')


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
            if frame.f_code is static_admission.STATIC_CODE:
                kind = 'static_predicate'
            elif frame.f_code is self.f.settlement._requests.__code__:
                kind = 'full_requests'
            elif frame.f_code is self.f.settlement._unique.__code__:
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

    # Observe the original Final5 filling the current order before rejecting an authenticated future intent.
    def test_a_old_final5_late_static_failure(self):
        self.submitted()
        f, before = self.f, self.state()
        with self.assertRaisesRegex(ValueError, 'Original positive whole desired quantity'):
            self.profiled(self.finish)
        self.assertTrue(any(row == ['flush', True] for row in self.trace))
        self.assertTrue(any(row == ['full_requests', True] for row in self.trace))
        self.assertEqual([row['filled_qty'] for row in f.client._orders.values()], ['5'])
        self.assertEqual((self.state()[0], f.writer._control()['next_slot'], f.store.snapshot()['head']),
            (before[0], 3, self.head))
        STATIC_UNITS.append({'scope': 'ACTUAL_UNCHANGED_FINAL5_NEGATIVE_BASELINE_NOT_ACCEPTANCE',
            'trace': self.trace, 'filled_qty': '5', 'native_save_advance': False})
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Reject the same original malformed future quantity before flush or output materialization.
    def test_b_static_refusal_before_flush(self):
        self.submitted()
        f, before = self.f, self.state()
        with self.assertRaisesRegex(ValueError, 'Original positive whole desired quantity'):
            self.profiled(self.finish)
        self.assertEqual(self.state(), before)
        self.assertEqual([row['status'] for row in f.client._orders.values()], ['accepted'])
        self.assertEqual([row['filled_qty'] for row in f.client._orders.values()], ['0'])
        self.assertEqual([row for row in self.trace if row[0] == 'static_predicate'], [['static_predicate', False]])
        self.assertFalse(any(row[0] in ('flush', 'native_asdict', 'orders_copy', 'full_requests') for row in self.trace))
        self.assertTrue(f.io.failed and f.binding._control()['failed'])
        self.assertIsNone(f.final.prepared_input)
        self.assertIsNone(f.final.request_admission)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Compare the derived static subset with the unchanged full predicate on independent declared unit data.
    def test_c_static_predicate_reference_units(self):
        original = self.f.settlement._requests
        derived = static_admission.predicate(original)
        observed = fixture.native._instant('2019-03-01T14:45:33+00:00')
        cases = ('valid', 'missing_acknowledged', 'bad_symbol', 'bad_side', 'bad_qty',
            'too_many_submitted', 'wrong_symbol', 'wrong_side', 'future_submitted', 'future_unsent')
        outcomes = []
        for case in cases:
            with self.subTest(case=case):
                state, orders = self.reference_inputs(case)
                native_before = transition.native_bytes(state, 1048576)
                order_before = deepcopy(orders)
                results = []
                for function in (original, derived):
                    try:
                        value = function(deepcopy(state), deepcopy(orders), observed)
                    except (ValueError, TypeError, AttributeError) as error:
                        results.append(('REFUSED', type(error).__name__, str(error)))
                    else:
                        results.append(('OK', sorted(value)))
                self.assertEqual(results[0], results[1])
                self.assertEqual(transition.native_bytes(state, 1048576), native_before)
                self.assertEqual(orders, order_before)
                outcomes.append({'case': case, 'result': results[0]})
        state, orders = self.reference_inputs('valid')
        orders[0]['status'] = 'accepted'
        with self.assertRaisesRegex(ValueError, 'outcome remains unresolved'):
            original(state, orders, observed)
        self.assertEqual(derived(state, orders, observed), {'unit'})
        STATIC_UNITS.append({'scope': 'SYNTHETIC_PURE_PREDICATE_DATA_NOT_REAL_FILLS_OR_CYCLE_ADMISSION',
            'comparisons': outcomes, 'accepted_outcome_check_intentionally_postflush': True})

    # Produce independent finite reference declarations rather than pretending unit status values are real broker results.
    def reference_inputs(self, case):
        state = paper.PaperState(start_equity=float('nan'), history=[{'text': 'é', 'value': float('nan')}],
            pending=[{'client_order_id': 'unit', 'symbol': 'AAPL', 'side': 'buy', 'qty': 8,
                'session': '2019-03-01', 'execution': {'submitted_at': '2019-03-01T14:45:31+00:00'}}])
        orders = [{'client_order_id': 'unit', 'symbol': 'AAPL', 'side': 'buy', 'qty': '5',
            'submitted_at': '2019-03-01T14:45:31+00:00', 'status': 'filled', 'execution_phase': 'market'}]
        row = state.pending[0]
        if case == 'missing_acknowledged':
            orders = []
        elif case == 'bad_symbol':
            row['symbol'] = 'invalid symbol'
        elif case == 'bad_side':
            row['side'] = 'other'
        elif case == 'bad_qty':
            row['qty'] = True
        elif case == 'too_many_submitted':
            orders[0]['qty'] = '9'
        elif case == 'wrong_symbol':
            orders[0]['symbol'] = 'MSFT'
        elif case == 'wrong_side':
            orders[0]['side'] = 'sell'
        elif case == 'future_submitted':
            orders[0]['submitted_at'] = '2019-03-01T15:00:00+00:00'
        elif case == 'future_unsent':
            state.pending.append({'client_order_id': 'future', 'symbol': 'AAPL', 'side': 'buy',
                'qty': 8, 'session': '2019-03-01', 'execute_on': '2019-03-04'})
        return state, orders

    # Persist only static submission inputs while the real flush supplies all execution outcomes.
    def test_d_full_graph_static_inputs(self):
        self.submitted()
        f, descriptors, held = self.f, [], []

        # Observe input-only metadata and released native references before the actual writer save.
        def observe(point):
            if point == 'reserved_final_requests_ready':
                owner = f.final.request_admission
                self.assertIs(owner.prior, f.final.prepared_input.prior)
                self.assertIs(owner.client, f.client)
                self.assertFalse(owner.used)
                self.assertEqual(owner.binding['resolution_at'], f.inputs['at'])
                row = owner.binding['static_inputs']['submissions'][0]
                self.assertEqual(set(row), {'client_order_id', 'symbol', 'side', 'qty', 'submitted_at'})
                self.assertEqual(row['qty'], '5')
                descriptors.append(deepcopy(owner.binding))
                held.append(owner)
            if point == 'reserved_final_input_released':
                self.assertTrue(f.final.request_admission.closed and f.final.request_admission.used)
                self.assertIsNone(f.final.request_admission.prior)
                self.assertIsNone(f.final.request_admission.client)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual([row for row in trace if row[0] == 'static_predicate'], [['static_predicate', False]])
        self.assertEqual([row for row in trace if row[0] == 'full_requests'], [['full_requests', True]])
        self.assertEqual([row for row in trace if row[0] == 'orders_copy'], [['orders_copy', True]])
        self.assertIsNone(f.final.request_admission)
        self.reopen(result['head'])
        before = self.state()
        again, recovered = self.profiled(self.recover)
        self.assertEqual((again, recovered), (result, []))
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
        STATIC_OBSERVATIONS.append({'trace': trace, 'recovery_trace': recovered,
            'historical_recovery_trace': historical, 'descriptor': descriptors[0],
            'mutable_execution_fields_presnapshotted': False, 'full_ram_admitted': False})

    # Refuse held static-input metadata drift after consumption before any real resolution effect.
    def test_e_consumed_static_metadata_drift(self):
        self.submitted()
        f, before = self.f, self.state()

        # Change the held input descriptor only, preserving the original broker and persisted reservation bytes.
        def mutate(point):
            if point == 'reserved_final_requests_consumed':
                f.final.request_admission.binding['static_inputs']['submissions'][0]['qty'] = '6'

        f.store.fault = mutate
        with self.assertRaisesRegex(ValueError, 'unused static-input ownership'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertFalse(any(row[0] == 'flush' for row in self.trace))
        self.assertTrue(f.io.failed)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after static input preparation cannot reexecute its predicate or resolution during recovery.
    def test_f_before_resolution_cut(self):
        row = self.killed('reserved_final_requests_ready')
        self.assertFalse(row['used'])
        self.assertTrue(row['owned_prior'])
        self.assertEqual((row['writer']['next_slot'], row['head']), (3, self.head))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after real flush preserves actual filled broker evidence without resuming the consumed input scope.
    def test_g_after_resolution_cut(self):
        row = self.killed('reserved_final_resolved')
        self.assertTrue(row['used'] and row['owned_prior'])
        self.assertEqual((row['writer']['next_slot'], row['head']), (3, self.head))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A committed result recovers only its original missing marker and seals without any native input re-preparation.
    def test_h_committed_original_cut(self):
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

    # Caught premature consumption cannot authorize a second use of either the static or identity admission.
    def test_i_caught_static_consumption(self):
        self.submitted()
        f, before, caught = self.f, self.state(), []

        # Consume the original nested leases early and catch one duplicate attempt.
        def consume(point):
            if point == 'reserved_final_requests_ready':
                owner, original = f.final.request_admission, f.final.prepared_input
                owner.consume(original.prior, original.binding, owner.binding)
                try:
                    owner.consume(original.prior, original.binding, owner.binding)
                except ValueError:
                    caught.append(True)

        f.store.fault = consume
        with self.assertRaisesRegex(ValueError, 'unused static-input ownership'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(caught, [True])
        self.assertEqual(self.state(), before)
        self.assertFalse(any(row[0] == 'flush' for row in self.trace))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

