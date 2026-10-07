"""Ordinary-intent continuation means on the actual sender interface, research only.

The launcher authenticates provider artifacts and input units. These are conditional
means, not calibrated confidence or a model deciding whether to retain a holding.
No production configuration imports or selects this reader.
"""

import math
from copy import deepcopy

import numpy as np

from backend.agents.trading.desk import intraday_orders
from backend.market import live_probability_timing as guards
from backend.market.sequential_execution_models import decision

POLICY = "live-self-continuation/1-research"


# Freeze original ordinary intents, observed funds and quotes before any submission.
def build_reader(provider, symbols, day, clock, session, now, snapshot, pending,
                 broker, cost_bps, trace):
    if not callable(provider):
        raise ValueError("Authenticated continuation provider required")
    # Validate only the shared observation contract; no CDF semantics are borrowed.
    now, session, symbols, start = guards._contract(
        None, symbols, day, clock, session, now, snapshot, pending, cost_bps, trace
    )
    identities = guards._intents(pending, session, symbols)
    original = {row[0]: row for row in identities}
    quotes = deepcopy(snapshot["quotes"])
    marks = {name: guards._quote(quote, start, now, session)
             for name, quote in quotes.items()}
    account_reason, nav, budget, held = guards._account(broker, marks, now)
    buys = [row for row in identities if row[2] == "buy"]
    missing_buy = any(marks.get(row[1]) is None for row in buys)
    spend = None if missing_buy else sum(
        row[3] * marks[row[1]] for row in buys
    ) * (1 + cost_bps / 1e4)
    if spend is not None and not math.isfinite(spend):
        raise ValueError("Finite original pending spend required")
    fraction = min(1.0, budget / spend) if (
        not account_reason and spend and budget is not None
    ) else 1.0

    # Decide a locked original row without seeing next-open outcomes or sale proceeds.
    def reader(row, latch, quote, observation, today):
        if guards._aware(observation) != now or today != session:
            raise ValueError("Continuation observation identity differs")
        identity = guards._intent(row)
        if original.get(identity[0]) != identity:
            raise ValueError("Continuation original intent identity differs")
        cid, symbol, side, qty = identity
        mark = guards._quote(quote, start, now, session)
        reason = account_reason or (
            "unsupported continuation clock" if clock >= 24 else
            "missing or stale completed raw quote"
            if mark is None or quote != quotes.get(symbol) else
            "unknown pending buy price" if side == "buy" and missing_buy else ""
        )
        observed_qty = (
            min(qty, math.floor(held.get(symbol, 0))) if side == "sell" else qty
        )
        weight = 0.0 if reason else (
            observed_qty * mark / nav * (fraction if side == "buy" else 1.0)
        )
        mean, state = None, "unavailable"
        if not reason and weight == 0:
            state, reason = "no_trade", "no funded quantity"
        elif not reason:
            supplied = provider(int(day), int(clock), symbols.index(symbol))
            values = np.asarray(supplied) if supplied is not None else np.array([])
            if values.shape != (2,) or values.dtype.kind not in "fiu":
                reason = "missing or malformed continuation means"
            else:
                selected = float(values[0 if side == "buy" else 1])
                if not np.isfinite(selected):
                    reason = "unavailable side continuation mean"
                else:
                    mean, state = selected, decision(selected, side)
        evidence = {
            "policy": POLICY, "intent_id": cid, "session": session.isoformat(),
            "day": int(day), "clock": int(clock), "symbol": symbol, "side": side,
            "desired_qty": qty, "observed_qty": observed_qty, "observed_price": mark,
            "nav": nav, "buying_power_budget": budget, "all_pending_buy_spend": spend,
            "buy_funding_fraction": fraction, "trade_fraction": weight,
            "state": state, "reason": reason, "continuation_mean": mean,
            "horizon": "remaining_regular_session_prediction_selected_suffix",
            "is_calibrated_confidence": False, "funding_is_ex_ante": True,
            "at": now.isoformat(),
        }
        trace.append(deepcopy(evidence))
        return {"send": intraday_orders.MARKET if state == "execute" else None,
                "timed": {**evidence, "open": (quote or {}).get("open"),
                          "trigger_bar": start.isoformat(), "trigger_price": mark}}

    return reader
