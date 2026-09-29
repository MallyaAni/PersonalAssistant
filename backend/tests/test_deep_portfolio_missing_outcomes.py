"""Retain the legacy portfolio's future-outcome selection defect without retuning it."""

from dataclasses import replace

import numpy as np
import pytest

from backend.market import deep_intraday
from backend.tests.test_deep_intraday_portfolio import _dataset


# A missing realized return cannot replace an unchanged highest-ranked decision name.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Observed 2026-09-28: fixed top forecasts select N09/N08; changing only "
        "N09's realized return to NaN changes the reported portfolio to N08/N07 "
        "and reports +15% rather than preserving an unscorable selected position. "
        "Dataset row-causality repair does not repair this complete-case P&L."
    ),
)
def test_missing_selected_outcome_cannot_silently_substitute_another_name():
    opening = np.full((1, 10), 100.0)
    closing = opening.copy()
    closing[0, 7:] = [110.0, 120.0, 150.0]
    dataset = _dataset(opening, closing)
    forecasts = np.arange(10, dtype=float)
    complete = deep_intraday.top_quantile_portfolio(dataset, forecasts, 0.0)
    np.testing.assert_allclose(complete.portfolio_gross, [0.35])
    assert complete.names.tolist() == [10.0]

    observed = dataset.y_return.copy()
    observed[-1] = np.nan
    incomplete = replace(dataset, y_return=observed)
    np.testing.assert_array_equal(incomplete.x_seq, dataset.x_seq)
    np.testing.assert_array_equal(incomplete.x_scalar, dataset.x_scalar)

    # Either refuse the unpriceable account or retain its explicit missing outcome;
    # dropping its session or selecting a lower-ranked stock would hide the failure.
    try:
        result = deep_intraday.top_quantile_portfolio(incomplete, forecasts, 0.0)
    except ValueError:
        return
    np.testing.assert_array_equal(result.dates, complete.dates)
    assert np.isnan(result.portfolio_gross).all(), (
        "The selected N09 return is unavailable; finite P&L substitutes a stock "
        "using information absent from the fixed forecast decision"
    )
