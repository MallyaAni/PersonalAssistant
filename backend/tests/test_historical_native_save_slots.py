"""NEW exact native save-slot allowances; no physical directory-capacity claim."""
from copy import deepcopy
import hashlib
import multiprocessing
import os
from pathlib import Path
import signal
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
from backend.tests import synthetic_native_save_slots_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS, BASELINE_OBSERVATIONS = [], [], []


# Exercise exact pre-effect native save counts without changing the original writer.
class NativeSaveSlotsTests(unittest.TestCase):
    # Use fresh finite two/three/five-slot pools for each explicit synthetic assertion.
    def setUp(self):
        name = self._testMethodName
        self.f = fixture.Fixture(name, slots=2 if name.startswith(('test_a_', 'test_b_')) else
            3 if name.startswith('test_c_') else 5, reserve_saves=not name.startswith('test_a_'))

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
            f.sql._control()['current'], f.context.policy_calls, len(fixture.CALLS),
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

    # Record an actual child namespace/native cut outside every fixed metadata pool.
    def child(self, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Persist only bounded immutable evidence before killing this owned process.
        def cut(boundary):
            if boundary == point:
                control = f.binding._control()
                broker = codec.encode(f.client, **f.nightly.pins())
                row = {'pid': os.getpid(), 'kind': 'native-save-slot-final', 'point': point,
                    'head': f.store.snapshot()['head'], 'policy_calls': f.context.policy_calls,
                    'broker_raw': broker.decode(), 'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'directory_cursor': control['cursor'],
                    'directory_pending': control['pending'], 'directory_records': len(control['records']), 'allowance': control['phases'][-1],
                    'native_directories': {name: native_directory.directory(f.writer.root if name == '.'
                        else f.writer.root / name) for name in native_directory.DIRECTORIES}}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.writer._point, f.binding.fault, f.store.fault = cut, cut, cut
        f.final._finish(submission_head=self.head, inputs=f.inputs)
        raise AssertionError('Expected original native-directory cut not reached')

    # Reap one real SIGKILL child and reopen only its original authoritative Store head.
    def killed(self, point):
        f = self.f
        f.submitted()
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
        witness = fixture.packet._decode((f.root / 'actual-child-cut.json').read_bytes())
        self.assertEqual((witness['pid'], witness['point']), (pid, point))
        self.assertEqual(hashlib.sha256(witness['broker_raw'].encode()).hexdigest(), witness['broker_sha256'])
        ended = {'pid': pid, 'point': point, 'head': witness['head'], 'exitcode': -9,
                 'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}
        f.legacy.write_once(f.root / 'actual-child-exit.json', demand.encoded(ended))
        ACTUAL_KILL_FILES.append((str(f.root / 'actual-child-cut.json'), str(f.root / 'actual-child-exit.json')))
        self.reopen(witness['head'])
        return witness

    # Reproduce late exhaustion in old mode after the real broker has accepted an order.
    def test_a_legacy_late_slot_gap(self):
        f = self.f
        f.submitted(submit=False)
        head = f.store.snapshot()['head']
        before = paper.state_path(f.nightly.root).read_bytes()
        with self.assertRaisesRegex(ValueError, 'slots exhausted'):
            f.submit_original()
        self.assertEqual([order['qty'] for order in f.client._orders.values()], ['5'])
        self.assertEqual(f.store.snapshot()['head'], head)
        self.assertEqual(paper.state_path(f.nightly.root).read_bytes(), before)
        self.assertEqual(f.writer._control()['next_slot'], 2)
        BASELINE_OBSERVATIONS.append({'scope': 'ACTUAL_OLD_MODE_LATE_EXHAUSTION_NOT_ACCEPTANCE',
            'accepted_qty': '5', 'slot': 2, 'head': head})

    # Exhausted submission allowance refuses before observation, order, save or latch.
    def test_b_submission_pre_effect_exhaustion(self):
        f = self.f
        f.submitted(submit=False)
        head, before = f.store.snapshot()['head'], self.state()
        latch = f.bridge.latch_bytes(f.store, f.nightly.root, '2019-03-01')
        self.assertIsNone(latch)
        with self.assertRaisesRegex(ValueError, 'exhausted BEFORE effects'):
            f.submit_original()
        self.assertEqual(self.state(), before)
        self.assertEqual(f.client._orders, {})
        self.assertEqual(f.store.snapshot()['head'], head)
        self.assertTrue(f.binding._control()['failed'])
        self.paused(f.submit_original)
        self.assertEqual(f.bridge.latch_bytes(f.store, f.nightly.root, '2019-03-01'), latch)

    # Exhausted final allowance refuses before the real flush can create a fill.
    def test_c_final_pre_flush_exhaustion(self):
        f = self.f
        f.submitted()
        head, before = f.store.snapshot()['head'], self.state()
        self.assertEqual([o['status'] for o in f.client._orders.values()], ['accepted'])
        with self.assertRaisesRegex(ValueError, 'exhausted BEFORE effects'):
            f.final._finish(submission_head=head, inputs=f.inputs)
        self.assertEqual(self.state(), before)
        self.assertEqual([o['status'] for o in f.client._orders.values()], ['accepted'])
        self.paused(lambda: f.final._recover(submission_head=head, inputs=f.inputs))

    # Consume exactly five original slots through the real graph and metadata-only recovery.
    def test_d_exact_full_graph_and_recovery(self):
        f = self.f
        f.submitted()
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
        control = f.binding._control()
        self.assertEqual([p['status'] for p in control['phases']], ['COMPLETE'] * 7)
        self.assertEqual([p['save_allowance']['count'] for p in control['phases']], [1, 1, 0, 0, 1, 1, 1])
        self.assertEqual([p['save_allowance']['first'] for p in control['phases']], [0, 1, 2, 2, 2, 3, 4])
        self.assertEqual(len(control['records']), 5)
        self.assertEqual(f.context.policy_calls, 2)
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty']), (8, 5))
        self.assertGreater(paper.state_path(f.nightly.root).stat().st_size, 262144)
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        self.assertIs(f.binding.binding['capacity_reserved'], False)

    # A manually armed negative unit cannot save under a zero-count PREPARE lease.
    def test_e_zero_count_and_typed_claim(self):
        f = self.f
        directory = f.nightly.root / 'operations' / ('a' * 64)
        protocol.create(f.nightly, directory, phase='PREPARE', inputs='b' * 64)
        f.io.begin(f.nightly, directory, f.legacy)
        lease, before = deepcopy(f.io.directory_lease), self.state()
        self.assertEqual(lease['save_allowance'], {'schema': native_directory.SAVE_SCHEMA, 'first': 0, 'count': 0})
        for field, value in (('count', 1), ('count', False), ('first', True), ('first', 1)):
            altered = deepcopy(lease)
            altered['save_allowance'][field] = value
            with self.assertRaises(ValueError):
                f.binding.verify(altered)
        with self.assertRaisesRegex(ValueError, 'exceeds original pre-effect allowance'):
            f.io.save(f.nightly.root, paper.PaperState())
        self.assertEqual(self.state(), before)
        self.assertTrue(f.binding._control()['failed'])

    # An exact one-save phase cannot publish a zero-save result or downgrade its evidence.
    def test_f_underconsumption_and_evidence_downgrade(self):
        f = self.f
        directory = f.nightly.root / 'operations' / ('c' * 64)
        protocol.create(f.nightly, directory, phase='BIRTH', inputs='d' * 64)
        f.io.begin(f.nightly, directory, f.legacy)
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'Exact reserved native save count'):
            f.binding.complete(f.io.directory_lease, 'e' * 64)
        evidence = f.io.evidence()
        with self.assertRaisesRegex(ValueError, 'Exact phase save count'):
            reserved_io.validate(f.nightly, directory, evidence, [], f.legacy, evidence)
        altered = deepcopy(evidence)
        altered['schema'] = reserved_io.DIRECTORY_SCHEMA
        with self.assertRaises(ValueError):
            reserved_io.validate(f.nightly, directory, altered, [], f.legacy, altered)
        self.assertEqual(self.state(), before)
        self.assertEqual(f.binding._control()['phases'][-1]['status'], 'OPEN')

    # A durable allowance cut before final effects never grants replay authority.
    def test_g_actual_allowance_before_effects(self):
        row = self.killed('native_save_allowance_reserved')
        self.assertEqual(row['allowance']['save_allowance'], {'first': 3, 'count': 1})
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertIsNone(row['directory_pending'])
        self.assertEqual(row['head'], self.head)
        self.paused(lambda: self.f.final._recover(submission_head=self.head, inputs=self.f.inputs))

    # Pending slot consumption before the original writer remains unreadable and unreplayable.
    def test_h_actual_pending_before_native(self):
        row = self.killed('native_directory_pending')
        self.assertEqual(row['directory_pending']['slot'], 3)
        self.assertEqual(row['writer']['next_slot'], 3)
        self.assertIsNone(row['writer']['operation'])
        self.paused(lambda: self.f.final._recover(submission_head=self.head, inputs=self.f.inputs))
        f = self.f
        first = f.binding._control()['records'][0]
        lease = f.binding._lease_value(first['phase'], f.binding._control()['phases'][first['phase']])
        self.assertEqual(f.binding.verify_save(lease, first['receipt']), first['receipt'])

    # Original published final result recovers only exact count seals without another native write.
    def test_i_actual_original_result_before_seal(self):
        row = self.killed('reserved_final_result_written')
        self.assertEqual(row['directory_records'], 4)
        self.assertEqual(row['allowance']['status'], 'OPEN')
        before = self.state()
        result = self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)
        self.assertEqual(result['head'], row['head'])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.binding._control()['phases'][-1]['status'], 'COMPLETE')
        self.assertEqual(self.f.final._recover(submission_head=self.head, inputs=self.f.inputs), result)
        self.assertEqual(self.state(), before)
