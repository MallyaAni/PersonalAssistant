"""NEW private SQLite-bank acceptance; closed protocol tests are not imported or rerun."""
from copy import deepcopy
import hashlib
import multiprocessing
import os
from pathlib import Path
import signal
import sqlite3
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_protocol as protocol
from backend.market import historical_reserved_sqlite as sqlbanks
from backend.market.historical_packet_store import Store
from backend.tests import synthetic_reserved_sqlite_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


# Exercise fresh real SQLite/native composition under the separately versioned bank strategy.
class ReservedSQLiteTests(unittest.TestCase):
    # Initialize every durable bank before a Store reservation or native account effect.
    def setUp(self):
        self.f = fixture.Fixture(self._testMethodName)

    # Retain original pool allocation/name observations and never delete failed or completed evidence.
    def tearDown(self):
        f = self.f
        PHYSICAL_OBSERVATIONS.append({'test': self._testMethodName,
            'fields': ['st_dev', 'st_ino', 'st_size', 'st_blocks'],
            'cas_root': str(f.cas.root), 'before': f.before, 'after': f.inventory(),
            'metadata_root': str(f.metadata.root), 'metadata_before': f.metadata_before,
            'metadata_after': f.metadata_inventory(), 'metadata_names': sorted(p.name for p in f.metadata.root.iterdir()),
            'sqlite_root': str(f.sql.directory), 'sqlite_before': f.sql_before,
            'sqlite_after': f.sql_inventory(), 'sqlite_names': sorted(p.name for p in f.sql.directory.iterdir())})
        self.assertFalse((f.store.root / 'state.sqlite').exists())
        self.assertFalse((f.store.root / 'state.sqlite-journal').exists())
        f.close()

    # Observe actual native state and the published SQLite selector without treating RAM as authority.
    def state(self):
        f = self.f
        path = paper.state_path(f.nightly.root)
        client = getattr(f, 'client', None)
        return (path.read_bytes() if path.exists() else None,
            None if client is None else codec.encode(client, **f.nightly.pins()),
            (f.writer.root / 'control').read_bytes(), (f.raw.root / 'control').read_bytes(),
            f.sql._control()['current'], f.context.policy_calls, len(fixture.CALLS))

    # Reopen only the original authenticated published image and both existing component namespaces.
    def reopen(self, head):
        f = self.f
        root = f.store.root
        f.store.close()
        f.sql = sqlbanks.SQLiteBanks(root, identity=f.identity)
        f.cas = cas.ReservedCAS(root / 'reserved-blobs', identity=f.identity)
        f.metadata = protocol.MetadataSlots(root / 'reserved-protocol', identity=f.identity)
        f.store = Store(root, f.identity, head, blob_reservation=f.cas,
                        metadata_reservation=f.metadata, sqlite_reservation=f.sql)
        f.nightly.store, f.nightly.expected_head = f.store, head

    # Retain bounded actual child RAM/publication/native witnesses at one owned protocol cut.
    def child(self, kind, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Publish a test-only witness outside the reserved SQLite and metadata namespaces.
        def cut(boundary):
            if boundary == point:
                control = f.sql._control()
                broker = codec.encode(f.client, **f.nightly.pins())
                row = {'pid': os.getpid(), 'kind': kind, 'point': point,
                    'head': control['current']['head'], 'ram_head': f.store.snapshot()['head'],
                    'generation': control['current']['generation'], 'pending': control['pending'],
                    'policy_calls': f.context.policy_calls, 'broker_raw': broker.decode(),
                    'broker_sha256': hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(paper.state_path(f.nightly.root).read_bytes()).hexdigest(),
                    'open_operations': [dict(row) for row in f.store.connection.execute(
                        "SELECT id,stage,status FROM operations WHERE status='OPEN'")]}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault, f.sql.fault = cut, cut
        if kind == 'submission':
            f.submit_original()
        else:
            f.final._finish(submission_head=self.head, inputs=f.inputs)
        raise AssertionError('Expected SQLite publication cut not reached')

    # Own one child, require its exact kill/reap result, and reopen its authoritative published head.
    def killed(self, kind, point):
        f = self.f
        f.submitted(submit=kind != 'submission')
        self.head = f.store.snapshot()['head']
        f.store.close()
        process = multiprocessing.get_context('fork').Process(target=self.child, args=(kind, point))
        pid, exitcode, alive = None, None, False
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
        raw = (f.root / 'actual-child-cut.json').read_bytes()
        witness = fixture.packet._decode(raw)
        self.assertEqual((witness['pid'], witness['kind'], witness['point']), (pid, kind, point))
        self.assertEqual(hashlib.sha256(witness['broker_raw'].encode()).hexdigest(), witness['broker_sha256'])
        ended = {'pid': pid, 'point': point, 'head': witness['head'], 'exitcode': -9,
                 'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}
        f.legacy.write_once(f.root / 'actual-child-exit.json', demand.encoded(ended))
        ACTUAL_KILL_FILES.append((str(f.root / 'actual-child-cut.json'), str(f.root / 'actual-child-exit.json')))
        self.reopen(witness['head'])
        return witness

    # Repeat a metadata-only refusal while proving published/native state did not change.
    def paused(self, action):
        before = self.state()
        for _ in range(2):
            with self.assertRaises((ValueError, FileNotFoundError)):
                action()
            self.assertEqual(self.state(), before)

    # Real SQL reservations, native partial final, reopen and same-session Nightly retain one authority.
    def test_a_full_bank_graph_and_nightly(self):
        f = self.f
        f.submitted()
        head = f.store.snapshot()['head']
        result = f.final._finish(submission_head=head, inputs=f.inputs)
        self.assertEqual(f.sql._control()['current']['head'], result['head'])
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
        self.assertEqual(f.context.policy_calls, 2)
        self.assertEqual([row['status'] for row in f.sql._control()['phases']], ['COMPLETE'] * 7)
        self.assertEqual([row['status'] for row in f.cas._control()['groups']], ['COMPLETE'] * 7)
        self.assertEqual(f.store.connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 7)
        self.assertEqual(f.store.connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty'], state.journal[0]['status']),
                         (8, 5, 'partial'))
        self.assertGreater(paper.state_path(f.nightly.root).stat().st_size, 262144)
        self.assertIn(b'NaN', paper.state_path(f.nightly.root).read_bytes())
        self.assertEqual(f.sql_before, f.sql_inventory())

    # A durably published SUBMISSION reservation exists before any new native submit callback.
    def test_b_actual_durable_submission_reservation(self):
        row = self.killed('submission', 'after_commit')
        self.assertEqual(row['ram_head'], row['head'])
        self.assertIsNone(row['pending'])
        self.assertEqual([r['stage'] for r in row['open_operations']], ['SUBMISSION_CAPTURED'])
        broker = codec.restore(row['broker_raw'].encode(), expected_sha256=row['broker_sha256'],
                               **self.f.nightly.pins())
        self.assertEqual(broker._orders, {})
        self.assertEqual(self.f.writer._control()['next_slot'], 2)
        self.paused(self.f.submit_original)

    # A native final followed by RAM COMMIT never adopts its unpublished SQLite head.
    def test_c_actual_ram_commit_before_publication(self):
        row = self.killed('final', 'sqlite_ram_committed')
        self.assertNotEqual(row['ram_head'], row['head'])
        self.assertIsNotNone(row['pending'])
        self.assertEqual(self.f.store.snapshot()['head'], self.head)
        self.paused(lambda: self.f.final._recover(submission_head=self.head, inputs=self.f.inputs))

    # Even a fully fsynced inactive image stays unadopted before its selector is published.
    def test_d_actual_inactive_bank_written(self):
        row = self.killed('final', 'sqlite_bank_written')
        self.assertNotEqual(row['ram_head'], row['head'])
        self.assertIsNotNone(row['pending'])
        self.assertEqual(self.f.store.snapshot()['head'], self.head)
        self.paused(lambda: self.f.final._recover(submission_head=self.head, inputs=self.f.inputs))

    # An authoritative published final recovers only original metadata without another SQL generation.
    def test_e_actual_published_final(self):
        row = self.killed('final', 'sqlite_published')
        self.assertEqual(row['ram_head'], row['head'])
        self.assertIsNone(row['pending'])
        before = self.state()
        result = self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)
        self.assertEqual(result['head'], row['head'])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.final._recover(submission_head=self.head, inputs=self.f.inputs), result)
        self.assertEqual(self.state(), before)

    # Original result recovery seals only original SQL/CAS metadata without adopting a child broker.
    def test_f_actual_result_before_sql_seal(self):
        row = self.killed('final', 'reserved_final_result_written')
        self.assertEqual(row['ram_head'], row['head'])
        self.assertEqual(self.f.sql._control()['phases'][-1]['status'], 'OPEN')
        before = self.state()
        result = self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.sql._control()['phases'][-1]['status'], 'COMPLETE')
        self.assertEqual(self.f.final._recover(submission_head=self.head, inputs=self.f.inputs), result)
        self.assertEqual(self.state(), before)

    # Actual SQLite page exhaustion before birth poisons shortcuts and held cursors without native work.
    def test_g_actual_page_full_before_birth(self):
        f = self.f
        cursor = f.store.connection.execute("SELECT raw FROM meta")
        before = self.state()
        with self.assertRaises(sqlite3.DatabaseError) as caught:
            with f.store._transaction():
                for index in range(3):
                    f.store.connection.execute('INSERT INTO meta VALUES (?,?)',
                                                ('SYNTHETIC-cap-' + str(index), bytes(200000)))
        self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_FULL)
        self.assertTrue(f.sql._control()['failed'])
        self.assertIsNotNone(f.sql._control()['pending'])
        for action in (f.store.snapshot, cursor.fetchone, cursor.fetchall,
                       lambda: f.store.connection.executemany('SELECT 1', []), f.store.connection.serialize):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.state(), before)
        self.reopen(None)
        self.assertEqual(f.store.snapshot()['head'], None)
        self.paused(lambda: f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io))
        self.assertEqual(f.writer._control()['next_slot'], 0)

    # Exact previously prepared mutation and every supplied disk/DDL route remain structurally refused.
    def test_h_uncached_authorizer_and_memory_policy(self):
        f = self.f
        statement = 'INSERT INTO meta VALUES (?,?)'
        with f.store._transaction():
            f.store.connection.execute(statement, ('SYNTHETIC-allowed', b'a'))
        for action in (
            lambda: f.store.connection.execute(statement, ('SYNTHETIC-outside', b'b')),
            lambda: f.store.connection.cursor().executemany(statement, [('SYNTHETIC-batch', b'b')]),
            lambda: f.store.connection.execute('ATTACH DATABASE ? AS escaped', (str(f.root / 'escape.sqlite'),)),
            lambda: f.store.connection.execute('PRAGMA temp_store=FILE'),
            lambda: f.store.connection.execute('PRAGMA journal_mode=DELETE'),
            lambda: f.store.connection.execute('CREATE TEMP TABLE escaped (x)'),
            lambda: f.store.connection.execute('VACUUM'),
            lambda: f.store.connection.execute("SELECT load_extension('SYNTHETIC-forbidden')")):
            with self.assertRaises(sqlite3.DatabaseError):
                action()
        self.assertIsNone(f.store.connection.execute(
            "SELECT raw FROM meta WHERE key='SYNTHETIC-outside'").fetchone())
        self.assertFalse((f.root / 'escape.sqlite').exists())
        self.assertEqual(f.store.connection.execute('PRAGMA journal_mode').fetchone()[0], 'memory')
        self.assertEqual(f.store.connection.execute('PRAGMA temp_store').fetchone()[0], 2)
        self.assertEqual([tuple(r) for r in f.store.connection.execute('PRAGMA database_list')], [(0, 'main', '')])
        f.client, f.birth = f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
        self.assertEqual(f.writer._control()['next_slot'], 1)

    # Inconsistent pending generation/bank data cannot overwrite the original published bank.
    def test_i_generation_overlap_refusal(self):
        f = self.f
        before = self.state()
        value = deepcopy(f.sql._control())
        value['used'] += 1
        value['bootstrap_used'] += 1
        value['pending'] = {'generation': value['used'], 'bank': value['current']['bank'], 'head': None}
        physical._fixed_write(f.sql.directory / 'control', value)
        with self.assertRaises(ValueError):
            f.sql._control()
        with self.assertRaises(ValueError):
            f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
        self.assertEqual(f.writer._control()['next_slot'], 0)
        self.assertEqual(paper.state_path(f.nightly.root).exists(), before[0] is not None)

    # Original external mode refuses a native state.sqlite fallback before opening or creating that path.
    def test_j_missing_explicit_sql_mode(self):
        f = self.f
        root = f.store.root
        f.store.close()
        with self.assertRaisesRegex(ValueError, 'SQLite bank mode'):
            Store(root, f.identity, None, blob_reservation=f.cas, metadata_reservation=f.metadata)
        self.assertFalse((root / 'state.sqlite').exists())
        self.reopen(None)
        self.assertEqual(f.store.snapshot()['head'], None)

    # A caught fsynced-bank publication failure poisons live SQL and preserves only the old published image.
    def test_k_caught_bank_failure(self):
        f = self.f
        before = self.state()
        cursor = f.store.connection.execute('SELECT raw FROM meta')

        # Inject one explicit publication error after inactive-bank fsync, never a fake process cut.
        def cut(point):
            if point == 'sqlite_bank_written':
                raise ValueError('SYNTHETIC bank publication uncertainty')

        f.sql.fault = cut
        with self.assertRaisesRegex(ValueError, 'publication uncertainty'):
            with f.store._transaction():
                f.store.connection.execute("INSERT INTO meta VALUES ('SYNTHETIC-unpublished',?)", (b'x',))
        self.assertTrue(f.sql.live_failed)
        self.assertTrue(f.sql._control()['failed'])
        for action in (f.store.snapshot, cursor.fetchone):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.state(), before)
        self.reopen(None)
        self.assertIsNone(f.store.connection.execute(
            "SELECT raw FROM meta WHERE key='SYNTHETIC-unpublished'").fetchone())
        self.paused(lambda: f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io))
        self.assertEqual(f.writer._control()['next_slot'], 0)
