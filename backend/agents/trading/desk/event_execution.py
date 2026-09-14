"""FOMC share reductions, reconciled through the paper order journal.

The event owns a snapshot of shares, never a multiplier reapplied to holdings.
Scheduled rebalances wait until this cycle finishes; their clock keeps running.
Only confirmed event sales can be restored. A pending order blocks a new plan.
"""

import math
from dataclasses import asdict

from backend.agents.trading.desk import event_risk, paper


# Sum the latest confirmed fills of this event, including terminal partial fills.
def filled(state: paper.PaperState, side: str) -> dict[str, int]:
    quantities: dict[str, int] = {}
    for row in state.journal:
        if (
            row.get("event_id") != state.event_cycle.get("id")
            or row.get("side") != side
        ):
            continue
        symbol = row["symbol"]
        quantities[symbol] = quantities.get(symbol, 0) + int(row.get("filled_qty") or 0)
    return quantities


# Plan remaining event shares once, without moving the ordinary rebalance date.
def plan(session, state, held, prices, cash, policy):
    new = _advance_clock(state, session)
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
        return [], new, "hold"
    # A later meeting must never extend the previous meeting's unfinished cycle.
    reducing = session < new.event_cycle["decision_date"]
    sold, bought = filled(new, "sell"), filled(new, "buy")
    orders = []
    available = max(0.0, float(cash)) if math.isfinite(float(cash)) else 0.0
    remaining = False
    for symbol, baseline in sorted(new.event_cycle["baseline"].items()):
        current = max(0, int(held.get(symbol, 0)))
        if reducing:
            wanted = max(
                0, int(baseline * (1 - event_risk.REDUCED)) - sold.get(symbol, 0)
            )
            qty = min(current, wanted)
            side = "sell"
        else:
            wanted = max(0, sold.get(symbol, 0) - bought.get(symbol, 0))
            # Do not buy above the snapshot if positions changed outside this cycle.
            qty = min(wanted, max(0, int(baseline - current)))
            side = "buy"
        remaining = remaining or qty > 0
        price = float(prices.get(symbol) or 0)
        if not math.isfinite(price) or price <= 0:
            continue
        qty, available = _cash_limit(side, qty, price, available)
        if qty <= 0:
            continue
        seq = new.order_seq
        new.order_seq += 1
        orders.append(
            paper.PaperOrder(
                symbol,
                side,
                qty,
                "FOMC risk reduction" if reducing else "FOMC risk restoration",
                paper.order_id(session, symbol, side, seq),
                new.event_cycle["id"],
            )
        )
    if not reducing and not remaining:
        new.event_cycle = {}
        return [], new, "FOMC restoration complete"
    return orders, new, "FOMC reduction" if reducing else "FOMC restoration"


# Count a newly observed session once while leaving the rebalance date untouched.
def _advance_clock(state, session):
    new = paper.PaperState(**asdict(state))
    if session not in new.sessions_seen:
        new.sessions_seen.append(session)
        new.sessions_since_rebalance += 1
    return new


# Reserve cash for each restoration with a one-percent opening-price allowance.
def _cash_limit(side, qty, price, available):
    if side == "buy":
        qty = min(qty, int(available / (price * 1.01)))
        available -= qty * price * 1.01
    return qty, available
