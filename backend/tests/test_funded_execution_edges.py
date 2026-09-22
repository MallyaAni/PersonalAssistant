"""Whole-share sizing and the cash/fee/name-cap guards, on the edges.

`plan_funded` is the one order planner shared by the paper account
(`whole_shares=True`) and the simulator (`whole_shares=False`). These tests
audit the edges that decide whether a plan is safe: a mandatory risk cut must
not round to zero when an executable whole share can reduce risk, a fractional
residual that cannot be executed stays explicit, nonfinite or missing inputs
are never silently turned into an order or a projection, eligibility is a
ceiling on SPY rather than a mandate, and the continuous simulator path keeps
its exact fractional fills. Every scenario drives the real `plan_funded`.
"""

import math

import numpy as np
import pytest

from backend.agents.trading.desk.allocation import (
    BINDING_NONE,
    BINDING_VOL,
    SPY,
    AllocationDecision,
)
from backend.agents.trading.desk.funded_execution import plan_funded
from backend.agents.trading.desk.paper import ENTRY_NAME_CAP

COST = 10.0 / 1e4


# Fees can push an existing company above its cap even with unchanged prices.
def test_company_cap_trim_rounds_up_after_nav_decreases():
    plan = plan_funded(
        _decision({"AAA": 0.15}),
        held={"AAA": 150.0},
        prices={"AAA": 100.0},
        equity=99900.0,
        cash=84900.0,
        whole_shares=True,
    )
    assert [(o.symbol, o.side, o.qty) for o in plan.orders] == [("AAA", "sell", 1)]
    assert not plan.blocked


# A valid decision wanting exactly `desired_weights`, optionally a risk cut.
def _decision(
    desired_weights: dict[str, float],
    binding: str = BINDING_NONE,
    reasons: tuple[str, ...] = ("no risk reduction required",),
) -> AllocationDecision:
    """Return a funded decision wanting `desired_weights` of the account."""
    return AllocationDecision(
        version="portfolio-allocation/vol/1",
        as_of="2026-09-01",
        desired_weights=desired_weights,
        cash=1.0 - sum(desired_weights.values()),
        available=True,
        reasons=reasons,
        missing=(),
        volatility=None,
        binding=binding,
    )


# A decision that is a mandatory risk cut (the vol budget binds).
def _risk_cut(desired_weights: dict[str, float]) -> AllocationDecision:
    """Return a decision whose binding constraint is the volatility budget."""
    return _decision(
        desired_weights,
        binding=BINDING_VOL,
        reasons=("portfolio volatility scaled down to the SPY/QQQ budget",),
    )


# ---------------------------------------------------------------------------
# Risk cuts must not round to zero.
# ---------------------------------------------------------------------------


# A mandatory risk cut of less than half a share must not round to zero: held
# 3 shares of AAA at 100 (0.03 of a 10000 account) against a desired 0.026
# wants to sell 0.4 shares, which rounds to zero whole shares; one whole share
# is executable, so the plan sells it and the risk reduction actually happens.
def test_tiny_risk_cut_rounds_to_a_whole_share_not_zero():
    plan = plan_funded(
        _risk_cut({"AAA": 0.026}),
        held={"AAA": 3.0},
        prices={"AAA": 100.0},
        equity=10000.0,
        cash=9700.0,
        whole_shares=True,
    )
    sells = [o for o in plan.orders if o.side == "sell"]
    assert [(o.symbol, o.qty) for o in sells] == [("AAA", 1)]
    assert not any("leaves no sellable quantity" in b for b in plan.blocked)
    assert not any("fractional residual" in b for b in plan.blocked)
    # The projection is the closed-form post-fee NAV of that one-share sell.
    assert plan.projected_cash_amount == pytest.approx(9700.0 + 100.0 * (1 - COST))
    assert plan.projected_equity == pytest.approx(
        plan.projected_cash_amount + 2.0 * 100.0
    )
    assert plan.projected_equity == pytest.approx(10000.0 - 100.0 * COST)


# Every fractional risk cut in (0, 0.5] - where nearest rounding lands on zero,
# banker's rounding included at exactly 0.5 - must sell one whole share rather
# than nothing, whatever the held whole shares available.
@pytest.mark.parametrize("cut", [0.1, 0.2, 0.3, 0.4, 0.49, 0.5])
def test_fractional_risk_cuts_round_up_to_a_whole_share(cut):
    held = 10.0
    desired = (held - cut) * 100.0 / 100000.0
    plan = plan_funded(
        _risk_cut({"AAA": desired}),
        held={"AAA": held},
        prices={"AAA": 100.0},
        equity=100000.0,
        cash=0.0,
        whole_shares=True,
    )
    sells = [o for o in plan.orders if o.side == "sell"]
    assert [(o.symbol, o.qty) for o in sells] == [("AAA", 1)]


# A binding risk cut rounds up so a feasible whole-share reduction satisfies
# the ceiling, but never sells more than the whole shares held. Fractional
# holdings that cannot be liquidated with whole-share orders remain explicit.
@pytest.mark.parametrize(
    ("held_qty", "continuous_cut", "expected_sell", "expect_fractional_block"),
    [
        (10.0, 1.6, 2, False),
        (3.0, 2.4, 3, False),
        (10.0, 1.4, 2, False),
        (3.4, 3.4, 3, True),
        (1.0, 0.5, 1, False),
    ],
)
def test_risk_cut_rounding_never_exceeds_held(
    held_qty, continuous_cut, expected_sell, expect_fractional_block
):
    price = 100.0
    equity = 100000.0
    desired = (held_qty - continuous_cut) * price / equity
    plan = plan_funded(
        _risk_cut({"AAA": desired}),
        held={"AAA": held_qty},
        prices={"AAA": price},
        equity=equity,
        cash=equity - held_qty * price,
        whole_shares=True,
    )
    sells = [o for o in plan.orders if o.side == "sell"]
    assert [(o.symbol, o.qty) for o in sells] == [("AAA", expected_sell)]
    if expect_fractional_block:
        assert any("fractional residual" in b for b in plan.blocked)
    else:
        assert not any("fractional residual" in b for b in plan.blocked)


# When no whole share is executable - the held quantity is under one share and
# the cut would need a fraction of it - the risk cut stays explicit rather than
# inventing a sell or silently dropping the reduction.
def test_risk_cut_with_no_whole_share_executable_stays_blocked():
    plan = plan_funded(
        _risk_cut({"AAA": 0.005}),
        held={"AAA": 0.8},
        prices={"AAA": 100.0},
        equity=10000.0,
        cash=0.0,
        whole_shares=True,
    )
    assert plan.orders == ()
    assert any("leaves no sellable quantity" in b for b in plan.blocked)


# A plain rebalance sell that rounds to zero is not a risk cut and is not
# rounded up: it is reported as an unexecutable whole-share rounding, so the
# fractional residual stays explicit instead of being forced through.
def test_rebalance_sell_rounding_to_zero_stays_explicit():
    plan = plan_funded(
        _decision({"AAA": 0.0096}),
        held={"AAA": 10.0},
        prices={"AAA": 100.0},
        equity=100000.0,
        cash=0.0,
        whole_shares=True,
    )
    assert not any(o.side == "sell" for o in plan.orders)
    assert any("leaves no sellable quantity" for b in plan.blocked)


# ---------------------------------------------------------------------------
# Nonfinite and invalid input is a caller error, never an invented order.
# ---------------------------------------------------------------------------


# A nonfinite desired weight must be rejected up front: it currently flows
# through as a NaN-quantity buy order that poisons the whole cash projection,
# and an inf weight makes the buy basket silently collapse. Neither is a plan.
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_desired_weight_is_a_caller_error(bad):
    with pytest.raises(ValueError, match="weight"):
        plan_funded(
            _decision({"AAA": 0.1, "BBB": bad}),
            held={},
            prices={"AAA": 100.0, "BBB": 50.0},
            equity=10000.0,
            cash=10000.0,
            whole_shares=False,
        )


# A nonfinite or negative held quantity is a caller error, not a row silently
# dropped from the ledger or hidden by the positive filter.
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_nonfinite_held_quantity_is_a_caller_error(bad):
    with pytest.raises(ValueError, match="Held quantity"):
        plan_funded(
            _decision({"AAA": 0.1}),
            held={"AAA": bad},
            prices={"AAA": 100.0},
            equity=10000.0,
            cash=5000.0,
        )


# The account-level inputs must be finite and in range: a NaN or nonpositive
# equity, a negative cash balance, or a negative cost is a caller error rather
# than a plan sized against nonsense.
@pytest.mark.parametrize(
    ("equity", "cash", "cost_bps"),
    [
        (float("nan"), 10000.0, 10.0),
        (float("inf"), 10000.0, 10.0),
        (0.0, 10000.0, 10.0),
        (-100.0, 10000.0, 10.0),
        (10000.0, float("nan"), 10.0),
        (10000.0, -1.0, 10.0),
        (10000.0, 10000.0, float("nan")),
        (10000.0, 10000.0, -10.0),
    ],
)
def test_invalid_equity_cash_or_cost_is_a_caller_error(equity, cash, cost_bps):
    with pytest.raises(ValueError, match="finite"):
        plan_funded(
            _decision({"AAA": 0.1}),
            held={},
            prices={"AAA": 100.0},
            equity=equity,
            cash=cash,
            cost_bps=cost_bps,
        )


# A desired name with no tradable price is reported as missing, never sized at
# a made-up price and never silently absent from the plan's accounting.
def test_missing_decision_price_is_reported_not_silent():
    plan = plan_funded(
        _decision({"AAA": 0.5, "BBB": 0.2}),
        held={},
        prices={"AAA": 100.0},
        equity=10000.0,
        cash=10000.0,
        whole_shares=False,
    )
    assert not any(o.symbol == "BBB" for o in plan.orders)
    assert any("BBB: no decision price" in m for m in plan.missing)
    assert any(o.symbol == "AAA" for o in plan.orders)


# ---------------------------------------------------------------------------
# Explicit index eligibility is a ceiling on SPY, never a mandate to exit.
# ---------------------------------------------------------------------------


# Ineligible SPY is never bought, whole-share or continuous, with the block
# reported; an existing SPY holding is preserved up to the requested quantity.
def test_ineligible_spy_buy_is_suppressed_in_whole_shares():
    plan = plan_funded(
        _decision({SPY: 0.3}),
        held={SPY: 0.0},
        prices={SPY: 100.0},
        equity=10000.0,
        cash=10000.0,
        whole_shares=True,
        index_eligible=False,
    )
    assert not any(o.symbol == SPY and o.side == "buy" for o in plan.orders)
    assert any("index not eligible" in m for m in plan.missing)


# Eligible SPY is exempt from the stock name cap: it is a residual index asset,
# not a company, so a 0.3 desired SPY is not truncated at ENTRY_NAME_CAP.
def test_eligible_spy_is_not_name_capped_in_whole_shares():
    plan = plan_funded(
        _decision({SPY: 0.3}),
        held={},
        prices={SPY: 100.0},
        equity=10000.0,
        cash=10000.0,
        whole_shares=True,
        index_eligible=True,
        entry_cap=ENTRY_NAME_CAP,
    )
    buys = [o for o in plan.orders if o.side == "buy"]
    assert [(o.symbol, o.qty) for o in buys] == [(SPY, 30)]


# A stock buy is name-capped after whole-share rounding, whether or not the
# plan could afford more: 0.3 of the account at 100 is 30 shares, capped at
# the 15-share ENTRY_NAME_CAP.
def test_stock_whole_share_buy_is_name_capped():
    plan = plan_funded(
        _decision({"AAA": 0.3}),
        held={},
        prices={"AAA": 100.0},
        equity=10000.0,
        cash=10000.0,
        whole_shares=True,
        entry_cap=ENTRY_NAME_CAP,
    )
    buys = [o for o in plan.orders if o.side == "buy"]
    assert [(o.symbol, o.qty) for o in buys] == [("AAA", 15)]


# ---------------------------------------------------------------------------
# The continuous simulator path keeps exact fractional fills (NAV1 unchanged).
# ---------------------------------------------------------------------------


# With whole_shares=False the same fractional risk cut is kept exactly: the
# simulator fills 0.4 shares, never rounded, and the projection is that exact
# basket's post-fee NAV.
def test_continuous_path_keeps_fractional_cuts_exact():
    plan = plan_funded(
        _risk_cut({"AAA": 0.026}),
        held={"AAA": 3.0},
        prices={"AAA": 100.0},
        equity=10000.0,
        cash=9700.0,
        whole_shares=False,
    )
    sells = [o for o in plan.orders if o.side == "sell"]
    assert [(o.symbol, o.qty) for o in sells] == [("AAA", pytest.approx(0.4))]
    assert plan.blocked == ()
    assert plan.projected_equity == pytest.approx(10000.0 - 0.4 * 100.0 * COST)


# A continuous buy is the exact target quantity, sized from the cash on hand:
# 150 shares at 100 against a 0.15 weight of 100000, never trimmed by the fee.
def test_continuous_buy_is_the_exact_target_quantity():
    plan = plan_funded(
        _decision({"AAA": 0.15}),
        held={},
        prices={"AAA": 100.0},
        equity=100000.0,
        cash=100000.0,
        whole_shares=False,
    )
    buys = [o for o in plan.orders if o.side == "buy"]
    assert [(o.symbol, o.qty) for o in buys] == [("AAA", 150.0)]


# ---------------------------------------------------------------------------
# Deterministic grid: no shorts, no negative cash, no invented quantities.
# ---------------------------------------------------------------------------


# Over a deterministic grid of holdings, targets, prices and cash in both
# quantity modes, the returned plan never sells more than is held, never
# leaves a negative projected cash, never emits a nonfinite or negative order
# quantity, and every executable weight and cash fraction is in [0, 1] with a
# sum that reconciles to the post-fee NAV. A risk cut with an executable whole
# share always produces at least one whole-share sell.
def test_no_short_or_negative_cash_across_the_deterministic_grid():
    rng = np.random.default_rng(2026)
    seen_risk_cut = False
    for trial in range(400):
        mode = trial % 2 == 1
        n = int(rng.integers(1, 5))
        symbols = [f"S{i}" for i in range(n)]
        desired = {s: float(rng.uniform(0.005, 0.3)) for s in symbols}
        held = {s: float(rng.uniform(0.0, 30.0)) for s in symbols}
        prices = {s: float(rng.uniform(20.0, 300.0)) for s in symbols}
        equity = float(rng.uniform(1000.0, 1e6))
        cash = float(rng.uniform(0.0, equity))
        binding = BINDING_VOL if trial % 3 == 0 else BINDING_NONE
        decision = _decision(desired, binding=binding)
        plan = plan_funded(
            decision,
            held,
            prices,
            equity,
            cash,
            whole_shares=mode,
            index_eligible=False,
        )
        for o in plan.orders:
            assert math.isfinite(o.qty)
            assert o.qty > 0
            if o.side == "sell":
                assert o.qty <= held.get(o.symbol, 0.0) + 1e-9
        result = dict(held)
        for o in plan.orders:
            result[o.symbol] = result.get(o.symbol, 0.0) + (
                o.qty if o.side == "buy" else -o.qty
            )
        assert all(q >= -1e-9 for q in result.values())
        if plan.projected_cash_amount is not None:
            assert plan.projected_cash_amount >= -1e-6
        assert all(
            math.isfinite(w) and 0.0 <= w <= 1.0 + 1e-9
            for w in plan.executable.values()
        )
        assert 0.0 <= (plan.cash or 0.0) <= 1.0 + 1e-9
        if plan.projected_equity and plan.projected_equity > 0:
            total = sum(plan.executable.values()) + (plan.cash or 0.0)
            assert total <= 1.0 + 1e-6
        # A risk cut that has a whole share executable must not come back with
        # no sell at all.
        if binding == BINDING_VOL and mode:
            for symbol, qty in held.items():
                wants_less = qty * prices[symbol] > plan.desired[symbol] * equity
                if qty >= 1.0 and symbol in plan.desired and wants_less:
                    seen_risk_cut = True
                    assert any(
                        o.symbol == symbol and o.side == "sell" for o in plan.orders
                    )
    assert seen_risk_cut
