"""The trader's toolkit: EMAs exact, causal, candles named, weekly carried."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.market import technical
from backend.market.panel import Panel, panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory


# A weekday-only history from explicit OHLC rows.
def _history(
    ticker: str, rows: list[tuple[float, float, float, float]]
) -> TickerHistory:
    bars = []
    day = date(2024, 1, 1)
    for o, h, low, c in rows:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(DailyBar(day, o, h, low, c, c, 1_000_000))
        day += timedelta(days=1)
    return TickerHistory(
        ticker, tuple(bars), (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# The EMA matches the textbook recursion and is NaN until `span` values exist.
def test_ema_is_exact_and_warms_up():
    values = np.arange(1.0, 13.0)[:, None]
    out = technical.ema(values, 3)
    assert np.isnan(out[:2, 0]).all()
    state = 1.0
    for x in values[1:, 0]:
        state = 0.5 * x + 0.5 * state
    assert abs(out[-1, 0] - state) < 1e-12
    assert abs(technical.sma(values, 4)[-1, 0] - np.mean([9, 10, 11, 12])) < 1e-12


# Features at session t do not change when later sessions change.
def test_features_are_causal():
    rng = np.random.default_rng(0)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 320)))
    rows = [(c * 0.995, c * 1.01, c * 0.985, c) for c in closes]
    panel = panel_from_histories(
        {"AAA": _history("AAA", rows), "SPY": _history("SPY", rows)}, "SPY", {}
    )
    before = technical.technical_features(panel)
    rows2 = rows[:300] + [(c * 3, c * 3.1, c * 2.9, c * 3) for _, _, _, c in rows[300:]]
    panel2 = panel_from_histories(
        {"AAA": _history("AAA", rows2), "SPY": _history("SPY", rows2)}, "SPY", {}
    )
    after = technical.technical_features(panel2)
    assert np.allclose(before[:299], after[:299], equal_nan=True)


# A hammer and a bullish engulfing bar are named on the sessions that show
# them, and the reversal net counts them.
def test_candles_are_named():
    flat = [(100.0, 100.5, 99.5, 100.0)] * 10
    hammer = (100.0, 100.4, 95.0, 100.2)  # long lower wick, small body
    down = (100.0, 100.5, 98.0, 98.5)  # a red bar
    engulf = (98.0, 101.5, 97.9, 101.0)  # green, engulfs the red bar
    rows = flat + [hammer] + [down, engulf] + flat
    panel = panel_from_histories(
        {"AAA": _history("AAA", rows), "SPY": _history("SPY", rows)}, "SPY", {}
    )
    feats = technical.technical_features(panel)
    names = technical.TECHNICAL_NAMES
    a = panel.index("AAA")
    assert feats[10, a, names.index("hammer")] == 1.0
    assert feats[12, a, names.index("bullish_engulfing")] == 1.0
    assert feats[11, a, names.index("bullish_engulfing")] == 0.0
    assert feats[12, a, names.index("reversal_net_3")] >= 1.0


# A converging flag fires when the spread is negative and rising.
def test_converging_flag():
    spread = np.array(
        [[-0.05], [-0.04], [-0.03], [-0.02], [0.05], [0.04], [0.03], [0.02]]
    )
    flags = technical._converging(spread, 3)
    assert np.isnan(flags[:3]).all()
    assert flags[3, 0] == 1.0  # below zero, rising
    assert flags[4, 0] == 0.0  # crossed above and still rising: neither
    assert flags[7, 0] == -1.0  # above zero, falling


# Weekly EMAs change only at week ends and carry between them.
def test_weekly_ema_is_carried_between_week_ends():
    rows = [(c, c, c, c) for c in np.linspace(100, 200, 120)]
    panel = panel_from_histories(
        {"AAA": _history("AAA", rows), "SPY": _history("SPY", rows)}, "SPY", {}
    )
    weekly = technical._weekly_ema(panel, panel.adj_close, 4)
    a = panel.index("AAA")
    dates = panel.dates.astype("datetime64[D]")
    weeks = (dates.astype(int) + 3) // 7  # Monday-to-Friday weeks
    changes = 0
    for t in range(1, len(dates)):
        if (
            np.isfinite(weekly[t, a])
            and np.isfinite(weekly[t - 1, a])
            and weekly[t, a] != weekly[t - 1, a]
        ):
            changes += 1
            # The weekly bar is known at a Friday close, or at the last
            # session of a week whose Friday is a holiday.
            friday = (dates.astype(int) + 3) % 7 == 4
            assert friday[t] or (t + 1 < len(dates) and weeks[t + 1] != weeks[t])
    assert changes >= 10


# The weekly EMA must not change when later sessions are removed: the last
# row of a panel is a forming week, not a closed one, so a mid-week session
# carries the last completed week's value both live and in a backtest.
def test_weekly_ema_does_not_change_when_the_future_is_removed():
    from dataclasses import replace as dc_replace

    from backend.market.technical import _weekly_ema

    rng = np.random.default_rng(7)
    days = 400  # enough weeks for a 21-week EMA to be defined
    # Business days only, the way a session panel is shaped.
    dates = np.busday_offset(
        np.datetime64("2026-01-01"), np.arange(days), roll="forward"
    ).astype("datetime64[D]")
    close = 100.0 * np.exp(np.cumsum(rng.normal(scale=0.01, size=(days, 1)), axis=0))
    panel = Panel(
        dates=dates,
        tickers=("AAA",),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={"AAA": ()},
        benchmark="AAA",
    )
    full = _weekly_ema(panel, close, 21)
    # Cut on a Wednesday, mid-week, and again on the following day.
    for stop in (380, 381, 382, 383, 384):
        short = dc_replace(
            panel,
            dates=dates[: stop + 1],
            open=close[: stop + 1],
            high=close[: stop + 1],
            low=close[: stop + 1],
            close=close[: stop + 1],
            adj_close=close[: stop + 1],
            volume=panel.volume[: stop + 1],
        )
        cut = _weekly_ema(short, close[: stop + 1], 21)
        assert np.isfinite(full[stop, 0])
        assert cut[stop, 0] == pytest.approx(full[stop, 0]), stop
