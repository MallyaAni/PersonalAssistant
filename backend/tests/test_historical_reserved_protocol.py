"""NEW fixed marker/latch assertions; no closed acceptance test body is invoked."""
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
from backend.market import historical_timing_packet as packet
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import synthetic_reserved_protocol_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []


# Exercise new actual metadata composition on fresh private accounts and finite pools.
class ReservedProtocolTests(unittest.TestCase):
    # Initialize every original namespace extent before birth or any broker callback.
    def setUp(self):
        self.f = fixture.Fixture(self._testMethodName)

    # Retain exact original namespace/allocation observations without deleting evidence.
    def tearDown(self):
        f = self.f
        names = sorted(item.name for item in f.metadata.root.iterdir())
        PHYSICAL_OBSERVATIONS.append({'test': self._testMethodName,
            'fields': ['st_dev', 'st_ino', 'st_size', 'st_blocks'],
            'cas_root': str(f.cas.root), 'before': f.before, 'after': f.inventory(),
            'metadata_root': str(f.metadata.root), 'metadata_before': f.metadata_before,
            'metadata_after': f.metadata_inventory(), 'metadata_names': names})
        f.close()

    # Compare actual native/Store state while permitting only original metadata completion.
    def state(self):
        f = self.f
        path = paper.state_path(f.nightly.root)
        client = getattr(f, 'client', None)
        return (path.read_bytes() if path.exists() else None,
            None if client is None else codec.encode(client, **f.nightly.pins()),
            (f.writer.root / 'control').read_bytes(), (f.raw.root / 'control').read_bytes(),
            f.store.snapshot(), f.context.policy_calls, len(fixture.CALLS))

    # Reopen with both original explicitly persisted pools and the actual observed head.
    def reopen(self, head):
        f = self.f
        root = f.store.root
        f.store.close()
        f.cas = cas.ReservedCAS(root / 'reserved-blobs', identity=f.identity)
        f.metadata = protocol.MetadataSlots(root / 'reserved-protocol', identity=f.identity)
        f.store = Store(root, f.identity, head, blob_reservation=f.cas, metadata_reservation=f.metadata)
        f.nightly.store, f.nightly.expected_head = f.store, head

    # Execute one owned protocol-boundary child and persist its actual native evidence before kill.
    def child(self, kind, point):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        f = self.f
        self.reopen(self.head)

        # Publish bounded test-only witness files outside the reserved product namespace.
        def cut(boundary):
            if boundary == point:
                client = getattr(f, 'client', None)
                broker = None if client is None else codec.encode(client, **f.nightly.pins())
                path = paper.state_path(f.nightly.root)
                row = {'pid': os.getpid(), 'kind': kind, 'point': point,
                    'head': f.store.snapshot()['head'], 'policy_calls': f.context.policy_calls,
                    'broker_raw': None if broker is None else broker.decode(),
                    'broker_sha256': None if broker is None else hashlib.sha256(broker).hexdigest(),
                    'paper_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
                    'metadata_pending': f.metadata._control()['pending']}
                f.legacy.write_once(f.root / 'actual-child-cut.json', demand.encoded(row))
                os.kill(os.getpid(), signal.SIGKILL)

        f.store.fault, f.metadata.fault = cut, cut
        if kind == 'birth':
            f.client, f.birth = f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
        elif kind == 'latch':
            f.submit_original()
        else:
            result = f.final._finish(submission_head=self.head, inputs=f.inputs)
            if kind == 'nightly':
                f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
                    previous=result['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io)
        raise AssertionError('Actual metadata SIGKILL boundary was not reached')

    # Bound, reap and authenticate one child before any read or metadata recovery.
    def killed(self, kind, point):
        f = self.f
        if kind != 'birth':
            f.submitted(submit=kind != 'latch')
        self.head = f.store.snapshot()['head']
        f.store.close()
        child = multiprocessing.get_context('fork').Process(target=self.child, args=(kind, point))
        try:
            watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM}
            old = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                child.start()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
            child.join(timeout=20)
            self.assertFalse(child.is_alive())
            self.assertEqual(child.exitcode, -signal.SIGKILL)
            row = packet._decode((f.root / 'actual-child-cut.json').read_bytes())
            self.assertEqual((row['pid'], row['point'], row['kind']), (child.pid, point, kind))
            if row['broker_raw'] is not None:
                self.assertEqual(hashlib.sha256(row['broker_raw'].encode()).hexdigest(), row['broker_sha256'])
            self.reopen(row['head'])
            exit_row = {'pid': child.pid, 'point': point, 'head': row['head'], 'exitcode': child.exitcode,
                        'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}
            f.legacy.write_once(f.root / 'actual-child-exit.json', demand.encoded(exit_row))
            ACTUAL_KILL_FILES.append((str(f.root / 'actual-child-cut.json'), str(f.root / 'actual-child-exit.json')))
            return row
        finally:
            if child.pid is not None and child.is_alive():
                child.terminate()
                child.join(timeout=1)
                if child.is_alive():
                    child.kill()
                    child.join(timeout=1)
            if child.pid is not None:
                self.assertFalse(child.is_alive())
                child.close()

    # Refuse any native replay while leaving the observed original native/Store state unchanged.
    def paused(self, action):
        before = self.state()
        for _ in range(2):
            with self.assertRaises((ValueError, FileNotFoundError)):
                action()
            self.assertEqual(self.state(), before)

    # Preserve exact semantic absence/bytes, original inodes, commitment and all private continuations.
    def test_a_full_namespace_journey_and_reopen(self):
        f = self.f
        self.assertIsNone(f.metadata.read_latch('2019-03-01'))
        f.submitted()
        self.assertEqual(f.metadata.read_latch('2019-03-01'),
            demand.encoded({'session': '2019-03-01', 'scope': 'SYNTHETIC_LATCH'}))
        head = f.submission['head']
        final = f.final._finish(submission_head=head, inputs=f.inputs)
        self.reopen(final['head'])
        before = self.state()
        self.assertEqual(f.final._recover(submission_head=head, inputs=f.inputs), final)
        self.assertEqual(self.state(), before)
        close = f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=final['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io)
        self.reopen(final['head'])
        before = self.state()
        self.assertEqual(f.nightly._close(f.context, f.client, '2019-03-01', birth=f.birth,
            previous=final['receipt'], raw_checkpoint=f.raw, native_io=f.nightly_io), close)
        self.assertEqual(self.state(), before)
        state = paper.load_state(f.nightly.root)
        self.assertEqual((state.journal[0]['qty'], state.journal[0]['filled_qty'], state.journal[0]['status']),
                         (8, 5, 'partial'))
        raw = paper.state_path(f.nightly.root).read_bytes()
        self.assertGreater(len(raw), 262144)
        self.assertIn(b'NaN', raw)
        self.assertEqual((f.context.policy_calls, len(f.metadata._control()['operations'])), (2, 7))
        self.assertEqual([g['status'] for g in f.cas._control()['groups']], ['COMPLETE'] * 7)
        self.assertEqual(list((f.nightly.root / 'operations').iterdir()), [])
        self.assertFalse((f.nightly.root / 'synthetic-latch').exists())
        for index, operation in enumerate(f.metadata._control()['operations']):
            self.assertIn(operation['phase'], protocol.PHASES)
            self.assertEqual(operation['status'], 'COMPLETE')
            aux = operation['records']['reserved-native-save.json']
            self.assertEqual(aux['status'], 'COMPLETE')
            self.assertEqual(operation['records']['result.json']['status'], 'COMPLETE')
        self.assertEqual(f.metadata_before, f.metadata_inventory())

    # An actual pending-aux cut precedes native birth and cannot authorize a retry.
    def test_b_actual_birth_aux_pending(self):
        row = self.killed('birth', 'metadata_pending_reserved-native-save.json')
        self.assertEqual((row['broker_raw'], row['paper_sha256'], row['policy_calls']), (None, None, 0))
        self.assertEqual(row['metadata_pending'], {'slot': 0, 'role': 'reserved-native-save.json'})
        self.paused(lambda: self.f.nightly._initialize(self.f.context, raw_checkpoint=self.f.raw,
                                                      native_io=self.f.nightly_io))
        with self.assertRaisesRegex(ValueError, 'PENDING'):
            self.f.metadata.read(self.f.nightly.operation('BIRTH', '2019-02-28'), 'reserved-native-save.json')
        self.assertEqual(self.f.writer._control()['next_slot'], 0)

    # Actual accepted submit/save followed by pending latch bytes stays paused with old records readable.
    def test_c_actual_latch_body_pending(self):
        row = self.killed('latch', 'metadata_body_written_latch')
        client = codec.restore(row['broker_raw'].encode(), expected_sha256=row['broker_sha256'],
                               **self.f.nightly.pins())
        self.assertEqual(client._orders['SYNTHETIC-reserved-outcome']['qty'], '5')
        self.assertEqual(row['metadata_pending'], {'slot': 4, 'role': 'latch'})
        with self.assertRaisesRegex(ValueError, 'PENDING'):
            self.f.metadata.read_latch('2019-03-01')
        self.f.nightly.read_raw_birth(self.f.birth, raw_checkpoint=self.f.raw)
        self.paused(self.f.submit_original)
        self.assertEqual(self.f.writer._control()['next_slot'], 3)

    # A committed final fills only its original EMPTY marker and CAS seal after actual process death.
    def test_d_actual_committed_missing_marker(self):
        row = self.killed('final', 'reserved_final_committed')
        self.assertIsNone(row['metadata_pending'])
        before = self.state()
        result = self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.final._recover(submission_head=self.head, inputs=self.f.inputs), result)
        self.assertEqual(self.state(), before)
        _, directory = self.f.final_ns['operation'](self.f.nightly, self.head)
        self.assertEqual(self.f.metadata.read(directory, 'result.json'), demand.encoded(result))
        self.assertEqual(len(self.f.metadata._control()['operations']), 6)
        self.assertEqual(self.f.cas._control()['groups'][-1]['status'], 'COMPLETE')

    # An original completed operation cannot acquire another role or reopen for later writes.
    def test_l_completed_operation_cannot_extend(self):
        f = self.f
        f.client, f.birth = f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
        directory = f.nightly.operation('BIRTH', '2019-02-28')
        original = f.metadata.read(directory, 'result.json')
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'cannot extend'):
            f.metadata.write_once(directory, 'prepared.json', b'{}')
        self.assertEqual(f.metadata._control()['operations'][0]['status'], 'COMPLETE')
        self.assertTrue(f.metadata._control()['failed'])
        self.assertEqual(f.metadata.read(directory, 'result.json'), original)
        f.nightly.read_raw_birth(f.birth, raw_checkpoint=f.raw)
        self.assertEqual(self.state(), before)

    # Even complete-looking result bytes cannot be adopted when their original metadata commit is PENDING.
    def test_e_actual_result_body_pending(self):
        row = self.killed('final', 'metadata_body_written_result.json')
        self.assertEqual(row['metadata_pending'], {'slot': 5, 'role': 'result.json'})
        self.paused(lambda: self.f.final._recover(submission_head=self.head, inputs=self.f.inputs))
        self.f.nightly.read_raw_birth(self.f.birth, raw_checkpoint=self.f.raw)
        self.assertEqual(self.f.cas._control()['groups'][-1]['status'], 'ACTIVE')

    # An original published Nightly marker permits only its missing seal, without another policy/save.
    def test_f_actual_nightly_original_marker(self):
        row = self.killed('nightly', 'reserved_phase_result_written')
        self.assertEqual((row['metadata_pending'], row['policy_calls']), (None, 2))
        result = self.f.final._recover(submission_head=self.head, inputs=self.f.inputs)
        before = self.state()
        close = self.f.nightly._close(self.f.context, self.f.client, '2019-03-01',
            birth=self.f.birth, previous=result['receipt'], raw_checkpoint=self.f.raw, native_io=self.f.nightly_io)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.f.nightly.read_lifecycle(close, raw_checkpoint=self.f.raw)['value']['previous'],
                         result['receipt'])
        self.assertEqual(self.f.cas._control()['groups'][-1]['status'], 'COMPLETE')

    # The unchanged payload cap refuses before body bytes and poisons later native use if caught.
    def test_g_payload_cap_before_birth(self):
        f = self.f
        directory = f.nightly.operation('BIRTH', '2019-02-28')
        f.metadata.claim(directory, phase='BIRTH', head=None, inputs='a' * 64)
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'payload cap'):
            f.metadata.write_once(directory, 'reservation.json', bytes(physical.META + 1))
        self.assertTrue(f.metadata._control()['failed'])
        self.assertIsNone(f.metadata._control()['pending'])
        self.paused(lambda: f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io))
        self.assertEqual(self.state(), before)

    # Exact repeated original bytes are idempotent; conflicting bytes refuse while older results stay readable.
    def test_h_original_bytes_and_conflict(self):
        f = self.f
        f.client, f.birth = f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
        directory = f.nightly.operation('BIRTH', '2019-02-28')
        raw = f.metadata.read(directory, 'result.json')
        control = (f.metadata.root / 'control').read_bytes()
        f.metadata.write_once(directory, 'result.json', raw)
        self.assertEqual((f.metadata.root / 'control').read_bytes(), control)
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'conflict'):
            f.metadata.write_once(directory, 'result.json', b'{}')
        self.assertEqual(f.metadata.read(directory, 'result.json'), raw)
        f.nightly.read_raw_birth(f.birth, raw_checkpoint=f.raw)
        with self.assertRaises(ValueError):
            f.nightly_io.save(f.nightly.root, paper.load_state(f.nightly.root))
        self.assertEqual(self.state(), before)

    # Persisted mode refuses missing original bindings even while its original directory is unavailable.
    def test_i_removed_pool_cannot_downgrade(self):
        f = self.f
        root = f.store.root
        f.store.close()
        moved = root / 'retained-mode-negative'
        f.metadata.root.rename(moved)
        try:
            with self.assertRaisesRegex(ValueError, 'metadata namespace'):
                Store(root, f.identity, None, blob_reservation=f.cas)
        finally:
            moved.rename(f.metadata.root)
        self.assertFalse(paper.state_path(f.nightly.root).exists())
        self.assertEqual(f.context.policy_calls, 0)

    # A changed mandatory source pin rejects reopen and birth before a native effect.
    def test_j_source_header_refusal(self):
        f = self.f
        changed = deepcopy(f.metadata.header)
        key = str(Path(protocol.__file__).parent / 'historical_reserved_native_io.py')
        changed['source_sha256'][key] = '0' * 64
        physical._fixed_write(f.metadata.root / 'header', changed)
        with self.assertRaisesRegex(ValueError, 'source'):
            protocol.MetadataSlots(f.metadata.root, identity=f.identity)
        self.paused(lambda: f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io))
        self.assertEqual(f.writer._control()['next_slot'], 0)

    # Changed original head/claim data cannot create another attempt or enable a later native write.
    def test_k_original_claim_head_refusal(self):
        f = self.f
        f.client, f.birth = f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
        directory = f.nightly.operation('BIRTH', '2019-02-28')
        original = f.metadata.reference(directory)
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            f.metadata.claim(directory, phase='BIRTH', head='0' * 64, inputs=original['inputs'])
        self.assertTrue(f.metadata._control()['failed'])
        self.assertEqual(f.metadata.reference(directory), original)
        f.nightly.read_raw_birth(f.birth, raw_checkpoint=f.raw)
        self.assertEqual(self.state(), before)

    # A published original result ends effects even before the separate CAS phase is sealed.
    def test_m_result_before_cas_seal_refuses_effects(self):
        f = self.f
        observed = []

        # Catch attempted reuse at the actual original-result boundary without another native operation.
        def cut(point):
            if point == 'reserved_phase_result_written':
                self.assertEqual(f.metadata._control()['operations'][0]['status'], 'COMPLETE')
                self.assertEqual(f.cas._control()['groups'][0]['status'], 'ACTIVE')
                before = self.state()
                with self.assertRaisesRegex(ValueError, 'Completed metadata operation'):
                    f.nightly_io.evidence()
                with self.assertRaises(ValueError):
                    f.nightly_io.save(f.nightly.root, paper.load_state(f.nightly.root))
                self.assertEqual(self.state(), before)
                observed.append(point)

        f.store.fault = cut
        f.client, f.birth = f.nightly._initialize(f.context, raw_checkpoint=f.raw, native_io=f.nightly_io)
        self.assertEqual(observed, ['reserved_phase_result_written'])
        self.assertEqual(f.cas._control()['groups'][0]['status'], 'COMPLETE')
        self.assertEqual(f.writer._control()['next_slot'], 1)
        f.nightly.read_raw_birth(f.birth, raw_checkpoint=f.raw)
