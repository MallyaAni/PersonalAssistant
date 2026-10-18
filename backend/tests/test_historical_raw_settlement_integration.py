"""Raw settlement acceptance with real native broker, codec, paper and SQLite/CAS.

Settlement/Cycle and two market_daily helper CodeTypes come from complete source
compilation with explicitly isolated module globals. Native deferred imports run;
model-related declarations may import, but no model/provider/policy call runs.
"""
import ast
import builtins
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import types
from types import SimpleNamespace
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import historical_paper_component as component
from backend.market import historical_physical_checkpoint as physical
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.historical_packet_store import Store
from backend.tests import test_historical_paper_component_integration as fixture


# Instantiate exact complete-source function bodies without application module startup.
def functions(path, names, namespace):
    code = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
    codes = {item.co_name: item for item in code.co_consts if isinstance(item, types.CodeType)}
    declarations = {node.name: node for node in ast.parse(path.read_bytes()).body
                    if isinstance(node, ast.FunctionDef)}
    namespace.update({'__file__': str(path), '__builtins__': builtins.__dict__})
    for name in names:
        function = types.FunctionType(codes[name], namespace)
        declaration = declarations[name]
        function.__defaults__ = tuple(fixture.default_value(node, namespace)
            for node in declaration.args.defaults) or None
        function.__kwdefaults__ = {arg.arg: fixture.default_value(node, namespace)
            for arg, node in zip(declaration.args.kwonlyargs, declaration.args.kw_defaults)
            if node is not None}
        namespace[name] = function
    return SimpleNamespace(**namespace)


# Isolate CLI startup while retaining its exact pending filter and real deferred imports.
def settlement_namespace():
    daily_path = Path('/native/backend/cli/market_daily.py')
    daily = functions(daily_path, ('_acknowledged', '_reconciliation_pending'),
                      {'datetime': datetime, 'date': date})
    return functions(Path('/audit/backend/market/historical_conditional_settlement.py'),
        ('_sha', '_unique', '_requests', 'reconcile', '_native_serialization',
         'reconcile_raw', 'verify_raw_saved'),
        {'hashlib': hashlib, 'json': json, 'deepcopy': deepcopy, 'asdict': asdict,
         'Path': Path, 'paper': paper, 'native': native, 'codec': codec,
         'demand': demand, 'market_daily': daily})


# Verify actual native reconciliation and persisted raw components over synthetic accounts.
class RawSettlementIntegrationTests(unittest.TestCase):
    # Reuse only fixture setup, never its closed eleven-test gate.
    def setUp(self):
        fixture.PaperComponentIntegrationTests.setUpClass()
        self.fixture = fixture.PaperComponentIntegrationTests()
        self.fixture.profile = fixture.PaperComponentIntegrationTests.profile
        self.fixture.pin = fixture.PaperComponentIntegrationTests.pin
        self.fixture.writer = fixture.PaperComponentIntegrationTests.writer
        self.fixture.setUp()
        self.store, self.account, self.raw = self.fixture.store, self.fixture.account, self.fixture.raw
        self.pins = self.fixture.pins
        self.adapter = settlement_namespace()
        self.cycle = self.fixture.cycle
        self.cycle['codec'] = codec
        cycle_tree = ast.parse(Path(self.cycle['__file__']).read_bytes())
        self.cycle['SETTLEMENT_SHA256'] = next(ast.literal_eval(node.value)
            for node in cycle_tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'SETTLEMENT_SHA256'
                    for target in node.targets))
        self.cycle['_settlement_source'] = self.source
        functions(Path(self.cycle['__file__']), ('_raw_reconciliation',), self.cycle)

    # Leave all retained evidence while closing the actual SQLite writer lock.
    def tearDown(self):
        self.fixture.store.close()

    # Return only the exact isolated settlement implementation bound to its source pin.
    def source(self):
        self.assertEqual(hashlib.sha256(Path(self.adapter.__file__).read_bytes()).hexdigest(),
                         self.cycle['SETTLEMENT_SHA256'])
        return self.adapter

    # Resolve a declared synthetic native market order without provider or actual clocks.
    def scenario(self, *, side='sell', desired=8, submitted=5, large=True, nonfinite=True):
        self.client = native.ReplayBroker(1000, 10,
            initial_holdings={'AAPL': 5} if side == 'sell' else {},
            initial_average_prices={'AAPL': 80} if side == 'sell' else {})
        self.client.observe('2019-03-01T14:45:31.200000+00:00', {'AAPL': 100}, True)
        order = self.client.submit_market('AAPL', submitted, side, 'SYNTHETIC-raw-settlement')
        self.state = paper.PaperState(start_equity=float('nan') if nonfinite else 100000,
            history=[{'z': 'é' + 'x' * 25000, 'a': float('nan') if nonfinite else index}
                     for index in range(12)] if large else [],
            pending=[{'client_order_id': order['client_order_id'], 'symbol': 'AAPL',
                'side': side, 'qty': desired, 'session': '2019-02-28',
                'execute_on': '2019-03-01', 'execution_timing': 'dip_or_close',
                'sent': {'qty': submitted, 'at': order['submitted_at']},
                'execution': {'created_at': order['created_at'],
                              'submitted_at': order['submitted_at']}}])
        self.client.flush('2019-03-01T14:45:33+00:00', {'AAPL': 100})
        self.original = paper.save_state(self.account, self.state).read_bytes()
        self.pre = self.receipt()
        self.prior = self.read(self.pre)['components']['paper']
        return self.state

    # Retain actual broker bytes and raw native paper in a finite versioned receipt.
    def receipt(self, reconciliation=None):
        return self.cycle['_receipt'](self.store, self.client, self.account, self.pins,
            {'stage': 'SYNTHETIC_RAW_SETTLEMENT_COMPONENTS'}, raw_checkpoint=self.raw,
            raw_reconciliation=reconciliation)

    # Authenticate persisted evidence through the real edited read boundary.
    def read(self, reference):
        return self.cycle['_read_receipt'](self.store, reference, self.pins, raw_checkpoint=self.raw)

    # Run only pure native reconciliation and leave actual persistence to its caller.
    def reconcile(self, **changes):
        parameters = {'pins': self.pins, 'outcome_sha256': self.pre,
            'observed_at': self.client._now.isoformat(), 'prior_component': self.prior,
            'raw_checkpoint': self.raw, **changes}
        return self.adapter.reconcile_raw(self.client, self.state, **parameters)

    # Exercise actual pending-to-journal changes, finite receipt reopen and exact restore.
    def test_large_nan_native_settlement_save_receipt_restore(self):
        self.scenario()
        broker_before = codec.encode(self.client, **self.pins)
        updated, evidence = self.reconcile()
        self.assertGreater(len(self.original), 262144)
        self.assertIn(b'NaN', self.original)
        self.assertEqual(paper.state_path(self.account).read_bytes(), self.original)
        self.assertEqual(codec.encode(self.client, **self.pins), broker_before)
        self.assertEqual(updated.pending, [])
        row = updated.journal[0]
        self.assertEqual((row['qty'], row['submitted_qty'], row['sender_qty'], row['filled_qty']), (8, 5, 5, 5))
        self.assertEqual(row['status'], 'partial')
        self.assertIs(row['terminal'], True)
        self.assertNotIn('prior_paper_sha256', evidence)
        self.assertNotIn('reconciled_paper_sha256', evidence)
        saved = paper.save_state(self.account, updated).read_bytes()
        self.assertNotEqual(saved, self.original)
        self.assertIn(b'NaN', saved)
        self.assertEqual(len(paper.load_state(self.account).history), 12)
        final = self.receipt({'pre_settlement_receipt': self.pre, 'evidence': evidence})
        value = self.read(final)
        self.assertEqual(value['components']['broker'], hashlib.sha256(broker_before).hexdigest())
        self.store.close()
        self.store = Store(self.fixture.root / 'store', self.fixture.pin, None)
        self.fixture.store = self.store
        reopened = physical.PhysicalCheckpoint(self.raw.root,
            identity_sha256=self.fixture.pin, writer=self.fixture.writer)
        fresh = self.store.root / 'restored-settlement'
        restored_client, receipt = self.cycle['restore_receipt'](self.store, final, fresh,
            pins=self.pins, raw_checkpoint=reopened)
        self.assertEqual(receipt, value)
        self.assertEqual(codec.encode(restored_client, **self.pins), broker_before)
        self.assertEqual(paper.state_path(fresh).read_bytes(), saved)
        self.assertEqual(paper.load_state(fresh).journal, updated.journal)
        paper.save_state(fresh, paper.load_state(fresh))
        self.assertEqual(paper.state_path(fresh).read_bytes(), saved)
        self.assertIs(evidence['durable_state_committed'], False)
        self.assertIs(evidence['actual_execution_claim'], False)

    # Refuse an input dataclass that is not the exact native-serialized prior capture.
    def test_changed_state_refused_before_reconciliation(self):
        self.scenario()
        self.state.history[0]['z'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'input state differs'):
            self.reconcile()
        self.assertEqual(paper.state_path(self.account).read_bytes(), self.original)

    # Compare new raw rules to the unchanged legacy rules on their common finite domain.
    def test_finite_buy_sell_parity_with_legacy(self):
        for side in ('buy', 'sell'):
            with self.subTest(side=side):
                self.scenario(side=side, large=False, nonfinite=False)
                expected, legacy = self.adapter.reconcile(self.client, self.state,
                    pins=self.pins, outcome_sha256=self.pre,
                    observed_at=self.client._now.isoformat())
                actual, evidence = self.reconcile()
                self.assertEqual(asdict(actual), asdict(expected))
                self.assertEqual(evidence['settled'], legacy['settled'])
                self.assertEqual(actual.pending, [])

    # Authenticate metadata after actual native save without accepting altered bindings.
    def test_evidence_tampering_refused(self):
        self.scenario()
        updated, evidence = self.reconcile()
        paper.save_state(self.account, updated)
        final = component.capture(self.raw, paper.state_path(self.account), expected_identity=self.fixture.pin)
        changes = {'schema': 'old/1', 'adapter_sha256': '0' * 64,
            'identity_sha256': '0' * 64, 'durable_state_committed': True,
            'actual_execution_claim': True, 'source_sha256': {},
            'reconciled_native_serialization': {'schema': 'canonical-paper/1', 'raw_sha256': '0' * 64, 'raw_bytes': 1}}
        for key, value in changes.items():
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.adapter.verify_raw_saved({**evidence, key: value}, final, self.raw, pins=self.pins)

    # Refuse stale final bytes and links to an unrelated prior or broker component graph.
    def test_receipt_graph_and_native_save_mismatch(self):
        self.scenario()
        updated, evidence = self.reconcile()
        with self.assertRaisesRegex(ValueError, 'saved settlement bytes differ'):
            self.receipt({'pre_settlement_receipt': self.pre, 'evidence': evidence})
        paper.save_state(self.account, updated)
        for key, value in (('outcome_sha256', '0' * 64), ('broker_checkpoint_sha256', '0' * 64)):
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'component graph differs'):
                self.receipt({'pre_settlement_receipt': self.pre, 'evidence': {**evidence, key: value}})
        with self.assertRaisesRegex(ValueError, 'observation clock differs'):
            self.receipt({'pre_settlement_receipt': self.pre,
                'evidence': {**evidence, 'conditional_observed_at': '2019-03-01T14:45:34+00:00'}})
        self.assertEqual(paper.load_state(self.account).pending, [])

    # Keep unresolved and unacknowledged receipts separate from an actual resolved fold.
    def test_request_and_clock_guards(self):
        self.scenario()
        with self.assertRaisesRegex(ValueError, 'observation clock'):
            self.reconcile(observed_at='2019-03-01T14:45:34+00:00')
        self.client = native.ReplayBroker(1000, 10)
        self.client.observe('2019-03-01T14:45:33+00:00', {'AAPL': 100}, True)
        with self.assertRaisesRegex(ValueError, 'lacks original native broker receipt'):
            self.reconcile()
        self.assertEqual(paper.state_path(self.account).read_bytes(), self.original)

    # Preserve a future unsent intent while recording the resolved broker leg.
    def test_future_unsent_intent_retained(self):
        self.scenario()
        future = {'client_order_id': 'SYNTHETIC-future-intent', 'symbol': 'AAPL',
                  'side': 'buy', 'qty': 1, 'session': '2019-03-01',
                  'execute_on': '2019-03-04', 'execution_timing': 'next_open'}
        self.state.pending.append(future)
        self.original = paper.save_state(self.account, self.state).read_bytes()
        self.pre = self.receipt()
        self.prior = self.read(self.pre)['components']['paper']
        updated, evidence = self.reconcile()
        self.assertEqual(updated.pending, [future])
        self.assertEqual(evidence['unreconciled_pending'], [future['client_order_id']])
        self.assertEqual(len(updated.journal), 1)
        self.assertEqual(paper.state_path(self.account).read_bytes(), self.original)

    # Keep finite receipt metadata strict even while native state retains NaNs.
    def test_nonfinite_evidence_and_serialization_bound_refuse(self):
        self.scenario()
        with self.assertRaisesRegex(ValueError, 'exceeds reservation'):
            self.adapter._native_serialization(self.state, 1)
        updated, evidence = self.reconcile()
        paper.save_state(self.account, updated)
        changed = deepcopy(evidence)
        changed['settled'][0]['filled_price'] = float('nan')
        with self.assertRaises(ValueError):
            self.receipt({'pre_settlement_receipt': self.pre, 'evidence': changed})

    # Reject recursive raw evidence before any recursive receipt read can begin.
    def test_recursive_prior_and_mode_confusion_refuse(self):
        self.scenario()
        updated, evidence = self.reconcile()
        paper.save_state(self.account, updated)
        first = self.receipt({'pre_settlement_receipt': self.pre, 'evidence': evidence})
        with self.assertRaisesRegex(ValueError, 'recursive evidence refused'):
            self.receipt({'pre_settlement_receipt': first, 'evidence': evidence})
        with self.assertRaisesRegex(ValueError, 'explicit component storage'):
            self.cycle['_receipt'](self.store, self.client, self.account, self.pins, {},
                raw_reconciliation={'pre_settlement_receipt': self.pre, 'evidence': evidence})

    # Check literal bridge pins and exact native serialization semantics.
    def test_source_pins_and_native_serialization_semantics(self):
        self.scenario()
        expected = self.adapter._native_serialization(self.state, self.raw.limits['raw_bytes'])
        self.assertEqual(expected['raw_sha256'], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(expected['raw_bytes'], len(self.original))
        cycle = Path('/audit/backend/market/historical_conditional_cycle.py').read_bytes()
        nightly = ast.parse(Path('/audit/backend/market/historical_conditional_nightly.py').read_bytes())
        pins = {node.targets[0].id: ast.literal_eval(node.value) for node in nightly.body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'CYCLE'}
        self.assertEqual(pins['CYCLE'], hashlib.sha256(cycle).hexdigest())
