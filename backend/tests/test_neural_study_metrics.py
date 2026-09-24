"""Scorecards retain every account mark and compare the same net-return intervals."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.neural_study_metrics import (
    REGIME_NAMES,
    Curve,
    RegimeEvidence,
    from_simulation,
    regime_labels,
    regime_scorecard,
    scorecard,
)


# Build synthetic session observations, independent of any market outcomes.
def _curve(equity, *, cost=10, traded=None):
    return Curve(
        np.arange("2025-01-01", "2027-01-01", dtype="datetime64[D]")[: len(equity)],
        np.asarray(equity, dtype=float),
        cost,
        traded,
    )


# Supply every required control account without manufacturing strategy outcomes.
def _table(candidate):
    flat = replace(
        candidate,
        equity=np.ones(len(candidate.equity)),
        traded_notional=0,
        invested_fraction=None,
        largest_position_fraction=None,
    )
    return {
        "candidate": candidate,
        "incumbent": flat,
        "SPY": flat,
        "QQQ": flat,
        "equal_weight": flat,
    }


# Create enough causal SPY history to end in one requested trend/volatility state.
def _regime_evidence(*, above: bool, high_volatility: bool):
    count = 430
    drift = 0.004 if above else -0.004
    historical_noise = 0.001 if high_volatility else 0.012
    recent_noise = 0.012 if high_volatility else 0.0001
    noise = np.where(np.arange(count - 1) % 2, historical_noise, -historical_noise)
    noise[-40:] = np.where(np.arange(40) % 2, recent_noise, -recent_noise)
    closes = 100 * np.cumprod(np.concatenate(([1.0], 1 + drift + noise)))
    dates = np.arange("2025-01-01", "2027-01-01", dtype="datetime64[D]")[:count]
    return RegimeEvidence(dates, closes)


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
    assert row["fees_paid_per_starting_nav"] == pytest.approx(0.00209)
    assert row["mean_invested_fraction"] is None
    assert row["mean_largest_position_fraction"] is None
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
        "fees_paid_per_starting_nav",
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


# The stated maximum-growth gate is strict and names every primary comparator.
def test_primary_objective_requires_candidate_to_beat_incumbent_spy_and_qqq():
    candidate = _curve([1, 1.2])
    curves = _table(candidate)
    curves["incumbent"] = replace(candidate, equity=np.array([1.0, 1.21]))
    failed = scorecard(curves, cost_bps=10)["primary_objective"]
    assert failed["comparators"] == ["incumbent", "SPY", "QQQ"]
    assert failed["candidate_minus_comparator"]["incumbent"] == pytest.approx(-0.01)
    assert failed["passes"] is False

    curves["incumbent"] = replace(candidate, equity=np.array([1.0, 1.19]))
    assert scorecard(curves, cost_bps=10)["primary_objective"]["passes"] is True


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
    with pytest.raises(ValueError, match="missing required accounts"):
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
    result = SimpleNamespace(
        dates=original.dates,
        equity=original.equity,
        traded=0.72,
        invested=np.array([0.0, 0.8, 0.7]),
        top_weight=np.array([0.0, 0.4, 0.3]),
    )
    curve = from_simulation(result, 10)
    result.equity[1] = 50
    result.invested[1] = 0
    result.top_weight[1] = 0
    assert curve.equity[1] == 1.1
    assert curve.invested_fraction[1] == 0.8
    assert curve.largest_position_fraction[1] == 0.4
    assert curve.traded_notional == 0.72
    row = scorecard(_table(curve), cost_bps=10)["rows"]["candidate"]
    assert row["mean_invested_fraction"] == pytest.approx(0.5)
    assert row["maximum_invested_fraction"] == pytest.approx(0.8)
    assert row["mean_largest_position_fraction"] == pytest.approx(0.7 / 3)
    assert row["maximum_largest_position_fraction"] == pytest.approx(0.4)
    with pytest.raises(ValueError, match="did not provide account equity"):
        from_simulation(SimpleNamespace(equity=None), 10)


# Exposure and concentration must be complete fractions or explicitly unavailable.
def test_invalid_exposure_or_concentration_diagnostics_fail_closed():
    candidate = _curve([1, 1.1, 1.2])
    with pytest.raises(ValueError, match="Invested fraction"):
        scorecard(
            _table(replace(candidate, invested_fraction=np.array([0.0, np.nan, 0.5]))),
            cost_bps=10,
        )
    with pytest.raises(ValueError, match="Largest-position fraction"):
        scorecard(
            _table(
                replace(
                    candidate,
                    largest_position_fraction=np.array([0.0, 0.5, 1.01]),
                )
            ),
            cost_bps=10,
        )


# The four frozen combinations are produced from pre-interval information only.
@pytest.mark.parametrize(
    ("above", "high_volatility", "expected"),
    [
        (True, True, "above_200_mean_high_volatility"),
        (True, False, "above_200_mean_low_volatility"),
        (False, True, "below_200_mean_high_volatility"),
        (False, False, "below_200_mean_low_volatility"),
    ],
)
def test_fixed_regime_definitions_cover_all_four_combinations(
    above, high_volatility, expected
):
    evidence = _regime_evidence(above=above, high_volatility=high_volatility)
    assert regime_labels(evidence.dates[-2:], evidence).tolist() == [expected]


# A return's own closing price and every later price cannot alter its label.
def test_regime_labels_are_same_day_and_future_invariant():
    evidence = _regime_evidence(above=True, high_volatility=True)
    account_dates = evidence.dates[-12:-1]
    original = regime_labels(account_dates, evidence)
    changed = evidence.spy_adjusted_closes.copy()
    same_day = int(np.searchsorted(evidence.dates, account_dates[-1]))
    changed[same_day:] = changed[same_day:] * np.linspace(
        0.1, 10, len(changed[same_day:])
    )
    mutated = regime_labels(
        account_dates, replace(evidence, spy_adjusted_closes=changed)
    )
    assert np.array_equal(mutated, original)


# Warm-up gaps remain visible instead of disappearing from the comparison.
def test_unknown_regime_is_explicit_and_never_drops_an_interval():
    dates = np.arange("2026-01-01", "2026-01-08", dtype="datetime64[D]")
    evidence = RegimeEvidence(dates, np.ones(len(dates)))
    candidate = Curve(dates, np.array([1, 1.1, 1, 1.2, 1.1, 1.3, 1.4]), 10)
    result = regime_scorecard(_table(candidate), cost_bps=10, evidence=evidence)
    assert result["regime_order"] == list(REGIME_NAMES)
    assert result["regime_intervals_reconcile"] is True
    assert result["regimes"]["unknown_or_unavailable"]["return_intervals"] == 6
    assert sum(block["return_intervals"] for block in result["regimes"].values()) == 6
    for name in REGIME_NAMES[:-1]:
        assert (
            result["regimes"][name]["rows"]["candidate"]["log_growth_contribution"]
            is None
        )


# The frozen boundary assigns trend equality above and volatility equality low.
def test_fixed_threshold_equalities_match_the_prior_regime_replay():
    dates = np.arange("2025-01-01", "2027-01-01", dtype="datetime64[D]")[:430]
    evidence = RegimeEvidence(dates, np.ones(len(dates)))
    assert regime_labels(dates[-2:], evidence).tolist() == [
        "above_200_mean_low_volatility"
    ]


# An invalid close makes every dependent interval explicit as unavailable.
def test_invalid_regime_evidence_is_unknown_until_windows_are_complete_again():
    evidence = _regime_evidence(above=True, high_volatility=True)
    closes = evidence.spy_adjusted_closes.copy()
    closes[-30] = np.nan
    labels = regime_labels(
        evidence.dates[-10:], replace(evidence, spy_adjusted_closes=closes)
    )
    assert labels.tolist() == ["unknown_or_unavailable"] * len(labels)


# Regime rows compound the same selected net returns for every required account.
def test_regime_scorecard_reports_compounded_growth_against_all_benchmarks():
    evidence = _regime_evidence(above=True, high_volatility=True)
    dates = evidence.dates[-10:]
    candidate = Curve(dates, 1.02 ** np.arange(len(dates)), 10)
    curves = _table(candidate)
    result = regime_scorecard(curves, cost_bps=10, evidence=evidence)
    block = result["regimes"]["above_200_mean_high_volatility"]
    assert block["return_intervals"] == len(dates) - 1
    assert block["rows"]["candidate"]["compounded_selected_return"] == pytest.approx(
        1.02 ** (len(dates) - 1) - 1
    )
    assert block["candidate_comparisons"]["SPY"][
        "excess_log_growth_contribution"
    ] == pytest.approx(np.log(1.02) * (len(dates) - 1))
    assert "cagr" not in block["rows"]["candidate"]
    assert block["candidate_beats_all_primary_comparators"] is True
    for benchmark in ("incumbent", "SPY", "QQQ"):
        contributions = [
            regime["candidate_comparisons"][benchmark]["excess_log_growth_contribution"]
            or 0.0
            for regime in result["regimes"].values()
        ]
        expected = np.log(candidate.equity[-1] / candidate.equity[0])
        assert sum(contributions) == pytest.approx(expected)


# A skipped account session cannot be mislabeled as a one-session regime return.
def test_regime_scorecard_rejects_noncontiguous_or_missing_spy_evidence():
    evidence = _regime_evidence(above=True, high_volatility=True)
    candidate = Curve(evidence.dates[-4::2], np.array([1.0, 1.1]), 10)
    with pytest.raises(ValueError, match="contiguous"):
        regime_scorecard(_table(candidate), cost_bps=10, evidence=evidence)

    candidate = Curve(evidence.dates[-3:], np.array([1.0, 1.1, 1.2]), 10)
    shortened = RegimeEvidence(evidence.dates[:-1], evidence.spy_adjusted_closes[:-1])
    with pytest.raises(ValueError, match="contain every account session"):
        regime_scorecard(_table(candidate), cost_bps=10, evidence=shortened)
