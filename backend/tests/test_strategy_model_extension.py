"""Prove a dated numerical continuation cannot reset, borrow or repeat its boundary."""
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
import sys
import backend.market

if '/calc' in sys.path[0]:
    backend.market.__path__.insert(0, '/calc')

import numpy as np
from backend.market import probabilistic_execution as probability
from backend.market.strategy_model_history import replay
from backend.market.strategy_model_extension import InitialBook, rebase_units


# Exercise original entry/exit mathematics using independently owned input arrays.
def run_case(last, first=1, initial_book=None):
    dates = np.array(['2026-09-29','2026-09-30','2026-10-01'],dtype='datetime64[D]')[:last]
    prices = np.full((last,2),100.0)
    panel = SimpleNamespace(dates=dates,tickers=('AAA','SPY'),adj_close=prices,open=prices.copy(),close=prices.copy())
    grades = np.array([[2,-1],[1,-1],[1,-1]])[:last]
    weights = np.array([[.2,0],[0,0],[0,0]])[:last]
    quote = np.full((last,25,2),100.0,dtype=np.float32)
    # These synthetic panels have no membership history; every name is eligible.
    return replay(SimpleNamespace(cost_bps=10.0,timing_policy=probability.POLICY),panel,grades,np.zeros_like(grades,dtype=bool),np.ones_like(grades,dtype=bool),quote,quote.copy(),lambda *args:None,first=first,provenance={},generated_at=datetime.now(UTC),allocations=weights,initial_book=initial_book)


# Bind the prior numerical output without accepting paper account state or a new unit budget.
class ExtensionTests(unittest.TestCase):
    # Corporate-action-adjusted unit changes preserve wealth and cannot manufacture a trade.
    def test_rebase_preserves_marked_wealth(self):
        units = rebase_units([2,3,0],[100,40,np.nan],[50,39.5,np.nan])
        np.testing.assert_allclose(units,[4,120/39.5,0],rtol=0,atol=0)
        self.assertEqual(float(units @ np.array([50,39.5,0])),320)
        with self.assertRaisesRegex(ValueError,'every owned unit'):
            rebase_units([1],[100],[np.nan])

    # A split calculation must preserve exact original cash, fees, ownership and sequence.
    def test_continuation_matches_single_calculation(self):
        original = run_case(3)
        left = run_case(2)
        book = InitialBook('2026-09-30',('AAA','SPY'),(left['stocks']['AAA']['latest_holding'],0.0),left['curve'][-1]['cash'],left['fees'],1,'a'*64)
        right = run_case(3,2,book)
        self.assertEqual(left['stocks']['AAA']['decisions']+right['stocks']['AAA']['decisions'],original['stocks']['AAA']['decisions'])
        self.assertEqual(right['curve'][-1],original['curve'][-1])
        self.assertEqual(right['fees'],original['fees'])
        self.assertEqual(right['provenance']['continuation_of_sha256'],'a'*64)

    # The existing terminal session cannot be replayed or a gap silently skipped.
    def test_wrong_boundary_refuses(self):
        book = InitialBook('2026-09-29',('AAA','SPY'),(0.0,0.0),1.0,0.0,0,'a'*64)
        with self.assertRaisesRegex(ValueError,'preceding session'):
            run_case(3,2,book)

    # Unauthenticated account-shaped dictionaries cannot seed the counterfactual book.
    def test_untyped_book_refuses(self):
        with self.assertRaisesRegex(ValueError,'Typed original'):
            run_case(3,2,{'cash':1.0,'holdings':{}})

    # Negative ownership or cash cannot become borrowing through a continuation.
    def test_negative_book_refuses(self):
        book = InitialBook('2026-09-30',('AAA','SPY'),(-.1,0.0),1.0,0.0,0,'a'*64)
        with self.assertRaisesRegex(ValueError,'original numerical book'):
            run_case(3,2,book)


# Run the bounded extension checks before any original market dataset is consumed.
if __name__ == '__main__':
    unittest.main()
