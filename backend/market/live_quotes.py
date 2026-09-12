"""Live prices for the action board, one fifteen-minute candle at a time.

The board's levels are decided at the close. Whether a name is near or
through its stop is a fact of the current candle, and a person watching
it during the session needs that fact against the levels without
re-deciding anything. This reads the session's fifteen-minute bars from
Alpaca's free feed for a handful of names, remembers them for the length
of a candle so a page that refreshes often costs nothing, and returns the
last close, the session's high and low, and the bar's time.

It decides nothing. The intraday measurements found no signal at this
resolution that survives cost; what a candle adds is risk information.
"""

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as day_time
from zoneinfo import ZoneInfo

from backend.market import alpaca

CANDLE_SECONDS = 15 * 60


@dataclass(frozen=True)
class Quote:
    """One name's session so far: the last bar's close, the high, the low."""

    symbol: str
    last: float
    open: float  # the session's first bar's open
    high: float
    low: float
    bar: str  # the last bar's start, ISO
    as_of: str  # when this was fetched, ISO


# In-process memory of the last fetch per symbol, so a refresh inside the
# same candle answers from memory.
_cache: dict[str, tuple[float, Quote]] = {}


# Normalize provider timestamps, whose naive representation also means UTC.
def _bar_time(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC)


# Fold regular-session bars into a quote only when its opening candle exists.
def quote_from_bars(
    symbol: str, bars: list, fetched_at: datetime, session: date | None = None
) -> Quote | None:
    """Return the Quote of the session's bars, oldest first, or None."""
    today = session or fetched_at.astimezone(NEW_YORK).date()
    opening = datetime.combine(today, day_time(9, 30), NEW_YORK)
    closing = datetime.combine(today, day_time(16), NEW_YORK)
    # Provider timestamps are UTC; ignore extended hours and other dates.
    bars = sorted(
        (b for b in bars if opening <= _bar_time(b.start) < closing),
        key=lambda b: _bar_time(b.start),
    )
    if not bars or _bar_time(bars[0].start) != opening:
        return None
    last = bars[-1]
    return Quote(
        symbol=symbol,
        last=float(last.close),
        open=float(bars[0].open),
        high=float(max(b.high for b in bars)),
        low=float(min(b.low for b in bars)),
        bar=(
            last.start.isoformat()
            if hasattr(last.start, "isoformat")
            else str(last.start)
        ),
        as_of=fetched_at.isoformat(timespec="seconds"),
    )


NEW_YORK = ZoneInfo("America/New_York")


# Quotes for the symbols on the given session, from memory when the
# candle has not turned, else from the feed.
def quotes(
    symbols: list[str],
    session: date | None = None,
    fetch=alpaca.fetch_bars,
    now=time.monotonic,
    clock=lambda: datetime.now(UTC),
    headers: dict | None = None,
) -> dict[str, Quote]:
    """Return {symbol: Quote} for the symbols the feed has bars for."""
    # The session is the New York calendar day, not the UTC one: from 20:00
    # to midnight Eastern the UTC date has already rolled to tomorrow, and
    # asking the feed for tomorrow's bars gave the page no quotes, no live
    # read and no "prices as of" for those four hours every evening.
    today = session or clock().astimezone(NEW_YORK).date()
    out: dict[str, Quote] = {}
    for symbol in symbols:
        held = _cache.get(symbol)
        if (
            held
            and now() - held[0] < CANDLE_SECONDS
            and _bar_time(datetime.fromisoformat(held[1].bar))
            .astimezone(NEW_YORK)
            .date()
            == today
        ):
            out[symbol] = held[1]
            continue
        try:
            bars = fetch(symbol, today, today, headers=headers)
        except Exception:  # the feed is a convenience; the board stands without it
            continue
        quote = quote_from_bars(symbol, bars, clock(), session=today)
        if quote is not None:
            _cache[symbol] = (now(), quote)
            out[symbol] = quote
    return out


def forget() -> None:
    """Drop the memory, for tests."""
    _cache.clear()
