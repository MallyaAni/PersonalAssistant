"""Dated extended-hours display quotes, separate from strategy/execution inputs."""

import json
import math
import time
from datetime import UTC, datetime, timedelta
from datetime import time as day_time
from itertools import count
from threading import Lock
from urllib.parse import urlencode

from backend.market import alpaca, calendar, desk_freshness

MAX_AGE_SECONDS = 60
CACHE_SECONDS = 10
_cache = {}
_denied_until = {}
_attempts = {}
_sequence = count()
_state_lock = Lock()


# Keep two sequential display reads within the browser's five-second request budget.
def transport(url, headers):
    from curl_cffi import requests

    response = requests.get(url, headers=headers, timeout=2)
    return response.status_code, response.content


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


# Date observations independently of the schedule and reject expired prices.
def describe(raw, feed, now):
    try:
        stamp = desk_freshness.timestamp(raw.get("t"))
        observation_session = session_window(stamp)[0] if stamp else "unknown"
    except (ValueError, OverflowError):
        stamp, observation_session = None, "unknown"
    result = {
        "price": None,
        "at": stamp.isoformat() if stamp else None,
        "feed": feed,
        "session": observation_session,
        "indicative": feed == "overnight",
        "status": "unavailable",
        "reason": "No fresh quote from available feeds",
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
    if stamp is None or stamp > now:
        return {**result, "reason": "Missing or future quote timestamp"}
    deadline = stamp + timedelta(seconds=MAX_AGE_SECONDS)
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


# Read one feed with a short raw cache and feed-wide backoff for provider failures.
def _request_quotes(symbols, feed, tick, request):
    key = (feed, symbols)
    # Only metadata is locked; separate requests never wait on a provider here.
    with _state_lock:
        if tick < _denied_until.get(feed, 0):
            return {}
        cached = _cache.get(key)
        if cached and 0 <= tick - cached[0] < CACHE_SECONDS:
            return cached[1]
        attempt = next(_sequence)
        _attempts[feed] = attempt
    quotes = {}
    backoff = 0
    try:
        headers = alpaca.credentials()
        status, body = request(
            "https://data.alpaca.markets/v2/stocks/quotes/latest?"
            + urlencode({"symbols": ",".join(symbols), "feed": feed}),
            headers,
        )
        if status == 200:
            payload = json.loads(body)
            raw = payload.get("quotes") if isinstance(payload, dict) else None
            if isinstance(raw, dict):
                quotes = raw
        else:
            backoff = {403: 300, 429: 30}.get(status, 10)
    except Exception:
        backoff = 10
    # An obsolete completion cannot erase newer evidence or impose older backoff.
    with _state_lock:
        if _attempts.get(feed) == attempt:
            _denied_until[feed] = tick + backoff
            if len(_cache) >= 8:
                _cache.clear()
            # Current failures replace old success rather than revive its price.
            _cache[key] = (tick, quotes)
    return quotes


# Prefer fresh primary evidence, fresh fallback, then the newest valid stale quote.
def _select(primary, fallback):
    if primary["status"] == "fresh":
        return primary
    if fallback["status"] == "fresh":
        return fallback
    stale = [row for row in (primary, fallback) if row["status"] == "stale"]
    if stale:
        return max(stale, key=lambda row: desk_freshness.timestamp(row["at"]))
    return primary if primary["at"] else fallback


# Fetch a bounded display batch without purchasing data or sending orders.
def fetch(symbols, now=None, request=transport, monotonic=time.monotonic):
    supplied_now = now is not None
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("session prices require a dated instant")
    phase, _, _ = session_window(now)
    result = {
        "session": phase,
        "as_of": now.isoformat(),
        "signal_scope": "regular-session",
        "quotes": {},
    }
    symbols = tuple(sorted(set(symbols)))
    if not symbols:
        return result
    wall = now.astimezone(calendar.NEW_YORK).time().replace(tzinfo=None)
    preferred, fallback = (
        ("boats", "overnight")
        if wall >= day_time(20) or wall < day_time(4)
        else ("sip", "iex")
    )
    primary = _request_quotes(symbols, preferred, monotonic(), request)
    if not supplied_now:
        now = datetime.now(UTC)
    first = {
        symbol: describe(
            primary.get(symbol) if isinstance(primary.get(symbol), dict) else {},
            preferred,
            now,
        )
        for symbol in symbols
    }
    unresolved = tuple(
        symbol for symbol in symbols if first[symbol]["status"] != "fresh"
    )
    secondary = (
        _request_quotes(unresolved, fallback, monotonic(), request)
        if unresolved
        else {}
    )
    if not supplied_now:
        now = datetime.now(UTC)
    result["session"] = session_window(now)[0]
    result["as_of"] = now.isoformat()
    # Revalidate at completion without changing original observation times.
    for symbol in symbols:
        candidates = [
            describe(
                raw.get(symbol) if isinstance(raw.get(symbol), dict) else {}, feed, now
            )
            for raw, feed in ((primary, preferred), (secondary, fallback))
        ]
        result["quotes"][symbol] = _select(*candidates)
    return result
