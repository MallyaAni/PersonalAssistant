"""Fifteen-minute bars from Alpaca's free market data, as dated features.

Daily bars answered the question about daily technical analysis. The
operator's own method reads a 15-minute chart against the daily EMAs, and
below fifteen minutes is noise by their own account, so this is the one
intraday resolution the pipeline keeps. Alpaca's Basic plan (a free
account, no card) serves historical minute bars from the IEX feed back to
2016; prices are fine for bar shapes, volume is IEX's share only, which the
features here never use as an absolute.

Fetch: `/v2/stocks/bars` with `timeframe=15Min`, `feed=iex`,
`adjustment=all`, paged by `next_page_token`, keys from the environment
(`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`). Stored as immutable frames
(kind `bars_15m`) per ticker per as-of day, like everything else.

Features per (session, name), all from the session's own bars and so
known at its close:

    intraday trend      fraction of the session's 15-minute closes above
                        the session's running VWAP
    path                log(close / open) of the session (the daily gap is
                        already a daily channel; this is the day's body)
    first-hour return   log return over the first four bars
    last-hour return    log return over the last four bars
    intraday reversal   sign agreement of first-hour and last-hour returns
                        (-1 reversed, +1 continued, 0 flat)
    bars above 9 ema    fraction of 15-minute closes above the 15-minute
                        9-bar EMA (the operator's "holding the 9")
    ema9 crosses        number of times the 15-minute close crossed its
                        9-bar EMA, as a measure of chop
    range position      where the close sat in the session's range
    volume front-load   fraction of the session's volume in its first hour
    has_intraday        1 where the session had bars

The 15-minute bars are aligned to the daily panel by session date in New
York time. A session with fewer than eight bars is treated as absent.
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.market.panel import Panel

_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
_NEW_YORK = ZoneInfo("America/New_York")
BARS_KIND = "bars_15m"
MIN_BARS_PER_SESSION = 8

FEATURE_NAMES: tuple[str, ...] = (
    "intraday_trend",
    "intraday_path",
    "first_hour_return",
    "last_hour_return",
    "intraday_reversal",
    "bars_above_ema9",
    "ema9_crosses",
    "intraday_range_position",
    "volume_front_load",
    "has_intraday",
)
FEATURE_COUNT = len(FEATURE_NAMES)


class AlpacaUnavailableError(RuntimeError):
    """A fetch failed, was refused, or no keys are configured."""


@dataclass(frozen=True, slots=True)
class IntradayBar:
    """One 15-minute bar in UTC."""

    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


Transport = Callable[[str, dict[str, str]], tuple[int, bytes]]


# The API keys from the environment, or an error that says which is missing.
def credentials() -> dict[str, str]:
    """Return the Alpaca auth headers from APCA_API_KEY_ID / APCA_API_SECRET_KEY."""
    key = os.environ.get("APCA_API_KEY_ID", "").strip()
    secret = os.environ.get("APCA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        raise AlpacaUnavailableError(
            "APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set (free Alpaca account)"
        )
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


# The default transport: a GET with the auth headers.
def alpaca_transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    """GET an Alpaca URL and return (status, body)."""
    from curl_cffi import requests

    response = requests.get(url, headers=headers, timeout=60)
    return response.status_code, response.content


# Pure: one page of the bars response into IntradayBar rows for a symbol.
def parse_bars_page(
    payload: dict[str, Any], symbol: str
) -> tuple[list[IntradayBar], str | None]:
    """Return (bars, next_page_token) from one bars-endpoint page."""
    rows = (payload.get("bars") or {}).get(symbol) or []
    bars: list[IntradayBar] = []
    for row in rows:
        try:
            start = datetime.fromisoformat(
                str(row["t"]).replace("Z", "+00:00")
            ).astimezone(UTC)
            bars.append(
                IntradayBar(
                    start=start,
                    open=float(row["o"]),
                    high=float(row["h"]),
                    low=float(row["l"]),
                    close=float(row["c"]),
                    volume=float(row.get("v", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return bars, payload.get("next_page_token")


# Fetch every 15-minute bar for a symbol between two dates, paged.
def fetch_bars(
    symbol: str,
    start: date,
    end: date,
    transport: Transport = alpaca_transport,
    headers: dict[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[IntradayBar]:
    """Return the symbol's 15-minute bars over [start, end], oldest first."""
    headers = headers or credentials()
    bars: list[IntradayBar] = []
    token: str | None = None
    for _ in range(10_000):
        url = (
            f"{_BARS_URL}?symbols={symbol}&timeframe=15Min&feed=iex&adjustment=all"
            f"&limit=10000&sort=asc&start={start.isoformat()}T00:00:00Z"
            f"&end={end.isoformat()}T23:59:59Z"
        )
        if token:
            url += f"&page_token={token}"
        status, body = transport(url, headers)
        if status == 429:
            sleep(5.0)
            continue
        if status != 200:
            raise AlpacaUnavailableError(f"{symbol}: Alpaca returned HTTP {status}")
        page, token = parse_bars_page(json.loads(body), symbol)
        bars.extend(page)
        if not token:
            break
        # Basic plan: 200 requests a minute.
        sleep(0.35)
    return bars


# Serialise bars for the store's frames.
def bars_frame(bars: list[IntradayBar]) -> dict[str, list]:
    """Return the columns of a 15-minute bars frame."""
    return {
        "start": [b.start.isoformat() for b in bars],
        "open": [b.open for b in bars],
        "high": [b.high for b in bars],
        "low": [b.low for b in bars],
        "close": [b.close for b in bars],
        "volume": [b.volume for b in bars],
    }


# Rebuild bars from a stored frame.
def bars_from_frame(columns: dict[str, list]) -> list[IntradayBar]:
    """Return the IntradayBars a frame encodes."""
    return [
        IntradayBar(
            start=datetime.fromisoformat(columns["start"][i]),
            open=float(columns["open"][i]),
            high=float(columns["high"][i]),
            low=float(columns["low"][i]),
            close=float(columns["close"][i]),
            volume=float(columns["volume"][i]),
        )
        for i in range(len(columns.get("start", [])))
    ]


# Group bars by New York session date, regular hours only.
def sessions(bars: list[IntradayBar]) -> dict[date, list[IntradayBar]]:
    """Return {session date: bars in regular hours, in order}."""
    out: dict[date, list[IntradayBar]] = {}
    for bar in bars:
        local = bar.start.astimezone(_NEW_YORK)
        minutes = local.hour * 60 + local.minute
        if minutes < 9 * 60 + 30 or minutes >= 16 * 60:
            continue
        out.setdefault(local.date(), []).append(bar)
    return out


# The feature vector of one session from its bars.
def session_features(bars: list[IntradayBar]) -> np.ndarray:
    """Return the FEATURE_COUNT features of one session, or NaNs if too few bars."""
    out = np.full(FEATURE_COUNT, np.nan)
    if len(bars) < MIN_BARS_PER_SESSION:
        return out
    closes = np.array([b.close for b in bars])
    opens = np.array([b.open for b in bars])
    highs = np.array([b.high for b in bars])
    lows = np.array([b.low for b in bars])
    volumes = np.array([b.volume for b in bars])
    typical = (highs + lows + closes) / 3.0
    cum_volume = np.cumsum(np.maximum(volumes, 1e-9))
    vwap = np.cumsum(typical * np.maximum(volumes, 1e-9)) / cum_volume
    ema9 = np.empty_like(closes)
    ema9[0] = closes[0]
    for i in range(1, len(closes)):
        ema9[i] = 0.2 * closes[i] + 0.8 * ema9[i - 1]
    above = closes > ema9
    crosses = int(np.sum(above[1:] != above[:-1]))
    first = np.log(closes[3] / opens[0]) if closes[3] > 0 and opens[0] > 0 else 0.0
    last = np.log(closes[-1] / closes[-5]) if closes[-5] > 0 else 0.0
    reversal = float(np.sign(first) * np.sign(last)) if first and last else 0.0
    day_high, day_low = highs.max(), lows.min()
    position = (
        (closes[-1] - day_low) / (day_high - day_low) if day_high > day_low else 0.5
    )
    total_volume = volumes.sum()
    front = volumes[:4].sum() / total_volume if total_volume > 0 else 0.0
    out[:] = [
        float(np.mean(closes > vwap)),
        float(np.log(closes[-1] / opens[0])) if opens[0] > 0 else 0.0,
        first,
        last,
        reversal,
        float(np.mean(above)),
        float(crosses),
        float(position),
        float(front),
        1.0,
    ]
    return out


# Build the (T, N, FEATURE_COUNT) intraday feature array for a panel from
# per-ticker bars; names or sessions without bars get zeros and has=0.
def intraday_features(
    panel: Panel, bars_by_ticker: dict[str, list[IntradayBar]]
) -> np.ndarray:
    """Return per-(session, name) intraday features aligned to the panel."""
    out = np.zeros(
        (len(panel.dates), len(panel.tickers), FEATURE_COUNT), dtype=np.float32
    )
    calendar = {
        d: i for i, d in enumerate(panel.dates.astype("datetime64[D]").astype(object))
    }
    for column, ticker in enumerate(panel.tickers):
        bars = bars_by_ticker.get(ticker)
        if not bars:
            continue
        for session, rows in sessions(bars).items():
            t = calendar.get(session)
            if t is None:
                continue
            values = session_features(rows)
            if np.isfinite(values).all():
                out[t, column] = values
    return out
