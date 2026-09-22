"""The fixed-candidate evaluation scorecard and its reproducible runner.

These tests fix the evaluation role's boundary: the fixed common window and
conventions, the strict rejection of misaligned or missing data, the
two-benchmark objective (against EACH of SPY and QQQ), the reference
arithmetic that must reproduce the independently checked numbers, and the
funded candidate runner that must produce a clean, complete trace through the
integrated simulator's shared execution path (`simulate.run` with
`funded_allocation=True`). They are self-contained (synthetic calendars and
reports) so they run without the cached inputs or any service; the baseline
cross-check against the real `common-window-reference` NPZ is exercised
separately by the CLI and by a test that skips when the cache is absent.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import allocation
from backend.market import allocation_evaluation as ev
from backend.tests.test_trading_simulate import _report

# The number of evaluated sessions in the fixed common window.
COMMON_SESSIONS = 2693


# The exact common-window dates (2016-01-04 .. 2026-09-18, 2693 sessions).
def _common_dates() -> np.ndarray:
    """Return the 2693 common-window session dates."""
    span = int((ev.COMMON_END - ev.COMMON_START).astype("int64"))
    days = np.linspace(0, span, COMMON_SESSIONS).astype("int64")
    return ev.COMMON_START + days


# A benchmark calendar that starts before the common window and ends on it.
def _benchmark_dates() -> np.ndarray:
    """Return a full calendar from before COMMON_START to COMMON_END."""
    span = int((ev.COMMON_END - ev.COMMON_START).astype("int64"))
    return ev.COMMON_START + np.arange(-40, span + 1, 2, dtype="int64")


# A candidate series over the common dates: leading NAV slot plus `fill`.
def _series(fill: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (dates, daily, equity) for a candidate over the common dates."""
    dates = _common_dates()
    daily = np.concatenate([[np.nan], np.asarray(fill, dtype=float)])
    equity = np.r_[1.0, np.cumprod(1.0 + daily[1:])]
    return dates, daily, equity


# Write a synthetic common-window-reference npz with the given series.
def _write_reference_npz(path, incumbent=None, spy=None, qqq=None) -> np.ndarray:
    """Return the dates and write a reference npz holding synthetic series."""
    dates = _common_dates()
    n = len(dates)
    rng = np.random.default_rng(11)
    incumbent = (
        incumbent
        if incumbent is not None
        else np.concatenate([[np.nan], rng.normal(0.0006, 0.012, n - 1)])
    )
    spy = (
        spy
        if spy is not None
        else np.concatenate([[np.nan], rng.normal(0.0004, 0.01, n - 1)])
    )
    qqq = (
        qqq
        if qqq is not None
        else np.concatenate([[np.nan], rng.normal(0.0006, 0.014, n - 1)])
    )
    equity = np.r_[1.0, np.cumprod(1.0 + incumbent[1:])]
    spy_equity = np.r_[1.0, np.cumprod(1.0 + spy[1:])]
    qqq_equity = np.r_[1.0, np.cumprod(1.0 + qqq[1:])]
    invested = np.clip(0.5 + 0.4 * np.sin(np.arange(n) / 40.0), 0.0, 1.0)
    np.savez(
        path,
        dates=dates,
        incumbent_daily=incumbent,
        incumbent_equity=equity,
        invested=invested,
        spy_daily=spy,
        spy_equity=spy_equity,
        qqq_daily=qqq,
        qqq_equity=qqq_equity,
    )
    return dates


# A first-session loss against the initial NAV of 1 must show in the metrics.
def test_first_day_loss_shows_against_nav1():
    fill = np.full(COMMON_SESSIONS - 1, 0.001)
    fill[0] = -0.05
    dates, daily, equity = _series(fill)
    _, _ = ev.validate_candidate_series("candidate", dates, daily, equity)
    assert equity[1] == pytest.approx(0.95)
    measured = ev.metrics(daily[1:])
    assert measured["worst_day"] == pytest.approx(-0.05)
    # The drawdown is measured from the NAV of 1, so the first-day loss is a
    # real drawdown, never hidden behind a zero return.
    assert measured["drawdown"] == pytest.approx(0.05)


# A calendar that does not match the fixed window is rejected, not re-aligned.
def test_misaligned_calendar_is_rejected():
    fill = np.full(COMMON_SESSIONS - 1, 0.001)
    dates, daily, equity = _series(fill)
    shifted = dates + np.timedelta64(1, "D")
    with pytest.raises(ValueError, match="dates must be exactly"):
        ev.validate_candidate_series("candidate", shifted, daily, equity)


# A missing interior or trailing return rejects the whole candidate.
def test_interior_and_trailing_nan_are_rejected():
    fill = np.full(COMMON_SESSIONS - 1, 0.001)
    dates, daily, equity = _series(fill)
    for bad in (5, COMMON_SESSIONS - 2):
        broken = daily.copy()
        broken[bad] = np.nan
        with pytest.raises(ValueError, match="interior or trailing"):
            ev.validate_candidate_series("candidate", dates, broken, equity)


# The intentional initial NAV slot must be NaN and equity 1; nothing else may
# be missing, and the returns must be the equity curve's own returns.
def test_nav_slot_and_consistency_are_enforced():
    dates = _common_dates()
    daily = np.full(len(dates), 0.001)
    daily[0] = np.nan
    equity = np.r_[1.0, np.cumprod(1.0 + daily[1:])]
    with pytest.raises(ValueError, match="initial NAV"):
        ev.validate_candidate_series("candidate", dates, np.ones(len(dates)), equity)
    bad_equity = equity.copy()
    bad_equity[0] = 0.99
    with pytest.raises(ValueError, match="NAV 1"):
        ev.validate_candidate_series("candidate", dates, daily, bad_equity)
    disagreeing = equity.copy()
    disagreeing[3:] += 0.01
    with pytest.raises(ValueError, match="own returns"):
        ev.validate_candidate_series("candidate", dates, daily, disagreeing)


# The two-benchmark objective needs higher net return AND no greater drawdown
# against EACH of SPY and QQQ.
def test_two_benchmark_objective_requires_each_benchmark():
    n = 300
    spy = np.full(n, 0.001)
    qqq = np.full(n, 0.002)
    controls = {ev.SPY: spy, ev.QQQ: qqq}
    beats_spy_not_qqq = np.full(n, 0.0015)
    both = np.full(n, 0.0025)
    equal = np.full(n, 0.001)
    higher_return_higher_dd = np.full(n, 0.0015)
    higher_return_higher_dd[0] = -0.10
    assert not ev.compare_candidate(beats_spy_not_qqq, controls)["both_objectives_met"]
    assert ev.compare_candidate(both, controls)["both_objectives_met"]
    assert not ev.compare_candidate(equal, controls)["both_objectives_met"]
    # A higher return is not enough when the drawdown is also higher.
    result = ev.compare_candidate(higher_return_higher_dd, controls)
    assert result["vs"][ev.SPY]["objective_met"] is False
    assert result["vs"][ev.QQQ]["objective_met"] is False


# The reference arithmetic reproduces analytic values for a known series.
def test_metrics_match_analytic_values():
    fill = np.full(100, 0.01)
    measured = ev.metrics(fill)
    assert measured["total"] == pytest.approx(1.01**100 - 1.0)
    assert measured["annual"] == pytest.approx(1.01**252 - 1.0)
    assert measured["drawdown"] == pytest.approx(0.0)
    assert measured["worst_day"] == pytest.approx(0.01)
    assert measured["longest_underwater_sessions"] == 0
    dipped = fill.copy()
    dipped[10] = -0.30
    dd = ev.metrics(dipped)
    assert dd["drawdown"] == pytest.approx(0.30)
    assert dd["worst_day"] == pytest.approx(-0.30)


# The common-window reference loader reads and validates the authoritative npz.
def test_load_common_window_reference_validates(tmp_path):
    path = tmp_path / "common-window-reference.npz"
    dates = _write_reference_npz(path)
    reference = ev.load_common_window_reference(path)
    np.testing.assert_array_equal(reference.dates, dates)
    assert reference.dates[0] == ev.COMMON_START
    assert reference.dates[-1] == ev.COMMON_END
    assert reference.incumbent_equity[0] == 1.0
    assert np.isnan(reference.incumbent_daily[0])
    assert ev.metrics(reference.incumbent_daily[1:])["total"] == pytest.approx(
        reference.incumbent_equity[-1] - 1.0
    )


# A missing interior return in the reference is a hard rejection.
def test_load_common_window_reference_rejects_interior_gap(tmp_path):
    path = tmp_path / "common-window-reference.npz"
    fill = np.full(COMMON_SESSIONS - 1, 0.001)
    fill[5] = np.nan
    incumbent = np.concatenate([[np.nan], fill])
    _write_reference_npz(path, incumbent=incumbent)
    with pytest.raises(ValueError, match="interior gap"):
        ev.load_common_window_reference(path)


# The benchmark price loader rejects a NaN interior and a missing series.
def test_load_benchmark_prices_rejects_gaps_and_missing(tmp_path):
    dates = _benchmark_dates()
    spy = np.full(len(dates), 100.0)
    qqq = np.full(len(dates), 100.0)
    good = tmp_path / "prices.npz"
    np.savez(good, dates=dates, SPY=spy, QQQ=qqq)
    inputs = ev.load_benchmark_prices(good)
    assert inputs.dates[0] < ev.COMMON_START
    assert inputs.dates[-1] == ev.COMMON_END
    assert inputs.spy[inputs.common_start] == pytest.approx(100.0)
    bad = spy.copy()
    bad[10] = np.nan
    gap = tmp_path / "gap.npz"
    np.savez(gap, dates=dates, SPY=bad, QQQ=qqq)
    with pytest.raises(ValueError, match="finite positive"):
        ev.load_benchmark_prices(gap)
    missing = tmp_path / "missing.npz"
    np.savez(missing, dates=dates, SPY=spy)
    with pytest.raises(ValueError, match="QQQ"):
        ev.load_benchmark_prices(missing)


# The trailing-252 comparison is explicitly overlapping, never independent.
def test_rolling_252_is_explicitly_overlapping():
    n = 300
    candidate = np.full(n, 0.001)
    controls = {ev.SPY: np.full(n, 0.0005), ev.QQQ: np.full(n, 0.0015)}
    rolling = ev.rolling_252(candidate, controls)
    assert rolling["windows"] == n - 252 + 1
    assert rolling["overlapping"] is True
    for symbol in controls:
        assert 0.0 <= rolling["fraction_objective_met"][symbol] <= 1.0
    assert 0.0 <= rolling["fraction_both_met"] <= 1.0


# A fully-cash account is flat, and a full-equity account at zero cost matches
# buy-and-hold, so the constant-equity diagnostic is a funded ledger.
def test_constant_equity_account_is_a_funded_ledger():
    rng = np.random.default_rng(3)
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, 200)))
    opens = np.full(len(prices), prices[0])
    cash = ev.constant_equity_account(prices, 0.0, opens=opens)
    np.testing.assert_allclose(cash, 1.0, atol=1e-12)
    full = ev.constant_equity_account(prices, 1.0, cost_bps=0.0, opens=opens)
    # Buy-and-hold at the first session's close: NAV 1 until session 1, then
    # the price ratio from that fill.
    expected = np.ones(len(prices))
    expected[1:] = prices[1:] / opens[1]
    np.testing.assert_allclose(full, expected, rtol=1e-12)


# The hindsight comparison includes selection and timing, using actual opens.
def test_exposure_matched_reports_return_difference():
    dates, daily, equity = _series(np.full(COMMON_SESSIONS - 1, 0.001))
    candidate = ev.CandidateResult(
        name="test",
        dates=dates,
        daily=daily,
        equity=equity,
        exposure=np.full(len(dates), 0.5),
        trace=None,
        method="synthetic",
    )
    prices = 100.0 * np.exp(np.arange(COMMON_SESSIONS) / 2000.0)
    common = {ev.SPY: prices, ev.QQQ: prices * 1.2}
    controls = {
        ev.SPY: np.full(COMMON_SESSIONS - 1, 0.0005),
        ev.QQQ: np.full(COMMON_SESSIONS - 1, 0.0006),
    }
    opens = {symbol: values * 1.05 for symbol, values in common.items()}
    diagnostic = ev.exposure_matched_diagnostic(candidate, common, controls, opens)
    assert diagnostic["mean_observed_equity_exposure"] == pytest.approx(0.5)
    assert ev.SPY in diagnostic["accounts"]
    assert "total_return_difference" in diagnostic["accounts"][ev.SPY]
    assert "timing_contribution" not in diagnostic["accounts"][ev.SPY]
    from backend.market.allocation_controls import constant_exposure

    expected = constant_exposure(prices, opens[ev.SPY], 0.5, candidate.cost_bps)
    assert diagnostic["accounts"][ev.SPY]["metrics"]["total"] == pytest.approx(
        expected[-1] - 1.0
    )


# False-exit diagnostics detect a merged risk cut, its costly label and its
# censoring when the terminal episode lacks a full 20-session horizon.
def test_false_exit_diagnostics_episodes_and_censoring():
    target = [1.0, 1.0, 0.75, 0.60, 0.65, 1.0, 1.0, 1.0, 1.0]
    actual = [1.0, 0.99, 0.72, 0.58, 0.64, 0.98, 1.0, 1.0, 1.0]
    trace = []
    for i, t in enumerate(target):
        trace.append(
            {
                "decision_date": f"2026-01-0{i + 1}",
                "fill_date": f"2026-01-0{i + 2}",
                "desired_equity": t,
                "exposure": actual[i],
            }
        )
    rising = np.full(30, 0.002)
    controls = {ev.SPY: rising}
    diagnostics = ev.false_exit_diagnostics(trace, controls)
    episodes = diagnostics["episodes"]
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["pre_cut_target"] == pytest.approx(1.0)
    assert episode["cut_depth_points"] >= 0.10
    # The actual exposure regains 90% of its pre-cut level on session 5,
    # three sessions after the decision.
    assert episode["reentry_delay_sessions"] == 3
    # The trace ends before 20 sessions: a longer control cannot uncensor it.
    assert episode["forward"][ev.SPY]["forward_20"] is None
    assert episode["forward"][ev.SPY]["costly_exit"] is None
    assert episode["full_20_session_horizon"] is False


# The funded candidate runner runs the real integrated simulator path: its
# series and trace are exactly what `simulate.run` with `funded_allocation`
# produces over the same window, with the aligned SPY/QQQ benchmark context and
# no incompatible live-policy option applied.
def test_run_funded_candidate_runs_the_integrated_simulator():
    from backend.agents.trading.desk import event_risk, paper, simulate

    rng = np.random.default_rng(9)
    rows, names = 60, 6
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, (rows, names)), axis=0))
    report = _report(close=close)
    panel = report.panel
    dates = panel.dates
    spy = np.asarray(panel.adj_close[:, panel.index(ev.SPY)], dtype=float)
    qqq = 100.0 * np.exp(np.cumsum(rng.normal(0.0007, 0.014, rows)))
    benchmarks = ev.BenchmarkInputs(dates=dates, spy=spy, qqq=qqq, common_start=0)
    result = ev.run_funded_candidate(
        report, benchmarks, "vol", start=dates[10], end=dates[-1]
    )
    assert result.trace is not None
    assert len(result.trace) >= 1
    checks = ev.trace_checks(result.trace)
    assert checks["clean"], checks["violations"]
    assert np.isfinite(result.equity).all()
    assert (result.equity > 0).all()
    assert np.isnan(result.daily[0])
    assert ev.metrics(result.daily[1:])["total"] == pytest.approx(
        result.equity[-1] - 1.0
    )
    # The candidate is exactly the integrated simulator's own series over the
    # same window: dates, returns, equity and invested, with a trace that is
    # the simulator's own enriched only by the derived desired-equity/exposure
    # fields the false-exit diagnostics read.
    direct = simulate.run(
        report,
        since=dates[10],
        rebalance=paper.REBALANCE_EVERY,
        cost_bps=ev.COST_BPS,
        use_exits=False,
        event_exposure=event_risk.live_path(report.panel),
        funded_allocation=True,
        allocation_policy="vol",
        index_eligible=False,
        benchmark_prices={"dates": panel.dates, ev.SPY: spy, ev.QQQ: qqq},
    )
    count = len(dates) - 10
    np.testing.assert_array_equal(result.dates, direct.dates[:count])
    np.testing.assert_array_equal(result.daily, direct.returns[:count])
    np.testing.assert_array_equal(result.equity, direct.equity[:count])
    np.testing.assert_array_equal(result.exposure, direct.invested[:count])
    assert [
        {
            k: v
            for k, v in entry.items()
            if k
            not in (
                "desired_equity",
                "exposure",
                "nav_before",
                "nav_after",
                "actual_weights",
            )
        }
        for entry in result.trace
    ] == direct.trace
    for entry in result.trace:
        assert "desired_equity" in entry
        assert "exposure" in entry
    diagnostics = ev.false_exit_diagnostics(result.trace, {ev.SPY: direct.returns[1:]})
    assert "episodes" in diagnostics
    assert ev.turnover_and_fees(result.trace, result.equity[-1])["fees"] >= 0.0


# The live-policy flags are incompatible with the funded path, so the candidate
# runner must never pass them: `simulate.run` refuses the combination rather
# than silently running a different book.
def test_funded_path_refuses_incompatible_live_policy_flags():
    from backend.agents.trading.desk import event_risk, paper, simulate

    rng = np.random.default_rng(4)
    rows, names = 40, 6
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, (rows, names)), axis=0))
    report = _report(close=close)
    panel = report.panel
    spy = np.asarray(panel.adj_close[:, panel.index(ev.SPY)], dtype=float)
    qqq = np.full(rows, 100.0)
    with pytest.raises(ValueError, match="cannot be combined"):
        simulate.run(
            report,
            since=panel.dates[5],
            rebalance=paper.REBALANCE_EVERY,
            cost_bps=ev.COST_BPS,
            use_exits=False,
            event_exposure=event_risk.live_path(report.panel),
            funded_allocation=True,
            allocation_policy="vol",
            index_eligible=False,
            benchmark_prices={"dates": panel.dates, ev.SPY: spy, ev.QQQ: qqq},
            **simulate.LIVE_POLICY,
        )


# An unknown policy is refused rather than silently defaulted.
def test_run_funded_candidate_rejects_unknown_policy():
    rng = np.random.default_rng(2)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.005, (20, 6)), axis=0))
    report = _report(close=close)
    panel = report.panel
    benchmarks = ev.BenchmarkInputs(
        dates=panel.dates,
        spy=np.full(len(panel.dates), 100.0),
        qqq=np.full(len(panel.dates), 100.0),
        common_start=0,
    )
    with pytest.raises(ValueError, match="policy"):
        ev.run_funded_candidate(
            report, benchmarks, "nonsense", start=panel.dates[2], end=panel.dates[-1]
        )


# The cached-report loader validates the panel calendar covers the window.
def test_load_cached_report_validates_coverage(tmp_path):
    import pickle

    span = int((ev.COMMON_END - ev.COMMON_START).astype("int64"))
    dates = ev.COMMON_START + np.arange(0, span + 1, 2, dtype="int64")
    report = SimpleNamespace(panel=SimpleNamespace(dates=dates))
    path = tmp_path / "report.pickle"
    with open(path, "wb") as handle:
        pickle.dump(report, handle)
    loaded, index = ev.load_cached_report(path)
    np.testing.assert_array_equal(loaded.panel.dates, dates)
    assert dates[index] == ev.COMMON_START


# The reviewed decision is the one the funded runner consumes: a decision that
# scales volatility produces a finite desired composition or missing evidence.
def test_decision_flow_produces_a_bounded_target():
    rng = np.random.default_rng(5)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, (40, 6)), axis=0))
    report = _report(close=close)
    panel = report.panel
    dates = panel.dates
    spy = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, 40)))
    qqq = 100.0 * np.exp(np.cumsum(rng.normal(0.0007, 0.014, 40)))
    tickers = [t for t in panel.tickers if t not in (panel.benchmark, ev.QQQ)]
    tickers.append(ev.SPY)
    tickers.append(ev.QQQ)
    matrix = np.column_stack(
        [
            panel.adj_close[:, panel.index(t)]
            for t in tickers
            if t not in (ev.SPY, ev.QQQ)
        ]
        + [spy, qqq]
    )
    t = 39
    decision = allocation.decide(
        dates,
        matrix,
        tickers,
        t,
        desired={f"N{i}": 0.2 for i in range(5)},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy="vol",
        index_eligible=False,
    )
    assert decision.available or decision.missing
    assert decision.cash >= 0.0
    assert decision.cash <= 1.0
    assert sum(decision.desired_weights.values()) <= 1.0 + 1e-9


# A cached benchmark's own dates must survive the runner boundary unchanged.
def test_runner_rejects_relabelled_benchmark_calendar():
    report = _report()
    dates = report.panel.dates
    benchmarks = ev.BenchmarkInputs(
        dates=dates + np.timedelta64(1, "D"),
        spy=report.panel.adj_close[:, -1],
        qqq=report.panel.adj_close[:, -1],
        common_start=0,
    )
    with pytest.raises(ValueError, match="calendar"):
        ev.run_funded_candidate(
            report, benchmarks, "vol", start=dates[60], end=dates[-1]
        )


# Execution gaps must reach the exit diagnostics as actual, not projected, exposure.
def test_runner_trace_exposure_is_the_real_post_fill_account():
    report = _report()
    dates = report.panel.dates
    benchmarks = ev.BenchmarkInputs(
        dates=dates,
        spy=report.panel.adj_close[:, -1],
        qqq=report.panel.adj_close[:, -1],
        common_start=0,
    )
    result = ev.run_funded_candidate(
        report,
        benchmarks,
        "vol",
        start=dates[60],
        end=dates[-1],
        index_eligible=True,
    )
    np.testing.assert_allclose(
        [entry["exposure"] for entry in result.trace],
        result.exposure[1:],
        rtol=1e-12,
        atol=1e-12,
    )


# Invalid chronology, invented fills and incorrect cash/fees cannot pass acceptance.
@pytest.mark.parametrize("defect", ["date", "cash", "shares", "fees", "fill"])
def test_trace_checks_reject_execution_corruption(defect):
    entry = {
        "decision_date": "2026-01-05",
        "fill_date": "2026-01-06",
        "cash_before": 100.0,
        "cash_after": 49.95,
        "shares_before": {},
        "shares_after": {"AAA": 5.0},
        "deltas": {"AAA": 5.0},
        "notional_traded": 50.0,
        "fees": 0.05,
        "fills": {
            "AAA": {"side": "buy", "qty": 5.0, "fill_price": 10.0, "notional": 50.0}
        },
    }
    assert ev.trace_checks([entry])["clean"]
    if defect == "date":
        entry["fill_date"] = entry["decision_date"]
    elif defect == "cash":
        entry["cash_after"] = 50.0
    elif defect == "shares":
        entry["shares_after"]["AAA"] = 6.0
    elif defect == "fees":
        entry["fees"] = 0.1
    else:
        entry["fills"]["AAA"]["fill_price"] = float("nan")
    assert not ev.trace_checks([entry])["clean"]


# Forward returns start after the decision; unavailable horizons stay null.
def test_false_exit_forward_alignment_and_terminal_censoring():
    trace = [
        {
            "decision_date": str(np.datetime64("2026-01-01") + np.timedelta64(i, "D")),
            "desired_equity": 1.0 if i < 2 else 0.5,
            "exposure": 0.5,
        }
        for i in range(22)
    ]
    returns = np.zeros(22)
    returns[2] = 0.1
    episode = ev.false_exit_diagnostics(trace, {ev.SPY: returns})["episodes"][0]
    assert episode["forward"][ev.SPY]["forward_5"] == pytest.approx(0.1)
    assert episode["forward"][ev.SPY]["forward_20"] == pytest.approx(0.1)
    assert episode["full_20_session_horizon"] is True
    short = ev.false_exit_diagnostics(trace[:10], {ev.SPY: returns[:10]})["episodes"][0]
    assert short["forward"][ev.SPY]["costly_exit"] is None


# Turnover uses capital at each decision, not the much larger terminal account.
def test_turnover_uses_each_decision_nav():
    trace = [
        {"nav_before": 100.0, "notional_traded": 20.0, "fees": 0.02},
        {"nav_before": 200.0, "notional_traded": 40.0, "fees": 0.04},
    ]
    result = ev.turnover_and_fees(trace, 200.0)
    assert result["sum_traded_notional_over_decision_nav"] == pytest.approx(0.4)
    assert result["annualized_two_way_turnover"] == pytest.approx(50.4)
    assert result["sum_fees_over_decision_nav"] == pytest.approx(0.0004)
