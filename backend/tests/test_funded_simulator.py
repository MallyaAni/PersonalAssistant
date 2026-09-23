"""The funded-allocation simulator corrections, on the real run and ledger.

The shared allocation path (`simulate.run` with `funded_allocation=True`) must
keep a stable unscaled stock composition that refreshes only on its scheduled
rebalance, consume a dated causal benchmark context rather than one aligned by
length, and report a complete actual execution trace. These tests drive the
real `simulate.run` and `funded_execution.daily_decision` on synthetic panels -
never patched call counts - so a future reworded prompt or reshaped order
basket cannot silently change the behavior the milestone claims.
"""

import numpy as np
import pytest

from backend.agents.trading.desk import funded_execution
from backend.agents.trading.desk.allocation import AllocationDecision
from backend.agents.trading.desk.grading import Graded
from backend.market.panel import Panel
from backend.tests.funded_simulator_fixtures import (
    CONFIG,
    COST,
    SESSIONS,
    _benchmarks,
    _panel,
    _report,
    _run,
)

# ---------------------------------------------------------------------------
# Correction 1: stable scheduled supplied composition.
# ---------------------------------------------------------------------------


# The supplied composition is consumed as-is: a name absent from it is not
# bought however strong its grade in the report.
def test_daily_decision_consumes_the_supplied_composition():
    report = _report()
    price_map = {
        s: float(report.panel.adj_close[60, j])
        for j, s in enumerate(report.panel.tickers)
        if np.isfinite(report.panel.adj_close[60, j])
        and report.panel.adj_close[60, j] > 0
    }
    supplied = {"N0": 0.15, "N3": 0.15}
    daily = funded_execution.daily_decision(
        report,
        report.panel,
        CONFIG,
        60,
        policy="vol",
        index_eligible=False,
        benchmark_prices=_benchmarks(report.panel),
        desired=supplied,
        held={},
        prices=price_map,
        equity=1.0,
        regime_cap=1.0,
        event_cap=1.0,
    )
    # N1 is graded A+ and would be in the engine's own composition, but the
    # supplied composition omits it, so it is not desired and not bought.
    assert "N1" not in daily.decision.desired_weights
    assert set(daily.decision.desired_weights) <= set(supplied)


# The composition refreshes only on the scheduled rebalance clock: between two
# rebalances it is byte-identical even when the report's scores change, and it
# changes exactly at a rebalance when the grades change.
def test_composition_refreshes_only_on_the_scheduled_rebalance():
    report = _report()
    grades = report.graded.grades.copy()
    grades[80:, 1] = 0  # N1 leaves the graded set at the t=80 rebalance
    scores = grades.astype(float)
    report.graded = Graded(grades=grades, votes=scores.copy(), stances={})
    report.scores = scores
    scores[70, 1] = 99.0  # a strong score swing on an ordinary day
    result = _run(report)
    trace = result.trace
    # Sessions 60..79 are the same rebalance interval, so the composition is
    # identical across them even though scores changed at t=70.
    assert trace[60]["composition"] == trace[70]["composition"]
    assert trace[60]["composition"] == trace[79]["composition"]
    assert "N1" in trace[70]["composition"]
    # The t=80 rebalance sees the dropped grade and the composition changes.
    assert "N1" not in trace[80]["composition"]
    assert trace[80]["composition"] == trace[90]["composition"]


# Only the scheduled rebalances count: with rebalance=30 over 139 decision
# sessions the composition refreshes at 0, 30, 60, 90, 120 - five times - and
# never between them.
def test_rebalances_count_only_scheduled_refreshes():
    result = _run(_report(), rebalance=30)
    assert result.rebalances == 5


# A risk-only cut keeps the composition for re-entry: the stable composition is
# untouched while the desired exposure is scaled to the event cap and restored
# after it.
def test_risk_cut_retains_composition_and_reenters():
    report = _report()
    event = np.ones(SESSIONS)
    event[65:80] = 0.2
    result = _run(report, event_exposure=event)
    trace = result.trace
    assert trace[60]["composition"] == trace[70]["composition"]
    assert sum(trace[60]["desired"].values()) > 0.4
    assert sum(trace[70]["desired"].values()) == pytest.approx(0.2, abs=1e-6)
    assert trace[70]["binding"] == "event cap"
    assert sum(trace[80]["desired"].values()) > 0.4


# A missing score between rebalances is not a company exit: the name stays in
# the stable composition until the next scheduled refresh.
def test_missing_score_is_not_treated_as_a_company_exit():
    report = _report()
    scores = report.scores.copy()
    scores[70, 1] = np.nan
    report.scores = scores
    result = _run(report)
    assert "N1" in result.trace[70]["composition"]


# The shared explicit exit mechanism removes exactly the named companies and
# keeps the rest, so a genuine delisting can be reflected without touching any
# other name.
def test_exclude_names_removes_only_the_named_companies():
    composition = {"N0": 0.15, "N1": 0.15, "N3": 0.15}
    reduced = funded_execution.exclude_names(composition, {"N1"})
    assert reduced == {"N0": 0.15, "N3": 0.15}
    assert funded_execution.exclude_names(composition, ()) == composition


# ---------------------------------------------------------------------------
# Correction 2: explicitly dated causal benchmark context.
# ---------------------------------------------------------------------------


# A missing or malformed dates array is a caller error, and equal length is not
# alignment - the calendar must match the panel exactly.
def test_incorrect_benchmark_dates_are_a_caller_error():
    panel = _report().panel
    good = _benchmarks(panel)
    with pytest.raises(ValueError, match="must carry its own dates"):
        funded_execution.validate_benchmarks(
            panel, {"SPY": good["SPY"], "QQQ": good["QQQ"]}
        )
    shifted = np.array(panel.dates, copy=True)
    shifted[0] = shifted[0] - np.timedelta64(1, "D")
    with pytest.raises(ValueError, match="equal the panel calendar exactly"):
        funded_execution.validate_benchmarks(panel, {**good, "dates": shifted})
    short = good["dates"][:-1]
    with pytest.raises(ValueError, match="equal length is not alignment"):
        funded_execution.validate_benchmarks(panel, {**good, "dates": short})
    bad = np.full(len(panel.dates), np.datetime64("NaT", "D"), dtype="datetime64[D]")
    with pytest.raises(ValueError, match="must not contain NaT"):
        funded_execution.validate_benchmarks(panel, {**good, "dates": bad})


# A benchmark gap in the future does not reject earlier decisions: every
# decision through the gap is identical to the clean run.
def test_future_benchmark_gap_does_not_reject_earlier_decisions():
    report = _report()
    benchmarks = _benchmarks(report.panel)
    benchmarks["SPY"][-6:] = np.nan
    benchmarks["QQQ"][-6:] = np.nan
    clean = _run(report)
    gapped = _run(report, benchmark_prices=benchmarks)
    for t in range(0, len(clean.trace) - 6):
        assert clean.trace[t]["desired"] == gapped.trace[t]["desired"]


# Missing *current* benchmark history reaches the known-cap fallback: the
# decision is unavailable, actual holdings are retained and never fabricated
# from missing evidence.
def test_missing_current_benchmark_history_retains_holdings():
    report = _report()
    panel = report.panel
    benchmarks = _benchmarks(panel)
    benchmarks["SPY"][60:71] = np.nan
    benchmarks["QQQ"][60:71] = np.nan
    price_map = {
        s: float(panel.adj_close[70, j])
        for j, s in enumerate(panel.tickers)
        if np.isfinite(panel.adj_close[70, j]) and panel.adj_close[70, j] > 0
    }
    daily = funded_execution.daily_decision(
        report,
        panel,
        CONFIG,
        70,
        policy="vol",
        index_eligible=False,
        benchmark_prices=benchmarks,
        desired={"N0": 0.15, "N1": 0.15, "N3": 0.15},
        held={"N0": 0.10, "N1": 0.10, "N3": 0.10},
        prices=price_map,
        equity=100.0,
        regime_cap=1.0,
        event_cap=1.0,
    )
    assert daily.decision.available is False
    held_weight = {s: 0.10 * price_map[s] / 100.0 for s in ("N0", "N1", "N3")}
    for symbol, weight in held_weight.items():
        assert daily.decision.desired_weights[symbol] == pytest.approx(weight, rel=1e-6)
    assert any("SPY risk" in m or "QQQ risk" in m for m in daily.decision.missing)


# Changing or appending future rows cannot change an earlier decision: the
# decision at t reads only rows through t.
def test_changed_future_rows_do_not_change_an_earlier_decision():
    base = _report()
    close = np.asarray(base.panel.adj_close, dtype=float)
    altered = close.copy()
    altered[101:, 0] *= 2.0  # N0 doubles from session 101 onward
    other = _report(close=altered)

    def decision(report):
        panel = report.panel
        price_map = {
            s: float(panel.adj_close[60, j])
            for j, s in enumerate(panel.tickers)
            if np.isfinite(panel.adj_close[60, j]) and panel.adj_close[60, j] > 0
        }
        return funded_execution.daily_decision(
            report,
            panel,
            CONFIG,
            60,
            policy="vol",
            index_eligible=False,
            benchmark_prices=_benchmarks(panel),
            desired={"N0": 0.15, "N1": 0.15, "N3": 0.15},
            held={},
            prices=price_map,
            equity=1.0,
            regime_cap=1.0,
            event_cap=1.0,
        ).decision

    assert decision(base).desired_weights == decision(other).desired_weights


# A panel that already contains QQQ is legitimate: the benchmark QQQ column is
# used for risk, the panel column is never duplicated, and the frozen scores
# and grades are untouched.
def test_a_panel_already_containing_qqq_works():
    tickers = ("N0", "N1", "N2", "N3", "QQQ", "SPY")
    report = _report(tickers=tickers)
    frozen = report.graded.grades.copy()
    result = _run(report)
    assert result.rebalances > 0
    tickers_out, matrix = funded_execution._decision_inputs(
        report.panel, _benchmarks(report.panel)
    )
    assert len(tickers_out) == len(set(tickers_out))
    assert tickers_out.count("QQQ") == 1
    assert tickers_out.count("SPY") == 1
    assert matrix.shape[1] == len(tickers_out)
    np.testing.assert_array_equal(report.graded.grades, frozen)


# The SPY agreement check is causal: a conflict after the decision session is
# not seen, and a conflict through the decision session is reported as a caller
# error.
def test_spy_context_disagreement_is_reported_but_only_through_t():
    report = _report()
    panel = report.panel
    benchmarks = _benchmarks(panel)
    benchmarks["SPY"] = np.asarray(benchmarks["SPY"], dtype=float).copy()
    benchmarks["SPY"][10] = benchmarks["SPY"][10] * 1.2

    def decision(t):
        price_map = {
            s: float(panel.adj_close[t, j])
            for j, s in enumerate(panel.tickers)
            if np.isfinite(panel.adj_close[t, j]) and panel.adj_close[t, j] > 0
        }
        return funded_execution.daily_decision(
            report,
            panel,
            CONFIG,
            t,
            policy="vol",
            index_eligible=False,
            benchmark_prices=benchmarks,
            desired={"N0": 0.15, "N1": 0.15, "N3": 0.15},
            held={},
            prices=price_map,
            equity=1.0,
            regime_cap=1.0,
            event_cap=1.0,
        )

    # The conflict sits at row 10; a decision at t=5 must not see it.
    assert decision(5).decision is not None
    with pytest.raises(ValueError, match="disagrees with the panel"):
        decision(12)


# Execution respects the supplied index eligibility: a prebuilt decision may
# carry SPY, but it authorizes no new SPY buy when eligibility is false.
def test_execution_eligibility_blocks_new_spy_buys_only():
    decision = AllocationDecision(
        version="portfolio-allocation/vol_trend/1",
        as_of="2026-09-01",
        desired_weights={"SPY": 0.3},
        cash=0.7,
        available=True,
        reasons=("no risk reduction required",),
        missing=(),
        volatility=None,
        binding="none",
    )
    blocked = funded_execution.plan_funded(
        decision,
        held={},
        prices={"SPY": 100.0},
        equity=100.0,
        cash=100.0,
        whole_shares=False,
        index_eligible=False,
    )
    assert not any(o.symbol == "SPY" for o in blocked.orders)
    assert any("index not eligible" in m for m in blocked.missing)
    allowed = funded_execution.plan_funded(
        decision,
        held={},
        prices={"SPY": 100.0},
        equity=100.0,
        cash=100.0,
        whole_shares=False,
        index_eligible=True,
    )
    assert any(o.symbol == "SPY" and o.side == "buy" for o in allowed.orders)


# ---------------------------------------------------------------------------
# Correction 3: complete actual execution trace.
# ---------------------------------------------------------------------------


# A full exit is present in the deltas: when a rebalance drops a name from the
# composition, the trace records the entire sold quantity, not zero.
def test_trace_records_a_full_exit_delta():
    report = _report()
    grades = report.graded.grades.copy()
    grades[80:, 1] = 0
    scores = grades.astype(float)
    report.graded = Graded(grades=grades, votes=scores.copy(), stances={})
    report.scores = scores
    result = _run(report)
    entry = result.trace[80]
    assert "N1" in entry["shares_before"]
    assert entry["deltas"]["N1"] == pytest.approx(
        -entry["shares_before"]["N1"], rel=1e-9
    )
    assert entry["fills"]["N1"]["side"] == "sell"
    assert entry["fills"]["N1"]["qty"] == pytest.approx(
        entry["shares_before"]["N1"], rel=1e-9
    )


# The trace's cash and fees reconcile against the actual fills at the cost:
# closing cash is the opening cash plus net sale proceeds minus the gross buy
# spend, and the fee is the traded notional times the cost.
def test_trace_fees_and_cash_reconcile_with_actual_fills():
    result = _run(_report())
    entry = result.trace[60]
    sell_notional = sum(
        f["notional"] for f in entry["fills"].values() if f["side"] == "sell"
    )
    buy_notional = sum(
        f["notional"] for f in entry["fills"].values() if f["side"] == "buy"
    )
    expected = (
        entry["cash_before"] + sell_notional * (1 - COST) - buy_notional * (1 + COST)
    )
    assert entry["cash_after"] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert entry["fees"] == pytest.approx(entry["notional_traded"] * COST, rel=1e-9)
    assert any(f["side"] == "buy" for f in entry["fills"].values())


# The fills are derived from actual ledger changes, not the proposed orders: a
# name the plan wanted to buy but could not fill (a missing opening price)
# leaves no fill record and no delta.
def test_fills_are_actual_ledger_changes_not_proposed_orders():
    report = _report()
    close = np.asarray(report.panel.adj_close, dtype=float)
    open_prices = close.copy()
    open_prices[61, 1] = np.nan  # N1 cannot be filled at session 61's open
    report.panel = Panel(
        dates=report.panel.dates,
        tickers=report.panel.tickers,
        open=open_prices,
        high=open_prices,
        low=open_prices,
        close=close,
        adj_close=close,
        volume=report.panel.volume,
        themes=report.panel.themes,
        benchmark="SPY",
    )
    result = _run(report)
    entry = result.trace[60]
    assert "N1" in entry["desired"]
    assert "N1" not in entry["fills"]
    assert "N1" not in entry["deltas"]


# A held position whose closing valuation is missing makes that session's NAV
# and return unavailable rather than a fake loss; shares and cash are retained.
def test_missing_held_valuation_marks_nav_unavailable_and_retains_shares():
    report = _report()
    close = np.asarray(report.panel.adj_close, dtype=float)
    close[62, 1] = np.nan  # N1 has no closing valuation at session 62
    report.panel = _panel(close)
    result = _run(report)
    entry = result.trace[61]
    assert entry["unavailable"] == ["N1"]
    assert np.isnan(result.equity[62])
    assert np.isnan(result.returns[62])
    assert entry["shares_after"]["N1"] == pytest.approx(
        entry["shares_before"]["N1"], rel=1e-9
    )


# When a held position cannot be valued at the decision close, sizing is
# blocked: no orders are planned, no shares move, and the block is recorded.
def test_blocked_held_valuation_defers_sizing():
    report = _report()
    close = np.asarray(report.panel.adj_close, dtype=float)
    close[70, 1] = np.nan
    open_prices = close.copy()
    open_prices[70, 1] = np.nan
    report.panel = Panel(
        dates=report.panel.dates,
        tickers=report.panel.tickers,
        open=open_prices,
        high=open_prices,
        low=open_prices,
        close=close,
        adj_close=close,
        volume=report.panel.volume,
        themes=report.panel.themes,
        benchmark="SPY",
    )
    result = _run(report)
    entry = result.trace[70]
    assert any("held valuation unavailable for N1" in b for b in entry["blocked"])
    assert entry["fills"] == {}
    assert entry["shares_after"]["N1"] == pytest.approx(
        entry["shares_before"]["N1"], rel=1e-9
    )
