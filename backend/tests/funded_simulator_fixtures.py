"""Shared synthetic inputs for the funded simulator's behavioral tests."""

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import simulate
from backend.agents.trading.desk.grading import Graded
from backend.agents.trading.desk.regime import RegimeState
from backend.market.panel import Panel
from backend.market.sizing import SizingConfig

SESSIONS = 140
CONFIG = SizingConfig(
    top_fraction=0.6, target_volatility=0.15, name_cap=0.15, theme_cap=0.4
)
COST = 10.0 / 1e4


# Build a deterministic panel with optional distinct opens and a trailing SPY column.
def _panel(close, tickers=None, open=None) -> Panel:
    """Return a Panel over `close` with SPY as the trailing benchmark column."""
    rows, names = close.shape
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(rows)],
        dtype="datetime64[D]",
    )
    if tickers is None:
        tickers = tuple(f"N{i}" for i in range(names - 1)) + ("SPY",)
    op = open if open is not None else close
    return Panel(
        dates=dates,
        tickers=tickers,
        open=op,
        high=op,
        low=op,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: () for t in tickers if t not in ("SPY", "QQQ")},
        benchmark="SPY",
    )


# A quiet regime state so the decisions are not cut by the regime itself.
def _state(exposure: float = 1.0) -> RegimeState:
    """Return a neutral regime state at the given exposure."""
    return RegimeState(
        ai_participation=0.5,
        software_participation=0.5,
        participation_percentile=0.5,
        ai_vs_software_correlation=0.0,
        correlation_z=0.0,
        novelty_z=0.0,
        rotation_leader="ai",
        rotation_spread=0.0,
        ai_drawdown=0.0,
        selection_confidence=1.0,
        exposure=exposure,
        flags=(),
        tightening=False,
    )


# A full desk report over a deterministic quiet panel, with the grades handed in
# per session so a rebalance can change them.
def _report(close=None, grades=None, tickers=None, open=None):
    """Return a desk report over a deterministic panel, with N0/N1 A+ and N2/N3 B."""
    if close is None:
        rng = np.random.default_rng(7)
        names = len(tickers) if tickers else 6
        steps = rng.normal(loc=0.0005, scale=0.01, size=(SESSIONS, names))
        close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    panel = _panel(close, tickers, open=open)
    rows, names = close.shape
    if grades is None:
        grades = np.zeros((rows, names), dtype=int)
        grades[:, 0] = 3  # N0 A+
        grades[:, 1] = 3  # N1 A+
        grades[:, 2] = 2  # N2 B
        grades[:, 3] = 2  # N3 B
    scores = grades.astype(float)
    graded = Graded(grades=grades, votes=scores.copy(), stances={})
    regime = SimpleNamespace(states=[_state()] * rows)
    return SimpleNamespace(
        panel=panel,
        graded=graded,
        scores=scores,
        regime=regime,
        sides={t: "ai" for t in panel.tickers if t not in ("SPY", "QQQ")},
        book=[],
    )


# The dated benchmark context for a panel, SPY taken from the panel itself so
# the context agreement check holds by construction.
def _benchmarks(panel) -> dict:
    """Return the dated SPY/QQQ context for `panel`, SPY matching the panel."""
    spy = np.asarray(panel.adj_close[:, panel.index("SPY")], dtype=float).copy()
    return {"dates": panel.dates, "SPY": spy, "QQQ": spy * 0.9}


# The vol-policy funded run shared by the trace tests.
def _run(report, **kwargs) -> simulate.SimResult:
    """Return the funded-allocation run over `report` with the test config."""
    options = {
        "config": CONFIG,
        "use_exits": False,
        "rebalance": 20,
        "funded_allocation": True,
        "allocation_policy": "vol",
        "index_eligible": False,
        "benchmark_prices": _benchmarks(report.panel),
    }
    options.update(kwargs)
    return simulate.run(report, **options)
