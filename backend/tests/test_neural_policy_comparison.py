"""Ranking experiments must inherit the actual live account path and causal cutoffs."""

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import paper, risk, simulate
from backend.market import neural_policy_comparison as study
from backend.tests.test_trading_simulate import _report


# Supply a dated hypothetical model that exactly reproduces the rule's own scores.
def evidence_for(report):
    rows, names = report.scores.shape
    return study.ForecastEvidence(
        dates=report.panel.dates.copy(),
        tickers=report.panel.tickers,
        values=report.scores.copy(),
        fit_on=np.full(rows, np.datetime64("2023-12-31")),
        training_label_end=np.full(rows, np.datetime64("2023-12-29")),
        selection_label_end=np.full(rows, np.datetime64("2023-12-30")),
        feature_available_on=np.broadcast_to(
            report.panel.dates[:, None], (rows, names)
        ).copy(),
        model_sha256="a" * 64,
        input_sha256="b" * 64,
    )


# Compare all trade fields, including explicit missing entry weights.
def assert_trades_equal(actual, expected):
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected, strict=True):
        assert (left.ticker, left.opened, left.closed, left.grade, left.reason) == (
            right.ticker,
            right.opened,
            right.closed,
            right.grade,
            right.reason,
        )
        np.testing.assert_array_equal(
            [left.weight, left.ret], [right.weight, right.ret]
        )


# Same scores reproduce the live ledger, including event cuts and restores.
@pytest.mark.parametrize("policy", study.POLICIES)
@pytest.mark.parametrize("cost_bps", [0, 10, 25])
def test_same_scores_reproduce_real_live_account_exactly(cost_bps, policy):
    report = _report()
    events = np.ones(len(report.panel.dates))
    events[95:110] = 0.5
    before = report.scores.copy()
    result = study.compare(
        report,
        evidence_for(report),
        since=date(2024, 1, 1),
        event_exposure=events,
        cost_bps=cost_bps,
        policy=policy,
    )
    oracle = simulate.run(
        report,
        since=date(2024, 1, 1),
        rebalance=paper.REBALANCE_EVERY,
        use_exits=False,
        cost_bps=cost_bps,
        event_exposure=events,
        event_lifecycle=True,
        **simulate.LIVE_POLICY,
    )
    assert oracle.trades
    assert np.max(oracle.invested) > 0
    no_event = simulate.run(
        report,
        since=date(2024, 1, 1),
        rebalance=paper.REBALANCE_EVERY,
        use_exits=False,
        cost_bps=cost_bps,
        event_exposure=np.ones(len(events)),
        event_lifecycle=True,
        **simulate.LIVE_POLICY,
    )
    assert not np.array_equal(oracle.equity, no_event.equity)
    for name in ("incumbent", "candidate"):
        actual = result[name]
        np.testing.assert_array_equal(actual.equity, oracle.equity)
        np.testing.assert_array_equal(actual.returns, oracle.returns)
        assert_trades_equal(actual.trades, oracle.trades)
        assert actual.traded == oracle.traded
    np.testing.assert_array_equal(report.scores, before)
    assert result["adoption_eligible"] is False


# Blend both rankings equally and preserve every gap in incumbent evidence.
def test_blend_uses_equal_cross_sectional_ranks_and_incumbent_coverage():
    report = _report()
    evidence = evidence_for(report)
    report.scores[100] = np.arange(report.scores.shape[1], dtype=float)
    evidence.values[100] = report.scores[100][::-1]
    report.scores[100, 0] = np.nan
    actual = study.candidate_scores(report, evidence, study.POLICY_BLEND)
    common = np.isfinite(report.scores) & np.isfinite(evidence.values)
    expected = study.baselines.rank_blend(
        np.where(common, report.scores, np.nan),
        np.where(common, evidence.values, np.nan),
    )
    np.testing.assert_array_equal(actual, expected)
    assert np.isnan(actual[100, 0])
    assert np.isfinite(actual[100, 1:]).all()


# An unregistered candidate cannot reach the shared account simulator.
def test_unknown_comparison_policy_is_rejected_before_account_runs(monkeypatch):
    report = _report()
    calls = []
    monkeypatch.setattr(simulate, "run", lambda *args, **kwargs: calls.append(1))
    with pytest.raises(ValueError, match="unknown neural comparison policy"):
        study.compare(
            report,
            evidence_for(report),
            since=date(2024, 1, 1),
            event_exposure=np.ones(len(report.panel.dates)),
            cost_bps=10,
            policy="selected-after-seeing-results",
        )
    assert calls == []


# Reject future features or fitting outcomes before either account runs.
@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("feature_available_on", "features were unavailable"),
        ("fit_on", "later model"),
        ("training_label_end", "outcomes must end before fitting"),
        ("selection_label_end", "outcomes must end before fitting"),
    ],
)
def test_future_information_cannot_enter_either_side(field, message, monkeypatch):
    report = _report()
    evidence = evidence_for(report)
    changed = np.array(getattr(evidence, field), copy=True)
    changed[0] = np.datetime64("2025-01-01")
    evidence = replace(evidence, **{field: changed})
    calls = []
    monkeypatch.setattr(simulate, "run", lambda *args, **kwargs: calls.append(1))
    with pytest.raises(ValueError, match=message):
        study.compare(
            report,
            evidence,
            since=date(2024, 1, 1),
            event_exposure=np.ones(len(report.panel.dates)),
            cost_bps=10,
        )
    assert calls == []


# A missing prediction cannot silently remove a difficult ticker from only one policy.
def test_missing_forecast_invalidates_common_window():
    report = _report()
    evidence = evidence_for(report)
    evidence.values[25, 0] = np.nan
    with pytest.raises(ValueError, match="common comparison window"):
        study.compare(
            report,
            evidence,
            since=date(2024, 1, 1),
            event_exposure=np.ones(len(report.panel.dates)),
            cost_bps=10,
        )


# Future scores cannot rewrite earlier orders or returns in the shared account.
def test_future_forecasts_do_not_rewrite_prefix():
    report = _report()
    first = evidence_for(report)
    other = replace(first, values=first.values.copy())
    other.values[120:, 1] = 100
    options = dict(
        since=date(2024, 1, 1),
        event_exposure=np.ones(len(report.panel.dates)),
        cost_bps=10,
    )
    before = study.compare(report, first, **options)["candidate"]
    after = study.compare(report, other, **options)["candidate"]
    assert before.trades
    assert np.max(before.invested[:120]) > 0
    np.testing.assert_array_equal(before.equity[:121], after.equity[:121])
    assert not np.array_equal(before.equity[121:], after.equity[121:])
    cutoff = str(report.panel.dates[120])
    early = [
        trade for trade in before.trades if trade.closed and trade.closed <= cutoff
    ]
    later = [trade for trade in after.trades if trade.closed and trade.closed <= cutoff]
    assert_trades_equal(early, later)


# Neural scores cannot add a ticker absent from the incumbent's ranking evidence.
def test_neural_preserves_incumbent_score_coverage():
    report = _report()
    report.scores[:, 0] = np.nan
    evidence = evidence_for(report)
    evidence.values[:, 0] = 100.0
    study.validate(report, evidence, date(2024, 1, 1))
    actual = study._allocator_for(evidence)(report, report.panel, risk.BOOK_CONFIG, 100)
    expected = simulate._targets(report, report.panel, risk.BOOK_CONFIG, 100)
    np.testing.assert_array_equal(actual, expected)
    assert actual[0] == 0


# Subday timestamps must be resolved to actual available sessions upstream.
@pytest.mark.parametrize(
    "field",
    [
        "dates",
        "fit_on",
        "training_label_end",
        "selection_label_end",
        "feature_available_on",
    ],
)
def test_subday_provenance_is_not_silently_truncated(field):
    report = _report()
    evidence = evidence_for(report)
    timestamp = getattr(evidence, field).astype("datetime64[h]")
    evidence = replace(evidence, **{field: timestamp + np.timedelta64(23, "h")})
    with pytest.raises(ValueError, match="daily session dates required"):
        study.validate(report, evidence, date(2024, 1, 1))
