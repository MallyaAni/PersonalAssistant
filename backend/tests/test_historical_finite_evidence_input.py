"""NEW finite-evidence input admission; native diagnostic semantics and actual broker results remain unchanged."""
from copy import deepcopy
import math
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
from backend.market import historical_finite_evidence_input as finite_evidence
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_finite_evidence_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


EVIDENCE_OBSERVATIONS, EVIDENCE_UNITS = [], []

# Exercise pre-callback materialization and original metadata-only recovery.
class FiniteEvidenceTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        bad = self._testMethodName in ('test_a_old_final6_nonfinite_failure', 'test_b_nonfinite_refusal_before_flush')
        self.f = fixture.Fixture(self._testMethodName, baseline=self._testMethodName.startswith('test_a_'),
            program='stage_nonfinite_sender' if bad else ('stage_finite_sender_mismatch'
                if self._testMethodName == 'test_c_finite_anomaly_preserved' else 'stage_program'))


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
        compile_events, quantity_observations = [], []
        load_code = paper.load_state.__code__
        flush_code = fixture.native.ReplayBroker.flush.__code__
        copy_code, asdict_code = copy.deepcopy.__code__, asdict.__code__
        previous = sys.getprofile()

        # Observe the direct reconciliation order copy separately from nested broker-validation copies.
        def profile(frame, event, argument):
            if event == 'c_call' and argument is compile and frame.f_code is transition._certificate.__code__:
                compile_events.append(resolved[0])
            if event == 'return' and frame.f_code is paper._settlement_quantity_evidence.__code__:
                broker_qty, sender_qty, evidence = argument
                raw_sender = evidence.get('sender_qty')
                quantity_observations.append({'broker_qty': broker_qty, 'sender_qty': sender_qty,
                    'raw_sender_nonfinite': type(raw_sender) is float and not math.isfinite(raw_sender),
                    'anomalies': evidence.get('anomalies', []), 'filled_qty': frame.f_locals['filled']})
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
            if frame.f_code is finite_evidence.EvidenceInput.__init__.__code__:
                kind = 'evidence_input_prepare'
            elif frame.f_code is static_admission.STATIC_CODE:
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
            self.quantity_observations = quantity_observations
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
                owned = f.final.evidence_input
                row = {'pid': os.getpid(), 'kind': 'finite-evidence-input', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'evidence_input': owned.binding, 'used': owned.used,
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

    # Observe original Final6 preserving a native nonfinite diagnostic before its finite evidence encoding fails.
    def test_a_old_final6_nonfinite_failure(self):
        self.submitted()
        f, before = self.f, self.state()
        with self.assertRaisesRegex(ValueError, 'Out of range float values'):
            self.profiled(self.finish)
        self.assertTrue(any(row == ['flush', True] for row in self.trace))
        self.assertEqual([row['filled_qty'] for row in f.client._orders.values()], ['5'])
        self.assertEqual(self.quantity_observations, [{'broker_qty': 5, 'sender_qty': None,
            'raw_sender_nonfinite': True, 'anomalies': ['invalid_sender_qty'], 'filled_qty': 5}])
        self.assertEqual((self.state()[0], f.writer._control()['next_slot'], f.store.snapshot()['head']),
            (before[0], 3, self.head))
        EVIDENCE_UNITS.append({'scope': 'ACTUAL_UNCHANGED_FINAL6_NEGATIVE_BASELINE_NOT_ACCEPTANCE',
            'trace': self.trace, 'native_diagnostics': self.quantity_observations,
            'actual_filled_qty': '5', 'native_save_advance': False})
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Refuse only the unsupported finite encoding strategy before resolution, retaining original native NaN bytes.
    def test_b_nonfinite_refusal_before_flush(self):
        self.submitted()
        f, before = self.f, self.state()
        with self.assertRaisesRegex(ValueError, 'strict finite evidence strategy'):
            self.profiled(self.finish)
        self.assertEqual(self.state(), before)
        self.assertTrue(math.isnan(paper.load_state(f.nightly.root).pending[0]['sent']['qty']))
        self.assertEqual([row['filled_qty'] for row in f.client._orders.values()], ['0'])
        self.assertEqual([row['status'] for row in f.client._orders.values()], ['accepted'])
        self.assertFalse(any(row[0] in ('flush', 'native_asdict', 'orders_copy', 'full_requests') for row in self.trace))
        self.assertEqual(self.quantity_observations, [])
        self.assertTrue(f.io.failed and f.binding._control()['failed'])
        self.assertIsNone(f.final.evidence_input)
        self.assertIsNone(f.final.prepared_input)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Preserve finite native quantity disagreements as diagnostics while actual resolution and persistence succeed.
    def test_c_finite_anomaly_preserved(self):
        self.submitted()
        f = self.f
        result, trace = self.profiled(self.finish)
        expected = {'broker_qty': 5, 'sender_qty': 6, 'raw_sender_nonfinite': False,
                    'anomalies': ['broker_sender_disagreement'], 'filled_qty': 5}
        self.assertEqual(self.quantity_observations, [expected])
        self.assertTrue(any(row == ['flush', True] for row in trace))
        receipt = f.bridge.cycle._read_receipt(f.store, result['receipt'], f.nightly.pins(), raw_checkpoint=f.raw)
        settled = receipt['raw_reconciliation']['evidence']['settled'][0]
        self.assertEqual((settled['qty'], settled['filled_qty'], settled['submitted_qty'], settled['sender_qty']),
                         (8, 5, 5, 6))
        self.assertEqual(settled['quantity_evidence'], {'broker_qty': '5', 'sender_qty': 6,
            'anomalies': ['broker_sender_disagreement']})
        self.reopen(result['head'])
        before = self.state()
        again, recovered = self.profiled(self.recover)
        self.assertEqual((again, recovered), (result, []))
        self.assertEqual(self.state(), before)
        EVIDENCE_OBSERVATIONS.append({'scope': 'ACTUAL_FINITE_ANOMALY_NOT_REJECTED_AS_QUANTITY_POLICY',
            'diagnostics': expected, 'recovery_trace': recovered, 'actual_filled_qty': '5'})

    # Complete the real private graph with native NaN history outside the finite evidence-input projection.
    def test_d_full_graph_finite_strategy(self):
        self.submitted()
        f, descriptors, released = self.f, [], []

        # Observe original source/head admission and release before the real native writer save.
        def observe(point):
            if point == 'reserved_final_evidence_ready':
                owner = f.final.evidence_input
                self.assertIs(owner.prior, f.final.prepared_input.prior)
                self.assertFalse(owner.used)
                self.assertEqual(owner.binding['head'], self.head)
                self.assertEqual(owner.binding['strategy'], 'EXISTING_STRICT_FINITE_RECONCILIATION_2')
                descriptors.append(deepcopy(owner.binding))
            if point == 'reserved_final_input_released':
                self.assertTrue(f.final.evidence_input.closed and f.final.evidence_input.used)
                self.assertIsNone(f.final.evidence_input.prior)
                released.append(True)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual([row for row in trace if row[0] == 'evidence_input_prepare'], [['evidence_input_prepare', False]])
        self.assertEqual([row for row in trace if row[0] == 'orders_copy'], [['orders_copy', True]])
        self.assertEqual([row for row in trace if row[0] == 'full_requests'], [['full_requests', True]])
        self.assertEqual(released, [True])
        self.assertIsNone(f.final.evidence_input)
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
        EVIDENCE_OBSERVATIONS.append({'scope': 'ACTUAL_PRIVATE_GRAPH_FINITE_EVIDENCE_INPUT_STRATEGY',
            'trace': trace, 'recovery_trace': recovered, 'historical_recovery_trace': historical,
            'descriptor': descriptors[0], 'state_normalized': False, 'full_ram_admitted': False})

    # Keep finite-strategy type/bound/refusal units separate from whole Cycle or diagnostic policy admission.
    def test_e_input_strategy_units(self):
        for value in (None, True, 6, 'bad', {'source': 'raw'}):
            with self.subTest(value=value):
                prior = paper.PaperState(start_equity=float('nan'), history=[{'value': float('nan')}],
                    pending=[{'client_order_id': 'unit', 'sent': {'qty': value}, 'execution': {}}])
                binding = self.unit_binding(prior)
                before = transition.native_bytes(prior, 1048576)
                owner = finite_evidence.EvidenceInput(prior, binding)
                descriptor = deepcopy(owner.binding)
                wrong = deepcopy(descriptor)
                wrong['inputs']['bytes'] = True
                with self.assertRaises(ValueError):
                    finite_evidence.read_descriptor(wrong, binding)
                with self.assertRaises(ValueError):
                    owner.check(deepcopy(prior), binding, descriptor)
                owner.consume(prior, binding, descriptor)
                with self.assertRaises(ValueError):
                    owner.consume(prior, binding, descriptor)
                owner.close()
                owner.check_released(binding, descriptor)
                self.assertIsNone(owner.prior)
                self.assertEqual(transition.native_bytes(prior, 1048576), before)
        for execution in (None, [], 'bad'):
            prior = paper.PaperState(pending=[{'client_order_id': 'unit', 'execution': execution}])
            with self.assertRaisesRegex(ValueError, 'execution mapping'):
                finite_evidence.EvidenceInput(prior, self.unit_binding(prior))
        for value in (float('nan'), float('inf')):
            prior = paper.PaperState(pending=[{'client_order_id': 'unit', 'sent': {'qty': value}}])
            with self.assertRaisesRegex(ValueError, 'strict finite evidence strategy'):
                finite_evidence.EvidenceInput(prior, self.unit_binding(prior))
        prior = paper.PaperState(pending=[{'client_order_id': 'unit', 'execution': {'text': 'x' * 262144}}])
        with self.assertRaisesRegex(ValueError, 'strict finite evidence strategy'):
            finite_evidence.EvidenceInput(prior, self.unit_binding(prior))
        EVIDENCE_UNITS.append({'scope': 'SYNTHETIC_INPUT_UNITS_NOT_CYCLE_OR_QUANTITY_POLICY',
            'finite_anomaly_input_types_allowed': 5, 'shape_refusals': 3,
            'nonfinite_strategy_refusals': 2, 'bound_refusal': True})

    # Bind units to explicit original input bytes without claiming an armed graph or predicted broker result.
    def unit_binding(self, prior):
        return {'identity': self.f.identity, 'account': str(self.f.nightly.root), 'phase': 'OUTCOME_COMMITTED',
            'head': 'b' * 64, 'native_io_sha256': 'c' * 64, 'native_bytes': transition.native_bytes(prior, 1048576),
            'scope': 'SYNTHETIC_UNITS_NOT_ADMISSION'}

    # A cut after input strategy preparation cannot run its preparation or resolution again on recovery.
    def test_f_before_resolution_cut(self):
        row = self.killed('reserved_final_evidence_ready')
        self.assertFalse(row['used'])
        self.assertTrue(row['owned_prior'])
        self.assertEqual((row['writer']['next_slot'], row['head']), (3, self.head))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Actual post-flush uncertainty retains real broker evidence without replaying original input admission.
    def test_g_after_resolution_cut(self):
        row = self.killed('reserved_final_resolved')
        self.assertTrue(row['used'] and row['owned_prior'])
        self.assertEqual((row['writer']['next_slot'], row['head']), (3, self.head))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Authoritative outcome recovery publishes only its original missing result and seals after owner release.
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

    # Refuse held strategy metadata drift after consume before the original broker flush.
    def test_i_consumed_strategy_drift(self):
        self.submitted()
        f, before = self.f, self.state()

        # Change only owned descriptor metadata after consumption, retaining native and persisted original bytes.
        def mutate(point):
            if point == 'reserved_final_requests_consumed':
                f.final.evidence_input.binding['inputs']['bytes'] = True

        f.store.fault = mutate
        with self.assertRaisesRegex(ValueError, 'unused finite evidence-input ownership'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertTrue(f.io.failed)
        self.assertFalse(any(row[0] == 'flush' for row in self.trace))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

