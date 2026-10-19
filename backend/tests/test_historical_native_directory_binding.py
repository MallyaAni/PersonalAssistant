"""NEW native-directory lineage assertions; no directory-capacity or old-gate claim."""
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
from backend.tests import synthetic_native_directory_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS, BASELINE_OBSERVATIONS = [], [], []


# Exercise fresh original native rename lineage and pre-effect namespace refusals.
class NativeDirectoryTests(unittest.TestCase):
    # Keep the legacy missing-parent control explicitly separate from the new bound accounts.
    def setUp(self):
        self.f = fixture.Fixture(self._testMethodName,
                                 bind_directory=not self._testMethodName.startswith('test_a_'))

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
                row = {'pid': os.getpid(), 'kind': 'native-directory-final', 'point': point,
                    'head': f.store.snapshot()['head'], 'policy_calls': f.context.policy_calls,
                    'broker_raw': broker.decode(), 'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'writer': f.writer._control(), 'directory_cursor': control['cursor'],
                    'directory_pending': control['pending'], 'directory_records': len(control['records']),
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

    # Reproduce the unchanged unbound writer's directory recreation before missing-temp refusal.
    def test_a_actual_legacy_missing_parent_gap(self):
        f = self.f
        paper_dir = f.nightly.root / 'paper'
        original = native_directory.directory(paper_dir)
        held = f.root / 'original-paper-directory'
        paper_dir.rename(held)
        try:
            with self.assertRaises(FileNotFoundError):
                f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
            self.assertTrue(paper_dir.is_dir())
            self.assertEqual(list(paper_dir.iterdir()), [])
            self.assertFalse(paper.state_path(f.nightly.root).exists())
            self.assertEqual((f.writer._control()['operation'], f.writer._control()['next_slot']), (0, 1))
            BASELINE_OBSERVATIONS.append({'scope': 'ACTUAL_UNBOUND_LEGACY_GAP_NOT_ACCEPTANCE',
                'original': original, 'recreated': [str(getattr(paper_dir.stat(), key)) for key in
                    ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_blocks', 'st_nlink')],
                'native_operation_adopted': False})
            paper_dir.rename(f.root / 'retained-native-recreated-paper')
        finally:
            held.rename(paper_dir)

    # The original held parent must exist before birth can charge or recreate a native directory.
    def test_b_bound_missing_parent_before_birth(self):
        f = self.f
        paper_dir, held = f.nightly.root / 'paper', f.root / 'original-paper-directory'
        paper_dir.rename(held)
        try:
            before = self.state()
            for _ in range(2):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
                self.assertFalse(os.path.lexists(paper_dir))
                self.assertEqual(self.state(), before)
            self.assertEqual((f.writer._control()['operation'], f.writer._control()['next_slot']), (None, 0))
            self.assertTrue(f.binding._control()['failed'])
        finally:
            held.rename(paper_dir)

    # Exact actual rename transitions compose final commitment, original recovery and same-session Nightly.
    def test_c_full_original_namespace_graph(self):
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
        self.assertEqual(len(control['records']), 5)
        self.assertEqual(f.context.policy_calls, 2)
        self.assertIs(f.binding.binding['capacity_reserved'], False)
        self.assertIs(f.writer.header['directory_metadata_reserved'], False)
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty']), (8, 5))
        self.assertGreater(paper.state_path(f.nightly.root).stat().st_size, 262144)
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())

    # A cut before the actual original replace keeps the new directory lease pending and unreplayable.
    def test_d_actual_before_native_replace(self):
        row = self.killed('before_native_replace')
        self.assertIsNotNone(row['directory_pending'])
        self.assertEqual(row['writer']['operation'], row['directory_pending']['slot'])
        self.assertEqual(row['directory_records'], 3)
        before = self.state()
        self.paused(lambda: self.f.final._recover(submission_head=self.head, inputs=self.f.inputs))
        self.assertEqual(self.state(), before)
        first = self.f.binding._control()['records'][0]
        lease = {'schema': native_directory.SCHEMA, 'pool': self.f.binding.binding,
                 'slot': first['phase'], 'claim': self.f.binding._control()['phases'][first['phase']]['claim']}
        self.assertEqual(self.f.binding.verify_save(lease, first['receipt']), first['receipt'])

    # A published namespace/native save alone never manufactures a prepared final or replay authority.
    def test_e_actual_directory_result_before_caller(self):
        row = self.killed('native_directory_result_written')
        self.assertIsNone(row['directory_pending'])
        self.assertIsNone(row['writer']['operation'])
        self.assertEqual(row['directory_records'], 4)
        self.assertEqual(row['writer'], row['directory_cursor'])
        self.paused(lambda: self.f.final._recover(submission_head=self.head, inputs=self.f.inputs))

    # A committed outcome recovers only original metadata seals without another rename or save.
    def test_f_actual_committed_original_recovery(self):
        row = self.killed('after_commit')
        self.assertNotEqual(row['head'], self.head)
        before = self.state()
        result = self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)
        self.assertEqual(result['head'], row['head'])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.final._recover(submission_head=self.head, inputs=self.f.inputs), result)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.binding._control()['phases'][-1]['status'], 'COMPLETE')

    # An unexpected native name refuses submission before observe, broker acceptance, save or latch.
    def test_g_unexpected_name_before_submission(self):
        f = self.f
        f.submitted(submit=False)
        path = f.nightly.root / 'paper' / 'SYNTHETIC-unexpected'
        path.write_bytes(b'Explicit negative harness fault')
        before = self.state()
        try:
            self.paused(f.submit_original)
            self.assertEqual(self.state(), before)
            self.assertEqual(f.client._orders, {})
            self.assertEqual(f.writer._control()['next_slot'], 2)
            self.assertTrue(f.binding._control()['failed'])
        finally:
            path.rename(f.root / 'retained-unexpected-name-fault')

    # Omitted persisted mode and older native evidence cannot downgrade the new namespace admission.
    def test_h_mandatory_mode_and_original_phase(self):
        f = self.f
        f.submitted()
        head = f.store.snapshot()['head']
        f.store.close()
        with self.assertRaisesRegex(ValueError, 'native-directory mode'):
            Store(f.store.root, f.identity, head, sqlite_reservation=f.sql,
                  blob_reservation=f.cas, metadata_reservation=f.metadata)
        self.reopen(head)
        first = f.binding._control()['records'][0]
        lease = {'schema': native_directory.SCHEMA, 'pool': f.binding.binding, 'slot': first['phase'],
                 'claim': f.binding._control()['phases'][first['phase']]['claim']}
        altered = deepcopy(lease)
        altered['claim']['inputs'] = '0' * 64
        with self.assertRaises(ValueError):
            f.binding.verify(altered)
        record = f.nightly.read_lifecycle(f.birth, raw_checkpoint=f.raw)
        evidence = deepcopy(record['value']['detail']['reserved_native_io'])
        evidence.pop('native_directory')
        evidence['schema'] = reserved_io.SQLITE_SCHEMA
        with self.assertRaises(ValueError):
            reserved_io.validate(f.nightly, f.nightly.operation('BIRTH', '2019-02-28'), evidence,
                [(first['receipt']['state']['sha256'], first['receipt']['state']['length'])],
                f.legacy, record['operation']['native_io'])
        self.assertEqual(f.binding.verify_save(lease, first['receipt']), first['receipt'])
        before = self.state()
        with self.assertRaises(ValueError):
            f.binding.save(lease, paper.PaperState(), expected_preimage=f.writer._control()['current'])
        self.assertEqual(self.state(), before)
        self.assertEqual(f.binding.verify_save(lease, first['receipt']), first['receipt'])

    # Caught post-native uncertainty leaves PENDING forever, with older successful records still readable.
    def test_i_caught_directory_publication_uncertainty(self):
        f = self.f
        f.submitted()
        head = f.store.snapshot()['head']

        # Inject one explicit post-native exception before namespace result publication.
        def cut(point):
            if point == 'native_directory_returned':
                raise ValueError('SYNTHETIC directory publication uncertainty')

        f.binding.fault = cut
        with self.assertRaisesRegex(ValueError, 'directory publication uncertainty'):
            f.final._finish(submission_head=head, inputs=f.inputs)
        self.assertTrue(f.binding._control()['failed'])
        self.assertIsNotNone(f.binding._control()['pending'])
        self.assertEqual(f.binding._control()['cursor']['next_slot'], 3)
        self.assertEqual(f.writer._control()['next_slot'], 4)
        first = f.binding._control()['records'][0]
        lease = {'schema': native_directory.SCHEMA, 'pool': f.binding.binding, 'slot': first['phase'],
                 'claim': f.binding._control()['phases'][first['phase']]['claim']}
        self.assertEqual(f.binding.verify_save(lease, first['receipt']), first['receipt'])
        self.paused(lambda: f.final._recover(submission_head=head, inputs=f.inputs))
