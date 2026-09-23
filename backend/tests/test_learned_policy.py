"""Causal acceptance cases for the experimental shadow policy."""

from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate, trend_brake
from backend.market import learned_policy as lp
from backend.tests.test_trading_simulate import NAMES, _report
from backend.tests.test_trading_trend_brake import _allocation, _benchmarks, _qqq


# Build an archived-style toy panel with dates and memberships known then.
def _inputs(rows: int = 170) -> lp.HistoricalInputs:
    calendar = np.arange(
        np.datetime64("2020-01-01"),
        np.datetime64("2021-12-31"),
        dtype="datetime64[D]",
    )
    dates = calendar[np.is_busday(calendar)][:rows]
    t = np.arange(rows, dtype=float)
    opens = np.column_stack(
        (100 + 0.05 * t, 50 + 0.14 * t + np.sin(t / 5), 40 + 0.08 * t + np.cos(t / 7))
    )
    features = np.stack((opens / opens[0], np.tile(t[:, None], (1, 3))), axis=2)
    published = np.broadcast_to(dates[:, None], opens.shape).copy()
    feature_published = np.broadcast_to(dates[:, None, None], features.shape).copy()
    membership = np.ones(opens.shape, dtype=int)
    return lp.HistoricalInputs(
        dates,
        ("SPY", "AAA", "BBB"),
        opens,
        published,
        features,
        feature_published,
        membership,
        published,
    )


# Fix the executable-open endpoints and reject an outcome without its end.
def test_relative_label_uses_next_open_and_open_t_plus_eleven():
    inputs = _inputs(30)
    y = lp.relative_open_labels(inputs)
    opens = inputs.adjusted_open
    expected = np.log(opens[11, 1] / opens[1, 1]) - np.log(opens[11, 0] / opens[1, 0])
    assert y[0, 1] == pytest.approx(expected)
    assert np.isnan(y[-11:, 1]).all()
    assert np.isnan(y[:, 0]).all()


# Refuse values first recorded after the decision, including revised opens.
def test_future_published_inputs_and_unknown_membership_are_not_backfilled():
    inputs = _inputs(35)
    revised = inputs.adjusted_open_recorded_on.copy()
    revised[2, 1] = inputs.dates[4]
    with pytest.raises(ValueError, match="adjusted open was not recorded"):
        lp.validate(replace(inputs, adjusted_open_recorded_on=revised))
    future = inputs.feature_recorded_on.copy()
    future[2, 1, 0] = inputs.dates[4]
    with pytest.raises(ValueError, match="feature was not recorded"):
        lp.validate(replace(inputs, feature_recorded_on=future))
    membership = inputs.membership.copy()
    membership[:20, 1] = -1
    unknown = replace(inputs, membership=membership)
    assert np.isnan(lp.relative_open_labels(unknown)[:20, 1]).all()
    assert np.isnan(lp.cross_sectional_ranks(unknown)[:20, 1]).all()


# The last training label must end before the block whose model scores it.
def test_monthly_fits_are_purged_and_future_rows_cannot_change_old_scores():
    inputs = _inputs()
    result = lp.walk_forward_ranker(inputs, first_training_sessions=45)
    scored = np.flatnonzero(np.isfinite(result.values[:, 1]))
    assert len(scored) > 0
    assert all(result.last_training_label_end[t] < t for t in scored)
    assert all(result.fit_session[t] <= inputs.dates[t] for t in scored)
    first_month = scored[:10]
    later = _inputs(210)
    changed_opens = later.adjusted_open.copy()
    changed_features = later.features.copy()
    changed_opens[170:, 1] *= 100
    changed_features[170:, 1, :] *= 100
    altered = replace(later, adjusted_open=changed_opens, features=changed_features)
    extended = lp.walk_forward_ranker(altered, first_training_sessions=45)
    np.testing.assert_array_equal(
        result.values[first_month], extended.values[first_month]
    )
    assert result.model_hash[0] == extended.model_hash[0]


# Missing or ambiguous cross-sectional inputs cannot acquire a ranked value.
def test_cross_sectional_ranks_preserve_missing_and_ties():
    inputs = _inputs(20)
    features = inputs.features.copy()
    features[3, 1, 0] = features[3, 2, 0]
    ranks = lp.cross_sectional_ranks(replace(inputs, features=features))
    assert ranks[3, 1, 0] == ranks[3, 2, 0] == 0.5
    assert np.isnan(ranks[:, 0]).all()


# A crash label needs all twenty future closes and uses the running peak.
def test_brake_labels_and_hysteresis_do_not_anticipate_missing_future():
    close = np.full(55, 100.0)
    close[8] = 108
    close[9] = 97
    labels = lp.future_drawdown_labels(close)
    assert labels[0] == 1.0
    assert np.isnan(labels[-20:]).all()
    p = np.array([np.nan, 0.46, 0.40, 0.30, np.nan, 0.29, 0.44, 0.45])
    np.testing.assert_array_equal(
        lp.brake_scale_path(p), [1, 0.5, 0.5, 0.5, 0.5, 1, 1, 0.5]
    )


# The learned risk fit must not see its own test-block crash or its labels.
def test_brake_walk_forward_purges_twenty_sessions():
    inputs = _inputs(170)
    t = np.arange(170)
    qqq = 100 + 2 * np.sin(t / 8)
    qqq[50:60] -= 15
    qqq[110:120] -= 15
    features = np.column_stack((qqq, np.sin(t / 9)))
    published = np.broadcast_to(inputs.dates[:, None], features.shape).copy()
    result = lp.walk_forward_brake(
        features, published, inputs.dates, qqq, inputs.dates, first_training_sessions=40
    )
    scored = np.flatnonzero(np.isfinite(result.values))
    assert len(scored) > 0
    assert all(result.last_training_label_end[t] < t for t in scored)
    changed = qqq.copy()
    changed[150:] = 5
    extended = lp.walk_forward_brake(
        features,
        published,
        inputs.dates,
        changed,
        inputs.dates,
        first_training_sessions=40,
    )
    np.testing.assert_array_equal(result.values[:145], extended.values[:145])
    late = inputs.dates.copy()
    late[4] = inputs.dates[5]
    with pytest.raises(ValueError, match="QQQ close was not recorded"):
        lp.walk_forward_brake(
            features, published, inputs.dates, qqq, late, first_training_sessions=40
        )


# Both shadow rankings must use the live risk engine's grade and name caps.
def test_shadow_targets_keep_the_shared_account_sizing_constraints():
    report = _report(np.full((320, NAMES), 100.0))
    rows, names = report.scores.shape
    forecasts = lp.Forecasts(
        np.broadcast_to(np.linspace(0, 1, names), (rows, names)).copy(),
        np.broadcast_to(report.panel.dates[0], rows).copy(),
        np.zeros(rows, dtype=int),
        ("synthetic",),
        report.panel.dates.copy(),
        report.panel.tickers,
    )
    for policy in (lp.POLICY_RANK, lp.POLICY_BLEND):
        targets = lp.policy_targets(report, forecasts, 250, policy=policy)
        assert np.isfinite(targets).all()
        assert targets.sum() > 0
        assert np.all(targets >= 0)
        assert np.max(targets) <= 0.15 + 1e-12
        assert targets[report.panel.index(report.panel.benchmark)] == 0
    invalid = replace(forecasts, last_training_label_end=np.full(rows, 250))
    with pytest.raises(ValueError, match="purged"):
        lp.policy_targets(report, invalid, 250, policy=lp.POLICY_RANK)
    wrong_order = replace(forecasts, tickers=tuple(reversed(report.panel.tickers)))
    with pytest.raises(ValueError, match="align"):
        lp.policy_targets(report, wrong_order, 250, policy=lp.POLICY_RANK)
    shadow = simulate.run(
        report,
        use_exits=False,
        allocator=lp.allocator_for(forecasts, lp.POLICY_RANK),
    )
    assert np.isfinite(shadow.equity).all()
    assert shadow.invested[1] == 0
    # The fill fee makes held weight slightly larger than the target cap.
    assert np.nanmax(shadow.top_weight) <= 0.151


# An externally learned ceiling must traverse exactly the fixed brake's
# accounting path, including its FOMC minimum and next-open fills.
def test_brake_override_uses_the_existing_execution_path():
    report = _report(np.full((320, NAMES), 100.0))
    event = np.ones(320)
    event[300:303] = 0.5
    kwargs = {
        "use_exits": False,
        "rebalance": 20,
        "allocator": _allocation,
        "event_exposure": event,
    }
    fixed = simulate.run(
        report,
        **kwargs,
        trend_brake=True,
        benchmark_prices=_benchmarks(report.panel),
    )
    override = np.where(trend_brake.risk_off_path(_qqq()), 0.5, 1.0)
    learned = simulate.run(report, **kwargs, brake_path_override=override)
    np.testing.assert_array_equal(learned.equity, fixed.equity)
    np.testing.assert_array_equal(learned.invested, fixed.invested)
    np.testing.assert_array_equal(learned.risk_off, fixed.risk_off)
    baseline = simulate.run(report, **kwargs)
    explicit_none = simulate.run(report, **kwargs, brake_path_override=None)
    np.testing.assert_array_equal(baseline.equity, explicit_none.equity)
    with pytest.raises(ValueError, match="choose the fixed"):
        simulate.run(
            report,
            **kwargs,
            trend_brake=True,
            brake_path_override=override,
            benchmark_prices=_benchmarks(report.panel),
        )
