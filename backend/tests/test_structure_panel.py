"""The board's structure definitions on a panel agree with the board's own.

What has to hold (docs/research/structure-rules-plan-2026-09-30.md, "the
level definitions are shared with the board's `structure.py`, so the study
and the display cannot disagree"):

- `ema21` is `structure.ema_levels` read at every session: the same
  recursion, NaN until 21 closes have been seen, a NaN close skipped.
- `ema_falling` is `structure.ema_slope < 0`.
- `high20` is `structure.high_20` wherever the window is full.
- `buy_level` is the nearer of the two levels above the close, or none.
- `first_bar_tag` is `structure.tag_for` on the first bar: a tag needs the
  prior close under the level and the bar's high within TAG_BAND of it; a
  rejection is a tag whose bar closed back under.
- `lower_highs` is three falling highs, or `structure.consecutive_sessions`
  reaching three at the session's level.
- `notch_mask` is the conjunction, and never fires on a young name.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import structure
from backend.agents.trading.desk import structure_panel as sp
from backend.market.yahoo import DailyBar

SESSIONS = 80


# `n` weekday dates from 2025-01-06.
def _days(n: int) -> list[date]:
    out, day = [], date(2025, 1, 6)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


# A random daily history: closes with a drift, highs above them.
def _history(seed: int = 0, n: int = SESSIONS):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(rng.normal(-0.002, 0.02, size=n).cumsum())
    high = close * (1.0 + np.abs(rng.normal(0, 0.01, size=n)))
    return close, high


# The board's DailyBar list for the sessions through row t (inclusive).
def _bars(close: np.ndarray, high: np.ndarray, through: int) -> list[DailyBar]:
    days = _days(len(close))
    return [
        DailyBar(
            session_date=days[i],
            open=float(close[i]),
            high=float(high[i]),
            low=float(close[i]),
            close=float(close[i]),
            adjusted_close=float(close[i]),
            volume=1_000,
        )
        for i in range(through + 1)
    ]


# The EMA at every session is the board's `ema_levels` on the bars through
# that session; NaN before 21 closes; a NaN close is skipped, not carried.
def test_ema21_is_the_boards_ema_levels_at_every_session():
    close, high = _history()
    ema = sp.ema21(close)
    for t in range(SESSIONS):
        board, _ = structure.ema_levels(_bars(close, high, t))
        if board is None:
            assert math.isnan(ema[t])
        else:
            assert ema[t] == pytest.approx(board)
    holed = close.copy()
    holed[30] = np.nan
    with_hole = sp.ema21(holed)
    assert math.isnan(with_hole[30])
    finite = [float(v) for v in holed if np.isfinite(v)]
    assert with_hole[31] == pytest.approx(structure.ema(finite, 21)[30])
    # Two columns are two independent names.
    two = sp.ema21(np.stack([close, close * 2.0], axis=1))
    np.testing.assert_allclose(two[:, 0], ema, equal_nan=True)
    np.testing.assert_allclose(two[:, 1], ema * 2.0, equal_nan=True)


# Falling is the board's slope below zero, session by session.
def test_ema_falling_is_the_boards_slope_sign():
    close, high = _history(seed=3)
    ema = sp.ema21(close)
    falling = sp.ema_falling(ema)
    for t in range(SESSIONS):
        series = [float(v) for v in ema[: t + 1] if np.isfinite(v)]
        slope = structure.ema_slope(series) if series else None
        assert falling[t] == bool(slope is not None and slope < 0), t
    assert falling.any()
    assert not falling.all()
    assert not falling[:25].any()


# The rolling high is the board's `high_20` wherever the window is full,
# and NaN before it is.
def test_high20_is_the_boards_high_20_on_a_full_window():
    close, high = _history(seed=5)
    h20 = sp.high20(high)
    assert np.isnan(h20[:19]).all()
    for t in range(19, SESSIONS):
        assert h20[t] == pytest.approx(structure.high_20(_bars(close, high, t)))
    holed = high.copy()
    holed[40] = np.nan
    assert np.isnan(sp.high20(holed)[40:60]).all()
    assert np.isfinite(sp.high20(holed)[60])


# The level is the nearer of the two above the close; a level at or under
# the close is not one; none leaves NaN.
def test_buy_level_is_the_nearer_level_above_the_close():
    close = np.array([100.0, 100.0, 100.0, 100.0, np.nan])
    ema = np.array([101.0, 99.0, 103.0, np.nan, 101.0])
    h20 = np.array([104.0, 100.0, 102.0, np.nan, 102.0])
    level = sp.buy_level(close, ema, h20)
    np.testing.assert_allclose(level, [101.0, np.nan, 102.0, np.nan, np.nan])


# The vectorised tag is `structure.tag_for` on every row: a tag needs the
# prior close under the level and a bar high within the band; a rejection
# is a tag whose close is back under.
def test_first_bar_tag_is_the_boards_tag_for():
    rng = np.random.default_rng(7)
    n = 400
    level = np.where(rng.random(n) < 0.1, np.nan, 100.0)
    close_t = 100.0 * (1.0 + rng.normal(0, 0.01, size=n))
    bar_high = 100.0 * (1.0 + rng.normal(0, 0.006, size=n))
    bar_close = bar_high * (1.0 - np.abs(rng.normal(0, 0.006, size=n)))
    tagged, rejected = sp.first_bar_tag(level, close_t, bar_high, bar_close)
    for i in range(n):
        tag = structure.tag_for(
            "ema_21",
            None if np.isnan(level[i]) else float(level[i]),
            float(close_t[i]),
            {"high": float(bar_high[i]), "close": float(bar_close[i])},
            [],
        )
        assert tagged[i] == (tag is not None), i
        assert rejected[i] == bool(tag is not None and tag["rejected"]), i
    assert tagged.any()
    assert rejected.any()
    assert (tagged & ~rejected).any()
    # The band's edge: exactly L x (1 - TAG_BAND) tags; a hair under does not.
    edge = 100.0 * (1.0 - structure.TAG_BAND)
    t2, r2 = sp.first_bar_tag(
        [100.0, 100.0], [99.0, 99.0], [edge, edge * 0.9999], [99.5, 99.5]
    )
    assert t2.tolist() == [True, False]
    assert r2.tolist() == [True, False]


# Lower highs: three falling highs, or the board's consecutive sessions at
# the level reaching three (today counted); a close over the level breaks
# the run, as does a high away from it.
def test_lower_highs_are_three_falling_highs_or_three_sessions_at_the_level():
    high = np.array([90.0, 89.0, 88.0, 91.0, 99.5, 100.4, 99.2, 99.3, 100.6, 99.1])
    close = np.array([89.0, 88.0, 87.0, 90.0, 98.0, 99.0, 98.5, 98.6, 100.5, 98.5])
    level = np.full(10, 100.0)
    out = sp.lower_highs(high, close, level)
    # t=2: 88 < 89 < 90 falling; t=3 not; t=6: three sessions at the level.
    assert out.tolist() == [
        False,
        False,
        True,
        False,
        False,
        False,
        True,
        True,
        False,
        False,
    ]
    for t in (6, 7):
        bars = _bars(close, high, t - 1)
        assert structure.consecutive_sessions(100.0, bars) >= 3
    assert structure.consecutive_sessions(100.0, _bars(close, high, 8)) < 3
    # No level: only the falling-highs branch can fire.
    none = sp.lower_highs(high, close, np.full(10, np.nan))
    assert none.tolist() == [False, False, True] + [False] * 7
    assert not sp.lower_highs(high[:2], close[:2], level[:2]).any()


# The notch is the conjunction of the three conditions, never fires on a
# young name, and clears when any condition clears.
def test_notch_mask_is_the_conjunction_and_never_on_a_young_name():
    n = 60
    close = np.full(n, 100.0)
    high = np.full(n, 100.5)
    # A slide from session 30: the close falls under a falling EMA with
    # falling highs.
    slide = 100.0 * np.exp(-0.01 * np.arange(1, n - 30 + 1))
    close[30:] = slide
    high[30:] = slide * 1.003
    mask = sp.notch_mask(close, high)
    ema = sp.ema21(close)
    assert not mask[:20].any()  # no EMA yet
    assert mask[40:].all()
    assert (close[40:] < ema[40:]).all()
    assert sp.ema_falling(ema)[40:].all()
    # Every notched cell satisfies each condition; and a young name (fewer
    # than 21 closes) is never notched however it trades.
    level = sp.buy_level(close, ema, sp.high20(high))
    conj = (close < ema) & sp.ema_falling(ema) & sp.lower_highs(high, close, level)
    assert np.array_equal(mask, conj)
    assert not sp.notch_mask(close[35:55], high[35:55]).any()
    # A recovery clears it: highs stop falling and the close crosses the EMA.
    recover = close.copy()
    recover[50:] = ema[49] * 1.05
    rh = high.copy()
    rh[50:] = recover[50:] * 1.01
    cleared = sp.notch_mask(recover, rh)
    assert cleared[45]
    assert not cleared[52:].any()
    # Two columns: each name is judged on its own.
    two = sp.notch_mask(
        np.stack([close, recover], axis=1), np.stack([high, rh], axis=1)
    )
    assert np.array_equal(two[:, 0], mask)
    assert np.array_equal(two[:, 1], cleared)
