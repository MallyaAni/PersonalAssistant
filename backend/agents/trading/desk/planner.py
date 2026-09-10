"""One order plan shared by the desk's three execution paths.

The simulator, the paper account and the record tracker each decide what
to hold and then fill at the next open. They used to size in three places
and drifted apart: the simulator and the paper sized at the close, while
the record tracker sized at the next open, so an overnight gap changed how
much each of them thought a rebalance was worth, and the auction-order
failure this module replaces was only found in production. This is the one
place an order is decided.

`plan` takes only what the decision could see - target weights, current
holdings, the account's value and the prices at the close - and returns the
orders to move to those targets, each naming the price it was decided at and
why. The callers keep only their execution: the simulator fills continuous
shares at the open, the paper rounds to whole shares for the broker, and
the record tracker prices the nightly records forward. A written decision
record is the point: two paths can be compared order for order instead of
by whatever their totals happened to be.
"""

from dataclasses import dataclass

import numpy as np

MIN_TRADE = 0.005


@dataclass(frozen=True)
class Order:
    """One order: the name, the side, the quantity, and the decision behind it."""

    symbol: str
    side: str  # "buy" or "sell"
    qty: float  # shares, at the decision price
    reference_price: float
    reason: str


# The share count one name should end up holding, decided at `price` against
# the account's value at the same prices. A move too small to be worth its
# cost is not made; a missing price keeps the current holding.
def target_shares(
    target_weight: float,
    held_qty: float,
    equity: float,
    price: float | None,
    min_trade: float = MIN_TRADE,
) -> float:
    """Return the shares to hold of one name, sized at `price`."""
    if price is None or not np.isfinite(price) or price <= 0:
        return held_qty
    value_now = held_qty * price
    value_want = target_weight * equity
    if abs(value_want - value_now) < min_trade * equity:
        return held_qty
    return value_want / price


# The whole rebalance or exit as a written list, sized at the close.
def plan(
    targets: dict[str, float],
    held: dict[str, float],
    equity: float,
    prices: dict[str, float],
    min_trade: float = MIN_TRADE,
) -> list[Order]:
    """Return the Orders that move `held` shares to `targets` weights.

    `targets` is {symbol: weight}, `held` {symbol: shares} and `prices`
    {symbol: last close}. Sized at `prices` and `equity` - the close the
    decision could see - and filled later at the open, wherever the caller
    fills. A name leaving the book is a sell out of it; a name no longer
    moving is left out of the list entirely.
    """
    orders: list[Order] = []
    for symbol in sorted(set(held) | set(targets)):
        price = prices.get(symbol)
        target = targets.get(symbol, 0.0)
        held_qty = held.get(symbol, 0.0)
        wanted = target_shares(target, held_qty, equity, price, min_trade)
        delta = wanted - held_qty
        if abs(delta) < 1e-12:
            continue
        side = "buy" if delta > 0 else "sell"
        reason = f"rebalance to {target:.3f}" if target > 0 else "leaves the book"
        orders.append(Order(symbol, side, abs(delta), float(price), reason))
    return orders
