"""Test causal label indexing and actual saved numeric regressor behavior."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from rule_relative_entry import fit_month, numeric_predict, targets, training_days


class RuleRelativeTest(unittest.TestCase):
    # A label compares now with the next crossing, never a crossing at the same clock.
    def test_future_crossing_and_sign(self):
        observed = np.full((1, 25, 1), 100.0)
        execution = observed.copy()
        observed[0, 3, 0] = 98
        execution[0, 3, 0] = 97
        execution[0, 24, 0] = 102
        result = targets(
            observed, execution, np.array([[100.0]]), np.ones_like(observed)
        )
        np.testing.assert_allclose(result[0, 0, 0], 0.03, atol=5e-8, rtol=0)
        np.testing.assert_allclose(result[0, 3, 0], -5 / 98, atol=5e-8, rtol=0)
        assert np.isnan(result[0, 24, 0])

    # An unavailable selected outcome cannot become a later favorable price.
    def test_missing_selected_price(self):
        observed = np.full((1, 25, 1), 100.0)
        execution = observed.copy()
        observed[0, 3, 0] = 98
        execution[0, 3, 0] = np.nan
        result = targets(
            observed, execution, np.array([[100.0]]), np.ones_like(observed)
        )
        assert np.isnan(result[0, 0, 0])

    # Monthly learning cannot consume fit-day or frozen-out outcomes.
    def test_monthly_maturity(self):
        dates = np.arange(np.datetime64("2024-01-01"), np.datetime64("2026-10-01"))
        first = int(np.flatnonzero(dates == np.datetime64("2026-09-01"))[0])
        days = training_days(dates, first)
        assert (dates[days] < np.datetime64("2026-08-17")).all()
        assert len(training_days(dates, 100)) == 0

    # A real fitted model and saved numeric trees agree on unseen and missing inputs.
    def test_numeric_model_readback(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(1000, 3))
        y = x[:, 0] ** 2 - x[:, 1]
        x[::7, 2] = np.nan
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.npz"
            model = fit_month(x, y, path)
            probe = rng.normal(size=(30, 3))
            probe[0, :] = np.nan
            with np.load(path, allow_pickle=False) as saved:
                trees = [saved[f"tree{i}"] for i in range(64)]
                np.testing.assert_allclose(
                    numeric_predict(trees, float(saved["baseline"]), probe),
                    model.predict(probe),
                    rtol=1e-12,
                    atol=1e-12,
                )


if __name__ == "__main__":
    unittest.main()
