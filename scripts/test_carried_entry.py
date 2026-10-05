"""Exercise carried intent lifetimes through the actual funded account engine."""

import unittest
from types import SimpleNamespace

import numpy as np

from carried_entry import account


# Construct known prices with one qualifying stock and no implicit later entry.
def fixture():
    days = 24
    close = np.full((days, 2), 100.0)
    panel = SimpleNamespace(tickers=["AAA", "SPY"], adj_close=close,
                            dates=np.arange("2020-01-01", "2020-01-25",
                                            dtype="datetime64[D]"))
    grades = np.full((days, 2), 3)
    eligible = np.ones((days, 2), dtype=bool)
    observed = np.full((days, 25, 2), 100.0)
    dataset = {"dates": panel.dates, "current_close": observed,
               "next_open": observed.copy()}
    return panel, grades, eligible, dataset, close.copy(), np.ones(days, dtype=bool)


class CarriedEntryTests(unittest.TestCase):
    # Prove a missed first-day dip survives and executes on the next day's known bar.
    def test_carry_fills_next_session(self):
        panel, grades, eligible, data, opens, support = fixture()
        data["current_close"][2, 0, 0] = 98
        data["next_open"][2, 0, 0] = 97
        result = account(panel, grades, eligible, data, opens, 1, 0, support, True)
        trace = result["intent_trace"][0]
        self.assertEqual(trace["date"], str(panel.dates[1]))
        self.assertEqual(trace["attempt_date"], str(panel.dates[2]))
        self.assertEqual(trace["realized_price"], 97)
        self.assertAlmostEqual(result["cash"][2], 1 - .0025 * 97)
        self.assertEqual(result["cash"][1], 1)

    # Prove the control still buys at the first plan's terminal bar.
    def test_control_keeps_same_day_deadline(self):
        panel, grades, eligible, data, opens, support = fixture()
        result = account(panel, grades, eligible, data, opens, 1, 0, support, False)
        trace = result["intent_trace"][0]
        self.assertEqual(trace["attempt_date"], str(panel.dates[1]))
        self.assertEqual(trace["attempt_clock"], 24)
        self.assertAlmostEqual(result["cash"][1], .75)

    # Prove a superseding plan cancels an old buy rather than permitting a late fill.
    def test_replaced_plan_cancels_pending_buy(self):
        panel, grades, eligible, data, opens, support = fixture()
        grades[20:] = 0
        data["current_close"][21:, :, 0] = 98
        result = account(panel, grades, eligible, data, opens, 1, 0, support, True)
        self.assertEqual(result["counts"]["fills"], 0)
        self.assertEqual(result["counts"]["expired_unfilled"], 1)
        np.testing.assert_array_equal(result["nav"], 1)

    # Prove unavailable future execution changes a fill but not its locked decision.
    def test_future_price_does_not_choose_attempt(self):
        panel, grades, eligible, data, opens, support = fixture()
        data["current_close"][2, 0, 0] = 98
        data["next_open"][2, 0, 0] = np.nan
        result = account(panel, grades, eligible, data, opens, 1, 0, support, True)
        trace = result["intent_trace"][0]
        self.assertEqual(trace["attempt_date"], str(panel.dates[2]))
        self.assertIsNone(trace["realized_price"])
        self.assertEqual(trace["filled_delta"], 0)
        self.assertEqual(result["counts"]["missing_execution"], 1)


if __name__ == "__main__":
    unittest.main()
