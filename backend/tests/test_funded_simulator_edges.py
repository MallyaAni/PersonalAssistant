"""Edge-case tests of the optional funded-allocation loop, from the real ledger.

These tests drive the actual `simulate.run` funded path on synthetic panels and
assert on the per-session `trace` it derives from the `_Book` ledger - never on
a copied or mock ledger - so the decision-at-t/fill-at-t+1 causality, the cash
conservation across fills, the missing-open versus missing-held-close handling
and its recovery, and the explicit company-removal input are all proven from
the journey the run actually makes.

The company-removal edge is the `excluded_symbols_by_session` map: a caller
names, by ISO decision date, the companies that genuinely left, and the shared
`funded_execution.exclude_names` removes them from the stable composition
before that day's decision. The removal persists across later sessions and the
next scheduled refresh - a fresh selection cannot resurrect a departed company
- while a missing grade or a risk cut is never an exit.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

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


# A panel with a separate open series where one is wanted; the final column is
# the SPY benchmark so the decision context's SPY always agrees with the panel.
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
def _report(close=None, tickers=None, open=None):
    """Return a desk report over a deterministic panel, with N0/N1 A+ and N2/N3 B."""
    if close is None:
        rng = np.random.default_rng(7)
        names = len(tickers) if tickers else 6
        steps = rng.normal(loc=0.0005, scale=0.01, size=(SESSIONS, names))
        close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    panel = _panel(close, tickers, open=open)
    rows, names = close.shape
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


# The vol-policy funded run shared by the tests.
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


# ---------------------------------------------------------------------------
# The actual journey: decision at t, fills at t+1, cash-conserving gaps.
# ---------------------------------------------------------------------------


# Every session's cash and equity reconcile against the fills the ledger
# actually made: closing cash is the opening cash moved by the net sale
# proceeds and the gross buy spend including fees, and the session's equity is
# exactly that cash plus the marked holdings at the close. No session can hide
# a disappearing dollar, and none of the arrays are copied from a plan.
def test_every_session_cash_and_equity_reconcile_with_the_actual_ledger():
    report = _report()
    result = _run(report)
    closes = report.panel.adj_close
    for t, entry in enumerate(result.trace):
        buy = sum(f["notional"] for f in entry["fills"].values() if f["side"] == "buy")
        sell = sum(
            f["notional"] for f in entry["fills"].values() if f["side"] == "sell"
        )
        expected = entry["cash_before"] + sell * (1 - COST) - buy * (1 + COST)
        assert entry["cash_after"] == pytest.approx(expected, rel=1e-9, abs=1e-12)
        assert entry["cash_after"] >= -1e-12
        held_value = sum(
            qty * float(closes[t + 1, report.panel.index(s)])
            for s, qty in entry["shares_after"].items()
        )
        if not entry["unavailable"]:
            assert result.equity[t + 1] == pytest.approx(
                entry["cash_after"] + held_value, rel=1e-9, abs=1e-12
            )


# Buys never spend the proceeds of the same session's sells: the funded book
# sizes a buy from the cash on hand at the fill, so a session that both sells
# and buys cannot pay for the buy with money the sell has not delivered.
def test_buys_never_spend_same_session_sale_proceeds():
    result = _run(_report())
    for entry in result.trace:
        buy_spend = sum(
            f["notional"] * (1 + COST)
            for f in entry["fills"].values()
            if f["side"] == "buy"
        )
        assert buy_spend <= entry["cash_before"] + 1e-9


# A decision is made on session t and filled at t+1's open: the trace's fill
# date is the next session, never the decision session, and every fill is at
# the opening price of that next session.
def test_decisions_fill_at_the_next_open():
    report = _report()
    result = _run(report)
    for t, entry in enumerate(result.trace):
        assert np.datetime64(entry["fill_date"]) > np.datetime64(entry["decision_date"])
        for symbol, fill in entry["fills"].items():
            open_price = float(report.panel.open[t + 1, report.panel.index(symbol)])
            assert fill["fill_price"] == pytest.approx(open_price, rel=1e-9)


# A missing opening price at the fill defers that leg without losing it: no
# delta, no fill and no shares move that session, and the name is bought once
# its open returns, still under the same cash-conserving book.
def test_missing_open_defers_the_fill_and_the_name_trades_later():
    report = _report()
    close = np.asarray(report.panel.adj_close, dtype=float)
    open_prices = close.copy()
    open_prices[61, 1] = np.nan  # N1 cannot be filled at session 61's open
    report.panel = _panel(close, open=open_prices)
    result = _run(report)
    entry = result.trace[60]
    assert "N1" in entry["desired"]
    assert "N1" not in entry["fills"]
    assert "N1" not in entry["deltas"]
    assert "N1" not in entry["shares_after"]
    first_held = next(
        t for t, e in enumerate(result.trace) if "N1" in e.get("shares_after", {})
    )
    assert first_held == 61
    held = result.trace[first_held]["shares_after"]["N1"]
    assert held > 0


# A held closing valuation that is missing marks that session's NAV and return
# unavailable, blocks the next decision, and on recovery rejects the fake
# recovery return: shares are retained throughout, sizing resumes, and the
# equity is real again while the return across the missing value stays NaN.
def test_missing_held_close_blocks_sizing_and_rejects_the_recovery_return():
    report = _report()
    close = np.asarray(report.panel.adj_close, dtype=float)
    close[62, 1] = np.nan
    open_prices = close.copy()
    open_prices[62, 1] = np.nan
    report.panel = _panel(close, open=open_prices)
    result = _run(report)
    held = result.trace[61]["shares_before"]["N1"]
    assert result.trace[61]["unavailable"] == ["N1"]
    assert result.trace[61]["shares_after"]["N1"] == pytest.approx(held, rel=1e-9)
    assert np.isnan(result.equity[62])
    assert np.isnan(result.returns[62])
    assert any(
        "held valuation unavailable for N1" in b for b in result.trace[62]["blocked"]
    )
    assert result.trace[62]["fills"] == {}
    assert result.trace[62]["shares_after"]["N1"] == pytest.approx(held, rel=1e-9)
    # The close returns at 63: no block, shares retained, equity real, but the
    # return across the dropped value stays NaN - no fake recovery is shown.
    assert result.trace[63]["blocked"] == []
    assert result.trace[63]["unavailable"] == []
    assert result.trace[63]["shares_after"]["N1"] == pytest.approx(held, rel=1e-9)
    assert not np.isnan(result.equity[63])
    assert np.isnan(result.returns[63])
    assert not np.isnan(result.returns[64])
    # A later rebalance still trades the recovered name normally.
    assert "N1" in result.trace[80]["deltas"]


# ---------------------------------------------------------------------------
# The explicit company-removal path.
# ---------------------------------------------------------------------------


# The map's default is None, and passing an empty map changes nothing: the
# funded trace is identical to the plain run.
def test_exclusion_map_default_and_empty_change_nothing():
    report = _report()
    plain = _run(report)
    empty = _run(report, excluded_symbols_by_session={})
    assert [e["excluded"] for e in plain.trace] == [e["excluded"] for e in empty.trace]
    assert [e["composition"] for e in plain.trace] == [
        e["composition"] for e in empty.trace
    ]
    assert all(e["excluded"] == [] for e in plain.trace)


# An explicit company exit is causal and persistent: the name leaves the stable
# composition on the named decision date and every session after, the held
# shares are sold that same day, and the trace records the running exclusion.
def test_explicit_exclusion_removes_the_company_causally():
    report = _report()
    day = str(report.panel.dates[70])
    result = _run(report, excluded_symbols_by_session={day: {"N1"}})
    assert "N1" in result.trace[69]["composition"]
    assert "N1" not in result.trace[70]["composition"]
    assert result.trace[70]["excluded"] == ["N1"]
    held = result.trace[70]["shares_before"]["N1"]
    assert result.trace[70]["deltas"]["N1"] == pytest.approx(-held, rel=1e-9)
    assert result.trace[70]["fills"]["N1"]["side"] == "sell"
    for t in range(71, len(result.trace)):
        assert "N1" not in result.trace[t]["composition"]
        assert result.trace[t]["excluded"] == ["N1"]


# Explicit exits still liquidate when benchmark history is temporarily missing.
def test_exclusion_exits_despite_missing_policy_evidence():
    report = _report()
    benchmarks = _benchmarks(report.panel)
    benchmarks["QQQ"][70] = np.nan
    result = _run(
        report,
        benchmark_prices=benchmarks,
        excluded_symbols_by_session={str(report.panel.dates[70]): {"N1"}},
    )
    row = result.trace[70]
    assert row["shares_before"]["N1"] > 0
    assert row["deltas"]["N1"] == pytest.approx(-row["shares_before"]["N1"])
    assert row["fills"]["N1"]["side"] == "sell"


# The removal persists through a scheduled refresh: a company excluded before a
# rebalance does not reappear in the freshly selected composition even though
# its grade is still strong enough to have been selected again.
def test_exclusion_persists_across_the_rebalance_refresh():
    report = _report()
    day = str(report.panel.dates[70])  # 70 is within the 60..79 interval
    result = _run(report, excluded_symbols_by_session={day: {"N1"}})
    # A rebalance at 80 recomputes the selection, and N1's grade is unchanged,
    # but the exclusion keeps it out of the refreshed composition.
    assert "N1" not in result.trace[70]["composition"]
    assert "N1" not in result.trace[80]["composition"]
    assert "N1" not in result.trace[100]["composition"]
    assert result.trace[80]["excluded"] == ["N1"]


# A risk cut is not an exit: the event cap scales the same names and restores
# them when it lifts, so a cut name re-enters, while an explicitly excluded
# company stays out - the two removals do not blur into each other.
def test_risk_cut_reentry_is_not_blocked_by_the_exclusion_path():
    report = _report()
    event = np.ones(SESSIONS)
    event[65:80] = 0.2
    day = str(report.panel.dates[70])
    result = _run(
        report,
        event_exposure=event,
        excluded_symbols_by_session={day: {"N1"}},
    )
    # N0 is risk-cut (not excluded) and re-enters when the cap lifts.
    assert "N0" in result.trace[70]["composition"]
    assert result.trace[70]["binding"] == "event cap"
    assert result.trace[70]["desired"]["N0"] < result.trace[80]["desired"]["N0"]
    # N1 is excluded and stays out.
    assert "N1" not in result.trace[80]["composition"]
    assert "N1" not in result.trace[90]["composition"]


# A missing grade on an ordinary day is never a company exit: the exclusion
# list is driven only by the caller's explicit map, so only the named company
# is recorded even when another name's score is missing.
def test_missing_grade_is_never_recorded_as_a_company_exit():
    report = _report()
    scores = report.scores.copy()
    scores[70, 1] = np.nan
    report.scores = scores
    day = str(report.panel.dates[70])
    result = _run(report, excluded_symbols_by_session={day: {"N0"}})
    assert result.trace[70]["excluded"] == ["N0"]
    assert "N1" not in result.trace[70]["excluded"]
    assert "N1" in result.trace[70]["composition"]


# The explicit map is validated: a key that is not an ISO date is a caller
# error, because a silently ignored date would leave a company exit unapplied.
def test_non_iso_exclusion_date_is_a_caller_error():
    report = _report()
    with pytest.raises(ValueError, match="must be ISO dates"):
        _run(report, excluded_symbols_by_session={"not-a-date": {"N1"}})
    with pytest.raises(ValueError, match="must be a mapping"):
        _run(report, excluded_symbols_by_session=["2024-03-01"])


# ---------------------------------------------------------------------------
# The default path is untouched by the new input.
# ---------------------------------------------------------------------------


# The incumbent (non-funded) path never reads the new argument: a run with
# `excluded_symbols_by_session` set is identical to one without it.
def test_incumbent_path_is_unchanged_by_the_new_parameter():
    report = _report()
    plain = simulate.run(report, config=CONFIG)
    with_map = simulate.run(
        report,
        config=CONFIG,
        excluded_symbols_by_session={str(report.panel.dates[70]): {"N1"}},
    )
    assert np.array_equal(plain.returns, with_map.returns, equal_nan=True)
    assert np.array_equal(plain.equity, with_map.equity, equal_nan=True)
    assert plain.traded == with_map.traded
    assert plain.rebalances == with_map.rebalances
    assert len(plain.trades) == len(with_map.trades)
