"""New committed raw Cycle bridge assertions over explicitly synthetic production.

Actual native broker fills, paper saves, reconciliation, checkpoint and Store
operations run. Cycle orchestration/context and Nightly policy remain synthetic;
no full constructor, model, provider, genuine admission or old test body runs.
"""
import ast
from copy import deepcopy
from datetime import date
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_checkpoint as checkpoint
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_timing_packet as packet
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import test_historical_raw_nightly_lifecycle as lifecycle
from backend.tests import test_historical_raw_nightly_metadata as metadata_fixture
from backend.tests import test_historical_raw_settlement_integration as settlement_fixture


# Keep the intraday context distinct from the frozen synthetic holding provenance.
class SyntheticCycleContext:
    # Preserve exact supplied raw bytes and content address for the source-isolated API.
    def __init__(self, raw, sha256):
        self.raw, self.sha256 = raw, sha256


# Authenticate synthetic context bytes without claiming native96-cohort context coverage.
def read_context(value):
    if hashlib.sha256(value.raw).hexdigest() != value.sha256:
        raise ValueError('SYNTHETIC Cycle context hash differs')
    return packet._decode(value.raw)


# Produce an unsent native intent before the Cycle decision, using real snapshot/save.
def initial_trade(report, root, session, force, *, client_factory, decision_at, holding_policy):
    entry = lifecycle.synthetic_trade(report, root, session, force,
        client_factory=client_factory, decision_at=decision_at, holding_policy=holding_policy)
    state = paper.load_state(root)
    state.pending = [{'client_order_id': 'SYNTHETIC-cycle-bridge', 'symbol': 'AAPL',
        'side': 'buy', 'qty': 8, 'session': session, 'execute_on': '2019-03-01',
        'execution_timing': 'dip_or_close'}]
    paper.save_state(root, state)
    return entry


# Exercise only this new bridge using actual stage commits and native partial fills.
class RawCycleNightlyTests(unittest.TestCase):
    # Reuse setup helpers and exact source CodeTypes without running closed test methods.
    def setUp(self):
        self.fixture = lifecycle.RawNightlyLifecycleTests()
        self.fixture.setUp()
        self.store, self.raw = self.fixture.store, self.fixture.raw
        self.nightly, self.context = self.fixture.nightly, self.fixture.context
        self.pins = self.nightly.pins()
        self.cycle = self.fixture.fixture.fixture.cycle
        self.adapter = settlement_fixture.settlement_namespace()
        self.cycle.update({'codec': codec, 'checkpoint': checkpoint, 'entities': registry})
        source = Path(self.cycle['__file__'])
        tree = ast.parse(source.read_bytes())
        self.cycle['SETTLEMENT_SHA256'] = next(ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                and target.id == 'SETTLEMENT_SHA256' for target in node.targets))
        self.cycle['_settlement_source'] = self.source
        self.cycle['market'].Context = SyntheticCycleContext
        self.cycle['market'].read_context = read_context
        settlement_fixture.functions(source, ('_raw_reconciliation', '_head_entry'), self.cycle)
        bridge_path = Path('/audit/backend/market/historical_raw_cycle.py')
        self.bridge = settlement_fixture.functions(bridge_path,
            ('sources', 'paper_content', 'committed_operation', 'verify_latch', 'read_final'),
            {'date': date, 'sha256': hashlib.sha256, 'Path': Path,
             'cycle': SimpleNamespace(**self.cycle), 'component': lifecycle.component,
             'packet': packet, 'digest': registry.digest, 'Store': Store, 'StorePause': StorePause,
             'LINEAGE': 'raw-nightly-cycle-lineage/1',
             'LINEAGE_KEYS': {'schema', 'birth', 'previous_nightly', 'context', 'context_identity'},
             'FINAL_KEYS': {'stage', 'settlement_submission_head', 'settlement_cycle',
                            'raw_nightly_lineage', 'resolved'}})
        self.fixture.ns['raw_cycle'] = self.bridge
        self.fixture.legacy.market_daily.paper_trade = initial_trade

    # Retain every synthetic account while releasing its actual SQLite writer lock.
    def tearDown(self):
        self.fixture.tearDown()

    # Require the actual reviewed settlement bytes before any native reconciliation.
    def source(self):
        self.assertEqual(hashlib.sha256(Path(self.adapter.__file__).read_bytes()).hexdigest(),
                         self.cycle['SETTLEMENT_SHA256'])
        return self.adapter

    # Capture actual native components under the distinct raw Cycle receipt contract.
    def receipt(self, detail, reconciliation=None):
        return self.cycle['_receipt'](self.store, self.client, self.nightly.root, self.pins,
            detail, session=date(2019, 3, 1), context=self.cycle_context,
            raw_checkpoint=self.raw, raw_reconciliation=reconciliation)

    # Reserve and commit the real next Store stage without invoking any native sender.
    def commit_operation(self, stage, receipt):
        operation = packet._digest({'cycle': self.cycle_sha, 'stage': stage})
        self.store.reserve_operation(operation=operation, expected_head=self.store.snapshot()['head'],
            cycle=self.cycle_sha, stage=stage,
            inputs=packet._digest({'scope': 'SYNTHETIC_CYCLE_BRIDGE', 'stage': stage}))
        return self.store.complete_operation(operation, receipt)

    # Build one new real native partial fill and reconciled save, then optionally commit it.
    def scenario(self, *, commit=True, alteration=None):
        self.client, self.birth = self.fixture.birth()
        self.previous = self.fixture.close(self.client, '2019-02-28', self.birth, self.birth)
        prior = self.fixture.read(self.previous)
        self.lineage = {'schema': 'raw-nightly-cycle-lineage/1', 'birth': self.birth,
            'previous_nightly': self.previous, 'context': prior['context'],
            'context_identity': prior['context_identity']}
        raw = demand.encoded({'scope': 'SYNTHETIC_DISTINCT_INTRADAY_CONTEXT',
                              'window': {'completed_at': '2019-03-01T14:45:00Z'}})
        self.cycle_context = {'raw': raw.decode(), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.cycle_sha = hashlib.sha256(b'SYNTHETIC_RAW_CYCLE_BRIDGE').hexdigest()
        metadata_fixture.stage_namespace().ready(self.store, self.cycle_sha)
        self.commit_operation('DECISION_FROZEN', self.receipt(
            {'stage': 'DECISION_FROZEN', 'raw_nightly_lineage': self.lineage}))
        self.client.observe('2019-03-01T14:45:31.200000+00:00', {'AAPL': 100}, True)
        order = self.client.submit_market('AAPL', 5, 'buy', 'SYNTHETIC-cycle-bridge')
        state = paper.load_state(self.nightly.root)
        state.pending[0].update({'sent': {'qty': 5, 'at': order['submitted_at']},
            'execution': {'created_at': order['created_at'], 'submitted_at': order['submitted_at']}})
        paper.save_state(self.nightly.root, state)
        latch = self.cycle['entry_timing'].latch_path(self.nightly.root, date(2019, 3, 1))
        latch.parent.mkdir(mode=0o700)
        latch.write_bytes(demand.encoded({'session': '2019-03-01', 'scope': 'SYNTHETIC_LATCH'}))
        submission = self.commit_operation('SUBMISSION_CAPTURED', self.receipt(
            {'stage': 'SUBMISSION_CAPTURED', 'raw_nightly_lineage': self.lineage}))
        self.client.flush('2019-03-01T14:45:33+00:00', {'AAPL': 100})
        resolved = {'stage': 'OUTCOME_COMMITTED', 'scope': 'SYNTHETIC_RESOLVER_NOT_EXECUTED'}
        pre = self.receipt({'stage': 'PRE_SETTLEMENT_OUTCOME',
            'submission_head': submission['sha256'], 'cycle': self.cycle_sha,
            'raw_nightly_lineage': self.lineage, 'resolved': resolved})
        retained = self.cycle['_read_receipt'](self.store, pre, self.pins, raw_checkpoint=self.raw)
        self.before_broker = codec.encode(self.client, **self.pins)
        updated, evidence = self.adapter.reconcile_raw(self.client, paper.load_state(self.nightly.root),
            pins=self.pins, outcome_sha256=pre, observed_at=self.client._now.isoformat(),
            prior_component=retained['components']['paper'], raw_checkpoint=self.raw)
        self.saved = paper.save_state(self.nightly.root, updated).read_bytes()
        self.final = self.receipt({'stage': 'OUTCOME_COMMITTED',
            'settlement_submission_head': submission['sha256'], 'settlement_cycle': self.cycle_sha,
            'raw_nightly_lineage': self.lineage, 'resolved': resolved},
            {'pre_settlement_receipt': pre, 'evidence': evidence})
        if alteration is not None:
            value = packet._decode(self.store.read_blob(self.final, limit=262144))
            alteration(value)
            self.final = self.cycle['_put'](self.store, demand.encoded(value))
        if commit:
            self.entry = self.store.append(expected_head=submission['sha256'],
                cycle_sha256=self.cycle_sha, stage='OUTCOME_COMMITTED', receipt_sha256=self.final)
        self.nightly.expected_head = self.store.snapshot()['head']
        self.fixture.legacy.market_daily.paper_trade = lifecycle.synthetic_trade
        return updated

    # Prove native partial fill, committed final readback and same-session close/recovery.
    def test_committed_partial_fill_same_session_close_reopen_recovery(self):
        updated = self.scenario()
        self.assertEqual(updated.pending, [])
        self.assertEqual((updated.journal[0]['qty'], updated.journal[0]['filled_qty'],
                          updated.journal[0]['status']), (8, 5, 'partial'))
        self.assertGreater(len(self.saved), 262144)
        self.assertIn(b'NaN', self.saved)
        final = self.bridge.read_final(self.store, self.final, self.pins,
            expected_head=self.entry['sha256'], raw_checkpoint=self.raw)
        self.assertEqual(final['entry'], self.entry)
        self.assertEqual(final['lineage'], self.lineage)
        self.assertEqual(codec.encode(self.client, **self.pins), self.before_broker)
        self.store.close()
        self.store = Store(self.fixture.fixture.fixture.root / 'store',
                           self.pins['identity_sha256'], self.entry['sha256'])
        self.fixture.store = self.nightly.store = self.store
        self.raw = physical.PhysicalCheckpoint(self.raw.root,
            identity_sha256=self.pins['identity_sha256'], writer=self.fixture.fixture.fixture.writer)
        self.fixture.raw = self.raw
        result = self.fixture.close(self.client, '2019-03-01', self.birth, self.final)
        self.assertEqual(self.fixture.read(result)['previous'], self.final)
        self.assertEqual(self.store.snapshot()['head'], self.entry['sha256'])
        self.assertEqual(self.fixture.close(self.client, '2019-03-01', self.birth, self.final), result)
        self.assertEqual(self.context.policy_calls, 2)
        self.assertEqual(paper.load_state(self.nightly.root).journal, updated.journal)

    # Refuse a merely retained raw final before the OUTCOME stage has been committed.
    def test_uncommitted_final_and_stale_expected_head_refuse(self):
        self.scenario(commit=False)
        with self.assertRaisesRegex(StorePause, 'committed raw Cycle head'):
            self.nightly.raw_predecessor(self.final, raw_checkpoint=self.raw)
        self.nightly.expected_head = '0' * 64
        with self.assertRaisesRegex(StorePause, 'committed raw Cycle head'):
            self.nightly.raw_predecessor(self.final, raw_checkpoint=self.raw)
        self.assertEqual(self.context.policy_calls, 1)

    # Reject holding-context substitutions even when their receipt reaches the Store head.
    def test_committed_wrong_holding_lineage_refuses(self):
        self.scenario(alteration=lambda value: value['detail']['raw_nightly_lineage'].update(context='0' * 64))
        with self.assertRaisesRegex(ValueError, 'context/lineage differs'):
            self.nightly.raw_predecessor(self.final, raw_checkpoint=self.raw)
        self.assertEqual(self.context.policy_calls, 1)

    # Refuse a committed final whose resolved detail does not match its pre-fold receipt.
    def test_committed_wrong_resolved_graph_refuses(self):
        self.scenario(alteration=lambda value: value['detail']['resolved'].update(scope='CHANGED'))
        with self.assertRaisesRegex(ValueError, 'resolved outcome differs'):
            self.nightly.raw_predecessor(self.final, raw_checkpoint=self.raw)
        self.assertEqual(self.context.policy_calls, 1)

    # Reject a final receipt whose claimed parent differs from its real committed entry.
    def test_committed_wrong_submission_parent_refuses(self):
        self.scenario(alteration=lambda value: value['detail'].update(settlement_submission_head='0' * 64))
        with self.assertRaisesRegex(ValueError, 'settlement detail required'):
            self.nightly.raw_predecessor(self.final, raw_checkpoint=self.raw)
        self.assertEqual(self.context.policy_calls, 1)

    # Recheck the exact observed native broker clock after the receipt has been committed.
    def test_committed_wrong_observation_clock_refuses(self):
        self.scenario(alteration=lambda value: value['raw_reconciliation']['evidence'].update(
            conditional_observed_at='2019-03-01T14:45:34+00:00'))
        with self.assertRaisesRegex(ValueError, 'observation clock differs'):
            self.nightly.raw_predecessor(self.final, raw_checkpoint=self.raw)
        self.assertEqual(self.context.policy_calls, 1)

    # Catch changed current latches and native paper before any new close reservation.
    def test_changed_current_latch_and_paper_refuse_before_policy(self):
        self.scenario()
        path = self.cycle['entry_timing'].latch_path(self.nightly.root, date(2019, 3, 1))
        old = path.read_bytes()
        path.write_bytes(demand.encoded({'session': '2019-03-01', 'scope': 'CHANGED'}))
        with self.assertRaisesRegex(ValueError, 'current latch differs'):
            self.fixture.close(self.client, '2019-03-01', self.birth, self.final)
        path.write_bytes(old)
        state = paper.load_state(self.nightly.root)
        state.history[-1]['cash'] = -1
        paper.save_state(self.nightly.root, state)
        with self.assertRaisesRegex(ValueError, 'pre-close components differ'):
            self.fixture.close(self.client, '2019-03-01', self.birth, self.final)
        self.assertFalse(self.nightly.operation('NIGHTLY_CLOSE', '2019-03-01').exists())
        self.assertEqual(self.context.policy_calls, 1)

    # Preserve same-session discipline, legacy raw refusal and public genuine refusal.
    def test_wrong_session_legacy_and_public_admission_remain_closed(self):
        self.scenario()
        with self.assertRaisesRegex(ValueError, 'same-session'):
            self.fixture.close(self.client, '2019-03-04', self.birth, self.final)
        receipt = packet._decode(self.store.read_blob(self.final, limit=262144))
        with self.assertRaisesRegex(ValueError, 'not admitted'):
            self.cycle['_final_settlement'](self.store, receipt, self.pins)
        with self.assertRaisesRegex(StorePause, 'before effects'):
            self.nightly.close(self.context, self.client, '2019-03-01',
                birth=self.birth, previous=self.final, raw_checkpoint=self.raw)
        self.assertEqual(self.context.policy_calls, 1)
