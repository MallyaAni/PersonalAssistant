"""The macro layer: alignment, carry-forward, and shape."""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import macro
from backend.market.panel import panel_from_histories
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory


# A weekday-only history with the given closes.
def _history(ticker: str, first: date, closes: list[float]) -> TickerHistory:
    bars = []
    day = first
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bars.append(DailyBar(day, c, c, c, c, c, 1_000))
        day += timedelta(days=1)
    return TickerHistory(
        ticker, tuple(bars), (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# A series with a missing print is carried forward; before its first print
# it is NaN; the macro block has the documented width.
def test_macro_aligns_and_carries_forward(tmp_path):
    first = date(2025, 6, 2)
    panel = panel_from_histories(
        {
            "AAA": _history("AAA", first, [100.0] * 40),
            "SPY": _history("SPY", first, list(np.linspace(100, 110, 40))),
        },
        "SPY",
        {},
    )
    store = MarketStore(tmp_path)
    vix = _history("^VIX", first + timedelta(days=7), [15.0, 16.0, 17.0, 18.0, 19.0])
    store.write(date(2026, 1, 2), vix)
    aligned = macro.aligned_close(store, "^VIX", panel)
    dates = list(panel.dates.astype("datetime64[D]").astype(object))
    t0 = dates.index(vix.bars[0].session_date)
    assert np.isnan(aligned[:t0]).all()
    assert aligned[t0] == 15.0
    assert aligned[t0 + 4] == 19.0
    assert aligned[-1] == 19.0  # carried after the last print
    state = macro.macro_by_session(store, panel)
    assert state.shape == (40, macro.MACRO_COUNT)
    assert np.isfinite(state[-1, macro.MACRO_NAMES.index("vix_level")])
    assert np.isnan(state[-1, macro.MACRO_NAMES.index("tnx_level")])  # not stored
    per_name = macro.macro_features(store, panel)
    assert per_name.shape == (40, 2, macro.MACRO_COUNT)
