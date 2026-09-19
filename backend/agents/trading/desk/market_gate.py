"""The market gate: half the book when the benchmark is broken.

A grade is a lagging confirmation - it is read off the close after the
move happened - so the desk's risk control cannot wait for one. The gate
is the lead: when SPY closes below its own 50-day EMA the whole book is
halved (the other half sits in cash, like an FOMC reduction), and it is
restored when SPY closes back above. Measured on the book since 2015
this cut drawdown in the rare situations - the COVID crash of 2020 and
the 2022 bear - at a small cost to CAGR and no cost to Sharpe, which is
exactly the insurance a grade, read after the fall, cannot provide.

The gate is a market-level scale on the same exposure the FOMC cycle
cuts, and it composes the same way: a snapshot of what to hold, a cut to
`GATE_SCALE` on the trip, a restore on the lift, cash-capped. It lives
beside `paper.plan`, which applies it to rebalance targets and to the
book between rebalances, so entries continue while the book is halved.
"""

import math
from dataclasses import asdict

import numpy as np

from backend.market import technical

# The benchmark's own average, and the exposure fraction while it is broken.
GATE_EMA = 50
GATE_SCALE = 0.5
VERSION = "spy-50d-gate/1"


# The per-session exposure the gate wants: 1.0 in a healthy market, half below it.
def exposure_path(panel) -> np.ndarray:
    """Return one exposure factor per session: 1.0, or 0.5 below the 50-day."""
    close = panel.adj_close
    benchmark = panel.index(panel.benchmark)
    spy = close[:, benchmark]
    ema50 = technical.ema(close, GATE_EMA)[:, benchmark]
    with np.errstate(invalid="ignore"):
        below = (spy < ema50) & np.isfinite(spy) & np.isfinite(ema50)
    return np.where(below, GATE_SCALE, 1.0)


# Tonight's gate decision, for the record and the page.
def decision(panel) -> dict:
    """Return the gate's state at the last session: factor, prices, reason."""
    last = len(panel.dates) - 1
    close = panel.adj_close
    benchmark = panel.index(panel.benchmark)
    spy = float(close[last, benchmark])
    ema50 = float(technical.ema(close, GATE_EMA)[last, benchmark])
    below = bool(np.isfinite(spy) and np.isfinite(ema50) and spy < ema50)
    return {
        "version": VERSION,
        "session": str(panel.dates[last]),
        "factor": GATE_SCALE if below else 1.0,
        "below": below,
        "spy": spy,
        "ema50": ema50,
    }


# Move the book from one exposure to another, mid-cycle.
def transition_orders(
    session,
    state,
    held: dict[str, float],
    prices: dict[str, float],
    cash: float,
    desired: float,
) -> list:
    """Return the sell or buy orders that move the book to `desired`.

    Called only when `desired` differs from the exposure the book sits at.
    A cut (desired < current) is exact - selling never needs cash - and
    sells the same fraction of every holding. A restore (desired >
    current) buys the fraction back, capped by available cash with a
    one-percent opening-price allowance, and the residual is corrected at
    the next rebalance.
    """
    from backend.agents.trading.desk.paper import PaperOrder, order_id

    current = float(state.gate_factor)
    if current <= 0 or desired == current:
        return []
    orders = []
    fraction = abs(desired - current) / current
    # A cut to cash, the exact half when the benchmark is broken.
    if desired < current:
        for symbol, qty in sorted(held.items()):
            if qty <= 0:
                continue
            price = float(prices.get(symbol) or 0.0)
            if not math.isfinite(price) or price <= 0:
                continue
            sell = int(round(qty * fraction))
            if sell <= 0:
                continue
            seq = state.order_seq
            state.order_seq += 1
            orders.append(
                PaperOrder(
                    symbol,
                    "sell",
                    sell,
                    "market gate: SPY under its 50-day",
                    order_id(session, symbol, "sell", seq),
                )
            )
        return orders
    # A restore, capped by the cash the cut left on hand.
    available = max(0.0, float(cash)) if math.isfinite(float(cash)) else 0.0
    for symbol, qty in sorted(held.items()):
        if qty <= 0:
            continue
        price = float(prices.get(symbol) or 0.0)
        if not math.isfinite(price) or price <= 0:
            continue
        want = int(round(qty * fraction))
        if want <= 0:
            continue
        cost = want * price * 1.01
        if cost > available:
            want = int(available / (price * 1.01))
            cost = want * price * 1.01
        if want <= 0:
            continue
        available -= cost
        seq = state.order_seq
        state.order_seq += 1
        orders.append(
            PaperOrder(
                symbol,
                "buy",
                want,
                "market gate restored: SPY back above its 50-day",
                order_id(session, symbol, "buy", seq),
            )
        )
    return orders


# Copy the state so a planned gate never mutates the one on file.
def fresh(state) -> object:
    """Return a deep-enough copy of the paper state for planning."""
    return state.__class__(**asdict(state))
