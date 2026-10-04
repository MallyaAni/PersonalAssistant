"""Frozen one-bar CDF timing for unchanged ordinary paper intents.

The caller authenticates saved distributions and source bytes. This reader
changes permission to submit, never quantities, plans or account state. Its
funded exposure is an ex-ante estimate, not a broker-fill or holding-exit model.
"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import date, datetime, timedelta

import numpy as np

from backend.agents.trading.desk import intraday_orders
from backend.market import calendar, entry_timing
from backend.market import probabilistic_execution as probability
from backend.market.alpaca_trading import AlpacaTradingError

POLICY = "live-probability-timing/1-research"


# Require an actual aware datetime instead of assigning an implicit timezone.
def _aware(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Explicit aware observation datetime required")
    return value


# Validate JSON numeric evidence without treating booleans or strings as prices.
def _positive(value, *, zero=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        return None
    number = float(value)
    return (
        number
        if math.isfinite(number) and (number >= 0 if zero else number > 0)
        else None
    )


# Admit only the exact completed current bar with a known opening anchor.
def _quote(quote, start, now, session):
    if not isinstance(quote, dict):
        return None
    bar = entry_timing._instant(quote.get("bar"))
    published = entry_timing._instant(quote.get("as_of"))
    last, opened = _positive(quote.get("last")), _positive(quote.get("open"))
    if (
        bar != start
        or published != now
        or entry_timing.quote_session(quote) != session
        or last is None
        or opened is None
    ):
        return None
    return last


# Freeze the ordinary intent identity without inferring quantities from forecasts.
def _intent(row):
    if not isinstance(row, dict):
        raise ValueError("Explicit ordinary intent dictionary required")
    symbol, side, cid, qty = (
        row.get(k) for k in ("symbol", "side", "client_order_id", "qty")
    )
    if (
        not isinstance(symbol, str)
        or not symbol
        or side not in ("buy", "sell")
        or not isinstance(cid, str)
        or not cid
        or isinstance(qty, (bool, np.bool_))
        or not isinstance(qty, (int, np.integer))
        or qty <= 0
    ):
        raise ValueError("Explicit symbol/side/ID/positive whole quantity required")
    return cid, symbol, side, int(qty)


# Validate the fixed forecast clock and original named provider alignment.
def _contract(
    provider,
    symbols,
    day,
    clock,
    session,
    now,
    snapshot,
    pending,
    cost_bps,
    trace,
):
    now = _aware(now)
    if isinstance(session, str):
        session = date.fromisoformat(session)
    if not isinstance(session, date) or isinstance(session, datetime):
        raise ValueError("Explicit session date required")
    symbols = tuple(symbols)
    if (
        not symbols
        or any(not isinstance(s, str) or not s for s in symbols)
        or len(set(symbols)) != len(symbols)
        or any(
            isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer))
            for v in (day, clock)
        )
        or day < 0
        or not 0 <= clock <= 24
        or now.astimezone(calendar.NEW_YORK).date() != session
        or not isinstance(snapshot, dict)
        or not isinstance(snapshot.get("quotes"), dict)
        or not isinstance(pending, list)
        or not isinstance(trace, list)
        or (provider is not None and not callable(provider))
        or _positive(cost_bps, zero=True) is None
        or cost_bps >= 1e4
    ):
        raise ValueError(
            "Aligned explicit observation/provider/funding contract required"
        )
    years, sessions = calendar.reviewed_sessions()
    if session.year not in years or not np.is_busday(
        np.datetime64(session), busdaycal=sessions
    ):
        raise ValueError("Reviewed exchange session required")
    start = datetime.combine(
        session, calendar.REGULAR_OPEN, calendar.NEW_YORK
    ) + timedelta(minutes=15 * int(clock))
    if now != start + entry_timing.BAR or now > datetime.combine(
        session, calendar.session_close(session), calendar.NEW_YORK
    ):
        raise ValueError("Clock must name the exact current completed regular bar")
    owner = getattr(provider, "__self__", None)
    if (
        owner is not None
        and hasattr(owner, "verification")
        and (
            owner.verification.get("status") != "VERIFIED_SAVED_DISTRIBUTIONS"
            or tuple(owner.symbols) != symbols
            or day >= len(owner.dates)
            or owner.dates[day] != np.datetime64(session)
        )
    ):
        raise ValueError("Saved distribution symbol/date attestation differs")
    return now, session, symbols, start


# Preserve every ordinary unsent leg in the current batch, including repeated names.
def _intents(pending, session, symbols):
    if any(not isinstance(row, dict) for row in pending):
        raise ValueError("Explicit pending intent dictionaries required")
    rows = [
        r
        for r in pending
        if r.get("execution_timing") == intraday_orders.INTRADAY_TIMING
        and not r.get("event_id")
        and r.get("execute_on") == session.isoformat()
        and not r.get("sent")
    ]
    identities = [_intent(r) for r in rows]
    if len({r[0] for r in identities}) != len(identities) or any(
        r[1] not in symbols for r in identities
    ):
        raise ValueError("Unique aligned ordinary intent identities required")
    return identities


# Freeze only observed funds and held quantities before any request is submitted.
def _account(broker, marks, now):
    account_reason, nav, budget, held = "", None, None, {}
    try:
        account_clock = broker.clock()
        observed = entry_timing._instant(account_clock.get("timestamp"))
        if observed != now or account_clock.get("is_open") is not True:
            raise ValueError("Current observed open broker clock required")
        value = broker.account()
        nav, cash, power = (
            _positive(value.equity),
            _positive(value.cash, zero=True),
            _positive(value.buying_power, zero=True),
        )
        if nav is None or cash is None or power is None:
            raise ValueError("Finite positive equity and nonnegative cash required")
        budget = min(cash, power)
        for position in broker.positions():
            quantity = _positive(position.qty, zero=True)
            mark = _positive(position.current_price)
            if quantity is None or mark is None or position.symbol in held:
                raise ValueError("Explicit unique marked held quantities required")
            held[position.symbol] = quantity
            if (
                position.symbol in marks
                and marks[position.symbol] is not None
                and marks[position.symbol] != mark
            ):
                raise ValueError("Observed broker and quote price domains differ")
    except (AlpacaTradingError, OSError, ValueError, TypeError, AttributeError) as exc:
        account_reason = str(exc)
    return account_reason, nav, budget, held


# Freeze observable account and intent inputs before the sender's complete batch.
def build_reader(
    provider,
    symbols,
    day,
    clock,
    session,
    now,
    snapshot,
    pending,
    broker,
    cost_bps,
    trace,
):
    now, session, symbols, start = _contract(
        provider, symbols, day, clock, session, now, snapshot, pending, cost_bps, trace
    )
    identities = _intents(pending, session, symbols)
    original = {r[0]: r for r in identities}
    quotes = deepcopy(snapshot["quotes"])
    marks = {s: _quote(q, start, now, session) for s, q in quotes.items()}
    account_reason, nav, budget, held = _account(broker, marks, now)
    buying = [r for r in identities if r[2] == "buy"]
    missing_buy = any(marks.get(r[1]) is None for r in buying)
    spend = (
        None
        if missing_buy
        else sum(r[3] * marks[r[1]] for r in buying) * (1 + cost_bps / 1e4)
    )
    if spend is not None and not math.isfinite(spend):
        raise ValueError("Finite observed pending spend required")
    fraction = (
        min(1.0, budget / spend)
        if not account_reason and spend and budget is not None
        else 1.0
    )

    # Decide only the frozen current row without seeing fill outcomes or later cash.
    def reader(row, latch, quote, observation, today):
        if _aware(observation) != now or today != session:
            raise ValueError("Timing reader observation identity differs")
        identity = _intent(row)
        if original.get(identity[0]) != identity:
            raise ValueError("Timing reader original intent identity differs")
        cid, symbol, side, qty = identity
        mark = _quote(quote, start, now, session)
        reason = account_reason or (
            "unsupported learned clock"
            if clock > 22
            else "missing or stale completed raw quote"
            if mark is None or quote != quotes.get(symbol)
            else "unknown pending buy price"
            if side == "buy" and missing_buy
            else ""
        )
        observed_qty = (
            min(qty, math.floor(held.get(symbol, 0))) if side == "sell" else qty
        )
        weight = (
            0.0
            if reason
            else observed_qty * mark / nav * (fraction if side == "buy" else 1.0)
        )
        if reason:
            chosen = probability.Decision("unavailable", reason=reason)
        elif weight == 0:
            chosen = probability.Decision("no_trade", reason="no funded quantity")
        else:
            chosen = probability.decision(
                provider(int(day), int(clock), symbols.index(symbol))
                if provider is not None
                else None,
                side,
                weight,
                cost_bps,
                horizon=probability.HORIZON,
            )
        evidence = {
            "policy": POLICY,
            "intent_id": cid,
            "day": int(day),
            "session": session.isoformat(),
            "clock": int(clock),
            "symbol": symbol,
            "side": side,
            "desired_qty": qty,
            "observed_qty": observed_qty,
            "observed_price": mark,
            "nav": nav,
            "buying_power_budget": budget,
            "all_pending_buy_spend": spend,
            "buy_funding_fraction": fraction,
            "trade_fraction": weight,
            "state": chosen.state,
            "expected_log_utility": chosen.expected_log_utility,
            "reason": chosen.reason,
            "horizon": probability.HORIZON,
            "funding_is_ex_ante": True,
            "at": now.isoformat(),
        }
        trace.append(deepcopy(evidence))
        return {
            "send": intraday_orders.MARKET if chosen.state == "execute" else None,
            "timed": {
                **evidence,
                "open": (quote or {}).get("open"),
                "trigger_bar": start.isoformat(),
                "trigger_price": mark,
            },
        }

    return reader
