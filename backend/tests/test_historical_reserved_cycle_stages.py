"""NEW reserved private Cycle stages; no closed scenario, model or final resolver.

Real native broker/paper/checkpoint and Store execute. Whole source CodeTypes use
explicit synthetic context, decision/trade programs, calendar and source globals.
"""
import ast
import builtins
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import signal
from types import CodeType, FunctionType, SimpleNamespace
import unittest

from backend.agents.trading.desk import paper, intraday_orders
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_checkpoint as checkpoint
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_blob_store as cas
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_synthetic_native_write as writer_module
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import synthetic_reserved_stage_fixture as entities
from backend.tests import synthetic_reserved_nightly_setup as fixture

ACTUAL_KILL_FILES, PHYSICAL_OBSERVATIONS = [], []
CALLS = []


# Keep the exact synthetic Cycle context separate from frozen holding context bytes.
class Context:
    # Retain only supplied finite source-free context bytes and their declared digest.
    def __init__(self, raw, sha256):
        self.raw, self.sha256 = raw, sha256


# Authenticate the explicitly synthetic context without native model/archive admission.
def read_context(value):
    assert hashlib.sha256(value.raw).hexdigest() == value.sha256
    return packet._decode(value.raw)


# Create one real native unsent intent through the explicit reserved Nightly save.
def nightly_trade(report, root, session, force, *, client_factory, decision_at, holding_policy, native_save):
    holding_policy.decide()
    state = paper.load_state(root)
    state.start_equity = float('nan')
    entry = paper.snapshot(state, session, 100000, 100000,
        [{'z': 'é' + str(i) + 'x' * 25000, 'a': float('nan')} for i in range(12)])
    state.pending = [{'client_order_id': 'SYNTHETIC-reserved-cycle', 'symbol': 'AAPL', 'side': 'buy',
        'qty': 8, 'session': session,
        'execute_on': '2019-03-04' if report.mode == 'future' else '2019-03-01',
        'execution_timing': 'dip_or_close'}]
    native_save(root, state)
    return entry


# Return synthetic decisions and drive only the producer's bounded native capabilities.
def program(*, phase, inputs, effects):
    CALLS.append(phase)
    if phase == 'DECISION_FROZEN':
        return {'order': inputs['candidate']}
    effects.observe()
    order = effects.submit()
    state = effects.load()
    state.pending[0].update({'sent': {'qty': int(order['qty']), 'at': order['submitted_at']},
        'execution': {'created_at': order['created_at'], 'submitted_at': order['submitted_at']}})
    effects.save(state)
    effects.latch()
    return {'client_order_id': order['client_order_id'], 'submitted_qty': int(order['qty'])}


# Swallow a deliberate capability refusal to verify persistent lease poisoning.
def catching_program(*, phase, inputs, effects):
    CALLS.append(phase)
    if phase == 'DECISION_FROZEN':
        return {'order': inputs['candidate']}
    try:
        effects.submit()
    except ValueError:
        pass
    effects.observe()
    raise AssertionError('Poisoned submission continued')


# Fail after one real broker observation to test uncertainty outside capability scopes.
def failing_program(*, phase, inputs, effects):
    CALLS.append(phase)
    if phase == 'DECISION_FROZEN':
        return {'order': inputs['candidate']}
    effects.observe()
    raise ValueError('SYNTHETIC program failed after native observation')


# Violate the decision latch invariant directly; module identity is not a sandbox.
def changing_program(*, phase, inputs, effects):
    CALLS.append(phase)
    owner = effects.owner
    path = owner.nightly.root / 'synthetic-latch' / (owner.session + '.json')
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_bytes(demand.encoded({'session': owner.session, 'scope': 'SYNTHETIC_CHANGED_DECISION_LATCH'}))
    return {'order': inputs['candidate']}


# Load complete-source functions/classes with declared synthetic globals, never module startup.
def source_namespace(path, given, classes=()):
    code = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
    codes = {node.co_name: node for node in code.co_consts if type(node) is CodeType}
    tree = ast.parse(path.read_bytes())
    result = {'__name__': 'SYNTHETIC_RESERVED_CYCLE_SOURCE', '__file__': str(path),
              '__builtins__': builtins.__dict__, **given}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            fn = FunctionType(codes[node.name], result)
            fn.__defaults__ = tuple(ast.literal_eval(v) for v in node.args.defaults) or None
            fn.__kwdefaults__ = {arg.arg: ast.literal_eval(value) for arg, value in
                zip(node.args.kwonlyargs, node.args.kw_defaults) if value is not None}
            result[node.name] = fn
    for name in classes:
        result[name] = builtins.__build_class__(FunctionType(codes[name], result), name)
    return result


# Test the actual new stage producer, never pre-seed Store decision/submission fixtures.
class ReservedCycleStagesTests(unittest.TestCase):
    # Bind new pools/account and exact whole stage bodies with a synthetic surrounding context.
    def setUp(self):
        self.case = fixture.RawNightlyLifecycleTests()
        self.case.setUp()
        self.store, self.raw, self.nightly = self.case.store, self.case.raw, self.case.nightly
        self.legacy, self.context = self.case.legacy, self.case.context
        self.initial_calls = len(CALLS)
        base = self.case.fixture.fixture
        cycle = base.cycle
        cycle.update({'codec': codec, 'checkpoint': checkpoint, 'entities': registry})
        cycle['market'].Context, cycle['market'].read_context = Context, read_context
        path = Path(cycle['__file__'])
        compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
        codes = {n.co_name: n for n in compiled.co_consts if type(n) is CodeType}
        cycle['_head_entry'] = FunctionType(codes['_head_entry'], cycle)
        self.bridge_ns = source_namespace(Path('/audit/backend/market/historical_raw_cycle.py'),
            {'date': date, 'sha256': hashlib.sha256, 'Path': Path, 'cycle': SimpleNamespace(**cycle),
             'component': fixture.component, 'packet': packet, 'digest': registry.digest,
             'Store': Store, 'StorePause': StorePause})
        self.bridge_ns.update({'LINEAGE': 'raw-nightly-cycle-lineage/1',
            'LINEAGE_KEYS': {'schema', 'birth', 'previous_nightly', 'context', 'context_identity'}})
        self.bridge = SimpleNamespace(**self.bridge_ns)
        self.case.ns['raw_cycle'] = self.bridge
        self.cas = cas.reserve(self.store)
        self.store.bind_reserved_blobs(self.cas)
        self.writer = writer_module.reserve(self.store.root / 'SYNTHETIC-reserved-workspace',
            writer=paper.save_state, writer_source=Path(paper.__file__), identity=base.profile,
            identity_sha256=self.store.identity, slots=8)
        self.nightly.root = self.writer.root / 'work'
        (self.nightly.root / 'operations').mkdir(mode=0o700)
        self.nightly_io = reserved_io.SyntheticNativeIO(self.writer, nightly_trade,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.io = reserved_io.SyntheticNativeIO(self.writer, program,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.ns = source_namespace(Path('/audit/backend/market/historical_reserved_cycle_stages.py'),
            {'deepcopy': deepcopy, 'contextmanager': contextmanager, 'date': date, 'sha256': hashlib.sha256,
             'Path': Path, 'paper': paper, 'codec': codec, 'legacy': self.legacy, 'demand': demand,
             'registry': registry, 'physical': physical, 'bridge': self.bridge,
             'raw_nightly': SimpleNamespace(__file__=self.case.ns['__file__'],
                 RawNightly=type(self.nightly), sources=self.case.ns['sources']),
             'cas': cas, 'reserved_io': reserved_io, 'packet': packet, 'native': native,
             'Store': Store, 'StorePause': StorePause, 'SCHEMA': 'synthetic-reserved-cycle-stages/1',
             'PHASES': ('PREPARE', 'DECISION_FROZEN', 'SUBMISSION_CAPTURED'),
             'OBSERVE': native.ReplayBroker.observe, 'SUBMIT': native.ReplayBroker._submit,
             'SUBMIT_MARKET': native.ReplayBroker.submit_market,
             'intraday_orders': intraday_orders, 'DUE': intraday_orders.due}, ('_Effects', '_Stages'))
        self.before = self.inventory()

    # Retain complete physical inventories and all account evidence while closing Store.
    def tearDown(self):
        PHYSICAL_OBSERVATIONS.append({'test': self._testMethodName, 'root': str(self.cas.root),
            'fields': ['st_dev', 'st_ino', 'st_size', 'st_blocks'], 'before': self.before, 'after': self.inventory()})
        self.case.tearDown()

    # Record exact original allocated inode identities/sizes/blocks for every CAS file.
    def inventory(self):
        return {name: [str(getattr((self.cas.root / name).stat(), key)) for key in
            ('st_dev', 'st_ino', 'st_size', 'st_blocks')] for name in self.cas.inodes}

    # Reach the stage producer using new reserved birth/close, not closed test scenarios.
    def setup_account(self):
        self.client, birth = self.nightly._initialize(self.context, raw_checkpoint=self.raw, native_io=self.nightly_io)
        previous = self.nightly._close(self.context, self.client, '2019-02-28', birth=birth,
            previous=birth, raw_checkpoint=self.raw, native_io=self.nightly_io)
        prior = self.nightly.read_lifecycle(previous, raw_checkpoint=self.raw)['value']
        raw = demand.encoded({'scope': 'SYNTHETIC_RESERVED_CYCLE_CONTEXT',
                              'window': {'completed_at': '2019-03-01T14:45:00Z'}})
        self.stage = self.ns['_Stages'](self.nightly, self.client, self.raw, self.io,
            session='2019-03-01', context={'raw': raw.decode(), 'sha256': hashlib.sha256(raw).hexdigest()},
            lineage={'schema': 'raw-nightly-cycle-lineage/1', 'birth': birth, 'previous_nightly': previous,
                     'context': prior['context'], 'context_identity': prior['context_identity']})
        self.registry = entities.mapping()
        self.packet = {'origin': 'SYNTHETIC_RESERVED_CYCLE_INPUTS', 'declaration': 'NO_PROVIDER_ACQUISITION'}
        self.order = {'symbol': 'AAPL', 'side': 'buy', 'qty': 5, 'client_order_id': 'SYNTHETIC-reserved-cycle'}
        self.decision = {'candidate': self.order}
        self.submission = {'order': self.order, 'observe': {'at': '2019-03-01T14:45:31.200000+00:00',
            'marks': {'AAPL': 100}, 'market_open': True},
            'latch': {'session': '2019-03-01', 'scope': 'SYNTHETIC_RESERVED_LATCH'}}

    # Run the producer's real preparation and decision stages exactly once.
    def prepare_decision(self):
        self.setup_account()
        self.prepared = self.stage._prepare(self.registry, self.packet)
        self.decided = self.stage._run('DECISION_FROZEN', self.decision)

    # Reopen with the original pool and authoritative observed head, preserving producer identity.
    def reopen(self, head):
        root, identity = self.store.root, self.store.identity
        self.store.close()
        self.cas = cas.ReservedCAS(root / 'reserved-blobs', identity=identity)
        self.store = Store(root, identity, head, blob_reservation=self.cas)
        self.nightly.store = self.case.store = self.store
        self.nightly.expected_head = head

    # Prove actual causal Store stages, native accepted order/pending save and original metadata recovery.
    def test_real_preparation_decision_submission_and_reopen(self):
        self.prepare_decision()
        result = self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual(self.store.snapshot()['next_stage'], 'OUTCOME_COMMITTED')
        self.assertEqual([row[0] for row in self.store.connection.execute('SELECT stage FROM entries ORDER BY sequence')],
            ['PRIOR_VERIFIED', 'DEMAND_FROZEN', 'WAIT_PACKETS', 'PACKETS_FINALIZED',
             'DECISION_FROZEN', 'SUBMISSION_CAPTURED'])
        state = paper.load_state(self.nightly.root)
        self.assertEqual((state.pending[0]['qty'], state.pending[0]['sent']['qty']), (8, 5))
        self.assertEqual(list(self.client._orders.values())[0]['qty'], '5')
        self.assertEqual(list(self.client._orders.values())[0]['status'], 'accepted')
        self.assertEqual(state.journal, [])
        self.assertGreater(len(paper.state_path(self.nightly.root).read_bytes()), 262144)
        self.assertIn(b'NaN', paper.state_path(self.nightly.root).read_bytes())
        self.assertEqual(self.cas._control()['groups'][-1]['status'], 'COMPLETE')
        self.reopen(result['head'])
        before = (paper.state_path(self.nightly.root).read_bytes(), codec.encode(self.client, **self.nightly.pins()),
            (self.writer.root / 'control').read_bytes(), (self.raw.root / 'control').read_bytes(), self.store.snapshot(),
            (self.cas.root / 'control').read_bytes(), len(CALLS))
        self.assertEqual(self.stage._run('SUBMISSION_CAPTURED', self.submission), result)
        self.assertEqual(self.stage._prepare(self.registry, self.packet), self.prepared)
        self.assertEqual(before, (paper.state_path(self.nightly.root).read_bytes(), codec.encode(self.client, **self.nightly.pins()),
            (self.writer.root / 'control').read_bytes(), (self.raw.root / 'control').read_bytes(), self.store.snapshot(),
            (self.cas.root / 'control').read_bytes(), len(CALLS)))
        self.assertEqual(self.inventory(), self.before)

    # Changed inputs and tampered evidence cannot create a second eligible stage attempt.
    def test_changed_input_and_prepared_tamper_refuse_without_effects(self):
        self.prepare_decision()
        before = (len(CALLS), len(self.client.attempt_history), paper.state_path(self.nightly.root).read_bytes())
        changed = deepcopy(self.decision)
        changed['candidate']['qty'] = 4
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.stage._run('DECISION_FROZEN', changed)
        path = self.stage._directory('DECISION_FROZEN') / 'prepared.json'
        value = packet._decode(path.read_bytes())
        value['native_io']['effect_binding'] = '0' * 64
        path.write_bytes(demand.encoded(value))
        with self.assertRaises(ValueError):
            self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual(before, (len(CALLS), len(self.client.attempt_history), paper.state_path(self.nightly.root).read_bytes()))

    # A caught invalid capability permanently pauses before another broker or paper effect.
    def test_caught_capability_failure_poisoned_before_native_submit(self):
        self.io = reserved_io.SyntheticNativeIO(self.writer, catching_program,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.prepare_decision()
        before = (codec.encode(self.client, **self.nightly.pins()), paper.state_path(self.nightly.root).read_bytes())
        with self.assertRaises(ValueError):
            self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual(self.cas._control()['groups'][-1]['status'], 'PAUSED')
        self.assertEqual(before, (codec.encode(self.client, **self.nightly.pins()), paper.state_path(self.nightly.root).read_bytes()))
        calls = len(CALLS)
        with self.assertRaisesRegex(StorePause, 'never replay'):
            self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual(len(CALLS), calls)

    # Public entry and exhausted capacity refuse before a new callback or native effect.
    def test_public_and_capacity_refuse_before_cycle_work(self):
        with self.assertRaisesRegex(StorePause, 'before effects'):
            self.ns['execute']()
        self.prepare_decision()
        for index in range(4, 8):
            lease = self.cas.arm(operation=entities.sha('SYNTHETIC_CAPACITY' + str(index)),
                                 head=self.store.snapshot()['head'])
            self.cas.complete(lease, self.decided['receipt'])
        before = (len(CALLS), codec.encode(self.client, **self.nightly.pins()),
                  paper.state_path(self.nightly.root).read_bytes())
        with self.assertRaisesRegex(ValueError, 'capacity exhausted'):
            self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual(before, (len(CALLS), codec.encode(self.client, **self.nightly.pins()),
            paper.state_path(self.nightly.root).read_bytes()))

    # A callback failure after a successful effect blocks later save/evidence and replay.
    def test_program_failure_after_observation_blocks_save_and_evidence(self):
        self.io = reserved_io.SyntheticNativeIO(self.writer, failing_program,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.prepare_decision()
        before = paper.state_path(self.nightly.root).read_bytes()
        with self.assertRaisesRegex(ValueError, 'after native observation'):
            self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual(self.cas._control()['groups'][-1]['status'], 'PAUSED')
        self.assertEqual(self.client.open_orders(), [])
        with self.assertRaises(ValueError):
            self.io.save(self.nightly.root, paper.load_state(self.nightly.root))
        with self.assertRaises(ValueError):
            self.io.evidence()
        calls = len(CALLS)
        with self.assertRaisesRegex(StorePause, 'never replay'):
            self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual((len(CALLS), paper.state_path(self.nightly.root).read_bytes()), (calls, before))

    # A future intent cannot reach a decision callback or broker submission early.
    def test_future_pending_intent_refuses_before_callback(self):
        self.context.mode = 'future'
        self.setup_account()
        self.stage._prepare(self.registry, self.packet)
        before = (len(CALLS), codec.encode(self.client, **self.nightly.pins()),
                  paper.state_path(self.nightly.root).read_bytes())
        with self.assertRaisesRegex(ValueError, 'unsent due intent'):
            self.stage._run('DECISION_FROZEN', self.decision)
        self.assertEqual(before, (len(CALLS), codec.encode(self.client, **self.nightly.pins()),
            paper.state_path(self.nightly.root).read_bytes()))

    # A decision changing its latch cannot commit a receipt containing that changed value.
    def test_decision_latch_change_refuses_before_commit(self):
        self.io = reserved_io.SyntheticNativeIO(self.writer, changing_program,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.setup_account()
        prepared = self.stage._prepare(self.registry, self.packet)
        with self.assertRaisesRegex(ValueError, 'Decision changed'):
            self.stage._run('DECISION_FROZEN', self.decision)
        self.assertEqual(self.store.snapshot()['head'], prepared['head'])
        self.assertEqual(self.cas._control()['groups'][-1]['status'], 'PAUSED')
        self.assertEqual(self.client.open_orders(), [])

    # Kill a separately reopened owned child exactly at the requested durable protocol cut.
    def child(self, boundary):
        signal.pthread_sigmask(signal.SIG_SETMASK, set())
        self.reopen(self.decided['head'])

        # Record actual native effect/head evidence before the deliberate process kill.
        def cut(point):
            if point == boundary:
                marker = {'pid': os.getpid(), 'point': point, 'head': self.store.snapshot()['head'],
                    'paper_sha256': hashlib.sha256(paper.state_path(self.nightly.root).read_bytes()).hexdigest(),
                    'order_count': len(self.client._orders), 'calls': len(CALLS)}
                self.legacy.write_once(self.nightly.root / 'actual-child-cut.json', demand.encoded(marker))
                os.kill(os.getpid(), signal.SIGKILL)
        self.store.fault = cut
        self.stage._run('SUBMISSION_CAPTURED', self.submission)
        raise AssertionError('Requested child cut not reached')

    # Bound/reap the owned child and retain original cut/exit witnesses without replay.
    def killed(self, boundary):
        self.store.close()
        process = multiprocessing.get_context('fork').Process(target=self.child, args=(boundary,))
        try:
            watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM}
            old = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                process.start()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old)
            process.join(timeout=15)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, -9)
            marker = json.loads((self.nightly.root / 'actual-child-cut.json').read_bytes())
            self.assertEqual((marker['pid'], marker['point'], marker['order_count']), (process.pid, boundary, 1))
            self.reopen(marker['head'])
            self.assertEqual(hashlib.sha256(paper.state_path(self.nightly.root).read_bytes()).hexdigest(), marker['paper_sha256'])
            self.legacy.write_once(self.nightly.root / 'actual-child-exit.json', demand.encoded({
                'pid': process.pid, 'exitcode': process.exitcode, 'boundary': boundary,
                'head': marker['head'], 'scope': 'ACTUAL_OWNED_SIGKILL_NOT_POWER_LOSS'}))
            ACTUAL_KILL_FILES.append((str(self.nightly.root / 'actual-child-cut.json'),
                                      str(self.nightly.root / 'actual-child-exit.json')))
        finally:
            if process.pid is not None and process.is_alive():
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1)
            if process.pid is not None:
                self.assertFalse(process.is_alive())
                process.close()

    # OPEN after native submit/save never retries its callback or adopts its retained paper bytes.
    def test_actual_sigkill_after_effect_before_prepared_stays_open(self):
        self.prepare_decision()
        self.killed('reserved_cycle_effect_returned_SUBMISSION_CAPTURED')
        calls, raw = len(CALLS), paper.state_path(self.nightly.root).read_bytes()
        with self.assertRaisesRegex(StorePause, 'never replay'):
            self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual((len(CALLS), paper.state_path(self.nightly.root).read_bytes()), (calls, raw))
        self.assertEqual(self.store.snapshot()['head'], self.decided['head'])
        self.assertEqual(paper.load_state(self.nightly.root).pending[0]['sent']['qty'], 5)

    # Committed recovery writes only the original missing marker/seal, never another order or save.
    def test_actual_sigkill_after_commit_original_recovery_only(self):
        self.prepare_decision()
        self.killed('reserved_cycle_committed_SUBMISSION_CAPTURED')
        before = (len(CALLS), paper.state_path(self.nightly.root).read_bytes(),
                  (self.writer.root / 'control').read_bytes(), (self.raw.root / 'control').read_bytes(), self.store.snapshot())
        result = self.stage._run('SUBMISSION_CAPTURED', self.submission)
        self.assertEqual(self.stage._run('SUBMISSION_CAPTURED', self.submission), result)
        self.assertEqual(before, (len(CALLS), paper.state_path(self.nightly.root).read_bytes(),
            (self.writer.root / 'control').read_bytes(), (self.raw.root / 'control').read_bytes(), self.store.snapshot()))
        self.assertEqual(self.cas._control()['groups'][-1]['status'], 'COMPLETE')
