"""Opt-in, price-bounded execution; no fitted thresholds or live activation.

An explicitly bound order may attempt one whole-share IOC limit submission.
The contract freezes its identity, price budget, quote provenance and expiry.
An old bar is signal history, never an executable quote. An urgent exit bypasses
the ordinary bounce wait, but never its price floor or the regular-session clock.
IOC acceptance is not a fill; unfilled and partial outcomes must be reconciled.
"""

import math
from copy import deepcopy
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation

from backend.market import entry_timing

VERSION = "bounded-execution/1"
LIMIT_IOC = "limit_ioc"
FIELDS = {
    "version",
    "symbol",
    "side",
    "client_order_id",
    "session",
    "qty",
    "limit_price",
    "decision_at",
    "expires_at",
    "quote_source",
    "max_quote_age_seconds",
    "max_trigger_age_seconds",
    "max_spread_bps",
    "intent",
}


# Parse only positive, finite numerical values, excluding booleans.
def positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return (
        number
        if not isinstance(value, bool) and math.isfinite(number) and number > 0
        else None
    )


# Parse an explicit timezone-aware timestamp without inventing its timezone.
def instant(value):
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return result if result.utcoffset() is not None else None


# Round toward a stricter price bound using the broker's equity price increments.
def limit_text(value, side):
    if positive(value) is None or side not in ("buy", "sell"):
        raise ValueError("invalid limit price or side")
    try:
        price = Decimal(str(value))
        tick = Decimal("0.01") if price >= 1 else Decimal("0.0001")
        rounded = price.quantize(
            tick, rounding=ROUND_FLOOR if side == "buy" else ROUND_CEILING
        )
    except InvalidOperation as exc:
        raise ValueError("invalid limit price") from exc
    if rounded <= 0:
        raise ValueError("limit rounds to zero")
    return format(rounded, ".2f" if rounded >= 1 else ".4f")


# Reject malformed contracts or changes to the order identity they were bound to.
def contract_error(row, cfg):
    if not isinstance(cfg, dict) or set(cfg) != FIELDS or cfg.get("version") != VERSION:
        return "Invalid execution contract"
    for field, key in (
        ("symbol", "symbol"),
        ("side", "side"),
        ("client_order_id", "client_order_id"),
        ("qty", "qty"),
        ("session", "execute_on"),
    ):
        if cfg[field] != row.get(key):
            return "Order changed after execution was bound"
    qty = cfg["qty"]
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        return "Whole-share quantity required"
    if not all(
        isinstance(cfg[k], str) and cfg[k].strip()
        for k in ("symbol", "client_order_id", "quote_source")
    ):
        return "Execution identity and quote source required"
    intent = cfg["intent"]
    if (cfg["side"], intent) not in (
        ("buy", "entry"),
        ("sell", "trim"),
        ("sell", "exit"),
    ):
        return "Explicit entry, trim or exit intent required"
    if (
        row.get("event_id")
        or row.get("priority")
        or row.get("execution_timing") != entry_timing.RULE
    ):
        return "Only ordinary intraday orders support this contract"
    return budget_error(cfg)


# Validate explicit price and time budgets without selecting or fitting defaults.
def budget_error(cfg):
    if any(
        positive(cfg[k]) is None
        for k in (
            "limit_price",
            "max_quote_age_seconds",
            "max_trigger_age_seconds",
            "max_spread_bps",
        )
    ):
        return "Positive price, freshness and spread budgets required"
    start, end = instant(cfg["decision_at"]), instant(cfg["expires_at"])
    if start is None or end is None or start >= end:
        return "Explicit decision time and later expiry required"
    try:
        limit_text(cfg["limit_price"], cfg["side"])
    except ValueError:
        return "Invalid executable price bound"
    return None


# Bind an independent order copy to explicit budgets, without choosing their values.
def bind(
    row,
    *,
    limit_price,
    decision_at,
    expires_at,
    quote_source,
    max_quote_age_seconds,
    max_trigger_age_seconds,
    max_spread_bps,
    intent,
):
    cfg = {
        "version": VERSION,
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "client_order_id": row.get("client_order_id"),
        "session": row.get("execute_on"),
        "qty": row.get("qty"),
        "limit_price": limit_price,
        "decision_at": decision_at,
        "expires_at": expires_at,
        "quote_source": quote_source,
        "max_quote_age_seconds": max_quote_age_seconds,
        "max_trigger_age_seconds": max_trigger_age_seconds,
        "max_spread_bps": max_spread_bps,
        "intent": intent,
    }
    error = contract_error(row, cfg)
    if error:
        raise ValueError(error)
    cfg["limit_price"] = limit_text(limit_price, cfg["side"])
    for key in ("max_quote_age_seconds", "max_trigger_age_seconds", "max_spread_bps"):
        cfg[key] = float(cfg[key])
    return {**deepcopy(row), "execution_policy": cfg}


# Decide an attempt from the same causal evidence used by the board and executor.
def evaluate(row, timed, quote, now, today):
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Aware observation time required")
    cfg = row.get("execution_policy")
    out = {
        "version": VERSION,
        "send": None,
        "state": "invalid_contract",
        "reason": contract_error(row, cfg),
    }
    if out["reason"]:
        return out
    clock = entry_timing.session_clock(today)
    start, end = instant(cfg["decision_at"]), instant(cfg["expires_at"])
    out.update(
        limit_price=limit_text(cfg["limit_price"], cfg["side"]),
        expires_at=cfg["expires_at"],
        intent=cfg["intent"],
    )
    if (
        cfg["session"] != today.isoformat()
        or end.astimezone(entry_timing.NEW_YORK).date() != today
        or not clock["open"] < end <= clock["close"]
        or now < start
    ):
        out.update(
            state="invalid_contract", reason="Contract is not valid for this session"
        )
    elif now >= end:
        out.update(state="expired", reason="Execution permission expired")
    elif not timed.get("trading_day") or not clock["open"] <= now < clock["close"]:
        out.update(state="closed", reason="Outside the regular session")
    elif cfg["intent"] != "exit" and timed["state"] not in entry_timing.ACTING:
        out.update(state="waiting", reason="Waiting for an entry or trim trigger")
    else:
        if cfg["intent"] != "exit" and timed["state"] == entry_timing.TRIGGERED:
            bar = instant(timed.get("trigger_bar"))
            ended = bar + entry_timing.BAR if bar else None
            if (
                ended is None
                or not clock["open"] <= bar < ended <= now
                or ended > clock["close"]
                or (now - ended).total_seconds() > float(cfg["max_trigger_age_seconds"])
            ):
                out.update(
                    state="signal_expired",
                    reason="Earlier trigger is no longer actionable",
                )
                return out
        error = quote_error(quote, cfg, now, clock["open"])
        if error:
            out.update(state="quote_unavailable", reason=error)
        else:
            out["quote"] = {
                "symbol": quote["symbol"],
                "bid": float(quote["bid"]),
                "ask": float(quote["ask"]),
                "bid_size": float(quote["bid_size"]),
                "ask_size": float(quote["ask_size"]),
                "timestamp": quote["timestamp"],
                "received_at": quote["received_at"],
                "source": quote["source"],
                "price_basis": quote["price_basis"],
            }
            executable = quote["ask"] if cfg["side"] == "buy" else quote["bid"]
            limit = float(out["limit_price"])
            within = (
                float(executable) <= limit
                if cfg["side"] == "buy"
                else float(executable) >= limit
            )
            out.update(
                state="due" if within else "price_blocked",
                reason="IOC limit attempt due"
                if within
                else "Current price is outside the execution bound",
            )
            out["send"] = LIMIT_IOC if within else None
    return out


# Validate bid/ask evidence instead of treating a candle or fetch time as a quote.
def quote_error(quote, cfg, now, opening):
    if (
        not isinstance(quote, dict)
        or quote.get("symbol") != cfg["symbol"]
        or quote.get("source") != cfg["quote_source"]
        or quote.get("price_basis") != "raw"
    ):
        return "Qualified executable quote required"
    observed, received = (
        instant(quote.get("timestamp")),
        instant(quote.get("received_at")),
    )
    if (
        observed is None
        or received is None
        or not max(opening, instant(cfg["decision_at"])) <= observed <= received <= now
        or (now - observed).total_seconds() > float(cfg["max_quote_age_seconds"])
    ):
        return "Quote is stale, future-dated or predates the decision"
    bid, ask = positive(quote.get("bid")), positive(quote.get("ask"))
    if (
        bid is None
        or ask is None
        or bid > ask
        or positive(quote.get("bid_size")) is None
        or positive(quote.get("ask_size")) is None
    ):
        return "Valid bid/ask prices and displayed sizes required"
    if (ask - bid) / ((ask + bid) / 2) * 10000 > float(cfg["max_spread_bps"]):
        return "Spread exceeds the execution budget"
    return None


# Preserve provider timestamps and feed identity when attaching existing quote evidence.
def with_quotes(snapshot, evidence):
    result = deepcopy(snapshot or {})
    if (
        not isinstance(evidence, dict)
        or evidence.get("feed") not in ("iex", "sip")
        or evidence.get("market_open") is not True
    ):
        return result
    quotes = result.setdefault("quotes", {})
    raw_quotes = evidence.get("quotes")
    if not isinstance(raw_quotes, dict):
        return result
    for symbol, raw in raw_quotes.items():
        if not isinstance(raw, dict):
            continue
        bar = quotes.setdefault(symbol, {})
        bar["execution_quote"] = {
            "symbol": symbol,
            "bid": raw.get("bp"),
            "ask": raw.get("ap"),
            "bid_size": raw.get("bs"),
            "ask_size": raw.get("as"),
            "timestamp": raw.get("t"),
            "received_at": evidence.get("fetched_at"),
            "source": evidence["feed"],
            "price_basis": "raw",
        }
    return result
