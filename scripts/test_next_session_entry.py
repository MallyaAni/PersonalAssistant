"""Pin next-session label maturity and the absence of missing-price substitution."""

import unittest

import numpy as np

from next_session_entry import labels, mature_days


class NextSessionEntryTests(unittest.TestCase):
    # Require both current and future execution prices for a comparable outcome.
    def test_missing_prices_stay_missing(self):
        prices = np.array([100., 98., np.nan, 104.])[:, None, None]
        observed = np.full_like(prices, 100.)
        result = labels(prices, observed, np.full_like(prices, .02))
        self.assertEqual(result[0, 0, 0], 1)
        self.assertTrue(np.isnan(result[1:]).all())

    # Prove every next-session label is complete before monthly publication or freeze.
    def test_training_maturity(self):
        dates = np.arange("2023-01-01", "2026-10-01", dtype="datetime64[D]")
        for first in (800, len(dates) - 1):
            days = mature_days(dates, first)
            self.assertTrue(np.all(dates[days + 1] < dates[first]))
            self.assertTrue(np.all(dates[days + 1] < np.datetime64("2026-08-17")))
            self.assertGreaterEqual(len(days), 504)


if __name__ == "__main__":
    unittest.main()
