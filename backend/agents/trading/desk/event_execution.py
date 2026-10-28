"""FOMC share reductions, reconciled through the paper order journal.

The event owns a snapshot of shares, never a multiplier reapplied to holdings.
Scheduled rebalances wait until this cycle finishes; their clock keeps running.
Only confirmed event sales can be restored. A pending order blocks a new plan.

The restoration is planned on the eve of the decision, once the cut has
filled, and sent by the balancer on the decision session's last candle
(`decision_close`), after the 2:00 PM statement and the press
conference. Since the June 2026 guidance change the rebound came overnight,
between the decision-day close and the next open (+2.0%, +4.3% and +2.2% on
the book after June, July and September), which a restoration at the next
open missed; before 2026 that gap averaged +0.05%, so the earlier fill costs
nothing in the old regime (`docs/research/fomc-lead-in-2026-10-22.md`). A cut
that has not filled by the eve restores at the next open, as before.
"""

import math
from dataclasses import asdict, replace
from datetime import date

from backend.agents.trading.desk import decision_close, event_risk, intraday_orders, paper
from backend.market.labels import OrderSide, PlanDay

# The opening-price allowance a next-open restoration reserves, and the wider
# one for a restoration sent a session later at the decision-day close.
OPEN_ALLOWANCE = 0.01
CLOSE_ALLOWANCE = 0.03


# Sum the latest confirmed fills of this event, including terminal partial fills.
def filled(state: paper.PaperState, side: OrderSide) -> dict[str, int]:
    side = OrderSide(side)
    quantities: dict[str, int] = {}
    for row in state.journal:
        # Only this event's rows are read; every journal row carries its side.
        if (
            row.get("event_id") != state.event_cycle.get("id")
            or OrderSide(row["side"]) is not side
        ):
            continue
        symbol = row["symbol"]
        quantities[symbol] = quantities.get(symbol, 0) + int(row.get("filled_qty") or 0)
    return quantities


# Plan remaining event shares once, without moving the ordinary rebalance date.
def plan(session, state, held, prices, cash, policy, *, advance_clock=True):
    new = (
        _advance_clock(state, session)
        if advance_clock
        else paper.PaperState(**asdict(state))
    )
    if state.pending:
        return [], new, "FOMC waiting for broker settlement"
    if not policy.get("calendar_known"):
        return [], new, "FOMC calendar unavailable; exposure changes paused"
    reduced = policy.get("factor") == event_risk.REDUCED
    if not new.event_cycle and reduced:
        new.event_cycle = {
            "id": f"{event_risk.VERSION}:{policy['decision_date']}",
            "decision_date": policy["decision_date"],
            "baseline": {s: float(q) for s, q in held.items() if q > 0},
        }
    if not new.event_cycle:
        return [], new, PlanDay.HOLD
    # A later meeting must never extend the previous meeting's unfinished cycle.
    reducing = session < new.event_cycle["decision_date"]
    sold, bought = filled(new, OrderSide.SELL), filled(new, OrderSide.BUY)
    # On the eve of the decision with the cut filled, plan the restoration now,
    # for the decision session's close, instead of waiting for that night.
    at_close = (
        reducing
        and _eve_of(session, new.event_cycle["decision_date"])
        and _cut_filled(new, held, sold)
    )
    if at_close:
        reducing = False
    allowance = CLOSE_ALLOWANCE if at_close else OPEN_ALLOWANCE
    orders = []
    available = max(0.0, float(cash)) if math.isfinite(float(cash)) else 0.0
    unpriced = False
    unrestored = {}
    for symbol, baseline in sorted(new.event_cycle["baseline"].items()):
        current = max(0, int(held.get(symbol, 0)))
        if reducing:
            wanted = max(
                0, int(baseline * (1 - event_risk.REDUCED)) - sold.get(symbol, 0)
            )
            qty = min(current, wanted)
            side = OrderSide.SELL
        else:
            wanted = max(0, sold.get(symbol, 0) - bought.get(symbol, 0))
            # Do not buy above the snapshot if positions changed outside this cycle.
            qty = min(wanted, max(0, int(baseline - current)))
            side = OrderSide.BUY
            unrestored[symbol] = qty
        price = float(prices.get(symbol) or 0)
        if not math.isfinite(price) or price <= 0:
            unpriced = unpriced or qty > 0
            continue
        qty, available = _cash_limit(side, qty, price, available, allowance)
        if qty <= 0:
            continue
        seq = new.order_seq
        new.order_seq += 1
        order = paper.PaperOrder(
            symbol,
            side,
            qty,
            "FOMC risk reduction" if reducing else "FOMC risk restoration",
            paper.order_id(session, symbol, side, seq),
            new.event_cycle["id"],
        )
        if at_close:
            order = replace(order, execution_timing=decision_close.DECISION_CLOSE)
        orders.append(order)
    if reducing:
        return orders, new, "FOMC reduction"
    result = _restoration_result(new, session, orders, unpriced, unrestored)
    if at_close and result[0]:
        return result[0], result[1], "FOMC restoration at the decision close"
    return result


# Release a settled cycle when restored or unaffordable, retaining unbought evidence.
def _restoration_result(new, session, orders, unpriced, unrestored):
    unrestored = {symbol: qty for symbol, qty in unrestored.items() if qty > 0}
    if not unrestored:
        new.event_cycle = {}
        return [], new, "FOMC restoration complete"
    if not orders and not unpriced:
        new.event_outcomes.append(
            {
                "event_id": new.event_cycle["id"],
                "session": session,
                "status": "cash-limited",
                "unrestored": unrestored,
            }
        )
        new.event_cycle = {}
        return [], new, "FOMC restoration cash-limited; regular rebalance released"
    return orders, new, "FOMC restoration"


# Whether the decision session is the next reviewed session after `session`.
def _eve_of(session, decision_date) -> bool:
    following = intraday_orders.next_session(date.fromisoformat(str(session)))
    return following is not None and following.isoformat() == str(decision_date)


# Whether every name the cycle cut has had its whole reduction confirmed (or
# holds nothing left to cut): only confirmed sales are ever restored.
def _cut_filled(cycle_state, held, sold) -> bool:
    for symbol, baseline in cycle_state.event_cycle["baseline"].items():
        wanted = int(baseline * (1 - event_risk.REDUCED)) - sold.get(symbol, 0)
        if wanted > 0 and int(held.get(symbol, 0)) > 0:
            return False
    return bool(sold)


# Count a newly observed session once while leaving the rebalance date untouched.
def _advance_clock(state, session):
    new = paper.PaperState(**asdict(state))
    if session not in new.sessions_seen:
        new.sessions_seen.append(session)
        new.sessions_since_rebalance += 1
    return new


# Reserve cash for each restoration with a price allowance over the last close.
def _cash_limit(side, qty, price, available, allowance=OPEN_ALLOWANCE):
    if side is OrderSide.BUY:
        qty = min(qty, int(available / (price * (1 + allowance))))
        available -= qty * price * (1 + allowance)
    return qty, available
