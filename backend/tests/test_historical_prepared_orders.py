"""NEW finite-evidence input admission; native diagnostic semantics and actual broker results remain unchanged."""
from copy import deepcopy
import math
import json
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
from backend.market import historical_prepared_orders as prepared_orders
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_prepared_orders_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


EVIDENCE_OBSERVATIONS, EVIDENCE_UNITS = [], []

# Exercise pre-callback materialization and original metadata-only recovery.
class PreparedOrdersTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        self.inject_late_copy = self.compare_original = self.duplicate_take = False
        self.parity = []
        self.f = fixture.Fixture(self._testMethodName, baseline=self._testMethodName.startswith('test_a_'),
                                 program='stage_moderate_annotation')


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
            if event == 'return' and frame.f_code.co_name == '_derived_reconcile_prepared_orders' and argument is not None and self.compare_original:
                self.reference_parity(frame, argument)
            if event == 'return' and frame.f_code is prepared_orders.PreparedOrders.take.__code__ and self.duplicate_take and argument is not None:
                with self.assertRaisesRegex(ValueError, 'once-only'):
                    self.f.final.prepared_orders.take(self.f.client)
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
            if frame.f_code is prepared_orders.PreparedOrders.__init__.__code__:
                kind = 'order_containers_prepare'
            elif frame.f_code is prepared_orders.PreparedOrders.take.__code__:
                kind = 'actual_order_values_take'
            elif frame.f_code.co_name == '_derived_reconcile_prepared_orders':
                kind = 'derived_reconciliation'
            elif frame.f_code is finite_evidence.EvidenceInput.__init__.__code__:
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
                if kind == 'orders_copy' and self.inject_late_copy:
                    raise MemoryError('INJECTED at original postflush orders deepcopy, not actual OOM')

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
                owned = f.final.prepared_orders
                row = {'pid': os.getpid(), 'kind': 'prepared-orders', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'prepared_orders': owned.binding, 'used': owned.used,
                    'empty_containers': (not owned.closed and not owned.used and all(v is owned.empty for row in owned.orders for v in row.values())),
                    'released': owned.closed and owned.orders is None and owned.client is None}
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

    # Compare a derived fold with the unchanged original on a fresh independent input and actual broker results.
    def reference_parity(self, frame, actual):
        f = self.f
        values = frame.f_locals
        state = deepcopy(values['state'])
        before = json.dumps(state, indent=2, default=paper._state_json).encode()
        broker = codec.encode(f.client, **f.nightly.pins())
        expected = f.settlement.reconcile_raw(f.client, state, pins=values['pins'],
            outcome_sha256=values['outcome_sha256'], observed_at=values['observed_at'],
            prior_component=deepcopy(values['prior_component']), raw_checkpoint=values['raw_checkpoint'])
        actual_state = json.dumps(actual[0], indent=2, default=paper._state_json).encode()
        expected_state = json.dumps(expected[0], indent=2, default=paper._state_json).encode()
        self.assertEqual(actual_state, expected_state)
        self.assertEqual(demand.encoded(actual[1]), demand.encoded(expected[1]))
        self.assertEqual(json.dumps(state, indent=2, default=paper._state_json).encode(), before)
        self.assertEqual(codec.encode(f.client, **f.nightly.pins()), broker)
        self.parity.append({'native_bytes': len(actual_state), 'sha256': hashlib.sha256(actual_state).hexdigest(),
                            'evidence_bytes': len(demand.encoded(actual[1])), 'input_preserved': True})

    # Inject at the unchanged original late-copy call after a real fill, without claiming an actual system OOM.
    def test_a_original_late_copy_failure(self):
        self.submitted()
        f, before = self.f, self.state()
        self.inject_late_copy = True
        with self.assertRaisesRegex(MemoryError, 'original postflush orders deepcopy'):
            self.profiled(self.finish)
        self.assertIn(['orders_copy', True], self.trace)
        self.assertEqual([r['filled_qty'] for r in f.client._orders.values()], ['5'])
        self.assertEqual((self.state()[0], f.writer._control()['next_slot'], f.store.snapshot()['head']),
                         (before[0], 3, self.head))
        EVIDENCE_UNITS.append({'scope': 'INJECTED_ORIGINAL_LATE_ALLOCATION_FAILURE_NOT_ACTUAL_OOM',
            'actual_filled_qty': '5', 'native_next_slot': 3, 'trace': self.trace})
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # An injected container-preparation failure refuses before the callback can resolve or clone an output state.
    def test_b_preparation_failure_before_flush(self):
        self.submitted()
        f, before = self.f, self.state()

        # Fail the pre-effect allocation boundary while retaining all original accepted order and account bytes.
        def fail(point):
            if point == 'reserved_final_orders_before_allocate':
                raise MemoryError('INJECTED container preparation failure, not actual OOM')

        f.store.fault = fail
        with self.assertRaisesRegex(MemoryError, 'container preparation'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertFalse(any(row[0] in ('flush', 'native_asdict', 'orders_copy') for row in self.trace))
        self.assertTrue(f.io.failed and f.binding._control()['failed'])
        self.assertIsNone(f.final.prepared_orders)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Compare prepared containers against actual native deepcopy across seven independently resolved native brokers.
    def test_c_actual_native_order_parity(self):
        results = []
        for index, kind in enumerate(('full', 'missing_price', 'partial_cash', 'canceled', 'terminal', 'working_close', 'empty')):
            with self.subTest(kind=kind):
                client = fixture.native.ReplayBroker(501 if kind == 'partial_cash' else 100000, 10)
                client.observe('2019-03-01T14:45:31+00:00', {'AAPL': 100}, True)
                cid = 'SYNTHETIC-prepared-orders-' + str(index)
                if kind != 'empty':
                    if kind == 'working_close':
                        client.submit_market_on_close('AAPL', 5, 'buy', cid)
                    else:
                        client.submit_market('AAPL', 5, 'buy', cid)
                if kind == 'canceled':
                    client.cancel_orders([cid])
                if kind == 'terminal':
                    client.flush('2019-03-01T14:45:32+00:00', {'AAPL': 100}, phase='market')
                binding = {'identity': self.f.identity, 'phase': 'OUTCOME_COMMITTED', 'head': 'b' * 64,
                    'account': 'SYNTHETIC-independent-native-unit', 'scope': 'UNIT_COMPARISON_NOT_CYCLE_ADMISSION'}
                owner = prepared_orders.PreparedOrders(client, binding, self.f.settlement.reconcile_raw, self.f.nightly.pins())
                self.assertTrue(all(v is owner.empty for row in owner.orders for v in row.values()))
                list_id, row_ids = id(owner.orders), tuple(id(row) for row in owner.orders)
                descriptor = deepcopy(owner.binding)
                bad = deepcopy(descriptor)
                bad['orders'] = True
                with self.assertRaises(ValueError):
                    prepared_orders.read_descriptor(bad, binding)
                client.flush('2019-03-01T14:45:33+00:00',
                    {} if kind == 'missing_price' else {'AAPL': 200 if kind == 'partial_cash' else 100}, phase='market')
                broker = codec.encode(client, **self.f.nightly.pins())
                expected = deepcopy(list(client._orders.values()))
                actual = owner.take(client)
                self.assertEqual((id(actual), tuple(id(row) for row in actual)), (list_id, row_ids))
                self.assertEqual(json.dumps(actual), json.dumps(expected))
                self.assertTrue(all(row is not native_row for row, native_row in zip(actual, client._orders.values())))
                owner.check(client, binding, descriptor)
                self.assertEqual(codec.encode(client, **self.f.nightly.pins()), broker)
                owner.close()
                owner.check_released(binding, descriptor)
                self.assertIsNone(owner.orders)
                self.assertIsNone(owner.client)
                results.append({'kind': kind, 'orders': len(actual), 'exact_deepcopy_parity': True,
                                'same_preallocated_containers': True})
        EVIDENCE_UNITS.append({'scope': 'SEVEN_ACTUAL_NATIVE_BROKERS_NOT_WHOLE_CYCLE', 'results': results})

    # Complete the actual private graph with source-bound derived reconciliation and unchanged-original byte parity.
    def test_d_full_graph_derived_parity(self):
        self.submitted()
        f, observed = self.f, []
        self.compare_original = True

        # Prove that pre-effect containers contain no execution values and ownership releases before saving.
        def observe(point):
            if point == 'reserved_final_orders_ready':
                owner = f.final.prepared_orders
                self.assertFalse(owner.used)
                self.assertTrue(all(v is owner.empty for row in owner.orders for v in row.values()))
                observed.append(deepcopy(owner.binding))
            if point == 'reserved_final_input_released':
                owner = f.final.prepared_orders
                self.assertTrue(owner.closed and owner.used)
                self.assertIsNone(owner.orders)
                self.assertIsNone(owner.client)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.compare_original = False
        self.assertEqual([r for r in trace if r[0] == 'order_containers_prepare'], [['order_containers_prepare', False]])
        self.assertEqual([r for r in trace if r[0] == 'actual_order_values_take'], [['actual_order_values_take', True]])
        self.assertFalse(any(r[0] == 'orders_copy' for r in trace))
        self.assertEqual(len(self.parity), 1)
        self.assertIsNone(f.final.prepared_orders)
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
        self.assertEqual((f.context.policy_calls, len(f.binding._control()['records'])), (2, 5))
        raw = paper.state_path(f.nightly.root).read_bytes()
        self.assertGreater(len(raw), 262144)
        self.assertIn(b'NaN', raw)
        EVIDENCE_OBSERVATIONS.append({'scope': 'ACTUAL_PRIVATE_GRAPH_DERIVED_ORDER_COPY_REPLACEMENT',
            'descriptor': observed[0], 'parity': self.parity, 'trace': trace, 'recovery': recovery, 'historical': historical})

    # A caught duplicate handoff after actual fill poisons later evidence and saving rather than replaying a snapshot.
    def test_e_caught_duplicate_take(self):
        self.submitted()
        f, before = self.f, self.state()
        self.duplicate_take = True
        with self.assertRaisesRegex(ValueError, 'prepared orders'):
            self.profiled(self.finish)
        self.assertEqual([r['filled_qty'] for r in f.client._orders.values()], ['5'])
        self.assertEqual((self.state()[0], f.writer._control()['next_slot'], f.store.snapshot()['head']),
                         (before[0], 3, self.head))
        self.assertTrue(f.io.failed)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A process cut after container reservation leaves no native resolution and cannot prepare or replay again.
    def test_f_reserved_containers_cut(self):
        row = self.killed('reserved_final_orders_ready')
        self.assertFalse(row['used'])
        self.assertTrue(row['empty_containers'])
        self.assertEqual(row['writer']['next_slot'], 3)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # An authoritative outcome cut permits only original missing metadata and seals after reference release.
    def test_g_committed_containers_cut(self):
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

    # Equivalent row bytes in a substituted broker dictionary do not satisfy the original owned-container binding.
    def test_h_original_row_identity_refusal(self):
        self.submitted()
        f, before = self.f, self.state()

        # Substitute only the in-memory row identity at a deliberate negative boundary before flush.
        def replace(point):
            if point == 'reserved_final_orders_ready':
                cid = next(iter(f.client._orders))
                f.client._orders[cid] = dict(f.client._orders[cid])

        f.store.fault = replace
        with self.assertRaisesRegex(ValueError, 'row/key identity'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertTrue(f.io.failed)
        self.assertFalse(any(r[0] == 'flush' for r in self.trace))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

