"""NEW phase-owned saved-byte assertions; native result copies/RAM remain unverified."""
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
from backend.tests import synthetic_final_saved_bytes_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


SAVED_BYTES_OBSERVATIONS = []

# Exercise pre-callback materialization and original metadata-only recovery.
class FinalSavedBytesTests(unittest.TestCase):
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

    # Capture exact owned-input/native/broker metadata before an actual child process cut.
    def child(self, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Retain the full broker witness and original ownership without copying account state.
        def cut(boundary):
            if boundary == point:
                broker = codec.encode(f.client, **f.nightly.pins())
                owned = f.final.saved_bytes
                row = {'pid': os.getpid(), 'kind': 'final-saved-bytes', 'point': point,
                    'head': f.store.snapshot()['head'], 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'saved_bytes': owned.binding,
                    'descriptor_frozen': demand.encoded(owned.binding) == owned.original,
                    'receipt': owned.receipt}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault = cut
        self.finish()
        raise AssertionError('Expected final saved-byte cut not reached')

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

    # Flip one original native byte in place without changing writer semantics or file length.
    def damage_native(self):
        path = paper.state_path(self.f.nightly.root)
        with path.open('r+b') as handle:
            first = handle.read(1)
            handle.seek(0)
            handle.write(b'[' if first != b'[' else b'{')
            handle.flush()
            os.fsync(handle.fileno())

    # Retain late save uncertainty and refuse original replay without reversing real broker fills.
    def refused_save(self, point, mutation):
        self.submitted()
        f, reached = self.f, []

        # Apply one explicit negative harness mutation at a named protocol boundary.
        def fault(boundary):
            if boundary == point:
                mutation()
                reached.append(True)

        f.store.fault = fault
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.finish()
        f.store.fault = None
        self.assertEqual(reached, [True])
        self.assertEqual(f.store.snapshot()['head'], self.head)
        self.assertEqual(f.writer._control()['next_slot'], 4)
        self.assertTrue(f.io.failed)
        self.assertIsNone(f.final.saved_bytes)
        self.assertEqual(next(iter(f.client._orders.values()))['status'], 'filled')
        self.reopen(self.head)
        self.paused(self.recover)

    # The full private graph reads the original input once and validates saved bytes without late JSON loads.
    def test_a_full_graph_no_readback_load(self):
        self.submitted()
        f, held, points = self.f, [], []

        # Observe the exact phase-owned binding at both live byte-verification points.
        def observe(boundary):
            if boundary in ('reserved_final_saved_bytes', 'reserved_final_saved_bytes_rechecked'):
                owned = f.final.saved_bytes
                self.assertEqual(demand.encoded(owned.binding), owned.original)
                self.assertEqual(owned.receipt['slot'], 3)
                self.assertEqual(owned.binding['slot'], 3)
                self.assertEqual(owned.binding['state'], f.writer._control()['current'])
                held.append(deepcopy(owned.binding))
                points.append(boundary)

        f.store.fault = observe
        result, trace = self.profiled(self.finish)
        f.store.fault = None
        self.assertEqual([r for r in trace if r[0] == 'load'], [['load', False]])
        self.assertEqual([r for r in trace if r[0] == 'input_copy'], [['input_copy', False]])
        self.assertIn(['native_asdict', True], trace)
        self.assertEqual([r for r in trace if r[0] == 'flush'], [['flush', True]])
        self.assertEqual(len(held), 2)
        self.assertEqual(held[0], held[1])
        self.assertIsNone(f.final.saved_bytes)
        self.assertIsNone(f.final.prepared_input)
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
        # Authenticate the historical final against its own receipt after the newer Nightly save.
        historical, historical_trace = self.profiled(self.recover)
        self.assertEqual(historical, result)
        self.assertEqual(historical_trace, [])
        self.assertEqual(f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io), close)
        self.assertEqual(self.state(), before)
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty']), (8, 5))
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        self.assertGreater(paper.state_path(f.nightly.root).stat().st_size, 262144)
        self.assertEqual(f.context.policy_calls, 2)
        self.assertEqual(len(f.binding._control()['records']), 5)
        SAVED_BYTES_OBSERVATIONS.append({'trace': trace, 'recovery_trace': recovered,
            'historical_recovery_trace': historical_trace, 'saved_bytes': held[0],
            'verification_points': points, 'late_native_asdict_remains': True, 'full_ram_admitted': False})

    # Changed actual native bytes refuse immediately after the original save rather than loading changed JSON.
    def test_b_post_save_native_tamper(self):
        self.refused_save('reserved_final_native_saved', self.damage_native)

    # A valid historical birth receipt cannot substitute for the sole save owned by this final phase.
    def test_c_foreign_phase_receipt(self):
        f = self.f

        # Substitute only the in-memory save evidence with an authentic earlier original receipt.
        def foreign():
            f.io.saved[0] = physical._fixed_read(f.writer.root / 'receipts/0')

        self.refused_save('reserved_final_native_saved', foreign)

    # A changed finite descriptor cannot pass the frozen precommit verification even if the callback catches errors.
    def test_d_frozen_descriptor_tamper(self):
        f = self.f

        # Mutate the typed original binding while leaving the native writer and original receipt untouched.
        def mutate():
            f.final.saved_bytes.binding['slot'] = True

        self.refused_save('reserved_final_prepared', mutate)

    # Explicit negative metadata units require strict integer fields, one save, original bytes and preimage.
    def test_e_strict_binding_units(self):
        self.submitted()
        f, checked = self.f, []

        # Exercise only typed finite metadata validation inside an otherwise real private final.
        def inspect(boundary):
            if boundary != 'reserved_final_saved_bytes':
                return
            owned = f.final.saved_bytes
            value, sha = f.final_ns['read_file'](f.nightly, f.io.directory / 'reservation.json')
            bind = f.final_ns['saved_binding']
            for field, bad in (('slot', True), ('slot', 2)):
                evidence = deepcopy(owned.evidence)
                evidence['saves'][0][field] = bad
                with self.assertRaises(ValueError):
                    bind(value, sha, evidence, owned.target)
            evidence = deepcopy(owned.evidence)
            evidence['saves'].append(deepcopy(evidence['saves'][0]))
            with self.assertRaises(ValueError):
                bind(value, sha, evidence, owned.target)
            evidence = deepcopy(owned.evidence)
            evidence['saves'][0]['prior'] = None
            with self.assertRaises(ValueError):
                bind(value, sha, evidence, owned.target)
            target = deepcopy(owned.target)
            target['raw_bytes'] = True
            with self.assertRaises(ValueError):
                bind(value, sha, owned.evidence, target)
            target = deepcopy(owned.target)
            target['raw_sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                bind(value, sha, owned.evidence, target)
            self.assertEqual(bind(value, sha, owned.evidence, owned.target), owned.binding)
            checked.append(True)

        f.store.fault = inspect
        result = self.finish()
        f.store.fault = None
        self.assertEqual(checked, [True])
        self.assertEqual(f.store.snapshot()['head'], result['head'])

    # A native-byte mutation after prepared publication is rejected at the second actual byte check.
    def test_f_precommit_native_tamper(self):
        self.refused_save('reserved_final_prepared', self.damage_native)

    # A process cut after first byte verification retains the native save but cannot adopt an unprepared outcome.
    def test_g_actual_first_verification(self):
        row = self.killed('reserved_final_saved_bytes')
        self.assertTrue(row['descriptor_frozen'])
        self.assertEqual(row['writer']['next_slot'], 4)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A cut after exact prepared bytes remains paused without replay or loading native paper.
    def test_h_actual_prepared_verification(self):
        row = self.killed('reserved_final_prepared')
        self.assertTrue(row['descriptor_frozen'])
        self.assertEqual(row['writer']['next_slot'], 4)
        self.assertEqual(row['head'], self.head)
        _, trace = self.profiled(lambda: self.paused(self.recover))
        self.assertEqual(trace, [])

    # A committed typed outcome recovers only original result and seals with no current-writer dependency.
    def test_i_actual_committed_original(self):
        row = self.killed('reserved_final_committed')
        self.assertTrue(row['descriptor_frozen'])
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
