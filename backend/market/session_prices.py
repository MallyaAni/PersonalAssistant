"""Dated extended-hours display quotes, separate from strategy/execution inputs."""

import json
import math
import time
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from urllib.parse import urlencode

from backend.market import alpaca, calendar, desk_freshness, execution_quotes

MAX_AGE_SECONDS = 60
_cache = {}
_denied_until = {}


# Assign the overnight trade date using the published exchange calendar and local DST.
def session_window(now):
    local = now.astimezone(calendar.NEW_YORK)
    day = local.date()
    wall = local.time().replace(tzinfo=None)
    target = day + timedelta(days=1) if wall >= day_time(20) else day
    status = calendar.exchange_status(
        datetime.combine(target, day_time(12), calendar.NEW_YORK)
    )
    if not status["calendar_known"]:
        return "unknown", None, None
    if not status["is_session"]:
        return "closed", None, None
    if wall >= day_time(20) or wall < day_time(4):
        start = datetime.combine(
            target - timedelta(days=1), day_time(20), calendar.NEW_YORK
        )
        end = datetime.combine(target, day_time(4), calendar.NEW_YORK)
        return "overnight", start, end
    opening = datetime.combine(day, day_time(9, 30), calendar.NEW_YORK)
    closing = datetime.combine(day, calendar.session_close(day), calendar.NEW_YORK)
    if local < opening:
        return (
            "pre-market",
            datetime.combine(day, day_time(4), calendar.NEW_YORK),
            opening,
        )
    if local < closing:
        return "regular", opening, closing
    return (
        "post-market",
        closing,
        datetime.combine(day, day_time(20), calendar.NEW_YORK),
    )


# Keep invalid, old, future, and previous-session prices out of the current-price field.
def describe(raw, feed, now, start, end):
    stamp = desk_freshness.timestamp(raw.get("t"))
    result = {
        "price": None,
        "at": stamp.isoformat() if stamp else None,
        "feed": feed,
        "indicative": feed == "overnight",
        "status": "unavailable",
        "reason": "Quote unavailable",
        "valid_until": None,
    }
    try:
        bid, ask, bid_size, ask_size = (float(raw[k]) for k in ("bp", "ap", "bs", "as"))
        if (
            not all(math.isfinite(v) and v > 0 for v in (bid, ask, bid_size, ask_size))
            or bid > ask
        ):
            return {**result, "reason": "Invalid or empty quote"}
    except (KeyError, TypeError, ValueError, OverflowError):
        return result
    if (
        stamp is None
        or stamp > now
        or start is None
        or end is None
        or not start <= stamp < end
    ):
        return {**result, "reason": "No quote from this session"}
    deadline = min(stamp + timedelta(seconds=MAX_AGE_SECONDS), end)
    result["valid_until"] = deadline.isoformat()
    if now >= deadline:
        return {**result, "status": "stale", "reason": "Quote expired"}
    return {
        **result,
        "price": bid / 2 + ask / 2,
        "bid": bid,
        "ask": ask,
        "status": "fresh",
        "reason": "Indicative midpoint" if feed == "overnight" else "Quoted midpoint",
    }


# Request an entitled feed without retaining prices after a provider failure.
def _request_quotes(symbols, preferred, fallback, tick, request):
    try:
        headers = alpaca.credentials()
        feeds = (
            [preferred, fallback]
            if tick >= _denied_until.get(preferred, 0)
            else [fallback]
        )
        for candidate in feeds:
            status, body = request(
                "https://data.alpaca.markets/v2/stocks/quotes/latest?"
                + urlencode({"symbols": ",".join(symbols), "feed": candidate}),
                headers,
            )
            if status == 403:
                _denied_until[candidate] = tick + 300
                continue
            if status != 200:
                break
            payload = json.loads(body).get("quotes")
            return (candidate, payload) if isinstance(payload, dict) else (None, {})
    except Exception:
        pass  # Only quote reads; failures must not expose credentials or old prices.
    return None, {}


# Fetch a bounded display batch without purchasing data or sending orders.
def fetch(
    symbols, now=None, request=execution_quotes.transport, monotonic=time.monotonic
):
    supplied_now = now is not None
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("session prices require a dated instant")
    phase, start, end = session_window(now)
    result = {
        "session": phase,
        "as_of": now.isoformat(),
        "signal_scope": "regular-session",
        "quotes": {},
    }
    symbols = tuple(sorted(set(symbols)))
    if phase in ("regular", "closed", "unknown") or not symbols:
        return result
    preferred, fallback = (
        ("boats", "overnight") if phase == "overnight" else ("sip", "iex")
    )
    key = (symbols, phase, start.isoformat())
    tick = monotonic()
    cached = _cache.get(key)
    # Revalidate timestamps on every cache read, including exact session boundaries.
    if cached and 0 <= tick - cached[0] < 10:
        _, feed, quotes = cached
    else:
        feed, quotes = _request_quotes(symbols, preferred, fallback, tick, request)
        if len(_cache) >= 8:
            _cache.clear()
        _cache[key] = (tick, feed, quotes)
    if not supplied_now:
        now = datetime.now(UTC)
        current_phase, current_start, current_end = session_window(now)
        result["as_of"] = now.isoformat()
        if current_phase != phase or current_start != start:
            return {**result, "session": current_phase, "quotes": {}}
        end = current_end
    result["quotes"] = {
        symbol: describe(
            quotes.get(symbol) if isinstance(quotes.get(symbol), dict) else {},
            feed,
            now,
            start,
            end,
        )
        for symbol in symbols
    }
    return result
