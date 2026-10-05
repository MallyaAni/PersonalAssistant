"""Actual-clock private sender adapter for supplied probabilistic forecasts.

The caller authenticates model, prefix, raw quote and opening-anchor sources.
This contract transports an opening-price forecast to a conditional current
midpoint proxy. It does not claim a midpoint fill or enable a production caller.
"""

import json
import math
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256

from backend.market import calendar, entry_timing, execution_quotes
from backend.market import live_probability_timing as original
from backend.market import probabilistic_execution as probability
from backend.market.alpaca_trading import AlpacaTradingError

CONTRACT = "forward-probability-timing/1-shadow"


# Bind the complete explicit receipt without accepting non-JSON evidence.
def _digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


# Read only actual observed balances and quantities, never promised sale proceeds.
def capture_account(broker, completed, *, clock=None):
    completed = original._aware(completed)
    now = None
    receipt = {"reason": "", "nav": None, "budget": None, "held": {}}
    try:
        before = broker.clock()
        first, positions = broker.account(), broker.positions()
        second, repeated = broker.account(), broker.positions()
        after = broker.clock()
        now = original._aware(clock() if clock else datetime.now(calendar.NEW_YORK))
        clocks = [
            entry_timing._instant(value.get("timestamp")) for value in (before, after)
        ]
        if (
            any(value.get("is_open") is not True for value in (before, after))
            or any(value is None for value in clocks)
            or not completed <= clocks[0] <= clocks[1] <= now
            or (now - clocks[0]).total_seconds() >= execution_quotes.MAX_AGE_SECONDS
        ):
            raise ValueError("Current observed open broker clocks required")
        amounts = []
        for account in (first, second):
            nav = original._positive(account.equity)
            cash = original._positive(account.cash, zero=True)
            power = original._positive(account.buying_power, zero=True)
            if nav is None or cash is None or power is None:
                raise ValueError(
                    "Finite observed equity and nonnegative funds required"
                )
            amounts.append((nav, cash, power))
        holdings = []
        for batch in (positions, repeated):
            held = {}
            for position in batch:
                quantity = original._positive(position.qty, zero=True)
                if (
                    not isinstance(position.symbol, str)
                    or not position.symbol
                    or position.symbol in held
                    or quantity is None
                    or quantity != math.floor(quantity)
                    or original._positive(position.current_price) is None
                ):
                    raise ValueError("Unique marked whole-share holdings required")
                held[position.symbol] = int(quantity)
            holdings.append(held)
        if amounts[0][1:] != amounts[1][1:] or holdings[0] != holdings[1]:
            raise ValueError("Account changed during the observed funding snapshot")
        # Independent feeds may mark equity differently; neither is a future fill.
        receipt.update(
            nav=amounts[1][0],
            budget=min(amounts[1][1:]),
            held=holdings[1],
            source_timestamps=[value.isoformat() for value in clocks],
        )
    except (AlpacaTradingError, OSError, ValueError, TypeError, AttributeError) as exc:
        receipt["reason"] = str(exc)
    if now is None:
        now = original._aware(clock() if clock else datetime.now(calendar.NEW_YORK))
    receipt.update(captured_at=now.isoformat(), completed_at=completed.isoformat())
    return {"receipt": receipt, "receipt_sha256": _digest(receipt)}


# Validate known current prices and the already published first next-bar opening.
def _quote(quote, start, completed, now):
    if not isinstance(quote, dict):
        return None
    stamps = [
        entry_timing._instant(quote.get(key))
        for key in ("as_of", "received_at", "next_open_at", "next_open_published_at")
    ]
    at, received, anchor_at, anchor_published = stamps
    values = [
        original._positive(quote.get(key))
        for key in ("bid", "ask", "bid_size", "ask_size", "next_open", "open", "last")
    ]
    bid, ask, _, _, anchor, _, last = values
    if (
        any(value is None for value in (*stamps, *values))
        or quote.get("basis") != "raw_current_shares"
        or quote.get("feed") not in ("iex", "sip")
        or entry_timing._instant(quote.get("bar")) != start
        or not completed <= at <= received <= now
        or not completed == anchor_at <= anchor_published <= now
        or (now - at).total_seconds() >= execution_quotes.MAX_AGE_SECONDS
        or ask < bid
    ):
        return None
    midpoint = bid / 2 + ask / 2
    if (
        not math.isfinite(midpoint)
        or last != midpoint
        or (ask - bid) / midpoint * 1e4 > execution_quotes.MAX_SPREAD_BPS
    ):
        return None
    return midpoint, anchor


# Freeze actual availability, current price transport and shared funded sender checks.
def build_reader(
    distributions,
    symbols,
    clock,
    session,
    now,
    snapshot,
    pending,
    observed_account,
    cost_bps,
    trace,
    *,
    forecast_available_at,
    source_identity,
):
    now, available = original._aware(now), original._aware(forecast_available_at)
    symbols = tuple(symbols)
    start = datetime.combine(session, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    start += timedelta(minutes=15 * int(clock))
    completed = start + entry_timing.BAR
    # Use the original reviewed session/symbol/intent checks at their own boundary.
    _, session, symbols, start = original._contract(
        None, symbols, 0, clock, session, completed, snapshot, pending, cost_bps, trace
    )
    if (
        not completed <= available <= now < completed + entry_timing.BAR
        or not isinstance(distributions, dict)
        or set(distributions) != set(symbols)
        or not isinstance(source_identity, dict)
        or not {"model_receipt", "residual_receipt", "observation"}
        <= set(source_identity)
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or len(value) != 64
            or any(letter not in "0123456789abcdef" for letter in value)
            for key, value in source_identity.items()
        )
    ):
        raise ValueError(
            "Actual forecast publication and fixed source identities required"
        )
    account = deepcopy(observed_account["receipt"])
    captured = entry_timing._instant(account.get("captured_at"))
    if (
        _digest(account) != observed_account["receipt_sha256"]
        or account.get("completed_at") != completed.isoformat()
        or captured is None
        or not completed <= captured <= now
        or (now - captured).total_seconds() >= execution_quotes.MAX_AGE_SECONDS
    ):
        raise ValueError("Original current observed account receipt required")
    closing = datetime.combine(
        session, calendar.session_close(session), calendar.NEW_YORK
    )
    supported = completed + entry_timing.BAR < closing and clock <= 22
    distributions = deepcopy(distributions)
    quotes = deepcopy(snapshot["quotes"])
    price_pairs = {
        symbol: _quote(quote, start, completed, now) for symbol, quote in quotes.items()
    }
    transported, identities = {}, {}
    for symbol, distribution in distributions.items():
        pair = price_pairs.get(symbol)
        transported[symbol] = None
        if distribution is None:
            identities[symbol] = None
            continue
        if (
            not isinstance(distribution, probability.Distribution)
            or distribution.horizon != probability.HORIZON
            or original._positive(distribution.scale) is None
            or not math.isfinite(distribution.mean)
        ):
            raise ValueError(
                "Original finite positive-risk probability forecast required"
            )
        residuals, weights = probability._sample(
            distribution.residuals, distribution.weights
        )
        identities[symbol] = {
            "mean": float(distribution.mean),
            "scale": float(distribution.scale),
            "residuals": sha256(residuals.tobytes()).hexdigest(),
            "weights": sha256(weights.tobytes()).hexdigest(),
        }
        if pair is not None and supported and symbol not in ("SPY", "QQQ"):
            midpoint, anchor = pair
            shift = math.log(midpoint) - math.log(anchor)
            transported[symbol] = probability.Distribution(
                distribution.mean + shift,
                distribution.scale,
                residuals,
                weights,
            )
    receipt = {
        "contract": CONTRACT,
        "session": session.isoformat(),
        "clock": int(clock),
        "completed_at": completed.isoformat(),
        "forecast_available_at": available.isoformat(),
        "decided_at": now.isoformat(),
        "source_identity": deepcopy(source_identity),
        "forecast_identity": identities,
        "quotes": quotes,
        "account": deepcopy(observed_account),
        "transport": "log(current_midpoint/original_next_bar_open)",
        "conditional_midpoint_proxy": True,
        "midpoint_fill_proven": False,
    }

    # Resolve only a frozen transported distribution for the original named stock.
    def provider(day, observed_clock, stock):
        return transported[symbols[stock]]

    # Price batch funding only from validated current quotes, never later bars.
    def quote_reader(quote):
        pair = _quote(quote, start, completed, now)
        return pair[0] if pair is not None else None

    # Freeze two stable GET observations before the sender submits any request.
    def account_reader(marks):
        return account["reason"], account["nav"], account["budget"], account["held"]

    return original._frozen_reader(
        provider,
        symbols,
        0,
        clock,
        session,
        now,
        quotes,
        pending,
        cost_bps,
        trace,
        quote_reader,
        account_reader,
        start,
        extra={"forward_receipt": receipt, "forward_receipt_sha256": _digest(receipt)},
    )
