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


# Build independent inputs with an A entry followed by a below-A grade exit.
def case(next_price=100.0):
    dates = np.array(['2026-01-05','2026-01-06','2026-01-07'],dtype='datetime64[D]')
    panel = SimpleNamespace(dates=dates,tickers=('AAA','SPY'),adj_close=np.full((3,2),100.0),open=np.full((3,2),100.0))
    grades = np.array([[2,-1],[1,-1],[1,-1]],dtype=np.int16)
    weights = np.array([[.2,0],[0,0],[0,0]])
    quote = np.full((3,25,2),100.0,dtype=np.float32)
    execution = quote.copy()
    execution[1,:,0] = next_price
    policy=SimpleNamespace(cost_bps=10.0,timing_policy=probabilistic_execution.POLICY)
    return replay(policy,panel,grades,np.zeros((3,2),dtype=bool),quote,execution,lambda *args:None,first=1,provenance={'test':True},generated_at=datetime.now(UTC),allocations=weights)


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
        result=continuous_targets({'A':0,'B':.8,'C':0},{'A':.4,'C':.3},{'A':2,'B':2,'C':-1})
        self.assertEqual(result['A'],.4)
        self.assertEqual(result['C'],.3)
        self.assertAlmostEqual(result['B'],.3)
        self.assertAlmostEqual(sum(result.values()),1)


# Run the same assertions in the bounded numerical container before reading historical inputs.
if __name__=='__main__':
    unittest.main()
