"""A fixed neural study must isolate fitting from every later observation."""

from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("torch")

from backend.cli import market_neural_price_study as study
from backend.market.growth_pilot import Dataset


# Build dated observations spanning the training boundary and examined period.
def observations():
    dates = np.busday_offset("2018-01-01", np.arange(2100))
    prices = np.exp(np.arange(len(dates))[:, None] * np.array([[0.001, 0.002]]))
    rng = np.random.default_rng(42)
    raw = rng.normal(size=(len(dates), 2, 18))
    raw[:, :, 8:] = np.nan
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, 1] = False
    data = Dataset(
        dates,
        prices,
        raw[:, :, :8],
        eligible,
        np.zeros((len(dates), 11)),
        ("ABC", "SPY"),
        1,
    )
    return data, raw


# Later prices and raw features cannot alter training labels or fitted normalization.
def test_future_data_cannot_change_fitting_inputs():
    data, raw = observations()
    original = study.training_inputs(data, raw)
    boundary = data.dates >= np.datetime64("2024-01-01")
    later_raw = raw.copy()
    later_raw[boundary, :, :8] += 10000
    later_prices = data.prices.copy()
    later_prices[boundary] *= 100
    changed = study.training_inputs(replace(data, prices=later_prices), later_raw)
    x, y, mask, normalization, endpoint = original
    np.testing.assert_array_equal(mask, changed[2])
    np.testing.assert_array_equal(x[mask], changed[0][mask])
    np.testing.assert_array_equal(y[mask], changed[1][mask])
    np.testing.assert_array_equal(normalization, changed[3])
    assert endpoint == changed[4]
    assert np.datetime64(endpoint) < np.datetime64("2024-01-01")
    last_decision = np.flatnonzero(mask.any(axis=1))[-1]
    assert endpoint == str(data.dates[last_decision + 21])
    assert not mask[boundary].any()
    assert not np.array_equal(x[boundary], changed[0][boundary])


# A file must match the predeclared trusted hash before the pickle loader sees it.
def test_untrusted_report_is_rejected_before_deserialization(tmp_path, monkeypatch):
    path = tmp_path / "report.pickle"
    path.write_bytes(b"not the declared artifact")
    calls = []
    monkeypatch.setattr(study.pickle, "load", lambda *args: calls.append(1))
    with pytest.raises(ValueError, match="predeclared trusted artifact"):
        study.load_report(path)
    assert not calls


# Removing a session must fail the exchange grid instead of shrinking the test window.
def test_missing_exchange_session_fails():
    pytest.importorskip("exchange_calendars")
    dates = np.array(["2025-01-02", "2025-01-06"], dtype="datetime64[D]")
    with pytest.raises(ValueError, match="Incomplete exchange grid"):
        study.verify_calendar(dates)
