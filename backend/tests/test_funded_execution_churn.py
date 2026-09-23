"""Turnover discipline of the shared funded planner, on the real `plan_funded`.

The paper account asks `plan_funded` for whole shares, and a whole-share book
can only ever sit within half a share of a fractional target. The planner
therefore rounds every gap to the nearest whole share and treats a gap inside
that half-share band as no trade, on both sides: a sell is never rounded up
past the target so the next session buys the share back, and a buy is never
rounded up so the next session sells it. These tests walk the planner over
hundreds of sessions with the fills fed back into the book and assert on the
order stream that came back - the churn the old round-up rule produced was
only visible there, never in a single plan.
"""

import numpy as np
import pytest

from backend.agents.trading.desk.allocation import (
    BINDING_EVENT,
    BINDING_NONE,
    BINDING_VOL,
    AllocationDecision,
)
from backend.agents.trading.desk.funded_execution import plan_funded
from backend.agents.trading.desk.planner import MIN_TRADE

COST_BPS = 10.0
COST = COST_BPS / 1e4


# A valid decision wanting exactly `desired_weights`, optionally a risk cut.
def _decision(
    desired_weights: dict[str, float], binding: str = BINDING_NONE
) -> AllocationDecision:
    """Return a funded decision wanting `desired_weights` of the account."""
    reasons = (
        ("portfolio volatility scaled down to the SPY/QQQ budget",)
        if binding == BINDING_VOL
        else ("no risk reduction required",)
    )
    return AllocationDecision(
        version="portfolio-allocation/vol/1",
        as_of="2026-09-01",
        desired_weights=dict(desired_weights),
        cash=max(0.0, 1.0 - sum(desired_weights.values())),
        available=True,
        reasons=reasons,
        missing=(),
        volatility=None,
        binding=binding,
    )


# Fill one plan's orders at the reference prices, paying the fee one way, and
# return the new (held, cash) the next session sizes from.
def _fill(held, cash, orders, prices):
    """Return (held, cash) after executing `orders` at `prices` with fees."""
    held = dict(held)
    for order in orders:
        price = prices[order.symbol]
        if order.side == "buy":
            held[order.symbol] = held.get(order.symbol, 0.0) + order.qty
            cash -= order.qty * price * (1.0 + COST)
        else:
            held[order.symbol] = held.get(order.symbol, 0.0) - order.qty
            cash += order.qty * price * (1.0 - COST)
    held = {s: q for s, q in held.items() if q > 1e-9}
    assert cash >= -1e-6
    return held, max(0.0, cash)


# Walk the whole-share planner over `sessions` sessions against a fixed
# decision, with the fills fed back into the book, and return the per-session
# order lists. `wobble(t)` is the deterministic relative price move on session
# t, so the share targets drift by fractions of a share the way a real book's
# do between rebalances.
def _walk(decision, prices, equity, sessions, wobble=lambda t: 0.0):
    """Return [orders per session] from walking `plan_funded` with fills."""
    held: dict[str, float] = {}
    cash = equity
    history = []
    for t in range(sessions):
        marks = {s: p * (1.0 + wobble(t)) for s, p in prices.items()}
        nav = cash + sum(q * marks[s] for s, q in held.items())
        plan = plan_funded(
            decision,
            held,
            marks,
            nav,
            cash,
            cost_bps=COST_BPS,
            whole_shares=True,
        )
        history.append(list(plan.orders))
        held, cash = _fill(held, cash, plan.orders, marks)
    return history


# The names sold on one session and bought back on the next (or the reverse),
# which is the ping-pong the planner must never produce against a constant
# target.
def _reversals(history):
    """Return [(session, symbol)] for every next-session same-name reversal."""
    out = []
    for t in range(len(history) - 1):
        today = {(o.symbol, o.side) for o in history[t]}
        tomorrow = {(o.symbol, o.side) for o in history[t + 1]}
        for symbol, side in today:
            other = "buy" if side == "sell" else "sell"
            if (symbol, other) in tomorrow:
                out.append((t, symbol))
    return out


# Fractional share targets under a binding volatility budget: 250 sessions of
# a constant target with the fills fed back must produce no same-name
# reversal at all. The old rule rounded every sell up while the budget bound,
# so each overweight name was sold below target and bought back the next day.
def test_constant_target_under_a_binding_budget_never_ping_pongs():
    prices = {"AAA": 37.0, "BBB": 410.0, "CCC": 123.0, "DDD": 61.5, "EEE": 250.0}
    # Weights chosen so the whole-share targets land on awkward fractions.
    desired = {"AAA": 0.09, "BBB": 0.07, "CCC": 0.11, "DDD": 0.05, "EEE": 0.13}
    history = _walk(
        _decision(desired, binding=BINDING_VOL),
        prices,
        equity=25_000.0,
        sessions=250,
        wobble=lambda t: 0.002 * np.sin(t / 3.0),
    )
    assert _reversals(history) == []
    # The book is established on the first session and then sits inside the
    # band: no order at all for the remaining sessions.
    assert history[0]
    assert all(not orders for orders in history[1:])


# The same walk with no binding constraint at all is equally quiet; the band
# is a property of whole shares, not of the risk label.
def test_constant_target_without_a_binding_constraint_never_ping_pongs():
    prices = {"AAA": 37.0, "BBB": 410.0, "CCC": 123.0}
    desired = {"AAA": 0.09, "BBB": 0.07, "CCC": 0.11}
    history = _walk(_decision(desired), prices, equity=25_000.0, sessions=250)
    assert _reversals(history) == []
    assert all(not orders for orders in history[1:])


# A gap of half a share or less on either side is no trade: neither a sell
# nor a buy is rounded up to a whole share, so the position stays within one
# rounding of the target.
@pytest.mark.parametrize("gap", [0.1, 0.3, 0.5])
@pytest.mark.parametrize("binding", [BINDING_NONE, BINDING_VOL])
def test_a_gap_inside_the_half_share_band_is_no_trade(gap, binding):
    price = 100.0
    equity = 10_000.0
    for held_qty in (10.0 + gap, 10.0 - gap):
        plan = plan_funded(
            _decision({"AAA": 10.0 * price / equity}, binding=binding),
            held={"AAA": held_qty},
            prices={"AAA": price},
            equity=equity,
            cash=equity - held_qty * price,
            whole_shares=True,
        )
        assert plan.orders == ()
        # A gap inside the band is not a blocked leg: the book already sits
        # within one whole-share rounding of the target.
        assert plan.blocked == ()


# Past the half-share band the gap rounds to the nearest whole share, never
# up: a 1.4-share sell is one share and a 1.6-share sell is two, and the same
# on the buy side.
@pytest.mark.parametrize(
    ("gap", "expected"), [(0.6, 1), (1.4, 1), (1.6, 2), (2.4, 2), (2.6, 3)]
)
@pytest.mark.parametrize("binding", [BINDING_NONE, BINDING_VOL])
def test_a_gap_past_the_band_rounds_to_the_nearest_whole_share(gap, expected, binding):
    # A 10-share target of a 10000 account: every gap past the band is worth
    # more than the 0.5% minimum trade, so only the rounding is under test.
    price = 100.0
    equity = 10_000.0
    for held_qty, side in ((10.0 + gap, "sell"), (10.0 - gap, "buy")):
        plan = plan_funded(
            _decision({"AAA": 10.0 * price / equity}, binding=binding),
            held={"AAA": held_qty},
            prices={"AAA": price},
            equity=equity,
            cash=equity - held_qty * price,
            whole_shares=True,
        )
        assert [(o.symbol, o.side, o.qty) for o in plan.orders] == [
            ("AAA", side, expected)
        ]


# A full exit sells every whole share held whatever the band says, and the
# fractional remainder that whole shares cannot sell stays an explicit block.
def test_a_full_exit_still_sells_every_whole_share_held():
    plan = plan_funded(
        _decision({"AAA": 0.0}, binding=BINDING_VOL),
        held={"AAA": 3.4},
        prices={"AAA": 100.0},
        equity=100_000.0,
        cash=0.0,
        whole_shares=True,
    )
    assert [(o.symbol, o.side, o.qty) for o in plan.orders] == [("AAA", "sell", 3)]
    assert any("fractional residual" in b for b in plan.blocked)


# ---------------------------------------------------------------------------
# One min-trade threshold on both sides.
# ---------------------------------------------------------------------------


# A constant 10% target of a 100000 account with the holding drifted by a
# notional inside the 0.5% minimum trade, on either side, is no order: the
# sell side used to have no threshold at all, so the book was trimmed on every
# small up-drift and sat below target while turning over.
@pytest.mark.parametrize("drift", [0.0, 100.0, 300.0, 499.0, -100.0, -300.0, -499.0])
def test_small_drift_on_either_side_is_no_order(drift):
    equity = 100_000.0
    held_qty = (10_000.0 + drift) / 100.0
    plan = plan_funded(
        _decision({"AAA": 0.1}),
        held={"AAA": held_qty},
        prices={"AAA": 100.0},
        equity=equity,
        cash=equity - held_qty * 100.0,
        whole_shares=False,
    )
    assert plan.orders == ()
    assert not plan.risk_cut
    if drift > 0:
        assert any("AAA: sell below min trade" in m for m in plan.missing)
    elif drift < 0:
        assert any("AAA: buy below min trade" in m for m in plan.missing)


# Once the drift clears the threshold on either side the order is the exact
# continuous gap - the threshold is the same number for a sell and a buy.
@pytest.mark.parametrize(("drift", "side"), [(501.0, "sell"), (-501.0, "buy")])
def test_drift_past_the_threshold_trades_on_either_side(drift, side):
    equity = 100_000.0
    held_qty = (10_000.0 + drift) / 100.0
    plan = plan_funded(
        _decision({"AAA": 0.1}),
        held={"AAA": held_qty},
        prices={"AAA": 100.0},
        equity=equity,
        cash=equity - held_qty * 100.0,
        whole_shares=False,
    )
    assert [(o.symbol, o.side) for o in plan.orders] == [("AAA", side)]
    assert plan.orders[0].qty == pytest.approx(abs(drift) / 100.0)
    assert MIN_TRADE * equity == 500.0


# Walking the continuous planner with a slowly drifting price against a
# constant target: no order at all until the drift has carried the holding's
# notional past the threshold, and then one trade that resets the gap.
def test_slow_drift_trades_only_when_the_threshold_is_crossed():
    held = {"AAA": 100.0}
    cash = 90_000.0
    traded_at = []
    for t in range(1, 40):
        price = 100.0 * (1.0 + 0.002 * t)
        nav = cash + held["AAA"] * price
        plan = plan_funded(
            _decision({"AAA": 0.1}),
            held,
            {"AAA": price},
            nav,
            cash,
            whole_shares=False,
        )
        if plan.orders:
            traded_at.append(t)
        held, cash = _fill(held, cash, plan.orders, {"AAA": price})
    # The 10% holding gains 0.2% of its value a session against a 0.5%
    # threshold of the account, so the first trim needs the position to be
    # about 5% of the account over target: no trades for the first sessions.
    assert traded_at
    assert traded_at[0] > 5
    assert all(b - a > 1 for a, b in zip(traded_at, traded_at[1:], strict=False))


# A full exit executes whatever its size: a 300-dollar position the decision
# no longer wants is sold, not held below the threshold forever.
def test_a_full_exit_is_never_suppressed_by_the_threshold():
    plan = plan_funded(
        _decision({"BBB": 0.1}),
        held={"AAA": 3.0, "BBB": 100.0},
        prices={"AAA": 100.0, "BBB": 100.0},
        equity=100_000.0,
        cash=89_700.0,
        whole_shares=False,
    )
    sells = [(o.symbol, o.qty) for o in plan.orders if o.side == "sell"]
    assert sells == [("AAA", 3.0)]


# A genuine risk cut - the event cap reduced the ceiling below what is held -
# executes every name's small reduction regardless of the threshold: each
# name sells 0.3% of the account, under the 0.5% threshold, but the cut as a
# whole took the ceiling 0.6% below the held exposure.
def test_a_genuine_risk_cut_is_never_suppressed_by_the_threshold():
    equity = 100_000.0
    plan = plan_funded(
        _decision({"AAA": 0.147, "BBB": 0.147}, binding=BINDING_EVENT),
        held={"AAA": 150.0, "BBB": 150.0},
        prices={"AAA": 100.0, "BBB": 100.0},
        equity=equity,
        cash=70_000.0,
        whole_shares=False,
    )
    assert plan.risk_cut
    sells = {o.symbol: o.qty for o in plan.orders if o.side == "sell"}
    assert sells == {"AAA": pytest.approx(3.0), "BBB": pytest.approx(3.0)}


# A binding constraint's name alone is not a risk cut. The budget binds on a
# day the book already sits at the scaled level and has only drifted, so the
# small sell it wants is drift and stays under the threshold.
def test_a_binding_name_without_a_reduction_is_not_a_risk_cut():
    equity = 100_000.0
    plan = plan_funded(
        _decision({"AAA": 0.1, "BBB": 0.1}, binding=BINDING_VOL),
        held={"AAA": 103.0, "BBB": 98.0},
        prices={"AAA": 100.0, "BBB": 100.0},
        equity=equity,
        cash=79_900.0,
        whole_shares=False,
    )
    assert not plan.risk_cut
    assert plan.orders == ()
    assert any("AAA: sell below min trade" in m for m in plan.missing)
    assert any("BBB: buy below min trade" in m for m in plan.missing)


# The same binding name with the held exposure genuinely above the ceiling is
# a risk cut, and the same small sell then goes.
def test_a_binding_name_with_a_reduction_is_a_risk_cut():
    equity = 100_000.0
    plan = plan_funded(
        _decision({"AAA": 0.1, "BBB": 0.1}, binding=BINDING_VOL),
        held={"AAA": 103.0, "BBB": 103.0},
        prices={"AAA": 100.0, "BBB": 100.0},
        equity=equity,
        cash=79_400.0,
        whole_shares=False,
    )
    assert plan.risk_cut
    sells = {o.symbol: o.qty for o in plan.orders if o.side == "sell"}
    assert sells == {"AAA": pytest.approx(3.0), "BBB": pytest.approx(3.0)}
