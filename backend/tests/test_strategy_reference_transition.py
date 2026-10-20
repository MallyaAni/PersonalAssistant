"""Native replay parity for explicitly counterfactual ongoing model advice."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import json
from unittest.mock import patch

import numpy as np

from backend.market import probabilistic_execution as timing
from backend.market import strategy_model_history as history
from backend.market import strategy_reference_transition as transition
from backend.market import strategy_publication as publication
from backend.market import strategy_entries
from backend.tests.test_strategy_entries import fixture, timing_cache, NOW


# Produce an independent original snapshot with complete synthetic stock rows.
def snapshot_for(root, targets, grades=None):
    snapshot, _, _ = fixture(root)
    prototype = deepcopy(snapshot['rows']['AAA'])
    reading = deepcopy(snapshot['grade_signals']['AAA'])
    snapshot['rows'], snapshot['grade_signals'] = {}, {}
    for name, weight in targets.items():
        grade = (grades or {}).get(name, 'A')
        snapshot['rows'][name] = deepcopy(prototype)
        snapshot['rows'][name].update(target_weight=weight)
        snapshot['rows'][name]['evidence'].update(grade=grade, model_position_size=weight)
        snapshot['grade_signals'][name] = {**reading, 'grade': grade,
            'action': 'buy' if grade in ('A', 'A+') else 'unavailable' if grade is None else 'avoid'}
    snapshot['receipt_sha256'] = publication._digest({k: v for k, v in snapshot.items() if k != 'receipt_sha256'})
    publication.validate(snapshot, NOW)
    return snapshot


# Name every reference stock and detach its units and close marks into immutable scalar tuples.
def book_for(snapshot, units, cash, marks=None):
    return transition.ReferenceBook(snapshot['strategy_identity'], snapshot['session'], 10.0,
        tuple((name, units.get(name, 0.0), (marks or {}).get(name, 100.0)) for name in sorted(snapshot['rows'])),
        cash, 'b' * 64)


# Supply an actual native probability distribution without replacing its economic decision.
def distribution(mean):
    return timing.Distribution(mean, .001, np.array([-1., 1.]), np.array([1., 1.]))


# Supply clearly synthetic already-validated history for reader-boundary refusal tests.
def prepared_history(snapshot, units=.002, cash=.8):
    stock = {'ticker': 'AAA', 'through': snapshot['session'], 'counterfactual': True,
             'real_orders': False, 'latest_holding': units}
    manifest = {'through': snapshot['session'], 'provenance': {'cost_bps': 10},
                'curve': [{'date': snapshot['session'], 'cash': cash, 'equity': cash + units * 100}]}
    return {'manifest': json.dumps(manifest).encode(), 'binding': {'strategy_identity': snapshot['strategy_identity']},
            'files': {'AAA': json.dumps(stock).encode()}}


# Compare ongoing reference changes with actual unchanged native simulation and timing.
class ReferenceTransitionTests(unittest.TestCase):
    # The existing pending-unit threshold also leaves an unpriced microscopic new position inactive.
    def test_native_pending_unit_threshold_never_invents_missing_price(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17, 'BBB': 1e-14})
            plan = transition.prepare(snapshot, book_for(snapshot, {'AAA': .003}, .7), NOW)
            result = transition.project(plan, {'AAA': 100.0}, {'AAA': distribution(.02)},
                evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
            self.assertEqual(result['rows']['AAA']['state'], 'execute')
            self.assertEqual(result['rows']['BBB']['state'], 'no_trade')
            self.assertIsNone(result['rows']['BBB']['action'])
            self.assertNotIn('BBB', result['marked_prices'])

    # An unused stock cannot make a valid held-position transition unavailable solely because it has no quote.
    def test_unowned_zero_target_does_not_require_unused_mark(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17, 'BBB': 0.0}, {'BBB': 'B'})
            plan = transition.prepare(snapshot, book_for(snapshot, {'AAA': .003}, .7), NOW)
            result = transition.project(plan, {'AAA': 100.0}, {'AAA': distribution(.02)},
                evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
            self.assertEqual(result['rows']['AAA']['state'], 'execute')
            self.assertIsNone(result['rows']['BBB']['action'])
            self.assertEqual(result['rows']['BBB']['trade_weight'], 0)
            self.assertNotIn('BBB', result['marked_prices'])

    # Preparing a scenario reads validated originals and remains identical when reopened without any inference.
    def test_reviewed_endpoint_preparation_is_repeatable_and_detached(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17})
            prepared = prepared_history(snapshot)
            context = SimpleNamespace(panel=SimpleNamespace(tickers=('AAA',), adj_close=np.array([[100.0]])),
                                      receipt={'explicit_synthetic_context': True})
            review = {'history_sha256': '1' * 64, 'audit_sha256': '2' * 64, 'binding_sha256': '3' * 64}
            with patch.object(transition.strategy_entry_context, 'load', return_value=context), \
                    patch.object(transition.strategy_history_installation, 'prepare', return_value=prepared):
                first, evidence = transition.from_reviewed_history(directory, snapshot, '/explicit-synthetic-assets', review, NOW)
                again, repeated = transition.from_reviewed_history(directory, snapshot, '/explicit-synthetic-assets', review, NOW)
            self.assertEqual(first, again)
            self.assertEqual(evidence, repeated)
            self.assertEqual(first.positions, (('AAA', .002, 100.0),))
            context.panel.adj_close[0, 0] = 150
            self.assertEqual(first.positions, (('AAA', .002, 100.0),))
            self.assertEqual(first.evidence_sha256, publication._digest(evidence))

    # A later snapshot cannot silently reseed itself from an older historical endpoint or foreign economics.
    def test_reviewed_endpoint_date_and_identity_refuse(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17})
            context = SimpleNamespace(panel=SimpleNamespace(tickers=('AAA',), adj_close=np.array([[100.0]])), receipt={})
            prepared = prepared_history(snapshot)
            old = deepcopy(prepared)
            manifest = json.loads(old['manifest']); manifest['through'] = '2026-01-05'
            old['manifest'] = json.dumps(manifest).encode()
            foreign = deepcopy(prepared); foreign['binding']['strategy_identity'] = '0' * 64
            for changed in (old, foreign):
                with patch.object(transition.strategy_entry_context, 'load', return_value=context), \
                        patch.object(transition.strategy_history_installation, 'prepare', return_value=changed):
                    with self.assertRaisesRegex(ValueError, 'endpoint must match'):
                        transition.from_reviewed_history(directory, snapshot, '/explicit-synthetic-assets', {}, NOW)

    # Source-validated history still must reconcile owned units against its original cash/equity accounting.
    def test_reviewed_reference_accounting_refuses_changed_units(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17})
            prepared = prepared_history(snapshot)
            stock = json.loads(prepared['files']['AAA']); stock['latest_holding'] = .003
            prepared['files']['AAA'] = json.dumps(stock).encode()
            context = SimpleNamespace(panel=SimpleNamespace(tickers=('AAA',), adj_close=np.array([[100.0]])), receipt={})
            review = {'history_sha256': '1' * 64, 'audit_sha256': '2' * 64, 'binding_sha256': '3' * 64}
            with patch.object(transition.strategy_entry_context, 'load', return_value=context), \
                    patch.object(transition.strategy_history_installation, 'prepare', return_value=prepared):
                with self.assertRaisesRegex(ValueError, 'accounting differ'):
                    transition.from_reviewed_history(directory, snapshot, '/explicit-synthetic-assets', review, NOW)

    # Preserve the real discrepancy as an assertion: fresh allocation is a Buy while an owned model position needs a Sell.
    def test_original_fresh_path_and_reference_transition_are_distinct(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17})
            cache, quotes, _ = timing_cache(snapshot)
            original = strategy_entries.project(snapshot, cache, quotes, NOW)
            self.assertEqual(original['rows']['AAA']['action'], 'Buy')
            self.assertEqual(original['rows']['AAA']['size_weight'], .17)
            plan = transition.prepare(snapshot, book_for(snapshot, {'AAA': .003}, .7), NOW)
            result = transition.project(plan, {'AAA': 100.0}, {'AAA': distribution(.02)},
                evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
            self.assertEqual(result['rows']['AAA']['action'], 'Sell')
            self.assertAlmostEqual(result['rows']['AAA']['trade_weight'], .13, places=14)
            self.assertEqual(result['rows']['AAA']['model_position_weight'], .17)

    # A still-A reduction must reproduce the unchanged replay's positive sell amount exactly.
    def test_original_replay_still_a_trim_matches(self):
        dates = np.array(['2026-01-05', '2026-01-06', '2026-01-07'], dtype='datetime64[D]')
        panel = SimpleNamespace(dates=dates, tickers=('AAA', 'SPY'),
            adj_close=np.full((3, 2), 100.0), open=np.full((3, 2), 100.0), close=np.full((3, 2), 100.0))
        grades = np.array([[2, -1], [2, -1], [2, -1]])
        allocations = np.array([[.2, 0], [.1, 0], [.1, 0]])
        observations = np.full((3, 25, 2), 100.0)
        # The first session buys immediately; the next session sells immediately using native utility.
        def provider(day, clock, stock):
            return distribution(-.02 if day == 1 else .02)
        # The synthetic panel has no membership history; every name is eligible.
        result = history.replay(SimpleNamespace(cost_bps=10.0, timing_policy=timing.POLICY), panel,
            grades, np.zeros((3, 2), dtype=bool), np.ones((3, 2), dtype=bool), observations, observations.copy(), provider,
            first=1, allocations=allocations, provenance={'explicit_synthetic_test': True}, generated_at=NOW)
        buy, sell = result['stocks']['AAA']['decisions']
        self.assertEqual((buy['action'], sell['action']), ('BUY', 'SELL'))
        self.assertEqual(sell['evidence']['grade'], 'A')
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .1})
            book = book_for(snapshot, {'AAA': .002}, result['curve'][0]['cash'])
            plan = transition.prepare(snapshot, book, NOW)
            actual = transition.project(plan, {'AAA': 100.0}, {'AAA': distribution(.02)},
                evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
            row = actual['rows']['AAA']
            self.assertEqual((row['action'], row['state']), ('Sell', 'execute'))
            self.assertEqual(row['trade_weight'], sell['weight'])
            self.assertEqual(row['waiting_log_utility'], sell['evidence']['waiting_log_utility'])
            self.assertEqual(row['model_position_weight'], sell['target_weight'])
            self.assertEqual(row['proposed_units'], .002 - .1 * .9998 / 100)
            self.assertLessEqual(row['proposed_units'], row['reference_units'])
            self.assertEqual(book.positions, (('AAA', .002, 100.0),))

    # Native timing must see the trade delta, rather than the entire position, on both sides.
    def test_buy_and_sell_execute_wait_match_native(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17})
            for units, cash, side in ((.001, .9, 'buy'), (.003, .7, 'sell')):
                plan = transition.prepare(snapshot, book_for(snapshot, {'AAA': units}, cash), NOW)
                for mean in (-.02, .02):
                    native = distribution(mean)
                    value = transition.project(plan, {'AAA': 100.0}, {'AAA': native},
                        evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
                    row = value['rows']['AAA']
                    # The unchanged replay computes desired units first, then marks their delta.
                    expected_weight = abs(.17 / 100 - units) * 100
                    expected = timing.decision(native, side, expected_weight, 10, horizon=timing.HORIZON)
                    self.assertEqual(row['state'], expected.state)
                    self.assertEqual(row['waiting_log_utility'], expected.expected_log_utility)
                    self.assertAlmostEqual(row['trade_weight'], abs(.17 - units * 100), places=14)

    # A below-A exit sells only the reference units and never displays a zero sell amount.
    def test_grade_exit_is_owned_amount_without_timing(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': 0.0}, {'AAA': 'B'})
            book = book_for(snapshot, {'AAA': .002}, .8)
            value = transition.project(transition.prepare(snapshot, book, NOW), {'AAA': 120.0}, {},
                evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
            row = value['rows']['AAA']
            self.assertEqual((row['action'], row['state'], row['reason']), ('Sell', 'execute', 'mandatory_grade_exit'))
            self.assertEqual(row['proposed_units'], .002)
            self.assertEqual(row['model_position_weight'], 0.0)
            self.assertEqual(row['trade_weight'], .24 / 1.04)

    # A suggested sale cannot fund a simultaneous buy and cannot imply that the sale happened.
    def test_no_sale_proceeds_or_unowned_short_funding(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .1, 'BBB': .25})
            book = book_for(snapshot, {'AAA': .01}, 0.0)
            original = deepcopy(book)
            result = transition.project(transition.prepare(snapshot, book, NOW), {'AAA': 100.0, 'BBB': 100.0},
                {'AAA': distribution(.02), 'BBB': distribution(-.02)}, evidence_sha256='c' * 64,
                price_basis=transition.PRICE_BASIS)
            self.assertEqual(result['buy_funding_factor'], 0.0)
            self.assertEqual(result['rows']['BBB']['state'], 'no_trade')
            self.assertIsNone(result['rows']['BBB']['action'])
            self.assertAlmostEqual(result['rows']['AAA']['proposed_units'], .009, places=15)
            self.assertEqual(book, original)
            self.assertTrue(result['recommendation_not_fill'])
            self.assertFalse(result['account_inputs'])

    # Eligible zero-size and unknown-grade holdings use the exact unchanged fractional preservation rule.
    def test_preserved_reference_is_not_a_fresh_book(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': 0.0, 'BBB': .25, 'CCC': 0.0}, {'CCC': None})
            book = book_for(snapshot, {'AAA': .004, 'CCC': .003}, .3)
            plan = transition.prepare(snapshot, book, NOW)
            expected = history.continuous_targets({'AAA': 0.0, 'BBB': .25, 'CCC': 0.0},
                {'AAA': .4, 'CCC': .3}, {'AAA': 2, 'BBB': 2, 'CCC': -1})
            self.assertEqual({row[0]: row[3] for row in plan.rows}, expected)
            result = transition.project(plan, dict.fromkeys(snapshot['rows'], 100.0), {},
                evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
            self.assertIsNone(result['rows']['AAA']['action'])
            self.assertIsNone(result['rows']['CCC']['action'])

    # Genuine small changes remain exact; a reporting fix cannot introduce an economic minimum trade.
    def test_micro_change_is_not_rounded_or_promoted_to_position(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .249999})
            book = book_for(snapshot, {'AAA': .00249998}, .750002)
            result = transition.project(transition.prepare(snapshot, book, NOW), {'AAA': 100.0}, {'AAA': distribution(-.02)},
                evidence_sha256='c' * 64, price_basis=transition.PRICE_BASIS)
            self.assertGreater(result['rows']['AAA']['trade_weight'], 0)
            self.assertLess(result['rows']['AAA']['trade_weight'], .00001)
            self.assertEqual(result['rows']['AAA']['model_position_weight'], .249999)

    # Changed reference basis, economics, identity or incomplete ownership cannot be accepted as the original book.
    def test_foreign_partial_and_ambiguous_reference_refuse(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .17})
            original = book_for(snapshot, {'AAA': .002}, .8)
            for changed in (replace(original, cash=True), replace(original, cost_bps=20),
                    replace(original, strategy_identity='0' * 64), replace(original, through='2026-01-05'),
                    replace(original, positions=()), replace(original, positions=(('AAA', -.1, 100.0),)),
                    replace(original, price_basis='raw_current_shares'), replace(original, evidence_sha256='wrong')):
                with self.subTest(changed=changed):
                    with self.assertRaises(ValueError):
                        transition.prepare(snapshot, changed, NOW)

    # Later observed prices change marking but never rewrite the objective or mutate the original result.
    def test_original_plan_and_result_survive_later_marking(self):
        with TemporaryDirectory() as directory:
            snapshot = snapshot_for(Path(directory), {'AAA': .1})
            plan = transition.prepare(snapshot, book_for(snapshot, {'AAA': .003}, .7), NOW)
            digest = plan.receipt_sha256()
            first = transition.project(plan, {'AAA': 100.0}, {}, evidence_sha256='c' * 64,
                price_basis=transition.PRICE_BASIS, terminal=True)
            original = deepcopy(first)
            later = transition.project(plan, {'AAA': 150.0}, {}, evidence_sha256='d' * 64,
                price_basis=transition.PRICE_BASIS, terminal=True)
            self.assertEqual(first, original)
            self.assertEqual(plan.receipt_sha256(), digest)
            self.assertEqual(first['rows']['AAA']['proposed_units'], later['rows']['AAA']['proposed_units'])
            self.assertNotEqual(first['rows']['AAA']['trade_weight'], later['rows']['AAA']['trade_weight'])
            for marks, basis in (({'AAA': float('nan')}, transition.PRICE_BASIS),
                    ({}, transition.PRICE_BASIS), ({'AAA': 100.0}, 'raw_current_shares')):
                with self.assertRaises(ValueError):
                    transition.project(plan, marks, {}, evidence_sha256='c' * 64, price_basis=basis)


# Run the exact new numerical cases in the bounded component container.
if __name__ == '__main__':
    unittest.main()
