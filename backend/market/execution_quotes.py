"""Read dated bid/ask evidence; never imply a quote guarantees an execution."""

import json
import math
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from backend.market import alpaca, alpaca_trading, desk_freshness

MAX_AGE_SECONDS = 30
MAX_SPREAD_BPS = 25  # Conservative execution filter, not a fitted return signal.
_cache: dict = {}
_sip_retry_at = 0.0


# Bound a quote request separately from the slower historical bar collector.
def transport(url, headers):
    from curl_cffi import requests

    response = requests.get(url, headers=headers, timeout=8)
    return response.status_code, response.content


# Fetch consolidated quotes when entitled, otherwise explicitly identify IEX evidence.
def fetch(symbols, request=transport, monotonic=time.monotonic):
    global _sip_retry_at
    symbols = tuple(sorted(set(symbols)))
    held = _cache.get(symbols)
    if held and monotonic() - held[0] < 5:
        return held[1]
    result = {"feed": None, "quotes": {}, "market_open": False}
    try:
        headers = alpaca.credentials()
        feed = "sip" if monotonic() >= _sip_retry_at else "iex"
        url = "https://data.alpaca.markets/v2/stocks/quotes/latest?"
        status, body = request(
            url + urlencode({"symbols": ",".join(symbols), "feed": feed}), headers
        )
        if status == 403 and feed == "sip":
            _sip_retry_at = monotonic() + 300
            feed = "iex"
            status, body = request(
                url + urlencode({"symbols": ",".join(symbols), "feed": feed}), headers
            )
        if status == 200:
            quotes = json.loads(body).get("quotes") or {}
            result = {
                "feed": feed,
                "quotes": {s: quotes[s] for s in symbols if s in quotes},
                "market_open": bool(
                    alpaca_trading.client_from_env().clock().get("is_open")
                ),
            }
    except Exception:
        # Fail closed without exposing authentication details.
        pass
    result["fetched_at"] = datetime.now(UTC).isoformat()
    _cache[symbols] = (monotonic(), result)
    return result


# Validate price shape, age, spread and positive displayed size independently per name.
def describe(raw, feed, market_open, now=None):
    now = now or datetime.now(UTC)
    stamp = desk_freshness.timestamp(raw.get("t"))
    result = {
        "feed": feed,
        "at": stamp.isoformat() if stamp else None,
        "eligible": False,
        "reason": "Quote unavailable",
        "valid_until": None,
    }
    try:
        bid, ask, bid_size, ask_size = [float(raw[k]) for k in ("bp", "ap", "bs", "as")]
        if (
            not all(math.isfinite(v) and v > 0 for v in (bid, ask, bid_size, ask_size))
            or ask < bid
        ):
            return {**result, "reason": "Invalid or empty quote"}
    except (KeyError, TypeError, ValueError):
        return result
    spread = (ask - bid) / ((ask + bid) / 2) * 10000
    result.update(
        bid=bid, ask=ask, spread_bps=spread, bid_size=bid_size, ask_size=ask_size
    )
    if stamp:
        result["valid_until"] = (stamp + timedelta(seconds=MAX_AGE_SECONDS)).isoformat()
    if not market_open:
        reason = "Market closed or clock unavailable"
    elif stamp is None or not 0 <= (now - stamp).total_seconds() < MAX_AGE_SECONDS:
        reason = "Quote expired"
    elif feed not in ("sip", "iex"):
        reason = "Unsupported quote feed"
    elif spread > MAX_SPREAD_BPS:
        reason = "Spread exceeds 25 bp"
    else:
        # The account has no consolidated feed, so an IEX quote is the best
        # dated evidence available; label the source rather than withholding.
        reason = f"{feed.upper()} quote checks passed"
        return {**result, "eligible": True, "reason": reason}
    return {**result, "reason": reason}
