"""Numeric boundary regressions for the separate nested research runner."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.nested_allocation import (
    NestedProtocol,
    _inputs,
    _protocol,
    choose_mode,
)
from backend.market.nested_ridge import RegressionInputs


# Supply finite extended values that cannot survive the runner's float64 arithmetic.
def test_forecast_overflow_is_not_a_stock_signal():
    if np.finfo(np.longdouble).max <= np.finfo(float).max:
        pytest.skip("runtime has no wider floating-point range")
    forecasts = np.array([np.finfo(np.longdouble).max, 0, 0], dtype=np.longdouble)
    with pytest.raises(ValueError, match="remain finite"):
        choose_mode(forecasts, "cash", 0)


# Refuse distinct declared grid entries that become the same effective fitted value.
@pytest.mark.parametrize("field", ["alphas", "switch_margins"])
def test_candidate_grid_cannot_collapse_during_float64_conversion(field):
    values = (
        np.longdouble("1.000000000000000001"),
        np.longdouble("1.000000000000000002"),
    )
    if values[0] == values[1]:
        pytest.skip("runtime has no wider floating-point precision")
    with pytest.raises(ValueError, match="duplicate"):
        _protocol(NestedProtocol(**{field: values}), 1500)


# Reject a price that is finite in its source dtype but infinite in the owned grid.
def test_execution_price_cannot_overflow_silently():
    if np.finfo(np.longdouble).max <= np.finfo(float).max:
        pytest.skip("runtime has no wider floating-point range")
    dates = np.arange("2024-01-01", "2024-01-04", dtype="datetime64[D]")
    inputs = RegressionInputs(
        dates,
        np.ones((3, 1)),
        dates[:, None],
        np.ones((3, 3)),
        np.broadcast_to((dates + np.timedelta64(1, "D"))[:, None], (3, 3)),
        np.broadcast_to((dates + np.timedelta64(1, "D"))[:, None], (3, 3)),
    )
    prices = np.full((3, 3), 100, dtype=np.longdouble)
    prices[0, 0] = np.finfo(np.longdouble).max
    panel = SimpleNamespace(
        dates=dates,
        tickers=("A", "SPY", "QQQ"),
        open=prices,
        close=prices,
        adj_close=prices,
    )
    with pytest.raises(ValueError, match="float64"):
        _inputs(panel, inputs, np.zeros((3, 3)))
