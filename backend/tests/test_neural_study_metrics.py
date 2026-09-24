"""Scorecards retain every account mark and compare the same net-return intervals."""

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.neural_study_metrics import (
    REGIME_NAMES,
    Curve,
    RegimeEvidence,
    chronological_fold_scorecard,
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


# Supply distinct matched accounts and costs with a causal warm-up for fold tests.
def _fold_inputs(intervals=21):
    evidence = _regime_evidence(above=True, high_volatility=True)
    dates = evidence.dates[-intervals - 1 :]
    daily_rates = {
        "candidate": 0.003,
        "incumbent": 0.002,
        "SPY": 0.001,
        "QQQ": 0.004,
        "equal_weight": 0.0,
    }
    tables = {
        cost: {
            name: Curve(
                dates,
                100 * (1 + rate - (cost - 10) / 100000) ** np.arange(len(dates)),
                cost,
                traded_notional=200,
                invested_fraction=np.linspace(0.2, 0.8, len(dates)),
                largest_position_fraction=np.linspace(0.02, 0.1, len(dates)),
            )
            for name, rate in daily_rates.items()
        }
        for cost in (10, 25)
    }
    return tables, evidence


# Run one declared fold geometry without selecting it from any observed outcome.
def _fold_report(tables, evidence, **parameters):
    options = {"train_size": 5, "test_size": 4, "horizon": 2, "embargo": 1}
    options.update(parameters)
    return chronological_fold_scorecard(tables, evidence=evidence, **options)


# Purge geometry must leave nonoverlapping returns and retain every boundary mark.
def test_chronological_folds_keep_purge_and_each_boundary_return():
    tables, evidence = _fold_inputs()
    result = _fold_report(tables, evidence)
    dates = tables[10]["incumbent"].dates
    ranges = []
    for number, fold in enumerate(result["folds"]):
        first = 8 + number * 4
        last = first + 4
        reference = fold["reference_history"]
        assert reference["start_index"] == number * 4
        assert reference["stop_index_exclusive"] == first - 3
        assert reference["last_hypothetical_label_session"] == str(dates[first - 2])
        assert reference["used_to_fit"] is False
        assert fold["purge_and_embargo"] == {
            "start_index": first - 3,
            "stop_index_exclusive": first,
            "decision_sessions": 3,
        }
        evaluation = fold["evaluation"]
        assert evaluation["starting_nav_session"] == str(dates[first])
        assert evaluation["first_return_session"] == str(dates[first + 1])
        assert evaluation["last_return_session"] == str(dates[last])
        ranges.extend(
            range(evaluation["start_index"], evaluation["stop_index_exclusive"])
        )
        for cost in (10, 25):
            card = fold["cost_levels"][str(cost)]["performance"]
            assert card["first_session"] == str(dates[first])
            assert card["last_session"] == str(dates[last])
            curve = tables[cost]["incumbent"]
            row = card["rows"]["incumbent"]
            assert row["return_intervals"] == 4
            assert row["total_return"] == pytest.approx(
                curve.equity[last] / curve.equity[first] - 1
            )
    assert ranges == list(range(8, 20))
    assert len(ranges) == len(set(ranges))
    assert result["coverage"]["complete_folds"] == 3


# Both cost tables retain actual outcomes and each comparator's separate verdict.
def test_fold_accounts_compare_spy_qqq_and_unchanged_incumbent_locally():
    tables, evidence = _fold_inputs()
    fold = _fold_report(tables, evidence)["folds"][0]
    for cost in (10, 25):
        block = fold["cost_levels"][str(cost)]
        comparisons = block["comparisons"]
        assert comparisons["candidate"]["incumbent"]["strict_win"] is True
        assert comparisons["candidate"]["SPY"]["strict_win"] is True
        assert comparisons["candidate"]["QQQ"]["strict_win"] is False
        assert comparisons["incumbent"]["SPY"]["strict_win"] is True
        assert comparisons["incumbent"]["QQQ"]["strict_win"] is False
        assert "incumbent" not in comparisons["incumbent"]
        assert block["performance"]["primary_objective"]["passes"] is False
        assert block["performance"]["cost_bps"] == cost
    first = fold["cost_levels"]["10"]["performance"]["rows"]["candidate"]
    stressed = fold["cost_levels"]["25"]["performance"]["rows"]["candidate"]
    assert stressed["total_return"] < first["total_return"]


# Retained aggregate trading evidence cannot be divided among folds without a ledger.
def test_fold_turnover_is_unavailable_and_exposure_uses_only_fold_marks():
    tables, evidence = _fold_inputs()
    result = _fold_report(tables, evidence)
    assert result["full_sample"]["10"]["rows"]["candidate"][
        "fees_paid_per_starting_nav"
    ] == pytest.approx(0.002)
    for fold in result["folds"]:
        start = fold["evaluation"]["start_index"]
        stop = fold["evaluation"]["stop_index_exclusive"] + 1
        row = fold["cost_levels"]["10"]["performance"]["rows"]["candidate"]
        for name in (
            "traded_notional_per_starting_nav",
            "annual_traded_notional_over_mean_nav",
            "fees_paid_per_starting_nav",
        ):
            assert row[name] is None
        source = tables[10]["candidate"]
        assert row["mean_invested_fraction"] == pytest.approx(
            np.mean(source.invested_fraction[start:stop])
        )
        assert row["maximum_largest_position_fraction"] == pytest.approx(
            np.max(source.largest_position_fraction[start:stop])
        )


# An earlier peak and earlier returns cannot leak into local drawdowns or rolling wins.
def test_fold_drawdown_and_rolling_metrics_use_local_history_only():
    tables, evidence = _fold_inputs()
    for cost in (10, 25):
        curve = tables[cost]["candidate"]
        values = np.full(len(curve.equity), 100.0)
        values[2] = 200
        values[8:13] = [100, 110, 99, 108, 109]
        tables[cost]["candidate"] = replace(curve, equity=values)
    result = _fold_report(tables, evidence)
    row = result["folds"][0]["cost_levels"]["10"]["performance"]["rows"]["candidate"]
    assert row["max_drawdown"] == pytest.approx(-0.1)
    assert row["total_return"] == pytest.approx(0.09)
    for comparator in ("incumbent", "SPY", "QQQ"):
        assert row["rolling_win_rate"][comparator]["63"]["windows"] == 0
    assert result["full_sample"]["10"]["rows"]["candidate"][
        "max_drawdown"
    ] == pytest.approx(-0.505)


# Prefix, complete folds, and incomplete tail must reconcile every causal regime.
def test_fold_regimes_reconcile_unscored_intervals_and_zero_observation_regimes():
    tables, evidence = _fold_inputs()
    result = _fold_report(tables, evidence)
    coverage = result["coverage"]
    partitions = coverage["partitions"]
    assert coverage["return_intervals"] == 21
    assert coverage["all_intervals_accounted_for"] is True
    assert [part["return_intervals"] for part in partitions.values()] == [8, 12, 1]
    labels = regime_labels(tables[10]["candidate"].dates, evidence)
    for name in REGIME_NAMES:
        assert sum(part["regime_intervals"][name] for part in partitions.values()) == (
            np.sum(labels == name)
        )
    for fold in result["folds"]:
        card = fold["cost_levels"]["10"]["regimes"]
        assert card["regime_intervals_reconcile"] is True
        assert card["regime_order"] == list(REGIME_NAMES)
        assert (
            sum(regime["return_intervals"] for regime in card["regimes"].values()) == 4
        )
        empty = card["regimes"]["below_200_mean_low_volatility"]
        assert empty["return_intervals"] == 0
        assert empty["candidate_beats_all_primary_comparators"] is None
        assert empty["rows"]["incumbent"]["log_growth_contribution"] is None
        for account, row in fold["cost_levels"]["10"]["performance"]["rows"].items():
            contribution = sum(
                regime["rows"][account]["log_growth_contribution"] or 0.0
                for regime in card["regimes"].values()
            )
            assert contribution == pytest.approx(np.log1p(row["total_return"]))


# A short series reports zero complete folds and never implies an assessed result.
def test_insufficient_history_preserves_full_sample_and_reports_no_folds():
    tables, evidence = _fold_inputs(intervals=7)
    result = _fold_report(tables, evidence)
    assert result["status"] == "insufficient_complete_folds"
    assert result["folds"] == []
    assert result["coverage"]["partitions"]["reference_prefix"]["return_intervals"] == 7
    assert result["coverage"]["all_intervals_accounted_for"] is True
    assert result["independent_validation"] is False
    assert result["adoption_eligible"] is False
    assert result["refit_performed"] is False


# A high-scoring fold still cannot turn an examined study into new validation.
def test_successful_diagnostic_cannot_claim_independent_validation_or_adoption():
    tables, evidence = _fold_inputs()
    for cost in (10, 25):
        tables[cost]["QQQ"] = tables[cost]["SPY"]
    result = _fold_report(tables, evidence)
    assert all(
        fold["cost_levels"]["10"]["performance"]["primary_objective"]["passes"]
        for fold in result["folds"]
    )
    assert result["analysis"] == "post_hoc_chronological_stability"
    assert result["independent_validation"] is False
    assert result["adoption_eligible"] is False
    assert result["refit_performed"] is False


# Equal local account growth is a visible tie and never passes the strict objective.
def test_fold_ties_are_distinct_from_wins_and_report_is_serializable():
    tables, evidence = _fold_inputs()
    for cost in (10, 25):
        tables[cost]["candidate"] = tables[cost]["incumbent"]
    result = _fold_report(tables, evidence, train_size=np.int64(5))
    for fold in result["folds"]:
        for cost in ("10", "25"):
            block = fold["cost_levels"][cost]
            assert block["comparisons"]["candidate"]["incumbent"] == {
                "net_total_return_difference": 0.0,
                "strict_win": False,
                "tie": True,
            }
            assert block["performance"]["primary_objective"]["passes"] is False
    assert json.loads(json.dumps(result, allow_nan=False)) == result


# Missing cost levels, mismatched grids, and unequal account sets invalidate comparison.
def test_fold_scorecard_requires_complete_matched_cost_tables():
    tables, evidence = _fold_inputs()
    with pytest.raises(ValueError, match="Both 10 and 25"):
        _fold_report({10: tables[10]}, evidence)
    shifted = {
        name: replace(curve, dates=curve.dates + np.timedelta64(1, "D"))
        for name, curve in tables[25].items()
    }
    with pytest.raises(ValueError, match="across both cost levels"):
        _fold_report({10: tables[10], 25: shifted}, evidence)
    tables[25]["additional_control"] = tables[25]["SPY"]
    with pytest.raises(ValueError, match="same accounts"):
        _fold_report(tables, evidence)


# Missing marks, wrong costs, and omitted sessions remain fatal within each cost table.
@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("mark", "account marks"),
        ("cost", "execution costs differ"),
        ("session", "account dates differ"),
        ("benchmark", "missing required accounts"),
    ],
)
def test_fold_scorecard_retains_existing_fail_closed_account_checks(defect, message):
    tables, evidence = _fold_inputs()
    curve = tables[25]["QQQ"]
    if defect == "mark":
        equity = curve.equity.copy()
        equity[10] = np.nan
        tables[25]["QQQ"] = replace(curve, equity=equity)
    elif defect == "cost":
        tables[25]["QQQ"] = replace(curve, cost_bps=0)
    elif defect == "session":
        tables[25]["QQQ"] = replace(curve, dates=curve.dates + np.timedelta64(1, "D"))
    else:
        del tables[25]["QQQ"]
    with pytest.raises(ValueError, match=message):
        _fold_report(tables, evidence)


# Shared missing account sessions must not masquerade as valid one-session observations.
def test_fold_scorecard_rejects_shared_gaps_and_keeps_unknown_warmup():
    tables, evidence = _fold_inputs()
    shortened = {
        cost: {
            name: replace(
                curve,
                dates=curve.dates[::2],
                equity=curve.equity[::2],
                invested_fraction=curve.invested_fraction[::2],
                largest_position_fraction=curve.largest_position_fraction[::2],
            )
            for name, curve in curves.items()
        }
        for cost, curves in tables.items()
    }
    with pytest.raises(ValueError, match="contiguous"):
        _fold_report(shortened, evidence)
    evidence = replace(
        evidence,
        dates=evidence.dates[-22:],
        spy_adjusted_closes=evidence.spy_adjusted_closes[-22:],
    )
    result = _fold_report(tables, evidence)
    for fold in result["folds"]:
        assert fold["evaluation"]["regime_intervals"]["unknown_or_unavailable"] == 4


# Later prices and account outcomes cannot alter an earlier completed diagnostic fold.
def test_earlier_folds_are_invariant_to_future_evidence_and_outcomes():
    tables, evidence = _fold_inputs()
    baseline = _fold_report(tables, evidence)
    modified = {}
    for cost, curves in tables.items():
        modified[cost] = {}
        for name, curve in curves.items():
            equity = curve.equity.copy()
            equity[13:] *= np.linspace(0.8, 1.2, len(equity[13:]))
            modified[cost][name] = replace(curve, equity=equity)
    closes = evidence.spy_adjusted_closes.copy()
    first_ending = tables[10]["candidate"].dates[12]
    start = int(np.searchsorted(evidence.dates, first_ending))
    closes[start:] *= np.linspace(0.5, 2, len(closes[start:]))
    changed = _fold_report(modified, replace(evidence, spy_adjusted_closes=closes))
    assert changed["folds"][0] == baseline["folds"][0]


# Session geometry cannot accept booleans, fractions, or negative lengths.
@pytest.mark.parametrize(
    ("parameter", "value", "message"),
    [
        ("train_size", True, "must be an integer"),
        ("test_size", 2.5, "must be an integer"),
        ("horizon", 0, "sizes and horizon"),
        ("embargo", -1, "sizes and horizon"),
    ],
)
def test_fold_geometry_requires_valid_session_counts(parameter, value, message):
    tables, evidence = _fold_inputs()
    with pytest.raises(ValueError, match=message):
        _fold_report(tables, evidence, **{parameter: value})
