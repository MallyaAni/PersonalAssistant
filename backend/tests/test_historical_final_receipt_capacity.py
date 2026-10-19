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
from backend.market import historical_final_receipt_capacity as receipt_capacity
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_receipt_capacity_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


EVIDENCE_OBSERVATIONS, EVIDENCE_UNITS = [], []

# Exercise pre-callback materialization and original metadata-only recovery.
class ReceiptCapacityTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        large = self._testMethodName.startswith(('test_a_', 'test_b_'))
        self.f = fixture.Fixture(self._testMethodName, baseline=self._testMethodName.startswith('test_a_'),
            program='stage_large_annotation' if large else 'stage_moderate_annotation')


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
                owned = f.final.receipt_capacity
                row = {'pid': os.getpid(), 'kind': 'receipt-capacity', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'receipt_capacity': owned.binding, 'used': owned.used,
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

    # Reproduce the unchanged Final7 receipt cap after a real fill and native save on fresh original input.
    def test_a_old_final7_late_receipt_cap(self):
        self.submitted()
        f = self.f
        with self.assertRaises((ValueError, RuntimeError)) as error:
            self.profiled(self.finish)
        self.assertIn('cap', str(error.exception).lower())
        self.assertEqual([row['filled_qty'] for row in f.client._orders.values()], ['5'])
        self.assertEqual(f.writer._control()['next_slot'], 4)
        self.assertEqual(f.store.snapshot()['head'], self.head)
        state = paper.load_state(f.nightly.root)
        self.assertEqual(len(state.journal[0]['execution']['original_annotation']), 250000)
        self.assertEqual(state.journal[0]['quantity_evidence']['anomalies'], ['broker_sender_disagreement'])
        EVIDENCE_UNITS.append({'scope': 'ACTUAL_UNCHANGED_FINAL7_NEGATIVE_BASELINE_NOT_ACCEPTANCE',
            'reason': str(error.exception), 'filled_qty': '5', 'native_next_slot': 4, 'head_unchanged': True})
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Reject unavailable receipt bytes before resolution and output cloning while preserving accepted state.
    def test_b_large_input_refused_before_flush(self):
        self.submitted()
        f, before = self.f, self.state()
        with self.assertRaisesRegex(ValueError, 'capacity unavailable before resolution'):
            self.profiled(self.finish)
        self.assertEqual(self.state(), before)
        self.assertEqual([row['status'] for row in f.client._orders.values()], ['accepted'])
        self.assertFalse(any(row[0] in ('flush', 'native_asdict', 'orders_copy') for row in self.trace))
        self.assertTrue(f.io.failed and f.binding._control()['failed'])
        self.assertIsNone(f.final.receipt_capacity)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Persist a real moderate annotated partial outcome within its original bound and continue the private lifecycle.
    def test_c_actual_bound_full_graph(self):
        self.submitted()
        f, seen = self.f, []

        # Observe only original budget metadata and actual serialized result bytes at their named boundaries.
        def observe(point):
            if point == 'reserved_final_capacity_ready':
                owner = f.final.receipt_capacity
                self.assertFalse(owner.used)
                self.assertIs(owner.prior, f.final.prepared_input.prior)
                descriptor = deepcopy(owner.binding)
                wrong = deepcopy(descriptor)
                wrong['orders'] = True
                with self.assertRaisesRegex(ValueError, 'integer'):
                    receipt_capacity.read_descriptor(wrong, f.final.prepared_input.binding)
                seen.append(descriptor)
            if point == 'reserved_final_capacity_checked':
                owner = f.final.receipt_capacity
                self.assertTrue(owner.closed and owner.used)
                self.assertIsNone(owner.prior)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        raw = f.store.read_blob(result['receipt'], limit=262144)
        self.assertLessEqual(len(raw), seen[0]['receipt_upper_bytes'])
        self.assertLessEqual(seen[0]['receipt_upper_bytes'], 262144)
        receipt = f.bridge.cycle._read_receipt(f.store, result['receipt'], f.nightly.pins(), raw_checkpoint=f.raw)
        self.assertEqual(receipt['raw_reconciliation']['evidence']['settled'][0]['sender_qty'], 6)
        self.assertEqual(receipt['raw_reconciliation']['evidence']['settled'][0]['filled_qty'], 5)
        self.assertIsNone(f.final.receipt_capacity)
        self.reopen(result['head'])
        before = self.state()
        again, recovery = self.profiled(self.recover)
        self.assertEqual((again, recovery), (result, []))
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
        self.assertEqual(f.context.policy_calls, 2)
        self.assertEqual(len(f.binding._control()['records']), 5)
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        EVIDENCE_OBSERVATIONS.append({'scope': 'ACTUAL_BOUNDED_ANNOTATED_PRIVATE_GRAPH',
            'descriptor': seen[0], 'actual_receipt_bytes': len(raw), 'recovery': recovery, 'historical': historical,
            'trace': trace, 'filled_qty': '5', 'sender_qty': 6, 'diagnostics_preserved': True})

    # A process cut after original byte allowance persistence does not authorize a second resolution attempt.
    def test_d_reserved_allowance_cut(self):
        row = self.killed('reserved_final_capacity_ready')
        self.assertFalse(row['used'])
        self.assertEqual(row['writer']['next_slot'], 3)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A process cut after authoritative commitment recovers only the original missing result and seals.
    def test_e_committed_allowance_cut(self):
        row = self.killed('reserved_final_committed')
        self.assertTrue(row['used'] and row['released'])
        self.assertEqual(row['writer']['next_slot'], 4)
        before = self.state()
        result, trace = self.profiled(self.recover)
        self.assertEqual((result['head'], trace), (row['head'], []))
        self.assertEqual(self.state(), before)
        again, trace = self.profiled(self.recover)
        self.assertEqual((again, trace), (result, []))
        self.assertEqual(self.state(), before)

