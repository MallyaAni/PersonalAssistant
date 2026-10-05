"""Verify each timing intervention against the original selectors."""

import unittest

import numpy as np

from run_timing_side_ablation import select_side


# Supply separate counters because each selector records its own unavailable actions.
def counters():
    return dict(waiting_decisions=0, forecast_unavailable=0, opening_unavailable=0)


class SideSelectorTest(unittest.TestCase):
    # Learned buys may act without a dip while sells retain the original pop gate.
    def test_buy_only(self):
        result = select_side("buy", np.zeros((2, 2)), np.array([100., 100.]),
                             np.array([100., 100.]), np.array([1., -1.]),
                             np.ones(2, bool), np.ones(2, bool), False, counters())
        np.testing.assert_array_equal(result, [True, False])

    # Learned sells may act without a pop while buys retain the original dip gate.
    def test_sell_only(self):
        result = select_side("sell", np.zeros((2, 2)), np.array([100., 100.]),
                             np.array([100., 100.]), np.array([1., -1.]),
                             np.ones(2, bool), np.ones(2, bool), False, counters())
        np.testing.assert_array_equal(result, [False, True])

    # Missing learned forecasts wait before the shared deadline and act at it.
    def test_missing_and_deadline(self):
        args = ("buy", np.full((2, 2), np.nan), np.array([100., 100.]),
                np.array([98., 102.]), np.array([1., -1.]),
                np.ones(2, bool), np.ones(2, bool))
        np.testing.assert_array_equal(select_side(*args, False, counters()), [False, True])
        np.testing.assert_array_equal(select_side(*args, True, counters()), [True, True])

    # Missing observations and completed intents remain inactive even at the deadline.
    def test_no_unobserved_or_completed_actions(self):
        result = select_side("buy", np.zeros((2, 2)), np.ones(2), np.ones(2),
                             np.array([1., -1.]), np.array([False, True]),
                             np.array([True, False]), True, counters())
        np.testing.assert_array_equal(result, [False, False])


if __name__ == "__main__":
    unittest.main()
