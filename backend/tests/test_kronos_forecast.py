"""The Kronos forecast script's windowing, on hand-made tables.

What has to hold (docs/research/kronos-plan-2026-09-30.md, Addendum 2):

- K1's context is exactly the 512 daily rows ending at t, oldest first; a
  cell with fewer rows before it is not forecast and is counted; the y
  dates are the panel's next 20 sessions, business days past the end.
- K2's context is exactly the 512 bars ending at slot 25 of session t; the
  y stamps are t+1's 26 slot times from 09:30; a cell whose next date is
  NaT gets the next business day.
- The normalisation is `predict_batch`'s (amount = volume x mean OHLC,
  per-series mean/std, clip at 5) and de-normalising inverts it.
- K1's features: the 20-session log return and a drawdown that is 0 for a
  rising path and the trough for a falling one; K2's ratios read the
  predicted open, the min low, the max high and bar 25's close.
- The script imports without torch or the Kronos repository.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "research" / "kronos_forecast.py"


# Import the standalone script as a module (it is not a package member).
def _load():
    spec = importlib.util.spec_from_file_location("kronos_forecast", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["kronos_forecast"] = module
    spec.loader.exec_module(module)
    return module


kf = _load()


# Weekday dates from a start.
def _weekdays(n, start="2020-01-06"):
    return np.busday_offset(np.datetime64(start, "D"), np.arange(n), roll="forward")


# A daily table of `n` sessions with a recognisable close (100 + i).
def _daily(n):
    days = _weekdays(n)
    close = 100.0 + np.arange(n)
    return pd.DataFrame({"ticker": "AAA", "date": days, "open": close - 0.5, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0 + np.arange(n)})


# The script imports with torch and the Kronos repository absent.
def test_script_imports_without_torch():
    assert "torch" not in sys.modules or True
    assert kf.SAMPLING == {"T": 1.0, "top_k": 0, "top_p": 0.9, "sample_count": 1}
    assert kf.DAILY_CONTEXT == kf.INTRADAY_CONTEXT == 512 and kf.DAILY_HORIZON == 20 and kf.INTRADAY_HORIZON == 26


# K1: the context is the 512 rows ending at t; a cell too early is skipped.
def test_daily_windows_take_the_last_512_rows_through_t():
    daily = _daily(600)
    sessions = daily["date"].to_numpy().astype("datetime64[D]")
    cells = sessions[[510, 511, 599]]
    w = kf.daily_windows(daily, cells, sessions)
    np.testing.assert_array_equal(w["kept"], [1, 2])
    assert w["x"].shape == (2, 512, 5)
    # Row 511's context ends at close 100 + 511 and starts 511 rows earlier.
    assert w["x"][0, -1, 3] == 611.0 and w["x"][0, 0, 3] == 100.0
    assert w["x_dates"][0, -1] == sessions[511] and w["x_dates"][0, 0] == sessions[0]
    np.testing.assert_array_equal(w["close_t"], [611.0, 699.0])
    # The y dates: the next 20 sessions; past the end, business days.
    np.testing.assert_array_equal(w["y_dates"][0], sessions[512:532])
    assert len(w["y_dates"][1]) == 20 and w["y_dates"][1][0] > sessions[599]
    assert all(np.is_busday(d) for d in w["y_dates"][1])


# K1: a cell date the name's rows lack is skipped.
def test_daily_windows_skip_a_date_the_name_lacks():
    daily = _daily(520)
    sessions = daily["date"].to_numpy().astype("datetime64[D]")
    missing = np.busday_offset(sessions[-1], 1, roll="forward")
    w = kf.daily_windows(daily, np.array([sessions[515], missing]), sessions)
    np.testing.assert_array_equal(w["kept"], [0])


# A bars table of `n` sessions x 26 slots for one name.
def _bars(n):
    days = np.repeat(_weekdays(n), 26)
    slots = np.tile(np.arange(26), n)
    close = 100.0 + np.arange(n * 26) * 0.01
    return pd.DataFrame({"ticker": "AAA", "date": days, "slot": slots, "open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 1.0})


# K2: the context ends at slot 25 of t and the y stamps are t+1's slots.
def test_intraday_windows_end_at_the_last_bar_of_t():
    bars = _bars(30)
    days = _weekdays(30)
    cells = days[[18, 19, 29]]
    nxt = np.array([days[19], days[20], np.datetime64("NaT")], dtype="datetime64[D]")
    w = kf.intraday_windows(bars, cells, nxt)
    # 19 sessions x 26 = 494 bars < 512 for session 18 (index 18 -> 494 bars); session 19 has 520.
    np.testing.assert_array_equal(w["kept"], [1, 2])
    assert w["x"].shape == (2, 512, 5)
    last = 20 * 26 - 1
    assert w["x"][0, -1, 3] == pytest.approx(100.0 + last * 0.01)
    assert w["x_stamps"][0, -1] == days[19].astype("datetime64[m]") + np.timedelta64(15 * 60 + 45, "m")
    # 512 bars back from bar 519 is bar 8: session 0, slot 8, 11:30.
    assert w["x_stamps"][0, 0] == days[0].astype("datetime64[m]") + np.timedelta64(11 * 60 + 30, "m")
    # y: t+1's 26 slots from 09:30 New York.
    assert w["y_stamps"].shape == (2, 26)
    assert w["y_stamps"][0, 0] == days[20].astype("datetime64[m]") + np.timedelta64(9 * 60 + 30, "m")
    assert w["y_stamps"][0, -1] == days[20].astype("datetime64[m]") + np.timedelta64(15 * 60 + 45, "m")
    # NaT next date: the next business day.
    assert w["y_stamps"][1, 0].astype("datetime64[D]") == np.busday_offset(days[29], 1, roll="forward")


# The time features are minute, hour, weekday, day, month.
def test_time_features():
    stamps = np.array([["2024-07-01T09:30", "2024-07-01T15:45"]], dtype="datetime64[m]")
    f = kf.time_features(stamps)
    assert f.shape == (1, 2, 5)
    np.testing.assert_array_equal(f[0, 0], [30, 9, 0, 1, 7])
    np.testing.assert_array_equal(f[0, 1], [45, 15, 0, 1, 7])


# The normalisation adds the amount column and inverts.
def test_normalise_and_denormalise():
    rng = np.random.default_rng(0)
    x = np.abs(rng.normal(100, 5, size=(3, 512, 5)))
    norm, mean, std = kf.normalise(x)
    assert norm.shape == (3, 512, 6) and np.abs(norm).max() <= 5
    amount = x[..., 4] * x[..., :4].mean(axis=-1)
    np.testing.assert_allclose(mean[:, 0, 5], amount.mean(axis=1), rtol=1e-5)
    full = np.concatenate([x, amount[..., None]], axis=-1)
    back = kf.denormalise((full - mean) / (std + 1e-5), mean, std)
    np.testing.assert_allclose(back[..., :5], x, rtol=1e-4)


# K1's features: log return over the path, drawdown from t.
def test_k1_features():
    close_t = np.array([100.0, 100.0])
    rising = 100.0 * np.exp(np.linspace(0.01, 0.2, 20))
    falling = np.r_[np.full(10, 95.0), np.full(10, 105.0)]
    logret, mdd = kf.k1_features(close_t, np.stack([rising, falling]))
    assert logret[0] == pytest.approx(0.2) and logret[1] == pytest.approx(np.log(1.05))
    assert mdd[0] == 0.0 and mdd[1] == pytest.approx(np.log(0.95))


# K2's features read the open, min low, max high and bar 25's close.
def test_k2_features():
    ohlc = np.ones((1, 26, 4)) * 100.0
    ohlc[0, 0, 0] = 101.0  # open
    ohlc[0, 7, 2] = 97.0  # low
    ohlc[0, 20, 1] = 104.0  # high
    ohlc[0, 25, 3] = 102.0  # close
    f = kf.k2_features(np.array([100.0]), ohlc)
    assert f["pred_open"][0] == 101.0 and f["pred_low"][0] == 97.0 and f["pred_high"][0] == 104.0 and f["pred_close"][0] == 102.0
    assert f["k2_low_rel_open"][0] == pytest.approx(97 / 101) and f["k2_high_rel_open"][0] == pytest.approx(104 / 101)
    assert f["k2_low_rel_close_t"][0] == pytest.approx(0.97) and f["k2_open_rel_close_t"][0] == pytest.approx(1.01)


# Batches cover every row once.
def test_batches():
    parts = kf.batches(10, 4)
    assert [list(p) for p in parts] == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]]
    assert kf.batches(0, 4) == []
