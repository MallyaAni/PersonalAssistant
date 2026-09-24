"""The published live-policy simulation cannot turn absent prices into returns."""

import numpy as np
import pytest

from backend.agents.trading.desk import paper, simulate
from backend.tests.test_trading_simulate import _report


# Keep a known position so a missing quote cannot be mistaken for no exposure.
def _fixed_position(*args):
    return np.array([0.15, 0, 0, 0, 0, 0])


# A held mark must fail the full live execution path, including its event cycle.
@pytest.mark.parametrize("bad_price", [np.nan, np.inf, 0.0, -1.0])
@pytest.mark.parametrize("event_cycle", [False, True])
def test_live_policy_rejects_unavailable_held_valuation(bad_price, event_cycle):
    closes = np.full((50, 6), 100.0)
    closes[25, 0] = bad_price
    report = _report(closes)
    exposure = np.ones(50)
    if event_cycle:
        exposure[23:28] = 0.5
    with pytest.raises(ValueError, match="held valuation unavailable.*N0"):
        simulate.run(
            report,
            allocator=_fixed_position,
            use_exits=False,
            rebalance=paper.REBALANCE_EVERY,
            event_exposure=exposure,
            event_lifecycle=True,
            **simulate.LIVE_POLICY,
        )


# An unheld missing symbol does not erase a perfectly observable account return.
def test_missing_unheld_symbol_preserves_live_account_path():
    clean = np.full((50, 6), 100.0)
    missing = clean.copy()
    missing[25, 4] = np.nan
    options = dict(
        allocator=_fixed_position,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        **simulate.LIVE_POLICY,
    )
    expected = simulate.run(_report(clean), **options)
    actual = simulate.run(_report(missing), **options)
    np.testing.assert_array_equal(actual.equity, expected.equity)
    assert np.isfinite(actual.equity).all()


# Actual held-price changes still produce returns; the guard does not freeze marks.
def test_observed_loss_is_retained_in_live_account_path():
    closes = np.full((50, 6), 100.0)
    closes[25:, 0] = 90.0
    actual = simulate.run(
        _report(closes),
        allocator=_fixed_position,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        **simulate.LIVE_POLICY,
    )
    assert actual.returns[25] == pytest.approx(-0.015 / 0.99985)
    assert actual.returns[26] == pytest.approx(0.0)
