"""Corporate-action accounting for observed outcomes, never for choosing signals."""

import math
from datetime import date

from backend.market import desk_freshness
from backend.market.store import MarketStore


# Require a stored action file and complete daily coverage for every evaluated symbol.
def load(root, symbols):
    store = MarketStore(root)
    actions = {}
    through = []
    for symbol in sorted(symbols):
        asof = store.latest_asof(symbol)
        if (
            asof is None
            or not (root / "actions" / f"asof={asof}" / f"{symbol}.parquet").exists()
        ):
            raise ValueError("Corporate-action history unavailable")
        history = store.read(symbol)
        through.append(history.complete_through)
        actions[symbol] = [
            {"date": a.action_date.isoformat(), "kind": a.kind, "value": a.value}
            for a in history.actions
        ]
    return actions, min(through).isoformat() if through else None


# Resolve a recorded timestamp to the exchange's date for ex-date accounting.
def session(value):
    return desk_freshness.timestamp(value).astimezone(desk_freshness.NEW_YORK).date()


# Adjust held shares and accrue dividends; unknown pay dates cannot fund new buys.
def apply(shares, start, end, actions):
    dividends = 0.0
    for symbol, quantity in list(shares.items()):
        events = sorted(
            actions.get(symbol, []), key=lambda a: (a["date"], a["kind"] != "split")
        )
        for action in events:
            if not start < date.fromisoformat(action["date"]) <= end:
                continue
            value = float(action["value"])
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid corporate action")
            if action["kind"] == "split":
                quantity *= value
            elif action["kind"] == "dividend":
                dividends += quantity * value
            else:
                raise ValueError("Unsupported corporate action")
        shares[symbol] = quantity
    return dividends


# Value one original share plus its split shares and accrued cash distributions.
def total_return(symbol, start_price, end_price, start, end, actions):
    shares = {symbol: 1.0}
    dividends = apply(shares, start, end, actions)
    return (shares[symbol] * end_price + dividends) / start_price - 1
