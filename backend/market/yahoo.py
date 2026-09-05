"""Fetch daily history from Yahoo Finance in a way it does not refuse.

What the previous version got wrong, and this one is built around:

- **Yahoo refuses by TLS fingerprint, not by IP.** A plain `urllib` request
  with a Chrome user agent got HTTP 429 from two networks all day; the same
  URL fetched with a browser-impersonating TLS stack (curl_cffi) returned
  200 immediately. So the transport impersonates Chrome, and the user agent
  string is irrelevant.
- **The last bar of a live session is not a close.** During market hours the
  chart's final bar is the in-progress day. The parser compares the bar's
  session to the exchange's regular-session end and drops it when the
  session has not ended, so nothing stores a 2pm price as a close.
- **Corporate actions are data.** `events=div|split` returns dividends and
  splits with the bars, and they are kept: they are what lets a later reader
  check that an adjusted series is consistent, and what a total-return label
  needs.
- **Pacing and backoff are the fetcher's job.** One paced request at a time,
  `Retry-After` honoured, bounded retries on 429 and 5xx, then a captured
  failure — never a crash of the whole run.

What the endpoint gives, stated precisely because it matters downstream:
`close` is already split-adjusted as of the fetch (NVDA's pre-split closes
come back in post-split dollars) and `adjclose` is split- and
dividend-adjusted. There is no unadjusted series. The store therefore keeps
what the source returned on the day it was fetched, immutably, and
reproducibility is a matter of pinning that day.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_DEFAULT_TIMEZONE = "America/New_York"

# Minimum seconds between two requests, and how many times a refused or
# failed request is retried before it is captured as a failure.
DEFAULT_MIN_INTERVAL_SECONDS = 0.35
DEFAULT_MAX_ATTEMPTS = 4


class MarketDataUnavailableError(RuntimeError):
    """A fetch failed or was refused; the caller must flag, not crash."""


@dataclass(frozen=True, slots=True)
class DailyBar:
    """One completed trading session for one ticker."""

    session_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adjusted_close: float | None
    volume: int | None


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """A dividend (amount per share) or a split (ratio, e.g. 10.0 for 10:1)."""

    action_date: date
    kind: str  # "dividend" | "split"
    value: float


@dataclass(frozen=True, slots=True)
class TickerHistory:
    """Everything one fetch returned for one ticker, ready to store."""

    ticker: str
    bars: tuple[DailyBar, ...]
    actions: tuple[CorporateAction, ...]
    complete_through: date
    source_time: datetime
    source: str = "yahoo"


# A transport returns (status code, headers, body) for a URL. It is a
# parameter so tests exercise retries and parsing with no network, and so
# the impersonating client is an import-time detail of one function.
Transport = Callable[[str], tuple[int, dict[str, str], bytes]]


# The exchange-local calendar date of a Unix timestamp. Yahoo keys a daily
# bar to the session's open (13:30 UTC for New York), and the session date
# must be the exchange's date, not UTC's, so a late-evening fetch of an
# Asian listing does not land on the wrong day.
def _session_date(timestamp: int, zone: ZoneInfo) -> date:
    return datetime.fromtimestamp(timestamp, tz=zone).date()


# Read one value out of a quote series at an index, None if absent.
def _at(series: dict[str, Any], key: str, index: int) -> float | None:
    values = series.get(key) or []
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


# Whether the last bar is the live session rather than a completed one: its
# session is the day of the last trade, and that trade was before the
# regular session's end.
def _last_bar_is_in_progress(
    meta: dict[str, Any], last_session: date, zone: ZoneInfo
) -> bool:
    market_time = meta.get("regularMarketTime")
    regular = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    regular_end = regular.get("end")
    if market_time is None or regular_end is None:
        # Without the session bounds, be conservative: a bar dated today in
        # exchange time is treated as in progress.
        return last_session >= datetime.now(tz=zone).date()
    if _session_date(int(market_time), zone) != last_session:
        return False
    return int(market_time) < int(regular_end)


# Parse the events block into dated corporate actions, oldest first.
def _parse_actions(
    events: dict[str, Any], zone: ZoneInfo
) -> tuple[CorporateAction, ...]:
    actions: list[CorporateAction] = []
    for entry in (events.get("dividends") or {}).values():
        try:
            actions.append(
                CorporateAction(
                    _session_date(int(entry["date"]), zone),
                    "dividend",
                    float(entry["amount"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    for entry in (events.get("splits") or {}).values():
        try:
            ratio = float(entry["numerator"]) / float(entry["denominator"])
            actions.append(
                CorporateAction(_session_date(int(entry["date"]), zone), "split", ratio)
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    actions.sort(key=lambda action: (action.action_date, action.kind))
    return tuple(actions)


# Turn one chart payload into a TickerHistory. Pure: no network, no clock
# except through `now`, which exists so a test can pin it.
#
# A bar with no close is skipped rather than stored as zero; the in-progress
# session is dropped; the result is oldest-first.
def parse_chart_payload(
    payload: dict[str, Any],
    ticker: str,
    now: datetime | None = None,
) -> TickerHistory:
    """Parse a Yahoo chart payload into completed bars plus corporate actions."""
    try:
        result = payload["chart"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise MarketDataUnavailableError(
            f"{ticker}: unrecognised Yahoo payload: {exc}"
        ) from exc
    meta = result.get("meta") or {}
    zone = ZoneInfo(meta.get("exchangeTimezoneName") or _DEFAULT_TIMEZONE)
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjusted = (result.get("indicators", {}).get("adjclose") or [{}])[0]

    bars: list[DailyBar] = []
    for index, raw_ts in enumerate(timestamps):
        try:
            session = _session_date(int(raw_ts), zone)
        except (TypeError, ValueError):
            continue
        close = _at(quote, "close", index)
        if close is None:
            continue
        volume = _at(quote, "volume", index)
        bars.append(
            DailyBar(
                session_date=session,
                open=_at(quote, "open", index),
                high=_at(quote, "high", index),
                low=_at(quote, "low", index),
                close=close,
                adjusted_close=_at(adjusted, "adjclose", index),
                volume=None if volume is None else int(volume),
            )
        )
    if bars and _last_bar_is_in_progress(meta, bars[-1].session_date, zone):
        bars.pop()
    if not bars:
        raise MarketDataUnavailableError(
            f"{ticker}: Yahoo returned no completed daily bars"
        )

    source_time = now or datetime.now(tz=UTC)
    return TickerHistory(
        ticker=ticker,
        bars=tuple(bars),
        actions=_parse_actions(result.get("events") or {}, zone),
        complete_through=bars[-1].session_date,
        source_time=source_time,
    )


# The default transport: a Chrome-impersonating GET. Imported lazily so the
# parser and the store never need curl_cffi present.
def impersonating_transport(url: str) -> tuple[int, dict[str, str], bytes]:
    """GET a URL with a browser TLS fingerprint and return (status, headers, body)."""
    from curl_cffi import requests

    response = requests.get(url, impersonate="chrome", timeout=25)
    return (
        response.status_code,
        {k.lower(): v for k, v in response.headers.items()},
        response.content,
    )


class Pacer:
    """Keeps requests at least `min_interval` apart; the clock is injectable."""

    # `sleep` and `clock` are parameters so tests can measure pacing without
    # waiting for it.
    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    # Block until the minimum interval since the previous request has passed.
    def wait(self) -> None:
        """Sleep whatever remains of the interval since the last request."""
        if self._last is not None:
            remaining = self._min_interval + self._last - self._clock()
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


# The seconds to wait before retrying attempt `attempt` (1-based): the
# server's Retry-After when it gave one, else exponential from 2 s.
def _backoff_seconds(headers: dict[str, str], attempt: int) -> float:
    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            pass
    return float(2**attempt)


# The chart URL for one ticker over [start, end], with events included.
def chart_url(ticker: str, start: date, end: date) -> str:
    """Build the chart endpoint URL for a ticker and date range."""
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
    # end is inclusive: ask through the end of that day.
    end_next = end + timedelta(days=1)
    period2 = int(
        datetime(end_next.year, end_next.month, end_next.day, tzinfo=UTC).timestamp()
    )
    return (
        _CHART_URL.format(ticker=ticker)
        + f"?period1={period1}&period2={period2}&interval=1d&events=div%7Csplit"
    )


# Fetch and parse one ticker's history, paced, with bounded retries.
#
# Raises MarketDataUnavailableError when every attempt is refused or the payload
# cannot be read; the snapshot layer turns that into a per-ticker flag.
def fetch_history(
    ticker: str,
    start: date,
    end: date | None = None,
    *,
    transport: Transport = impersonating_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    now: datetime | None = None,
) -> TickerHistory:
    """Fetch daily bars and corporate actions for one ticker over a date range."""
    end = end or datetime.now(tz=UTC).date()
    url = chart_url(ticker, start, end)
    pacer = pacer or Pacer(sleep=sleep)
    last_error = "no attempt made"
    for attempt in range(1, max_attempts + 1):
        pacer.wait()
        try:
            status, headers, body = transport(url)
        except Exception as exc:  # network layer: retry, then capture
            last_error = f"transport error: {exc}"
            if attempt < max_attempts:
                sleep(_backoff_seconds({}, attempt))
            continue
        if status == 200:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise MarketDataUnavailableError(
                    f"{ticker}: Yahoo returned non-JSON"
                ) from exc
            chart_error = (payload.get("chart") or {}).get("error")
            if chart_error:
                description = (
                    chart_error.get("description", chart_error)
                    if isinstance(chart_error, dict)
                    else chart_error
                )
                raise MarketDataUnavailableError(
                    f"{ticker}: Yahoo chart error: {description}"
                )
            return parse_chart_payload(payload, ticker, now=now)
        if status == 404:
            raise MarketDataUnavailableError(
                f"{ticker}: Yahoo does not know this symbol (HTTP 404)"
            )
        last_error = f"HTTP {status}"
        if status in (429, 500, 502, 503, 504) and attempt < max_attempts:
            sleep(_backoff_seconds(headers, attempt))
            continue
        break
    raise MarketDataUnavailableError(
        f"{ticker}: Yahoo refused after {max_attempts} attempts ({last_error})"
    )
