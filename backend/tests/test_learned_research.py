"""Acceptance of the conditional study's information and account boundaries."""

from dataclasses import replace

import numpy as np
import pytest

from backend.market import learned_policy as lp
from backend.market import learned_research as research
from backend.market.panel import Panel
from backend.tests.test_learned_policy import _inputs


# Supply a flat, complete market with twenty candidate names and two controls.
def panel(rows=330):
    calendar = np.arange("2020-01-01", "2022-01-01", dtype="datetime64[D]")
    dates = calendar[np.is_busday(calendar)][:rows]
    tickers = tuple(f"S{i:02}" for i in range(20)) + ("SPY", "QQQ")
    prices = np.full((rows, len(tickers)), 100.0)
    return Panel(
        dates,
        tickers,
        prices.copy(),
        prices + 1,
        prices - 1,
        prices.copy(),
        prices.copy(),
        np.full_like(prices, 1000),
        {},
        "SPY",
    )


# Supply already-made forecasts to isolate the account acceptance cases.
def forecasts(data):
    shape = data.inputs.membership.shape
    rank = lp.Forecasts(
        np.ones(shape),
        data.panel.dates,
        np.arange(shape[0]) - 1,
        (),
        data.panel.dates,
        data.panel.tickers,
        "retrospective-price",
    )
    brake = replace(rank, values=np.zeros(shape[0]), tickers=())
    return rank, brake


# Preserve market-wide levels while ranking genuine cross-sectional evidence.
def test_market_features_are_not_erased_by_stock_ranking():
    inputs = _inputs(30)
    raw = inputs.features.copy()
    raw[:, :, 1] = np.arange(30)[:, None] / 100
    result = lp.cross_sectional_ranks(
        replace(inputs, features=raw, rank_features=(True, False))
    )
    np.testing.assert_array_equal(result[:, 1, 1], raw[:, 1, 1])
    assert result[20, 1, 1] != result[25, 1, 1]
    with pytest.raises(ValueError, match="rank-feature mask"):
        lp.validate(replace(inputs, rank_features=(True,)))


# A retrospective model cannot be passed into the desk target adapter.
def test_reconstructed_forecasts_are_blocked_from_desk_targets():
    inputs = replace(_inputs(170), evidence_basis="retrospective-price")
    result = lp.walk_forward_ranker(inputs, first_training_sessions=45)
    assert result.evidence_basis == "retrospective-price"
    with pytest.raises(ValueError, match="retrospective forecasts"):
        lp.policy_targets(None, result, 100, policy=lp.POLICY_RANK)


# A later split and changed future prices cannot alter earlier features.
def test_features_are_split_invariant_and_prefix_causal():
    original = panel()
    base = research.prepare(original)
    split = replace(
        original,
        open=original.open.copy(),
        high=original.high.copy(),
        low=original.low.copy(),
        close=original.close.copy(),
    )
    for name in ("open", "high", "low", "close"):
        getattr(split, name)[290:, :20] /= 10
    observed = research.prepare(split)
    np.testing.assert_allclose(
        base.inputs.features, observed.inputs.features, equal_nan=True
    )
    changed = replace(original, adj_close=original.adj_close.copy())
    changed.adj_close[310:, :20] *= 9
    extended = research.prepare(changed)
    np.testing.assert_allclose(
        base.inputs.features[:310], extended.inputs.features[:310], equal_nan=True
    )


# Training excludes any outcome crossing the final holdout's first session.
def test_holdout_labels_are_removed_before_any_monthly_refit():
    days = panel().dates
    cutoff = days[300]
    values = np.ones((len(days), 3))
    labels, when = research.training_labels(values, days, 11, cutoff)
    assert np.isfinite(labels[288]).all()
    assert np.isnan(labels[289:]).all()
    assert np.all(when[np.isfinite(labels)] < cutoff)
    assert np.all(values == 1)


# Changing held-out returns cannot change any model trained before the holdout.
def test_heldout_outcomes_cannot_change_later_monthly_fit_hashes():
    inputs = replace(_inputs(170), evidence_basis="retrospective-price")
    cutoff = inputs.dates[100]
    labels, when = research.training_labels(
        lp.relative_open_labels(inputs), inputs.dates, 11, cutoff
    )
    first = lp.walk_forward_ranker(
        inputs,
        first_training_sessions=45,
        observed_labels=labels,
        labels_recorded_on=when,
    )
    opens = inputs.adjusted_open.copy()
    features = inputs.features.copy()
    opens[100:, 1:] *= 15
    features[100:, 1:] *= 15
    changed = replace(inputs, adjusted_open=opens, features=features)
    changed_labels, changed_when = research.training_labels(
        lp.relative_open_labels(changed), inputs.dates, 11, cutoff
    )
    second = lp.walk_forward_ranker(
        changed,
        first_training_sessions=45,
        observed_labels=changed_labels,
        labels_recorded_on=changed_when,
    )
    assert first.model_hash
    assert first.model_hash == second.model_hash
    scored = ~np.isnat(first.fit_session)
    assert np.all(first.last_training_label_end[scored] < 100)


# A next-open buyer receives no return from a gap that occurred before its fill.
def test_next_open_gap_and_costs_are_accounted_once():
    source = panel()
    data = research.prepare(source)
    rank, brake = forecasts(data)
    spy = source.index("SPY")
    source.open[261:, spy] = 200
    source.close[261:, spy] = 200
    source.adj_close[261:, spy] = 200
    result = research.replay(data, rank, brake, 260, "SPY", 10)
    assert result["nav"][0] == 1
    np.testing.assert_allclose(result["nav"][1:], 1 / 1.001)
    assert len(result["decisions"]) == 1
    assert np.all(result["cash"] >= 0)


# Rotations use existing cash; same-open sale proceeds fund the next day's retry.
def test_rotation_waits_for_sale_cash_without_daily_rebalancing():
    data = research.prepare(panel())
    scores = np.zeros_like(data.momentum)
    scores[:280, :10] = 1
    scores[280:, 10:20] = 2
    data = replace(data, momentum=scores)
    rank, brake = forecasts(data)
    result = research.replay(data, rank, brake, 260, "momentum120", 0)
    assert result["cash"][281 - 260] == pytest.approx(1)
    assert result["cash"][282 - 260] == pytest.approx(0, abs=1e-12)
    assert result["turnover"][281 - 260] == pytest.approx(1)
    assert result["turnover"][282 - 260] == pytest.approx(1)
    assert len(result["decisions"]) == 5
    broken = replace(data.panel, adj_close=data.panel.adj_close.copy())
    broken.adj_close[283, 10] = np.nan
    with pytest.raises(ValueError, match="missing required price"):
        research.replay(replace(data, panel=broken), rank, brake, 260, "momentum120", 0)


# Segment metrics include the first day's return without restarting holdings.
def test_metrics_include_boundary_return_and_report_insufficient_windows():
    dates = np.arange("2026-07-30", "2026-08-05", dtype="datetime64[D]")
    path = {
        "dates": dates,
        "nav": np.array([1, 1, 0.8, 0.8, 0.8, 0.8]),
        "turnover": np.zeros(6),
        "cash": np.zeros(6),
    }
    stats = research.metrics(path, "2026-08-01")
    assert stats["max_drawdown"] == pytest.approx(-0.2)
    assert stats["transitions"] == 4
    assert research.rolling_wins(path, path) == {"windows": 0, "win_fraction": None}
