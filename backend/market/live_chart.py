"""Read-only current-session IEX candles for charts, never strategy inputs."""

import math
import threading
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from backend.market import alpaca
from backend.market import calendar as exchange_calendar

_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()
TTL = timedelta(seconds=20)


# Qualify an exact regular-session grid without synthesizing missing or future candles.
def qualify(bars, now: datetime, status: dict) -> list:
    _aware(now)
    if not status.get("calendar_known") or not status.get("is_session"):
        return []
    opening = datetime.fromisoformat(status["opens_at"])
    closing = datetime.fromisoformat(status["closes_at"])
    found = {}
    for bar in bars:
        _aware(bar.start)
        if not opening <= bar.start < closing or bar.start > now:
            continue
        _validate_bar(bar, opening)
        if bar.start in found:
            raise ValueError("Duplicate live chart candle")
        found[bar.start] = bar
    ordered = sorted(found.values(), key=lambda bar: bar.start)
    if not ordered:
        return []
    if ordered[0].start != opening or any(
        right.start - left.start != timedelta(minutes=15)
        for left, right in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("Incomplete live chart grid")
    if now < closing and now - ordered[-1].start >= timedelta(minutes=30):
        raise ValueError("Live chart candles are stale")
    if now >= closing and ordered[-1].start + timedelta(minutes=15) < closing:
        raise ValueError("Live chart session is incomplete")
    return ordered


# Require explicit time zones for both the observation clock and provider bars.
def _aware(instant: datetime) -> None:
    if instant.tzinfo is None:
        raise ValueError("Live chart timestamps must be timezone aware")


# Validate the printed prices and exact slot before accepting a candle.
def _validate_bar(bar, opening: datetime) -> None:
    seconds = (bar.start - opening).total_seconds()
    values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    if seconds % 900 or not all(math.isfinite(v) for v in values):
        raise ValueError("Malformed live chart candle")
    if min(values[:4]) <= 0 or bar.volume < 0:
        raise ValueError("Invalid live chart price")
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        raise ValueError("Invalid live chart range")


# Bound provider reads so an unavailable feed cannot monopolize the API thread.
def _transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    from curl_cffi import requests

    try:
        response = requests.get(url, headers=headers, timeout=10)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("Current chart transport unavailable") from exc
    if response.status_code != 200:
        raise RuntimeError("Current chart provider unavailable")
    return response.status_code, response.content


# Reuse current-session raw IEX candles only within their observation window.
def read(ticker: str, now: datetime | None = None) -> dict:
    supplied_clock = now is not None
    now = now or datetime.now(UTC)
    _aware(now)
    status = exchange_calendar.exchange_status(now)
    out = {
        "bars": [],
        "session": status.get("session"),
        "as_of": now.isoformat(),
        "feed": "iex",
        "adjustment": "raw",
        "reason": None,
        "complete": False,
    }
    if not status.get("calendar_known") or not status.get("is_session"):
        out["reason"] = "No current exchange session"
        return out
    opening = datetime.fromisoformat(status["opens_at"])
    if now < opening:
        out["reason"] = "Regular session has not opened"
        return out
    key = (
        ticker.upper(),
        status["session"],
        int((now - opening).total_seconds() // 900),
    )
    with _lock:
        held = _cache.get(key)
        if held and timedelta(0) <= now - held[0] < TTL:
            return held[1]
    try:
        day = opening.date()
        calls = 0

        # Bound unexpected pagination for a session below the provider's page limit.
        def transport(url, headers):
            nonlocal calls
            calls += 1
            if calls > 2:
                raise RuntimeError("Current chart pagination exceeded")
            return _transport(url, headers)

        bars = alpaca.fetch_bars(
            ticker.upper(), day, day, feed="iex", adjustment="raw", transport=transport
        )
        observed = now if supplied_clock else datetime.now(UTC)
        out["as_of"] = observed.isoformat()
        out["bars"] = qualify(bars, observed, status)
        if not out["bars"]:
            out["reason"] = "Current IEX candles unavailable"
        else:
            out["complete"] = observed >= datetime.fromisoformat(status["closes_at"])
            out["last_bar_complete"] = (
                out["bars"][-1].start + timedelta(minutes=15) <= observed
            )
    except (OSError, ValueError, RuntimeError) as exc:
        out["reason"] = f"Current IEX candles unavailable ({type(exc).__name__})"
    with _lock:
        _cache[key] = (now, out)
        _cache.move_to_end(key)
        while len(_cache) > 32:
            _cache.popitem(last=False)
    return out
