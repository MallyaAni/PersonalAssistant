"""Fetch daily bars from Yahoo Finance, defensively.

Yahoo's v8 chart endpoint returns one OHLCV bar per trading session plus an
adjusted close that already accounts for splits and dividends. Every return
the research pipeline computes comes from adjusted close, so a stock split
never manufactures a return out of a raw close gap.

The endpoint is free and keyless but throttles by IP; a 429 or any non-200
raises MarketDataUnavailable, which the snapshot layer records as a flagged
ticker rather than a crash. The parser is a pure function over the payload,
so tests exercise it with a recorded fixture and never need the network.
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# A normal browser user agent, because Yahoo answers a plain script with 429.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


class MarketDataUnavailable(RuntimeError):
    """A fetch failed or was refused; the snapshot must flag, not crash."""


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One trading session for one ticker, as returned by a data source."""

    session_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adjusted_close: float | None
    volume: int | None


# The session date of a Yahoo daily timestamp. The endpoint keys each daily
# bar to the exchange's close, which for a US-listed name is the same UTC
# calendar date as the New York session, so the UTC date is the session date.
def _session_date(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp, tz=UTC).date()


# Turn one chart payload into daily bars, skipping bars with no data.
#
# Returns bars oldest-first. A bar with a missing quote is skipped rather
# than stored as zeros: a zero close would be read as a real price and a
# missing session is read as a gap, which is closer to the truth.
def parse_chart_payload(payload: dict[str, Any]) -> list[DailyBar]:
    """Parse a Yahoo chart payload into an oldest-first list of DailyBar."""
    try:
        result = payload["chart"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise MarketDataUnavailable(f"unrecognised Yahoo payload: {exc}") from exc
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjusted = (result.get("indicators", {}).get("adjclose") or [{}])[0]
    bars: list[DailyBar] = []
    for index, raw_ts in enumerate(timestamps):
        try:
            session_date = _session_date(int(raw_ts))
        except (TypeError, ValueError):
            continue
        close = quote.get("close", [None] * len(timestamps))[index]
        if close is None:
            continue
        bars.append(
            DailyBar(
                session_date=session_date,
                open=_at(quote, "open", index),
                high=_at(quote, "high", index),
                low=_at(quote, "low", index),
                close=float(close),
                adjusted_close=_at(adjusted, "adjclose", index),
                volume=_int_or_none(_at(quote, "volume", index)),
            )
        )
    if not bars:
        raise MarketDataUnavailable("Yahoo returned no daily bars")
    return bars


def _at(series: dict[str, Any], key: str, index: int) -> float | None:
    values = series.get(key) or []
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _int_or_none(value: float | None) -> int | None:
    return None if value is None else int(value)


# Fetch daily bars for one ticker over roughly `days` of sessions.
#
# Raises MarketDataUnavailable on a refused or unparseable response. The
# caller (the snapshot refresh) decides what a failure means per ticker.
def fetch_daily_bars(ticker: str, days: int = 730) -> list[DailyBar]:
    """Fetch daily bars for one ticker from Yahoo and parse them."""
    url = _CHART_URL.format(ticker=ticker) + f"?range={days}d&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise MarketDataUnavailable(
            f"{ticker}: Yahoo refused the request (HTTP {exc.code})"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MarketDataUnavailable(f"{ticker}: Yahoo unreachable ({exc})") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise MarketDataUnavailable(f"{ticker}: Yahoo returned non-JSON") from exc
    chart_error = (payload.get("chart") or {}).get("error")
    if chart_error:
        raise MarketDataUnavailable(
            f"{ticker}: Yahoo chart error: {chart_error.get('description', chart_error)}"
        )
    return parse_chart_payload(payload)
