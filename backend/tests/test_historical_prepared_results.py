"""NEW prepared frozen-result storage tests; actual native outcomes remain late."""
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
from backend.market import historical_prepared_results as prepared_results
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_prepared_results_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


EVIDENCE_OBSERVATIONS, EVIDENCE_UNITS = [], []

# Exercise pre-callback materialization and original metadata-only recovery.
class PreparedResultsTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        self.inject_late_init = self.compare_original = self.duplicate_init = False
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

    # Observe actual result initialization relative to flush without replacing native functions.
    def profiled(self, action):
        trace, resolved = [], [False]
        previous = sys.getprofile()

        # Record the original initializer timing and deliberate caught-duplicate negative control.
        def profile(frame, event, argument):
            if event == 'return' and frame.f_code.co_name == '_derived_reconcile_prepared_results' and argument is not None and self.compare_original:
                self.reference_parity(frame, argument)
            if event == 'return' and frame.f_code is prepared_results.PreparedResults.settle.__code__ and self.duplicate_init and argument is not None:
                with self.assertRaises(ValueError):
                    self.f.final.prepared_results.settle(self.f.final.prepared_results.due, list(self.f.client._orders.values()))
            if event != 'call':
                return
            kind = None
            if frame.f_code is fixture.native.ReplayBroker.flush.__code__:
                kind, resolved[0] = 'flush', True
            elif frame.f_code is prepared_results.INIT_CODE:
                kind = 'native_result_init'
            elif frame.f_code is prepared_results.PreparedResults.__init__.__code__:
                kind = 'result_storage_prepare'
            elif frame.f_code is prepared_results.PreparedResults.begin.__code__:
                kind = 'actual_results_begin'
            elif frame.f_code is paper.load_state.__code__:
                kind = 'load'
            elif frame.f_code is asdict.__code__ and type(frame.f_locals.get('obj')) is paper.PaperState:
                kind = 'native_asdict'
            if kind is not None:
                self.assertLess(len(trace), 64)
                trace.append([kind, resolved[0]])
                if kind == 'native_result_init' and self.inject_late_init:
                    raise MemoryError('INJECTED original postflush result allocation, not actual OOM')

        sys.setprofile(profile)
        try:
            return action(), trace
        finally:
            sys.setprofile(previous)
            self.trace = trace

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
                owned = f.final.prepared_results
                row = {'pid': os.getpid(), 'kind': 'prepared-results', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'prepared_results': owned.binding, 'used': owned.used,
                    'empty_containers': (not owned.closed and not owned.used and all(v is owned.empty for row in owned.output for v in row.__dict__.values())),
                    'released': owned.closed and owned.output is None and owned.client is None}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault = cut
        self.finish()
        raise AssertionError('Expected prepared-result cut not reached')

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

    # Reproduce an injected late original initializer failure after an actual native fill.
    def test_a_original_late_result_failure(self):
        self.submitted()
        f, before = self.f, self.state()
        self.inject_late_init = True
        with self.assertRaisesRegex(MemoryError, 'original postflush result'):
            self.profiled(self.finish)
        self.assertIn(['native_result_init', True], self.trace)
        self.assertEqual([r['filled_qty'] for r in f.client._orders.values()], ['5'])
        self.assertEqual((self.state()[0], f.writer._control()['next_slot'], f.store.snapshot()['head']),
                         (before[0], 3, self.head))
        EVIDENCE_UNITS.append({'scope': 'INJECTED_LATE_NATIVE_RESULT_FAILURE_NOT_ACTUAL_OOM', 'trace': self.trace})
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # An injected preparation failure retains accepted orders and refuses before actual broker resolution.
    def test_b_preparation_failure_before_flush(self):
        self.submitted()
        f, before = self.f, self.state()

        # Fail only the explicitly named pre-effect result-storage allocation boundary.
        def fail(point):
            if point == 'reserved_final_results_before_allocate':
                raise MemoryError('INJECTED result storage preparation failure, not actual OOM')

        f.store.fault = fail
        with self.assertRaisesRegex(MemoryError, 'result storage preparation'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertFalse(any(row[0] in ('flush', 'native_asdict', 'native_result_init') for row in self.trace))
        self.assertTrue(f.io.failed and f.binding._control()['failed'])
        self.assertIsNone(f.final.prepared_results)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Compare original frozen records and resulting native states on independent actual broker journeys.
    def test_c_actual_native_result_parity(self):
        results = []
        for index, kind in enumerate(('full', 'missing', 'partial', 'canceled', 'terminal', 'open', 'hold', 'empty')):
            with self.subTest(kind=kind):
                sell = kind == 'hold'
                client = fixture.native.ReplayBroker(501 if kind == 'partial' else 100000, 10,
                    initial_holdings={'AAPL': 5} if sell else None,
                    initial_average_prices={'AAPL': 100} if sell else None)
                client.observe('2019-03-01T14:45:31+00:00', {'AAPL': 100}, True)
                cid = 'SYNTHETIC-prepared-results-' + str(index)
                if kind != 'empty':
                    if kind == 'open':
                        client.submit_market_on_close('AAPL', 5, 'buy', cid)
                    else:
                        client.submit_market('AAPL', 5, 'sell' if sell else 'buy', cid)
                if kind in ('canceled', 'hold'):
                    client.cancel_orders([cid])
                if kind == 'terminal':
                    client.flush('2019-03-01T14:45:32+00:00', {'AAPL': 100}, phase='market')
                prior = paper.PaperState()
                prior.start_equity = float('nan')
                prior.unconfirmed_rebalance = '2019-03-01'
                prior.previous_rebalance = '2019-02-28'
                prior.pending = ([] if kind == 'empty' else [{'client_order_id': cid, 'symbol': 'AAPL',
                    'side': 'sell' if sell else 'buy', 'qty': 8, 'session': '2019-03-01',
                    'kind': 'rebalance', 'hold_requested': sell, 'sent': {'qty': float('nan')},
                    'execution': {'annotation': 'é', 'native_diagnostic': float('nan')}}])
                if kind != 'empty':
                    prior.pending.append({'client_order_id': cid + '-future', 'symbol': 'AAPL', 'side': 'buy',
                        'qty': 1, 'session': '2019-03-04', 'execute_on': '2019-03-04',
                        'execution_timing': 'dip_or_close'})
                raw = json.dumps(prior, indent=2, default=paper._state_json).encode()
                binding = {'identity': self.f.identity, 'phase': 'OUTCOME_COMMITTED', 'head': 'b' * 64,
                    'account': 'SYNTHETIC-native-result-unit', 'scope': 'UNIT_NOT_WHOLE_CYCLE'}
                owner = prepared_results.PreparedResults(prior, client, binding, self.f.settlement.reconcile_raw,
                    '2019-03-01T14:45:33+00:00')
                output_id, row_ids = id(owner.output), tuple(id(row) for row in owner.output)
                self.assertTrue(all(v is owner.empty for row in owner.output for v in row.__dict__.values()))
                descriptor = deepcopy(owner.binding)
                bad = deepcopy(descriptor)
                bad['count'] = True
                with self.assertRaises(ValueError):
                    prepared_results.read_descriptor(bad, binding)
                client.flush('2019-03-01T14:45:33+00:00',
                    {} if kind == 'missing' else {'AAPL': 200 if kind == 'partial' else 100}, phase='market')
                broker = codec.encode(client, **self.f.nightly.pins())
                orders = deepcopy(list(client._orders.values()))
                due = self.f.settlement.market_daily._reconciliation_pending(prior.pending, set(client._orders), client._now)
                expected = paper.settle(deepcopy(due), deepcopy(orders))
                actual = owner.settle(due, orders)
                self.assertEqual((id(actual), tuple(id(row) for row in actual)), (output_id, row_ids))
                self.assertEqual(json.dumps([asdict(row) for row in actual], indent=2),
                                 json.dumps([asdict(row) for row in expected], indent=2))
                self.assertTrue(all(type(row) is paper.Settled for row in actual))
                if actual:
                    with self.assertRaises(__import__('dataclasses').FrozenInstanceError):
                        actual[0].qty = 99
                a = paper.apply_settlements(prior, actual)
                b = paper.apply_settlements(deepcopy(prior), expected)
                self.assertEqual(json.dumps(a, indent=2, default=paper._state_json),
                                 json.dumps(b, indent=2, default=paper._state_json))
                self.assertEqual(json.dumps(prior, indent=2, default=paper._state_json).encode(), raw)
                self.assertEqual(codec.encode(client, **self.f.nightly.pins()), broker)
                owner.close()
                owner.check_released(binding, descriptor)
                results.append({'kind': kind, 'count': len(actual), 'native_bytes': len(raw),
                    'exact_native_record_state_parity': True, 'frozen_type_preserved': True})
        EVIDENCE_UNITS.append({'scope': 'EIGHT_NATIVE_BROKER_COMPARISONS_WITHIN_ONE_TEST', 'results': results})

    # Complete the private graph with exact original settlement and evidence parity on an independent input.
    def test_d_full_graph_derived_parity(self):
        self.submitted()
        f, observed = self.f, []
        self.compare_original = True

        # Inspect only private empty storage before resolution and released ownership before saving.
        def observe(point):
            if point == 'reserved_final_results_ready':
                owner = f.final.prepared_results
                self.assertFalse(owner.used)
                self.assertTrue(all(v is owner.empty for row in owner.output for v in row.__dict__.values()))
                observed.append(deepcopy(owner.binding))
            if point == 'reserved_final_input_released':
                owner = f.final.prepared_results
                self.assertTrue(owner.closed and owner.used and owner.finished)
                self.assertIsNone(owner.output)
                self.assertIsNone(owner.prior)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.compare_original = False
        self.assertEqual([r for r in trace if r[0] == 'result_storage_prepare'], [['result_storage_prepare', False]])
        self.assertEqual([r for r in trace if r[0] == 'native_result_init'], [['native_result_init', True]])
        self.assertEqual(len(self.parity), 1)
        self.assertIsNone(f.final.prepared_results)
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
        EVIDENCE_OBSERVATIONS.append({'scope': 'ACTUAL_PRIVATE_GRAPH_DERIVED_RESULT_STORAGE',
            'descriptor': observed[0], 'parity': self.parity, 'trace': trace, 'recovery': recovery, 'historical': historical})

    # A caught duplicate result initialization after a real fill poisons later saving and evidence.
    def test_e_caught_duplicate_initialize(self):
        self.submitted()
        f, before = self.f, self.state()
        self.duplicate_init = True
        with self.assertRaises(ValueError):
            self.profiled(self.finish)
        self.assertEqual([r['filled_qty'] for r in f.client._orders.values()], ['5'])
        self.assertEqual((self.state()[0], f.writer._control()['next_slot'], f.store.snapshot()['head']),
                         (before[0], 3, self.head))
        self.assertTrue(f.io.failed)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A process cut after persisted empty-storage reservation never resolves or initializes on recovery.
    def test_f_reserved_results_cut(self):
        row = self.killed('reserved_final_results_ready')
        self.assertFalse(row['used'])
        self.assertTrue(row['empty_containers'])
        self.assertEqual(row['writer']['next_slot'], 3)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A committed result recovers only original missing metadata and seals after releasing result storage.
    def test_g_committed_results_cut(self):
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

    # Changed private storage cannot smuggle predicted values into a pre-resolution result.
    def test_h_storage_mutation_refuses_before_flush(self):
        self.submitted()
        f, before = self.f, self.state()

        # Mutate only private reserved storage at a deliberate pre-effect negative boundary.
        def replace(point):
            if point == 'reserved_final_results_ready':
                f.final.prepared_results.output[0].__dict__['filled_qty'] = 5

        f.store.fault = replace
        with self.assertRaisesRegex(ValueError, 'predicted evidence'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertFalse(any(r[0] == 'flush' for r in self.trace))
        self.assertTrue(f.io.failed)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])
