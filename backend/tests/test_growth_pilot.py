"""Causal timing, funded accounting and regime attribution for the research pilot."""

import numpy as np
import pytest

from backend.market import growth_pilot as gp
from backend.market.panel import Panel


# Supply a tiny explicit price path without a production datastore.
def sample(prices):
    prices = np.asarray(prices, dtype=float)
    rows, names = prices.shape
    return gp.Dataset(
        np.arange(
            "2026-06-15", np.datetime64("2026-06-15") + rows, dtype="datetime64[D]"
        ),
        prices,
        np.ones((rows, names, 8)),
        np.ones((rows, names), dtype=bool),
        np.ones((rows, 11)),
        tuple(str(i) for i in range(names)),
        0,
    )


# A decision cannot capture the price jump before its delayed execution.
def test_next_close_execution_does_not_capture_prior_jump():
    data = sample([[100], [200], [220]])
    holdings, cash, nav, reward, turnover = gp.transition(
        data, 0, 2, np.zeros(1), 1.0, np.ones(1), 0.0
    )
    assert nav == pytest.approx([1.0, 1.1])
    assert holdings.sum() + cash == pytest.approx(1.1)
    assert reward == pytest.approx(np.log(1.1))
    assert turnover == pytest.approx(1.0)


# Existing holdings bear overnight losses before a pending sale can execute.
def test_pending_cash_action_cannot_avoid_pre_execution_loss():
    data = sample([[100], [80], [60]])
    _, cash, nav, _, _ = gp.transition(data, 0, 2, np.ones(1), 0.0, np.zeros(1), 0.0)
    assert nav == pytest.approx([0.8, 0.8])
    assert cash == pytest.approx(0.8)


# Entry and exit costs are charged exactly once and never borrow cash.
def test_costs_are_funded_and_paid_once():
    holdings, cash, _ = gp.rebalance(np.zeros(1), 1.0, np.ones(1), 0.01)
    assert holdings[0] == pytest.approx(1 / 1.01)
    assert cash >= -1e-12
    _, cash, _ = gp.rebalance(holdings, cash, np.zeros(1), 0.01)
    assert cash == pytest.approx(0.99 / 1.01)


# Missing held prices invalidate results rather than becoming flat returns.
def test_missing_held_price_fails_closed():
    with pytest.raises(ValueError, match="Missing held"):
        gp.mark(np.array([1.0, 0.0]), np.array([10.0, 10.0]), np.array([np.nan, 20.0]))
    assert gp.mark(
        np.array([0.0, 1.0]), np.array([10.0, 10.0]), np.array([np.nan, 20.0])
    ).tolist() == [0.0, 2.0]


# Small universes leave spare cash rather than breaching the position cap.
def test_basket_caps_and_missing_scores():
    weights = gp.basket(np.array([1.0, np.nan, 3.0]), np.ones(3, dtype=bool))
    assert weights.tolist() == [0.1, 0.0, 0.1]


# All supervised label endpoints remain strictly before the partition boundary.
def test_split_purges_label_endpoint():
    data = sample(np.ones((12, 2)))
    rows = gp.split_rows(data, "2026-06-15", "2026-06-24", horizon=5)
    assert rows.tolist() == [0, 1, 2, 3]
    assert np.all(data.dates[rows + 5] < np.datetime64("2026-06-24"))


# Report event-day returns separately and carry the original account into each period.
def test_regime_metrics_preserve_prior_nav():
    dates = [
        "2026-06-16",
        "2026-06-17",
        "2026-06-18",
        "2026-08-27",
        "2026-08-28",
        "2026-08-31",
    ]
    result = gp.regime_metrics(dates, [1.0, 0.9, 0.99, 1.1, 1.0, 1.2])
    assert result["june_statement_day"]["total_return"] == pytest.approx(-0.1)
    assert result["after_jackson_hole"]["total_return"] == pytest.approx(0.2)
    assert result["after_jackson_hole"]["transitions"] == 1


# Future prices cannot alter historical features, eligibility or market state.
def test_features_are_prefix_invariant():
    days = np.busday_offset("2023-01-02", np.arange(150))
    prices = np.exp(np.arange(150)[:, None] / 1000) * np.array([[100.0, 200.0]])
    panel = Panel(
        days,
        ("ABC", "SPY"),
        prices,
        prices,
        prices,
        prices,
        prices,
        np.ones_like(prices),
        {},
        "SPY",
    )
    before = gp.dataset(panel)
    changed = prices.copy()
    changed[140:] *= 10
    after = gp.dataset(
        Panel(
            days,
            panel.tickers,
            changed,
            changed,
            changed,
            changed,
            changed,
            panel.volume,
            {},
            "SPY",
        )
    )
    np.testing.assert_allclose(
        before.features[:140], after.features[:140], equal_nan=True
    )
    np.testing.assert_allclose(before.market[:140], after.market[:140], equal_nan=True)
    np.testing.assert_array_equal(before.eligible[:140], after.eligible[:140])


# A zero-investment strategy stays at its starting wealth under both cost levels.
@pytest.mark.parametrize("cost", [0.001, 0.003])
def test_cash_path_is_zero_growth(cost):
    data = sample(np.arange(1.0, 25.0).reshape(12, 2))
    result = gp.evaluate(
        data, np.arange(10), lambda t, holdings, cash: (np.zeros(2), "USD"), cost
    )
    assert result["metrics"]["total_return"] == pytest.approx(0.0)
    assert result["metrics"]["transitions"] == 10
