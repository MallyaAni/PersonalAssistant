"""NEW pre-resolution native-asdict clone assertions; derived tail is not native whole code."""
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
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_prepared_transition_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


TRANSITION_OBSERVATIONS, PARITY_OBSERVATIONS = [], []

# Exercise pre-callback materialization and original metadata-only recovery.
class PreparedTransitionTests(unittest.TestCase):
    # Use fresh exact-count accounts and explicitly source-bound negative programs.
    def setUp(self):
        fixture.CALLS.clear()
        fixture.CAPSULES.clear()
        fixture.EVENTS.clear()
        self.f = fixture.Fixture(self._testMethodName)


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
        load_code = paper.load_state.__code__
        flush_code = fixture.native.ReplayBroker.flush.__code__
        copy_code, asdict_code = copy.deepcopy.__code__, asdict.__code__
        previous = sys.getprofile()

        # Observe actual native calls and distinguish the later native result-copy allocations.
        def profile(frame, event, argument):
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
            if frame.f_code is paper.apply_settlements.__code__:
                kind = 'native_apply'
            elif frame.f_code is transition._apply_owned_tail.__code__:
                kind = 'derived_tail'
            elif frame.f_code is copy_code:
                rows = frame.f_locals.get('x')
                if type(rows) is list and rows and all(type(r) is dict and
                        'client_order_id' in r and 'status' in r and 'filled_qty' in r for r in rows):
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
                owned = f.final.prepared_transition
                row = {'pid': os.getpid(), 'kind': 'prepared-transition', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'transition': owned.binding, 'used': owned.used,
                    'owned_prior': not owned.closed and owned.prior is owned.original_prior,
                    'owned_output': not owned.closed and owned.output is owned.original_output,
                    'distinct': not owned.closed and owned.prior is not owned.output,
                    'released': owned.closed and all(v is None for v in
                        (owned.prior, owned.original_prior, owned.output, owned.original_output))}
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

    # Serialize exact native bytes for finite parity inputs without changing native values.
    def raw_state(self, state):
        raw = fixture.json.dumps(state, indent=2, default=paper._state_json).encode()
        self.assertLessEqual(len(raw), 1048576)
        return raw

    # Build fresh independent synthetic states for every native return/reset branch.
    def parity_state(self, case):
        row = {'client_order_id': 'unit', 'symbol': 'AAPL', 'side': 'buy', 'qty': 8,
            'session': '2019-03-01', 'execution': {'created_at': 'original'}, 'kind': 'rebalance'}
        state = paper.PaperState(start_equity=float('nan'), history=[{'unicode': 'é', 'value': float('nan')}],
            pending=[deepcopy(row), {**row, 'client_order_id': 'future', 'session': '2019-03-04'}],
            journal=[{'client_order_id': 'old', 'session': '2019-02-28', 'terminal': True,
                'status': 'filled', 'execution': {'retained': 'yes'}}],
            last_rebalance='2019-03-01', previous_rebalance='2019-02-01', sessions_since_rebalance=2)
        settled = []
        if case in ('open', 'partial_terminal', 'rebalance_open', 'confirmed', 'reset', 'pending_leg', 'prior_dead'):
            status = 'open' if case in ('open', 'rebalance_open') else 'partial' if case == 'partial_terminal' else (
                'dead' if case == 'reset' else 'filled')
            settled = [paper.Settled(client_order_id='unit', symbol='AAPL', side='buy', qty=8,
                session='2019-03-01', status=status, filled_qty=0 if status in ('open', 'dead') else 8 if status == 'filled' else 5,
                terminal=status != 'open', submitted_qty=8 if status == 'filled' else 5,
                sender_qty=8 if status == 'filled' else 5,
                quantity_evidence={'scope': 'SYNTHETIC_NATIVE_PARITY'}, execution={'updated': 'observed'})]
        if case in ('rebalance_empty', 'rebalance_open', 'confirmed', 'reset', 'pending_leg', 'prior_dead'):
            state.unconfirmed_rebalance = '2019-03-01'
        if case == 'pending_leg':
            state.pending.append({**row, 'client_order_id': 'unresolved_leg'})
        if case == 'prior_dead':
            state.journal.append({'client_order_id': 'dead_leg', 'session': '2019-03-01',
                'terminal': True, 'status': 'dead', 'execution': {}})
        return state, settled

    # Compare the explicitly derived tail against actual unchanged native apply on fresh independent inputs.
    def test_a_native_parity_matrix(self):
        cases = ('unresolved', 'open', 'partial_terminal', 'rebalance_empty', 'rebalance_open',
                 'confirmed', 'reset', 'pending_leg', 'prior_dead')
        rows = []
        for case in cases:
            with self.subTest(case=case):
                native_prior, native_settled = self.parity_state(case)
                derived_prior, derived_settled = self.parity_state(case)
                before = self.raw_state(native_prior)
                self.assertEqual(self.raw_state(derived_prior), before)
                binding = {'schema': transition.SCHEMA, 'sources': transition.sources(),
                    'native_bytes': transition.native_bytes(derived_prior, 1048576), 'raw_limit': 1048576,
                    'scope': 'SYNTHETIC_PURE_PARITY_NOT_CYCLE_ADMISSION'}
                capsule = transition.PreparedTransition(derived_prior, 1048576, binding=binding)
                self.assertIsNot(capsule.output, derived_prior)
                self.assertEqual(self.raw_state(capsule.output), before)
                expected = paper.apply_settlements(native_prior, native_settled)
                actual = capsule.apply(derived_prior, derived_settled)
                self.assertIs(actual, capsule.output)
                self.assertEqual(self.raw_state(actual), self.raw_state(expected))
                self.assertEqual(self.raw_state(native_prior), before)
                self.assertEqual(self.raw_state(derived_prior), before)
                self.assertIn(b'NaN', self.raw_state(actual))
                self.assertIn('future', [r['client_order_id'] for r in actual.pending])
                if case in ('reset', 'prior_dead'):
                    self.assertIsNone(actual.unconfirmed_rebalance)
                    self.assertEqual(actual.last_rebalance, '2019-02-01')
                    self.assertEqual(actual.sessions_since_rebalance, paper.REBALANCE_EVERY)
                if case == 'confirmed':
                    self.assertIsNone(actual.unconfirmed_rebalance)
                    self.assertEqual(actual.last_rebalance, '2019-03-01')
                if case in ('rebalance_empty', 'rebalance_open', 'pending_leg'):
                    self.assertEqual(actual.unconfirmed_rebalance, '2019-03-01')
                if case == 'partial_terminal':
                    self.assertNotIn('unit', [r['client_order_id'] for r in actual.pending])
                    self.assertEqual(next(r for r in actual.journal if r['client_order_id'] == 'unit')['filled_qty'], 5)
                if case == 'open':
                    self.assertIn('unit', [r['client_order_id'] for r in actual.pending])
                with self.assertRaises(ValueError):
                    capsule.apply(derived_prior, derived_settled)
                capsule.close()
                capsule.check_released(binding)
                rows.append({'case': case, 'bytes': len(self.raw_state(actual)),
                    'sha256': hashlib.sha256(self.raw_state(actual)).hexdigest()})
        PARITY_OBSERVATIONS.extend(rows)

    # Fail at the explicit pre-asdict point before any broker resolution or native save.
    def test_b_pre_asdict_failure(self):
        self.submitted()
        f, before = self.f, self.state()

        # Inject one preparation failure without replacing native dataclass or broker code.
        def fail(boundary):
            if boundary == 'reserved_final_transition_before_asdict':
                raise ValueError('SYNTHETIC pre-asdict failure')

        f.store.fault = fail
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC pre-asdict failure'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertEqual([r for r in self.trace if r[0] in ('flush', 'native_asdict', 'derived_tail')], [])
        self.assertTrue(f.io.failed)
        self.assertIsNone(f.final.prepared_input)
        self.assertIsNone(f.final.prepared_transition)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Reject changed owned output before flush while preserving the original accepted submission and native bytes.
    def test_c_changed_prepared_output(self):
        self.submitted()
        f, before, held = self.f, self.state(), []

        # Change only the new owned output clone after its source-bound descriptor is persisted.
        def mutate(boundary):
            if boundary == 'reserved_final_transition_reserved':
                owned = f.final.prepared_transition
                held.append(owned)
                owned.output.start_equity = 1

        f.store.fault = mutate
        with self.assertRaisesRegex(ValueError, 'Original unused prepared native transition'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertFalse(any(r[0] == 'flush' for r in self.trace))
        self.assertTrue(held[0].closed)
        self.assertIsNone(held[0].output)
        self.assertIsNone(held[0].prior)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # The full private graph materializes native-asdict output before resolution and uses the derived tail afterward.
    def test_d_full_graph_prepared_transition(self):
        self.submitted()
        f, held, released = self.f, [], []

        # Observe exact prior ownership and release before the original native writer is called.
        def observe(boundary):
            if boundary == 'reserved_final_transition_reserved':
                owned = f.final.prepared_transition
                self.assertIs(owned.prior, f.final.prepared_input.prior)
                self.assertIsNot(owned.output, owned.prior)
                self.assertIsNot(owned.output, f.final.prepared_input.state)
                held.append(owned)
            if boundary == 'reserved_final_input_released':
                owned = f.final.prepared_transition
                self.assertTrue(owned.closed and owned.used)
                self.assertIsNone(owned.prior)
                self.assertIsNone(owned.output)
                self.assertEqual(f.writer._control()['next_slot'], 3)
                released.append(True)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual([r for r in trace if r[0] == 'load'], [['load', False]])
        self.assertEqual([r for r in trace if r[0] == 'native_asdict'], [['native_asdict', False]])
        self.assertEqual([r for r in trace if r[0] == 'derived_tail'], [['derived_tail', True]])
        self.assertFalse(any(r[0] == 'native_apply' for r in trace))
        self.assertTrue(any(r == ['orders_copy', True] for r in trace))
        self.assertEqual(released, [True])
        self.assertIsNone(f.final.prepared_transition)
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
        self.assertEqual(again, result)
        self.assertEqual(historical, [])
        self.assertEqual(f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io), close)
        self.assertEqual(self.state(), before)
        native_state = paper.load_state(f.nightly.root)
        self.assertEqual((native_state.journal[0]['qty'], native_state.journal[0]['filled_qty']), (8, 5))
        self.assertGreater(len(paper.state_path(f.nightly.root).read_bytes()), 262144)
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        self.assertEqual(f.context.policy_calls, 2)
        self.assertEqual(len(f.binding._control()['records']), 5)
        TRANSITION_OBSERVATIONS.append({'trace': trace, 'recovery_trace': recovered,
            'historical_recovery_trace': historical, 'released_before_native_save': released == [True],
            'transition': held[0].binding, 'full_ram_admitted': False,
            'execution_mode': 'PRIVATE_DERIVED_TAIL_NOT_NATIVE_WHOLE_FUNCTION'})

    # A caught duplicate after premature consumption cannot enable broker flush or native adoption.
    def test_e_caught_premature_consumption(self):
        self.submitted()
        f, before, caught = self.f, self.state(), []

        # Deliberately consume the clone with empty synthetic settlements before the real resolver boundary.
        def consume(boundary):
            if boundary == 'reserved_final_transition_reserved':
                owned = f.final.prepared_transition
                owned.apply(owned.prior, [])
                try:
                    owned.apply(owned.prior, [])
                except ValueError:
                    caught.append(True)

        f.store.fault = consume
        with self.assertRaisesRegex(ValueError, 'Original unused prepared native transition'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(caught, [True])
        self.assertEqual(self.state(), before)
        self.assertFalse(any(r[0] == 'flush' for r in self.trace))
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # Mutation after actual flush retains filled broker state but refuses the original native save and replay.
    def test_f_post_flush_output_mutation(self):
        self.submitted()
        f, before = self.f, self.state()

        # Change only the prebuilt output after real broker results exist, before derived settlement application.
        def mutate(boundary):
            if boundary == 'reserved_final_resolved':
                f.final.prepared_transition.output.start_equity = 3

        f.store.fault = mutate
        with self.assertRaisesRegex(ValueError, 'Original unused prepared native transition'):
            self.profiled(self.finish)
        f.store.fault = None
        after = self.state()
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[2:], before[2:])
        self.assertNotEqual(after[1], before[1])
        self.assertEqual([r['filled_qty'] for r in f.client._orders.values()], ['5'])
        self.assertIsNone(f.final.prepared_transition)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after transition reservation loses RAM without permitting a second materialization or flush.
    def test_g_actual_before_resolution(self):
        row = self.killed('reserved_final_transition_reserved')
        self.assertFalse(row['used'])
        self.assertTrue(row['owned_prior'] and row['owned_output'] and row['distinct'])
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after real resolution retains filled broker bytes and cannot reapply the owned output on recovery.
    def test_h_actual_after_resolution(self):
        row = self.killed('reserved_final_resolved')
        self.assertFalse(row['used'])
        self.assertTrue(row['owned_prior'] and row['owned_output'] and row['distinct'])
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A committed derived result recovers only original metadata/seals after all capsule graph references release.
    def test_i_actual_committed_original(self):
        row = self.killed('reserved_final_committed')
        self.assertTrue(row['used'] and row['released'])
        self.assertEqual(row['writer']['next_slot'], 4)
        self.assertNotEqual(row['head'], self.head)
        before = self.state()
        result, trace = self.profiled(self.recover)
        self.assertEqual(trace, [])
        self.assertEqual(result['head'], row['head'])
        self.assertEqual(self.state(), before)
        again, trace = self.profiled(self.recover)
        self.assertEqual(trace, [])
        self.assertEqual(again, result)
        self.assertEqual(self.state(), before)
