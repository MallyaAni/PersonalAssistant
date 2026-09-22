"""The funded-plan projection, tested for economic consistency.

`plan_funded` sizes buys from the cash actually on hand - never from the
proceeds of the same day's sells - and reports `.cash` and `.executable` as
fractions of the post-fee NAV the returned order basket produces at the
reference prices, with the dollar balances behind them in
`projected_cash_amount` / `projected_equity`. These tests exercise the real
`plan_funded` with scenarios whose equity equals cash plus holdings, so every
asserted number is a closed-form projection of the same basket rather than a
reading of the old fee-free complement.
"""

import pytest

from backend.agents.trading.desk.allocation import AllocationDecision
from backend.agents.trading.desk.funded_execution import plan_funded

COST = 10.0 / 1e4


# A valid vol_trend decision wanting exactly `desired_weights`.
def _decision(desired_weights: dict[str, float]) -> AllocationDecision:
    """Return a funded decision wanting `desired_weights` of the account."""
    return AllocationDecision(
        version="portfolio-allocation/vol_trend/1",
        as_of="2026-09-01",
        desired_weights=desired_weights,
        cash=1.0 - sum(desired_weights.values()),
        available=True,
        reasons=("no risk reduction required",),
        missing=(),
        volatility=None,
        binding="none",
    )


# A pure buy from an all-cash account: 150 shares cost 15000 gross plus 15 in
# fees, leaving 84985 of cash against a 99985 post-fee NAV. The buy quantity
# is exactly the target 150, never trimmed by the fee.
def test_buy_projection_uses_post_fee_nav_and_exact_quantity():
    plan = plan_funded(
        _decision({"AAA": 0.15}),
        held={},
        prices={"AAA": 100.0},
        equity=100000.0,
        cash=100000.0,
        cost_bps=10,
    )
    buys = [o for o in plan.orders if o.side == "buy"]
    assert [(o.symbol, o.qty) for o in buys] == [("AAA", 150.0)]
    assert plan.projected_cash_amount == pytest.approx(
        100000.0 - 150 * 100.0 * (1 + COST)
    )
    assert plan.projected_equity == pytest.approx(
        plan.projected_cash_amount + 150 * 100.0
    )
    assert plan.projected_equity == pytest.approx(100000.0 - 150 * 100.0 * COST)
    assert plan.cash == pytest.approx(
        plan.projected_cash_amount / plan.projected_equity
    )
    assert plan.cash == pytest.approx(84985.0 / 99985.0)
    assert plan.executable["AAA"] == pytest.approx(150 * 100.0 / plan.projected_equity)
    assert plan.executable["AAA"] == pytest.approx(15000.0 / 99985.0)


# A pure sell: the net proceeds land in cash and the post-fee NAV drops by the
# sell fee, so the cash fraction reflects the credited proceeds, not the gross
# notional.
def test_sell_projection_credits_net_proceeds_to_cash():
    plan = plan_funded(
        _decision({"AAA": 0.5}),
        held={"AAA": 200.0},
        prices={"AAA": 100.0},
        equity=20000.0,
        cash=0.0,
        cost_bps=10,
    )
    sells = [o for o in plan.orders if o.side == "sell"]
    assert [(o.symbol, o.qty) for o in sells] == [("AAA", 100.0)]
    assert plan.projected_cash_amount == pytest.approx(100.0 * 100.0 * (1 - COST))
    assert plan.projected_equity == pytest.approx(
        plan.projected_cash_amount + 100.0 * 100.0
    )
    assert plan.projected_equity == pytest.approx(20000.0 - 100.0 * 100.0 * COST)
    assert plan.cash == pytest.approx(
        plan.projected_cash_amount / plan.projected_equity
    )
    assert plan.executable["AAA"] == pytest.approx(
        100.0 * 100.0 / plan.projected_equity
    )


# A mixed basket sells one name and buys another: the buy is sized from the
# pre-existing cash only - not from the same day's sale proceeds - so its
# quantity is the full target, and the projection reconciles cash, holdings
# and NAV against the fees on both legs.
def test_mixed_basket_projection_never_spends_sale_proceeds_on_buys():
    plan = plan_funded(
        _decision({"AAA": 0.05, "BBB": 0.25}),
        held={"AAA": 100.0, "BBB": 100.0},
        prices={"AAA": 100.0, "BBB": 100.0},
        equity=100000.0,
        cash=80000.0,
        cost_bps=10,
    )
    buys = [o for o in plan.orders if o.side == "buy"]
    sells = [o for o in plan.orders if o.side == "sell"]
    assert [(o.symbol, o.qty) for o in sells] == [("AAA", 50.0)]
    # The 150-share BBB buy is the full target: the 80000 of pre-existing cash
    # covers it even though the AAA sale also lands today.
    assert [(o.symbol, o.qty) for o in buys] == [("BBB", 150.0)]
    sell_notional = 50.0 * 100.0
    buy_notional = 150.0 * 100.0
    assert plan.projected_cash_amount == pytest.approx(
        80000.0 + sell_notional * (1 - COST) - buy_notional * (1 + COST)
    )
    final_value = 50.0 * 100.0 + 250.0 * 100.0
    assert plan.projected_equity == pytest.approx(
        plan.projected_cash_amount + final_value
    )
    assert plan.projected_equity == pytest.approx(
        100000.0 - (sell_notional + buy_notional) * COST
    )
    assert plan.cash == pytest.approx(
        plan.projected_cash_amount / plan.projected_equity
    )
    assert plan.executable["AAA"] == pytest.approx(50.0 * 100.0 / plan.projected_equity)
    assert plan.executable["BBB"] == pytest.approx(
        250.0 * 100.0 / plan.projected_equity
    )


# A held name with no usable price blocks sizing: no orders, no executable
# weights, and no made-up cash or NAV projection - both dollar projections and
# the cash fraction are explicitly None with the reason recorded.
def test_missing_held_valuation_exposes_no_made_up_projection():
    plan = plan_funded(
        _decision({"AAA": 0.5}),
        held={"AAA": 100.0},
        prices={},
        equity=10000.0,
        cash=5000.0,
        cost_bps=10,
    )
    assert plan.orders == ()
    assert plan.executable == {}
    assert plan.cash is None
    assert plan.projected_cash_amount is None
    assert plan.projected_equity is None
    assert any("held valuation unavailable for AAA" in b for b in plan.blocked)


# The headline ineligible-index case: holding 400 SPY at 200 (0.8 of the
# 100000 equity) against a desired 0.4, with eligibility false. The false flag
# prohibits increasing SPY, not exiting down to the requested quantity, so the
# plan sells the 200-share reduction and no more, and the projection stays the
# closed-form post-fee NAV of that basket.
def test_ineligible_spy_partial_cut_preserves_requested_reduction():
    plan = plan_funded(
        _decision({"SPY": 0.4}),
        held={"SPY": 400.0},
        prices={"SPY": 200.0},
        equity=100000.0,
        cash=20000.0,
        cost_bps=10,
        whole_shares=False,
        index_eligible=False,
    )
    sells = [o for o in plan.orders if o.symbol == "SPY" and o.side == "sell"]
    assert [(o.symbol, o.qty) for o in sells] == [("SPY", 200.0)]
    sell_notional = 200.0 * 200.0
    assert plan.projected_cash_amount == pytest.approx(
        20000.0 + sell_notional * (1 - COST)
    )
    final_value = 200.0 * 200.0
    assert plan.projected_equity == pytest.approx(
        plan.projected_cash_amount + final_value
    )
    assert plan.projected_equity == pytest.approx(100000.0 - sell_notional * COST)
    assert plan.cash == pytest.approx(
        plan.projected_cash_amount / plan.projected_equity
    )
    assert plan.executable["SPY"] == pytest.approx(final_value / plan.projected_equity)
    assert not any("index not eligible" in m for m in plan.missing)


# Ineligible SPY across the quantity cases and both quantity modes: eligibility
# is a ceiling, never an exit mandate. An increase beyond the holding is blocked
# (no buy, no forced sell); a desired equal to the holding is a no-op; a desired
# below it sells exactly the requested reduction; and an explicit desired of
# zero exits the whole holding. Whole-share rounding changes none of the
# quantities, which are integral here.
@pytest.mark.parametrize("whole_shares", [False, True])
@pytest.mark.parametrize(
    ("desired_weight", "expected_sell", "expect_blocked"),
    [
        (0.9, 0.0, True),
        (0.8, 0.0, False),
        (0.4, 200.0, False),
        (0.0, 400.0, False),
    ],
)
def test_ineligible_spy_blocks_increases_but_honors_reductions(
    desired_weight, expected_sell, expect_blocked, whole_shares
):
    plan = plan_funded(
        _decision({"SPY": desired_weight}),
        held={"SPY": 400.0},
        prices={"SPY": 200.0},
        equity=100000.0,
        cash=20000.0,
        cost_bps=10,
        whole_shares=whole_shares,
        index_eligible=False,
    )
    spy_buys = [o for o in plan.orders if o.symbol == "SPY" and o.side == "buy"]
    spy_sells = sum(
        o.qty for o in plan.orders if o.symbol == "SPY" and o.side == "sell"
    )
    assert spy_buys == []
    assert spy_sells == pytest.approx(expected_sell)
    if expect_blocked:
        assert any("index not eligible" in m for m in plan.missing)
    else:
        assert not any("index not eligible" in m for m in plan.missing)
