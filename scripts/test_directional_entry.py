"""Prove advance and defer interventions cannot change the other direction."""

import unittest

import numpy as np

from directional_entry import choose


class DirectionalEntryTests(unittest.TestCase):
    # Isolate crossing/noncrossing buys, unchanged sells, and unavailable forecasts.
    def test_each_direction_and_missing_forecast(self):
        opened = np.full(5, 100.)
        observed = np.array([100., 98., 101., 98., 100.])
        delta = np.array([1., 1., -1., 1., 1.])
        forecasts = np.array([[-1., 0.], [1., 0.], [1., 0.], [np.nan, 0.], [np.nan, 0.]])
        known = np.ones(5, dtype=bool)
        for mode, expected in (
            ("advance", [True, True, True, True, False]),
            ("defer", [False, False, True, True, False]),
        ):
            result = choose(mode, forecasts, opened, observed, delta, known, known,
                            False, {"waiting_decisions": 0, "opening_unavailable": 0})
            np.testing.assert_array_equal(result, expected)

    # Retain the original session's terminal attempt under both interventions.
    def test_terminal_unchanged(self):
        for mode in ("advance", "defer"):
            result = choose(mode, np.full((2, 2), np.nan), np.full(2, 100.),
                            np.full(2, 100.), np.array([1., -1.]),
                            np.ones(2, dtype=bool), np.ones(2, dtype=bool), True, {})
            np.testing.assert_array_equal(result, True)


if __name__ == "__main__":
    unittest.main()
