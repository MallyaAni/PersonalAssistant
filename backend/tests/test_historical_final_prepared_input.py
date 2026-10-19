"""NEW pre-resolution owned-input assertions; later native copies/RAM remain unverified."""
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
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_native_directory_binding as native_directory
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_final_prepared_input_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


PREPARATION_OBSERVATIONS = []

# Exercise pre-callback materialization and original metadata-only recovery.
class FinalPreparedInputTests(unittest.TestCase):
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

    # Refuse an injected preparation boundary without loading again or resolving an accepted order.
    def preparation_failure(self, point):
        self.submitted()
        f = self.f
        before = self.state()
        count = len(fixture.CALLS)

        # Raise only at an explicit pre-effect preparation point without replacing native code.
        def fail(boundary):
            if boundary == point:
                raise ValueError('SYNTHETIC final input preparation failure')

        f.store.fault = fail
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC final input preparation failure'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(self.state(), before)
        self.assertEqual(len(fixture.CALLS), count)
        self.assertEqual([r['status'] for r in f.client._orders.values()], ['accepted'])
        self.assertEqual([r for r in self.trace if r[0] == 'load'],
            [] if point.endswith('before_load') else [['load', False]])
        self.assertFalse(any(r[0] in ('flush', 'input_copy') for r in self.trace))
        self.assertTrue(f.binding._control()['failed'])
        self.assertIsNone(f.final.prepared_input)
        self.reopen(self.head)
        _, trace = self.profiled(lambda: self.paused(self.finish))
        self.assertEqual(trace, [])

    # Capture exact owned-input/native/broker metadata before an actual child process cut.
    def child(self, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Retain the full broker witness and original ownership without copying account state.
        def cut(boundary):
            if boundary == point:
                broker = codec.encode(f.client, **f.nightly.pins())
                owned = f.final.prepared_input
                row = {'pid': os.getpid(), 'kind': 'final-prepared-input', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'preparation': owned.binding, 'used': owned.used,
                    'owned_identity': not owned.closed and owned.state is owned.original_state
                        and owned.prior is owned.original_prior,
                    'distinct_objects': not owned.closed and owned.state is not owned.prior,
                    'released': owned.closed and all(v is None for v in
                        (owned.state, owned.prior, owned.original_state, owned.original_prior))}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault = cut
        self.finish()
        raise AssertionError('Expected final prepared-input cut not reached')

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

    # Failure before the original reader leaves the accepted broker and every native cursor unchanged.
    def test_a_pre_load_failure(self):
        self.preparation_failure('reserved_final_input_before_load')

    # Failure after native load but before its owned copy still refuses resolution and replay.
    def test_b_pre_copy_failure(self):
        self.preparation_failure('reserved_final_input_before_copy')

    # A changed separate input copy refuses before native resolution, without touching original paper.
    def test_c_changed_prepared_copy(self):
        self.submitted()
        f, held = self.f, []
        before = self.state()

        # Mutate only the private prepared copy after its descriptor was durably reserved.
        def mutate(boundary):
            if boundary == 'reserved_final_input_reserved':
                owned = f.final.prepared_input
                held.append(owned)
                owned.prior.pending[0]['qty'] += 1

        f.store.fault = mutate
        with self.assertRaisesRegex(ValueError, 'Prepared raw input bytes changed'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertFalse(any(r[0] == 'flush' for r in self.trace))
        self.assertEqual(self.state(), before)
        self.assertTrue(held[0].closed)
        self.assertIsNone(held[0].state)
        self.assertIsNone(held[0].prior)
        self.paused(self.finish)

    # The actual full graph prepares input before flush while native result copies and readbacks remain late.
    def test_d_full_graph_preparation_order(self):
        self.submitted()
        f, held, released = self.f, [], []

        # Retain the capsule only to verify that its two owned state references are later released.
        def observe(boundary):
            if boundary == 'reserved_final_input_reserved':
                owned = f.final.prepared_input
                self.assertIsNot(owned.state, owned.prior)
                self.assertFalse(owned.used)
                held.append(owned)
            if boundary == 'reserved_final_input_released':
                owned = f.final.prepared_input
                self.assertTrue(owned.closed and owned.used)
                self.assertIsNone(owned.state)
                self.assertIsNone(owned.prior)
                self.assertEqual(f.writer._control()['next_slot'], 3)
                released.append(True)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual([r for r in trace if r[0] == 'load'], [['load', False], ['load', True], ['load', True]])
        self.assertEqual([r for r in trace if r[0] == 'input_copy'], [['input_copy', False]])
        self.assertTrue(any(r == ['native_asdict', True] for r in trace))
        self.assertEqual([r for r in trace if r[0] == 'flush'], [['flush', True]])
        self.assertTrue(held[0].closed)
        self.assertIsNone(held[0].state)
        self.assertIsNone(held[0].prior)
        self.assertIsNone(f.final.prepared_input)
        self.assertEqual(released, [True])
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
        self.assertEqual(f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io), close)
        self.assertEqual(self.state(), before)
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty']), (8, 5))
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        self.assertGreater(paper.state_path(f.nightly.root).stat().st_size, 262144)
        self.assertEqual(f.context.policy_calls, 2)
        self.assertEqual(len(f.binding._control()['records']), 5)
        PREPARATION_OBSERVATIONS.append({'trace': trace, 'recovery_trace': recovered,
            'released_owned_references': True, 'binding': held[0].binding,
            'released_before_native_save': True,
            'late_native_asdict_remains': True, 'full_ram_admitted': False})

    # A premature consumed copy and caught duplicate cannot enable native flush or another fold.
    def test_e_caught_premature_consumption(self):
        self.submitted()
        f, held, refused = self.f, [], []
        before = self.state()

        # Exercise only negative ownership APIs before the final producer reaches resolution.
        def consume(boundary):
            if boundary == 'reserved_final_input_reserved':
                owned = f.final.prepared_input
                held.append(owned)
                self.assertIs(owned.take(owned.state, owned.native_bytes, owned.limit), owned.prior)
                try:
                    owned.take(owned.state, owned.native_bytes, owned.limit)
                except ValueError:
                    refused.append('duplicate')

        f.store.fault = consume
        with self.assertRaisesRegex(ValueError, 'Original once-owned raw input binding'):
            self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual(refused, ['duplicate'])
        self.assertFalse(any(r[0] == 'flush' for r in self.trace))
        self.assertEqual(self.state(), before)
        self.assertTrue(held[0].closed)
        self.paused(self.finish)

    # Post-flush uncertainty retains real fills without save; the ordinary pure fold remains available as a control.
    def test_f_post_flush_mutation_and_default_fold(self):
        self.submitted()
        f, held = self.f, []
        before = self.state()

        # Change only owned pre-fill input after the actual broker response, never the account file.
        def mutate(boundary):
            if boundary == 'reserved_final_resolved':
                owned = f.final.prepared_input
                held.append(owned)
                owned.prior.pending[0]['qty'] += 1

        f.store.fault = mutate
        with self.assertRaisesRegex(ValueError, 'Prepared raw input bytes changed'):
            self.finish()
        f.store.fault = None
        after = self.state()
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[2:], before[2:])
        self.assertNotEqual(after[1], before[1])
        self.assertEqual([r['filled_qty'] for r in f.client._orders.values()], ['5'])
        self.assertTrue(held[0].closed)
        self.assertEqual(f.store.snapshot()['head'], self.head)
        self.paused(self.finish)
        _, directory = f.final_ns['operation'](f.nightly, self.head)
        original, _ = f.final_ns['read_file'](f.nightly, directory / 'reservation.json')
        state = paper.load_state(f.nightly.root)
        # This token is explicitly synthetic pure-fold evidence, not an adopted Store outcome.
        token = hashlib.sha256(b'SYNTHETIC_DEFAULT_PURE_FOLD_CONTROL').hexdigest()
        updated, evidence = f.settlement.reconcile_raw(f.client, state, pins=f.nightly.pins(),
            outcome_sha256=token, observed_at=f.client._now.isoformat(),
            prior_component=original['declaration']['before']['paper'], raw_checkpoint=f.raw)
        self.assertEqual((updated.journal[0]['qty'], updated.journal[0]['filled_qty']), (8, 5))
        self.assertEqual(evidence['outcome_sha256'], token)
        self.assertFalse(evidence['durable_state_committed'])
        self.assertEqual(self.state(), after)

    # A process cut after input reservation loses RAM but cannot re-materialize or resolve the original attempt.
    def test_g_actual_input_before_resolution(self):
        row = self.killed('reserved_final_input_reserved')
        self.assertFalse(row['used'])
        self.assertTrue(row['owned_identity'] and row['distinct_objects'])
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after real flush retains the filled broker witness and unmodified native paper without replay.
    def test_h_actual_post_resolution(self):
        row = self.killed('reserved_final_resolved')
        self.assertFalse(row['used'])
        self.assertTrue(row['owned_identity'] and row['distinct_objects'])
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A committed outcome can publish only its original missing result and seals with no native input reconstruction.
    def test_i_actual_committed_original_recovery(self):
        row = self.killed('reserved_final_committed')
        self.assertTrue(row['used'])
        self.assertFalse(row['owned_identity'] or row['distinct_objects'])
        self.assertTrue(row['released'])
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

