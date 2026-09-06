"""Entry triggers and the trade-by-trade backtest."""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import backtest, entry, grading, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE


# A two-name panel plus SPY from close paths; opens equal the prior close.
def _panel(closes: np.ndarray) -> Panel:
    t, n = closes.shape
    full = np.concatenate([closes, np.full((t, 1), 100.0)], axis=1)
    opens = np.vstack([full[:1], full[:-1]])
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    return Panel(
        dates=dates,
        tickers=("N0", "N1", "SPY"),
        open=opens,
        high=np.maximum(opens, full) * 1.005,
        low=np.minimum(opens, full) * 0.995,
        close=full,
        adj_close=full,
        volume=np.full_like(full, 1e6),
        themes={"N0": (AI_COMPUTE,), "N1": (AI_COMPUTE,)},
        benchmark="SPY",
    )


def _report(panel: Panel, grades: np.ndarray) -> DeskReport:
    t, n = grades.shape
    state = regime.RegimeState(0, 0, 0.9, 0, 0, 0, "ai", 0.1, 0, 1.0, 1.0, ())
    view = regime.RegimeView(
        [state] * t, Opinion("rotation", np.full((t, n), np.nan)), np.zeros(t)
    )
    graded = grading.Graded(grades, grades.astype(float), {})
    return DeskReport(
        panel, {"N0": "ai", "N1": "ai"}, {}, view, graded, grades.astype(float), []
    )


# A dip fires when price is stretched below its 21-day EMA; a breakout when
# price sits at the top of its range with both trends up.
def test_entry_triggers():
    t = 300
    n0 = 100.0 * np.exp(np.cumsum(np.full(t, 0.003)))  # steady climb: breakout
    n1 = np.full(t, 100.0)
    n1[-1] = 85.0  # sudden 15% drop: dip
    panel = _panel(np.stack([n0, n1], axis=1))
    e = entry.entries(panel)
    assert e.breakout[-1, 0]
    assert not e.dip[-1, 0]
    assert e.dip[-1, 1]
    assert e.kind(t - 1, 1) == entry.DIP


# The backtest enters at the next open after an A grade with a trigger,
# exits on a support break at the next open, and pays costs both ways.
def test_backtest_enters_next_open_and_stops():
    t = 260
    n0 = np.full(t, 100.0)
    n0[200] = 85.0  # dip trigger on session 200
    n0[201:230] = 90.0  # recovers a little
    n0[230:] = 60.0  # then breaks every level
    n1 = np.full(t, 100.0)
    panel = _panel(np.stack([n0, n1], axis=1))
    grades = np.zeros((t, 3), dtype=int)
    grades[150:, 0] = grading.ORDINAL["A"]
    report = _report(panel, grades)
    e = entry.entries(panel)
    bt = backtest.run_name(report, e, "N0", backtest.Rules(stop=True, cost_bps=0.0))
    # The stop exits, then the dip re-triggers while the grade holds: two trades.
    assert len(bt.trades) == 2
    trade = bt.trades[0]
    assert trade.entry_date == panel.dates[201]
    assert trade.entry_kind == entry.DIP
    assert trade.exit_reason == "stop"
    assert trade.exit_date == panel.dates[231]
    assert trade.log_return == pytest.approx(np.log(60.0 / 85.0))  # entered at 85
    assert trade.size == pytest.approx(grading.SIZE_MULTIPLIER["A"])
    no_stop = backtest.run_name(
        report, e, "N0", backtest.Rules(stop=False, cost_bps=0.0)
    )
    assert no_stop.trades[0].exit_reason == "open"
