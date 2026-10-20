"""Accounting and causal selection checks for the independent historical producer."""
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
import sys
import backend.market

if '/calc' in sys.path[0]:
    backend.market.__path__.insert(0, '/calc')

import numpy as np

from backend.market import probabilistic_execution
from backend.market.strategy_model_history import continuous_targets, replay
from backend.market.strategy_model_extension import InitialBook


# Build independent inputs with an A entry followed by a below-A grade exit.
def case(next_price=100.0, eligible=None):
    dates = np.array(['2026-01-05','2026-01-06','2026-01-07'],dtype='datetime64[D]')
    panel = SimpleNamespace(dates=dates,tickers=('AAA','SPY'),adj_close=np.full((3,2),100.0),
        open=np.full((3,2),100.0),close=np.full((3,2),100.0))
    grades = np.array([[2,-1],[1,-1],[1,-1]],dtype=np.int16)
    weights = np.array([[.2,0],[0,0],[0,0]])
    quote = np.full((3,25,2),100.0,dtype=np.float32)
    execution = quote.copy()
    execution[1,:,0] = next_price
    # Synthetic tests carry no membership history; all names are eligible unless a case overrides it.
    mask = np.ones((3,2),dtype=bool) if eligible is None else eligible
    policy=SimpleNamespace(cost_bps=10.0,timing_policy=probabilistic_execution.POLICY)
    return replay(policy,panel,grades,np.zeros((3,2),dtype=bool),mask,quote,execution,lambda *args:None,first=1,provenance={'test':True},generated_at=datetime.now(UTC),allocations=weights)


# Prove the book sells owned exposure rather than labelling a zero remaining target as Sell0.
class HistoryTests(unittest.TestCase):
    # Preserve the original positive exit fraction, date, grade reason and nonnegative cash.
    def test_owned_grade_exit_has_positive_size(self):
        result=case()
        buy,sell=result['stocks']['AAA']['decisions']
        self.assertEqual((buy['action'],sell['action']),('BUY','SELL'))
        self.assertEqual(sell['target_weight'],0)
        self.assertGreater(sell['weight'],0)
        self.assertEqual(sell['evidence']['grade'],'B')
        self.assertEqual(sell['evidence']['timing_reason'],'mandatory_grade_exit')
        self.assertTrue(all(row['cash']>=0 for row in result['curve']))
        self.assertEqual(result['stocks']['AAA']['latest_holding'],0)
        self.assertAlmostEqual(result['curve'][0]['cash'],.7998,places=12)

    # Later execution prices can change accounting but cannot change the prior recommendation.
    def test_future_open_cannot_choose_first_entry(self):
        left=case(100)['stocks']['AAA']['decisions'][0]
        right=case(150)['stocks']['AAA']['decisions'][0]
        for key in ('action','weight','at','target_weight','evidence'):
            self.assertEqual(left[key],right[key])

    # Missing grades and zero sizing for an eligible holding preserve ownership without borrowing.
    def test_preserved_holdings_do_not_fund_extra_exposure(self):
        result = continuous_targets({'A':0,'B':.8,'C':0},{'A':.4,'C':.3},{'A':2,'B':2,'C':-1})
        self.assertEqual(result['A'],.4)
        self.assertEqual(result['C'],.3)
        self.assertAlmostEqual(result['B'],.3)
        self.assertAlmostEqual(sum(result.values()),1)

    # A split leaves raw opens on a different basis from the adjusted book; the
    # exit must use the same adjusted basis as the marks rather than 10x the price.
    def test_split_basis_cannot_misprice_a_grade_exit(self):
        dates = np.array(['2026-01-05','2026-01-06','2026-01-07'],dtype='datetime64[D]')
        names = ('AAA','SPY')
        adj_close = np.array([[100.,100.],[10.,10.],[10.,10.]])
        open_raw = np.array([[100.,100.],[100.,100.],[100.,100.]])
        close_raw = np.array([[100.,100.],[100.,100.],[100.,100.]])
        grades = np.array([[1,-1],[1,-1],[1,-1]],dtype=np.int16)
        quote = np.full((3,25,2),100.0)
        initial = InitialBook('2026-01-05',names,(1.0,0.0),0.0,0.0,0,'a'*64)
        result = replay(SimpleNamespace(cost_bps=10.0,timing_policy=probabilistic_execution.POLICY),
            SimpleNamespace(dates=dates,tickers=names,adj_close=adj_close,open=open_raw,close=close_raw),
            grades,np.zeros((3,2),dtype=bool),np.ones((3,2),dtype=bool),quote,quote.copy(),lambda *args:None,
            first=1,provenance={},generated_at=datetime.now(UTC),allocations=np.zeros((3,2)),initial_book=initial)
        self.assertAlmostEqual(result['curve'][0]['cash'],9.99,places=12)
        self.assertEqual(result['stocks']['AAA']['decisions'][0]['evidence']['timing_reason'],'mandatory_grade_exit')

    # A split must also scale the intraday execution price used for a fill.
    def test_split_basis_cannot_misprice_an_intraday_fill(self):
        dates = np.array(['2026-01-05','2026-01-06'],dtype='datetime64[D]')
        names = ('AAA','SPY')
        adj_close = np.array([[100.,100.],[10.,10.]])
        open_raw = np.full((2,2),100.0)
        close_raw = np.full((2,2),100.0)
        grades = np.array([[2,-1],[2,-1]],dtype=np.int16)
        allocations = np.array([[.2,0],[.2,0]])
        observations = np.full((2,25,2),100.0)
        distribution = probabilistic_execution.Distribution(
            .02,0.0,np.array([0.0]),np.array([1.0]))
        result = replay(
            SimpleNamespace(cost_bps=10.0,timing_policy=probabilistic_execution.POLICY),
            SimpleNamespace(dates=dates,tickers=names,adj_close=adj_close,open=open_raw,close=close_raw),
            grades,np.zeros((2,2),dtype=bool),np.ones((2,2),dtype=bool),observations,observations.copy(),
            lambda *args: distribution,first=1,provenance={},
            generated_at=datetime.now(UTC),allocations=allocations)
        buy = result['stocks']['AAA']['decisions'][0]
        self.assertEqual(buy['action'],'BUY')
        self.assertAlmostEqual(buy['evidence']['observed_price'],10.0,places=12)
        self.assertAlmostEqual(result['stocks']['AAA']['latest_holding'],.002,places=12)
        self.assertAlmostEqual(result['curve'][-1]['cash'],.97998,places=12)

    # A missing close cannot silently leave raw opens beside adjusted marks.
    def test_missing_close_refuses_instead_of_mixing_price_bases(self):
        dates = np.array(['2026-01-05','2026-01-06','2026-01-07'],dtype='datetime64[D]')
        panel = SimpleNamespace(dates=dates,tickers=('AAA','SPY'),
            adj_close=np.full((3,2),100.0),open=np.full((3,2),100.0))
        grades = np.array([[2,-1],[1,-1],[1,-1]],dtype=np.int16)
        quote = np.full((3,25,2),100.0)
        with self.assertRaisesRegex(ValueError,'close'):
            replay(SimpleNamespace(cost_bps=10.0,timing_policy=probabilistic_execution.POLICY),panel,
                grades,np.zeros((3,2),dtype=bool),np.ones((3,2),dtype=bool),quote,quote.copy(),
                lambda *args:None,first=1,provenance={},generated_at=datetime.now(UTC),allocations=np.zeros((3,2)))

    # A name outside the point-in-time book on the decision session is never bought.
    def test_ineligible_name_is_never_bought(self):
        eligible = np.ones((3,2),dtype=bool);eligible[0,0]=False
        result = case(eligible=eligible)
        self.assertEqual(result['stocks']['AAA']['decisions'],[])
        self.assertEqual(result['stocks']['AAA']['latest_holding'],0)

    # A held name that leaves the book is sold at the next open, not left as a stale holding.
    def test_held_name_becoming_ineligible_exits_at_next_open(self):
        dates = np.array(['2026-01-05','2026-01-06','2026-01-07'],dtype='datetime64[D]')
        panel = SimpleNamespace(dates=dates,tickers=('AAA','SPY'),adj_close=np.full((3,2),100.0),
            open=np.full((3,2),100.0),close=np.full((3,2),100.0))
        grades = np.array([[2,-1],[2,-1],[2,-1]],dtype=np.int16)
        allocations = np.array([[.2,0],[.2,0],[.2,0]])
        eligible = np.ones((3,2),dtype=bool);eligible[1,0]=False
        quote = np.full((3,25,2),100.0)
        result = replay(SimpleNamespace(cost_bps=10.0,timing_policy=probabilistic_execution.POLICY),panel,
            grades,np.zeros((3,2),dtype=bool),eligible,quote,quote.copy(),lambda *args:None,
            first=1,provenance={},generated_at=datetime.now(UTC),allocations=allocations)
        buy,sell = result['stocks']['AAA']['decisions']
        self.assertEqual((buy['action'],sell['action']),('BUY','SELL'))
        self.assertEqual(sell['evidence']['timing_reason'],'universe_exit')
        self.assertEqual(result['stocks']['AAA']['latest_holding'],0)


# Run the same assertions in the bounded numerical container before reading historical inputs.
if __name__=='__main__':
    unittest.main()
