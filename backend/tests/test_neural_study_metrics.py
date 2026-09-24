"""Scorecards retain every account mark and compare the same net-return intervals."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.neural_study_metrics import Curve, from_simulation, scorecard


# Build synthetic session observations, independent of any market outcomes.
def _curve(equity, *, cost=10, traded=None):
    return Curve(
        np.arange("2025-01-01", "2027-01-01", dtype="datetime64[D]")[: len(equity)],
        np.asarray(equity, dtype=float),
        cost,
        traded,
    )


# Supply both required benchmark accounts without manufacturing strategy outcomes.
def _table(candidate):
    flat = replace(candidate, equity=np.ones(len(candidate.equity)), traded_notional=0)
    return {"candidate": candidate, "SPY": flat, "QQQ": flat}


# A falling path after a new peak has a negative drawdown, not an absolute loss label.
def test_exact_return_drawdown_and_notional_definitions():
    result = scorecard(_table(_curve([100, 110, 99], traded=209)), cost_bps=10)
    row = result["rows"]["candidate"]
    assert row["total_return"] == pytest.approx(-0.01)
    assert row["cagr"] == pytest.approx(0.99**126 - 1)
    assert row["max_drawdown"] == pytest.approx(-0.1)
    assert row["sharpe_zero_risk_free"] == pytest.approx(0, abs=1e-12)
    assert row["traded_notional_per_starting_nav"] == pytest.approx(2.09)
    assert row["annual_traded_notional_over_mean_nav"] == pytest.approx(
        209 / 103 / (2 / 252)
    )
    assert row["return_intervals"] == 2


# Rescaling account currency must preserve every normalized metric.
def test_nav_and_notional_scale_equivalence():
    first = _curve([1, 1.1, 0.99, 1.02], traded=2)
    second = replace(first, equity=first.equity * 10000, traded_notional=20000)
    a = scorecard(_table(first), cost_bps=10)["rows"]["candidate"]
    b = scorecard(_table(second), cost_bps=10)["rows"]["candidate"]
    for key in (
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe_zero_risk_free",
        "traded_notional_per_starting_nav",
        "annual_traded_notional_over_mean_nav",
    ):
        assert a[key] == pytest.approx(b[key])


# Sixty-three returns require sixty-four marks; shorter histories are unavailable.
def test_rolling_window_boundaries_and_ties():
    short = scorecard(_table(_curve(np.ones(63))), cost_bps=10)["rows"]["candidate"]
    assert short["rolling_win_rate"]["SPY"]["63"] == {
        "windows": 0,
        "win_rate": None,
        "ties": 0,
    }
    full = scorecard(_table(_curve(np.ones(253))), cost_bps=10)["rows"]["candidate"]
    assert full["rolling_win_rate"]["SPY"]["63"] == {
        "windows": 190,
        "win_rate": 0.0,
        "ties": 190,
    }
    assert full["rolling_win_rate"]["QQQ"]["252"] == {
        "windows": 1,
        "win_rate": 0.0,
        "ties": 1,
    }
    assert full["sharpe_zero_risk_free"] is None


# Each benchmark has its own relative-win result rather than sharing the SPY verdict.
def test_rolling_wins_compare_both_benchmarks_independently():
    candidate = _curve(1.01 ** np.arange(253))
    curves = _table(candidate)
    curves["QQQ"] = replace(candidate, equity=1.02 ** np.arange(253))
    row = scorecard(curves, cost_bps=10)["rows"]["candidate"]
    assert row["rolling_win_rate"]["SPY"]["63"]["win_rate"] == 1
    assert row["rolling_win_rate"]["QQQ"]["63"]["win_rate"] == 0
    assert row["sharpe_zero_risk_free"] is None


# Missing marks invalidate the entire table rather than dropping the difficult sessions.
@pytest.mark.parametrize("value", [np.nan, np.inf, 0, -1])
def test_missing_or_invalid_marks_fail_closed(value):
    with pytest.raises(ValueError, match="account marks"):
        scorecard(_table(_curve([1, value, 1])), cost_bps=10)


# Identical endpoints do not excuse a missing interior session.
def test_full_calendar_alignment_required_without_inner_join():
    curves = _table(_curve([1, 1.1, 1.2, 1.3]))
    curves["QQQ"] = replace(
        curves["QQQ"], dates=curves["QQQ"].dates[[0, 2, 3]], equity=np.ones(3)
    )
    with pytest.raises(ValueError, match="account dates differ"):
        scorecard(curves, cost_bps=10)


# Cost metadata cannot silently compare a charged strategy with an uncharged benchmark.
def test_costs_and_required_benchmarks_are_explicit():
    curves = _table(_curve([1, 1.1]))
    curves["QQQ"] = replace(curves["QQQ"], cost_bps=0)
    with pytest.raises(ValueError, match="execution costs differ"):
        scorecard(curves, cost_bps=10)
    with pytest.raises(ValueError, match="Both SPY and QQQ"):
        scorecard({"SPY": curves["SPY"]}, cost_bps=10)
    with pytest.raises(ValueError, match="10 and 25"):
        scorecard(curves, cost_bps=30)


# The 25-bp table reads its own net curve and never deducts costs twice.
def test_second_cost_level_uses_supplied_account_outcomes():
    row = scorecard(_table(_curve([1, 1.075], cost=25)), cost_bps=25)["rows"][
        "candidate"
    ]
    assert row["total_return"] == pytest.approx(0.075)
    assert row["traded_notional_per_starting_nav"] is None


# Preserve actual simulator accounting instead of inferring turnover from NAV.
def test_simulation_adapter_preserves_and_copies_ledger_evidence():
    original = _curve([1, 1.1, 1.05])
    result = SimpleNamespace(dates=original.dates, equity=original.equity, traded=0.72)
    curve = from_simulation(result, 10)
    result.equity[1] = 50
    assert curve.equity[1] == 1.1
    assert curve.traded_notional == 0.72
    with pytest.raises(ValueError, match="did not provide account equity"):
        from_simulation(SimpleNamespace(equity=None), 10)
