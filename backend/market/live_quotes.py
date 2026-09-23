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
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

from backend.market import alpaca, calendar

CANDLE_SECONDS = 15 * 60
CANDLE = timedelta(seconds=CANDLE_SECONDS)
# How long a quote whose newest bar is behind the bar the clock says should
# be complete is held before the feed is asked again. Long enough that a
# late provider is not hot-polled by a page refreshing every few seconds,
# short enough that the board is not one bar behind for a whole candle.
RECHECK_SECONDS = 60


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


# In-process memory of the last fetch per symbol: when the feed was last
# asked (monotonic), when that was on the wall clock, and the quote, so a
# refresh that cannot learn anything new answers from memory.
_cache: dict[str, tuple[float, datetime, Quote]] = {}


# Normalize provider timestamps, whose naive representation also means UTC.
def _bar_time(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC)


# Fold completed regular-session bars into a quote once the opening candle closes.
def quote_from_bars(
    symbol: str, bars: list, fetched_at: datetime, session: date | None = None
) -> Quote | None:
    """Return the Quote of the session's bars, oldest first, or None."""
    today = session or fetched_at.astimezone(NEW_YORK).date()
    opening = datetime.combine(today, day_time(9, 30), NEW_YORK)
    closing = datetime.combine(today, calendar.session_close(today), NEW_YORK)
    # Provider timestamps are UTC; ignore extended hours and other dates.
    bars = sorted(
        (
            b
            for b in bars
            if opening <= _bar_time(b.start) < closing
            and _bar_time(b.start) + timedelta(seconds=CANDLE_SECONDS) <= fetched_at
        ),
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
        bar=_bar_time(last.start).isoformat(),
        as_of=fetched_at.isoformat(timespec="seconds"),
    )


NEW_YORK = ZoneInfo("America/New_York")


# The bar the clock says should be complete by now: the memory is keyed on
# it, not on wall-clock seconds since some arbitrary fetch. A read at 09:59
# expects the 09:30 bar, and at 10:00 the 09:45 bar is complete, so a memory
# holding 09:30 is behind from that moment whether a minute or fourteen have
# passed. After the close (16:00, or 13:00 on an early close) the last bar
# of the session is all there will be. Before 09:45 nothing is complete.
def _expected_bar(when: datetime, session: date) -> datetime | None:
    """Start of the newest bar that should be complete at ``when``, or None."""
    opening = datetime.combine(session, day_time(9, 30), NEW_YORK)
    closing = datetime.combine(session, calendar.session_close(session), NEW_YORK)
    ny = when.astimezone(NEW_YORK)
    if ny < opening + CANDLE:
        return None
    completed = (ny - opening) // CANDLE
    return min(opening + (completed - 1) * CANDLE, closing - CANDLE)


# Whether a remembered quote can still answer for ``symbol`` now. It can when
# it is the session's quote and already carries the bar the clock expects;
# and, when the feed has not published that bar yet, for RECHECK_SECONDS
# after the last ask, so a late provider is neither hot-polled nor left one
# bar stale for a whole candle. This used to hold any quote for the length
# of a candle: a fetch at 10:00:02, before the provider had the 09:45 bar,
# pinned the 09:30 close to the board until 10:15.
def _still_good(held, symbol_session: date, now_utc: datetime, tick: float) -> bool:
    """Return whether the cached entry answers for this read."""
    if not held:
        return False
    checked, _, quote = held
    bar = _bar_time(datetime.fromisoformat(quote.bar))
    if bar.astimezone(NEW_YORK).date() != symbol_session:
        return False
    expected = _expected_bar(now_utc, symbol_session)
    if expected is None or bar >= expected:
        return True
    return tick - checked < RECHECK_SECONDS


# Quotes for the symbols on the given session, from memory when it already
# holds the bar the clock expects, else from the feed.
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
    now_utc = clock()
    out: dict[str, Quote] = {}
    for symbol in symbols:
        held = _cache.get(symbol)
        if _still_good(held, today, now_utc, now()):
            out[symbol] = held[2]
            continue
        try:
            bars = fetch(symbol, today, today, headers=headers)
        except Exception:  # the feed is a convenience; the board stands without it
            continue
        quote = quote_from_bars(symbol, bars, now_utc, session=today)
        if quote is not None:
            _cache[symbol] = (now(), now_utc, quote)
            out[symbol] = quote
    return out


def forget() -> None:
    """Drop the memory, for tests."""
    _cache.clear()
