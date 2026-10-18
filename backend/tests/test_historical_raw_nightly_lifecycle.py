"""Exact raw lifecycle bodies with synthetic context/policy/trade orchestration.

Real ReplayBroker, codec, paper snapshot/save, metadata, checkpoint and SQLite/CAS
execute. Native market_daily planning/model orchestration is expressly replaced by
a synthetic callable. No closed test body or genuine account/model is executed.
"""
import ast
import builtins
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import time
import types
from types import SimpleNamespace
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_native_metadata as metadata
from backend.market import historical_paper_component as component
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_reserved_native_io as reserved_io
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.historical_packet_registry import digest
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import test_historical_raw_nightly_metadata as fixture


# Count actual synthetic policy invocations without calling any fitted model.
class SyntheticPolicy:
    # Bind one synthetic context so repeated execution remains observable.
    def __init__(self, context):
        self.context = context

    # Return large NaN-bearing decision data with observable invocation count.
    def decide(self):
        self.context.policy_calls += 1
        return {'AAPL': float('nan')}, {'text': 'q' * 270000, 'scope': 'SYNTHETIC_POLICY'}


# Supply only declared synthetic context/report/clock inputs to the whole close body.
class SyntheticContext:
    # Keep source-free synthetic data isolated from genuine model/archive interfaces.
    def __init__(self):
        self.provenance = b'SYNTHETIC_RAW_LIFECYCLE_CONTEXT'
        self.policy_calls, self.mode, self.invalid = 0, 'success', False
        self.panel = SimpleNamespace(dates=[date(2019, 2, 28), date(2019, 3, 1)])
        self.raw = SimpleNamespace(daily_close=[{'AAPL': 100}, {'AAPL': 101}])

    # Refuse explicit invalidation at the real post-native context validation boundary.
    def validate(self):
        if self.invalid:
            raise ValueError('SYNTHETIC changed context after native write')
        return {'symbols': ['AAPL'], 'scope': 'SYNTHETIC_CONTEXT_NO_MODEL'}

    # Return synthetic report/policy data while preserving the lifecycle's call order.
    def select(self, session):
        index = self.panel.dates.index(date.fromisoformat(session))
        return self, SyntheticPolicy(self), index


# Use a hypothetical fixture session clock while leaving datetime.now untouched.
def instant(day, clock):
    return datetime.combine(day, clock, tzinfo=native.calendar.NEW_YORK).astimezone(UTC)


# Declare the one sequential synthetic date pair without claiming full calendar coverage.
def next_session(day):
    return {date(2019, 2, 28): date(2019, 3, 1)}.get(day)


# Declare no economic events in this fixture; genuine action handling stays refused.
def due_actions(*args):
    return []


# Preserve only declared synthetic marks for the real broker observation call.
def account_marks(raw, index, at, marks):
    return marks


# Perform real native snapshot/save under an explicitly synthetic trade orchestrator.
def synthetic_trade(report, root, session, force, *, client_factory, decision_at, holding_policy):
    if report.mode == 'unavailable':
        raise AlpacaTradingError('SYNTHETIC broker unavailable before policy')
    holding_policy.decide()
    client = client_factory()
    if report.mode == 'submission':
        client.submit_market_on_close('AAPL', 1, 'buy', 'SYNTHETIC_FORBIDDEN')
    state = paper.load_state(root)
    state.start_equity = float('nan')
    entry = paper.snapshot(state, session, 100000, 100000,
        [{'z': session + str(index) + 'x' * 25000, 'a': float('nan')} for index in range(12)])
    paper.save_state(root, state)
    if report.mode == 'changed-context':
        report.invalid = True
    return {**entry, 'cash': 1} if report.mode == 'wrong-entry' else entry


# Instantiate complete-source raw class and exact helper CodeTypes with explicit globals.
def raw_namespace(legacy):
    path = Path('/audit/backend/market/historical_raw_nightly.py')
    compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
    codes = {item.co_name: item for item in compiled.co_consts if isinstance(item, types.CodeType)}
    tree = ast.parse(path.read_bytes())
    constants = {node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)}
    result = {'__name__': 'SYNTHETIC_RAW_LIFECYCLE', '__file__': str(path),
        '__builtins__': builtins.__dict__, 'legacy': legacy, 'paper': paper, 'native': native,
        'codec': codec, 'metadata': metadata, 'component': component, 'physical': physical,
        'packet': packet, 'digest': digest, 'StorePause': StorePause, 'reserved_io': reserved_io,
        'Path': Path, 'sha256': hashlib.sha256, 'datetime': datetime, 'UTC': UTC,
        'date': date, 'timedelta': timedelta, 'time': time, 'io': io, 'json': json,
        'deepcopy': deepcopy, **constants}
    for name in ('sources', 'execution_admission', 'content', 'write_reference'):
        result[name] = types.FunctionType(codes[name], result)
    result['RawNightly'] = builtins.__build_class__(
        types.FunctionType(codes['RawNightly'], result), 'RawNightly', legacy.Nightly)
    return result


# Verify full private lifecycle bodies while keeping genuine execution structurally closed.
class RawNightlyLifecycleTests(unittest.TestCase):
    # Reuse fixture setup only and allocate a distinct finite multi-close checkpoint.
    def setUp(self):
        self.fixture = fixture.RawNightlyMetadataTests()
        self.fixture.setUp()
        self.store = self.fixture.store
        self.raw = physical.reserve(self.fixture.fixture.root / 'lifecycle-checkpoint',
            identity=self.fixture.fixture.profile, identity_sha256=self.fixture.fixture.pin,
            writer=self.fixture.fixture.writer, limits={'span_bytes': 512 * 1024,
                'raw_bytes': 1024 * 1024, 'history_rows': 32, 'body_slots': 32,
                'page_slots': 32, 'directory_headroom_bytes': 65536})
        ns = self.fixture.ns
        ns.update({'codec': codec, 'native': native, 'SUBMIT': native.ReplayBroker._submit,
            'FrozenCurrentGradePolicy': SyntheticPolicy, 'HoldingContext': SyntheticContext,
            'AlpacaTradingError': AlpacaTradingError,
            'calendar': native.calendar, 'intraday_orders': SimpleNamespace(next_session=next_session),
            'live_policy_replay': SimpleNamespace(instant=instant, due_actions=due_actions, account_marks=account_marks),
            'market_daily': SimpleNamespace(paper_trade=synthetic_trade)})
        path = Path(ns['__file__'])
        compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
        code = next(item for item in compiled.co_consts if isinstance(item, types.CodeType) and item.co_name == 'context_identity')
        ns['context_identity'] = types.FunctionType(code, ns)
        self.legacy = SimpleNamespace(**ns)
        self.ns = raw_namespace(self.legacy)
        self.nightly = object.__new__(self.ns['RawNightly'])
        self.nightly.store, self.nightly.root = self.store, self.fixture.account
        self.nightly.expected_head = None
        self.nightly.pin_bytes = self.legacy.admitted.encoded(self.fixture.fixture.pins)
        self.context = SyntheticContext()

    # Retain all evidence files and ensure actual native hooks were restored.
    def tearDown(self):
        self.assertIs(paper.save_state, self.legacy.SAVE_STATE)
        self.assertIs(native.ReplayBroker._submit, self.legacy.SUBMIT)
        self.store.close()

    # Create one actual100k zero-share synthetic account through the private birth body.
    def birth(self):
        return self.nightly._initialize(self.context, raw_checkpoint=self.raw)

    # Drive the full private close body against the actual broker and synthetic orchestrator.
    def close(self, client, session, birth, previous):
        return self.nightly._close(self.context, client, session, birth=birth,
                                   previous=previous, raw_checkpoint=self.raw)

    # Read actual finite lifecycle receipts and their physically reserved lineage.
    def read(self, reference):
        return self.nightly.read_lifecycle(reference, raw_checkpoint=self.raw)['value']

    # Walk birth and two sequential closes, reopen and recover without more policy calls.
    def test_birth_two_closes_reopen_exact_lineage_and_native_restore(self):
        client, birth = self.birth()
        self.assertEqual(self.read(birth)['detail']['initial_cash'], 100000)
        first = self.close(client, '2019-02-28', birth, birth)
        second = self.close(client, '2019-03-01', birth, first)
        value = self.read(second)
        self.assertEqual(value['previous'], first)
        self.assertEqual(value['birth'], birth)
        self.assertEqual(value['context'], hashlib.sha256(self.context.provenance).hexdigest())
        self.assertEqual(self.context.policy_calls, 2)
        self.assertEqual(len(value['native_writes']), 1)
        self.assertEqual(value['native_writes'][-1]['raw_sha256'], value['components']['paper']['raw_sha256'])
        original = paper.state_path(self.nightly.root).read_bytes()
        self.assertGreater(len(original), 524288)
        self.assertIn(b'NaN', original)
        self.assertEqual(len(paper.load_state(self.nightly.root).history), 2)
        self.assertEqual(list(client.attempt_history), [])
        self.store.close()
        self.store = Store(self.fixture.fixture.root / 'store', self.fixture.fixture.pin, None)
        self.nightly.store = self.store
        self.raw = physical.PhysicalCheckpoint(self.raw.root,
            identity_sha256=self.fixture.fixture.pin, writer=self.fixture.fixture.writer)
        self.assertEqual(self.close(client, '2019-03-01', birth, first), second)
        self.assertEqual(self.context.policy_calls, 2)
        self.assertEqual(self.nightly._initialize(self.context, raw_checkpoint=self.raw), (None, birth))
        fresh = self.fixture.fixture.root / 'fresh-native'
        fresh.mkdir(mode=0o700)
        paper.state_path(fresh).parent.mkdir(mode=0o700)
        component.restore(value['components']['paper'], self.raw, paper.state_path(fresh),
                          expected_identity=self.fixture.fixture.pin)
        self.assertEqual(paper.state_path(fresh).read_bytes(), original)
        paper.save_state(fresh, paper.load_state(fresh))
        self.assertEqual(paper.state_path(fresh).read_bytes(), original)

    # Public raw execution refuses before reservation or account file creation.
    def test_public_admission_refuses_before_any_effect(self):
        with self.assertRaisesRegex(StorePause, 'before effects'):
            self.nightly.initialize(self.context, raw_checkpoint=self.raw)
        with self.assertRaisesRegex(StorePause, 'before effects'):
            self.nightly.close(self.context, None, '2019-02-28', birth='0' * 64,
                               previous='0' * 64, raw_checkpoint=self.raw)
        self.assertEqual(list((self.nightly.root / 'operations').iterdir()), [])
        self.assertFalse(paper.state_path(self.nightly.root).exists())
        self.assertEqual(self.context.policy_calls, 0)

    # An unavailable later close preserves NaN-bearing native paper and cannot advance.
    def test_unavailable_close_preserves_nan_and_recovery_does_not_repeat(self):
        client, birth = self.birth()
        first = self.close(client, '2019-02-28', birth, birth)
        before = paper.state_path(self.nightly.root).read_bytes()
        self.context.mode = 'unavailable'
        result = self.close(client, '2019-03-01', birth, first)
        value = self.read(result)
        self.assertEqual(value['detail']['status'], 'NIGHTLY_BROKER_UNAVAILABLE')
        self.assertEqual(value['decisions'], [])
        self.assertEqual(value['native_writes'], [])
        self.assertEqual(paper.state_path(self.nightly.root).read_bytes(), before)
        self.assertEqual(self.close(client, '2019-03-01', birth, first), result)
        self.assertEqual(self.context.policy_calls, 1)

    # Attempted submissions stop at the observer and leave an interrupted operation paused.
    def test_submission_refused_before_native_broker_and_never_replayed(self):
        client, birth = self.birth()
        self.context.mode = 'submission'
        with self.assertRaisesRegex(ValueError, 'PAUSED before submit'):
            self.close(client, '2019-02-28', birth, birth)
        self.assertEqual(list(client.attempt_history), [])
        self.assertEqual(client._orders, {})
        with self.assertRaisesRegex(StorePause, 'never re-execute'):
            self.close(client, '2019-02-28', birth, birth)
        self.assertEqual(self.context.policy_calls, 1)

    # Refuse stale paper, context, dates and non-lifecycle predecessors before a new policy call.
    def test_predecessor_context_session_and_source_guards(self):
        client, birth = self.birth()
        first = self.close(client, '2019-02-28', birth, birth)
        with self.assertRaisesRegex(ValueError, 'Sequential'):
            self.close(client, '2019-03-04', birth, first)
        self.context.provenance += b'CHANGED'
        with self.assertRaisesRegex(ValueError, 'lineage'):
            self.close(client, '2019-03-01', birth, first)
        self.context.provenance = b'SYNTHETIC_RAW_LIFECYCLE_CONTEXT'
        other = self.legacy.put(self.store, b'{"schema":"private-conditional-cycle-receipt/2"}')
        with self.assertRaisesRegex(ValueError, 'reserved raw lifecycle'):
            self.nightly.raw_predecessor(other, raw_checkpoint=self.raw)
        changed = self.legacy.admitted.decoded(self.store.read_blob(first, limit=262144))
        changed['sources'] = {}
        altered = self.legacy.put(self.store, self.legacy.admitted.encoded(changed))
        with self.assertRaisesRegex(ValueError, 'reserved raw lifecycle'):
            self.nightly.read_lifecycle(altered, raw_checkpoint=self.raw)
        self.assertEqual(self.context.policy_calls, 1)

    # A mismatched return after native save leaves original bytes and an OPEN reservation.
    def test_wrong_returned_entry_preserves_failure_without_result(self):
        client, birth = self.birth()
        self.context.mode = 'wrong-entry'
        with self.assertRaisesRegex(ValueError, 'differs from native saved history'):
            self.close(client, '2019-02-28', birth, birth)
        directory = self.nightly.operation('NIGHTLY_CLOSE', '2019-02-28')
        self.assertTrue((directory / 'reservation.json').exists())
        self.assertFalse((directory / 'result.json').exists())
        self.assertIn(b'NaN', paper.state_path(self.nightly.root).read_bytes())
        with self.assertRaisesRegex(StorePause, 'never re-execute'):
            self.close(client, '2019-02-28', birth, birth)
        self.assertEqual(self.context.policy_calls, 1)

    # Post-save context invalidation retains native bytes and pauses without another call.
    def test_post_native_context_change_keeps_open_reservation(self):
        client, birth = self.birth()
        self.context.mode = 'changed-context'
        with self.assertRaisesRegex(ValueError, 'changed context after native write'):
            self.close(client, '2019-02-28', birth, birth)
        directory = self.nightly.operation('NIGHTLY_CLOSE', '2019-02-28')
        operation = self.legacy.admitted.decoded((directory / 'reservation.json').read_bytes())
        self.assertEqual(operation['previous'], birth)
        self.assertFalse((directory / 'result.json').exists())
        self.assertIn(b'NaN', paper.state_path(self.nightly.root).read_bytes())
        with self.assertRaisesRegex(StorePause, 'never re-execute'):
            self.close(client, '2019-02-28', birth, birth)
        self.assertEqual(self.context.policy_calls, 1)
