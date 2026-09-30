"""The structure the board shows and the desk does not act on.

The operator trades his own account from the board, so before any rule
about levels is measured (`docs/research/trading-scenarios-2026-09-30.md`,
S0) he can at least see the two levels he reads: the 21-session EMA of the
adjusted close and the 20-session high, the distance to each, the EMA's
slope over five sessions, and whether the session's first 15-minute bar
tagged a level from below and closed back under it. Nothing here decides
anything: the balancer's rows carry these fields, the board prints them,
and every rule that might act on them is a registered study, not this file.

The inputs are what the balancer already has: the daily bars in the store
(`MarketStore.read`, split-adjusted, with the dividend-adjusted close), the
candle's quote (`live_quotes.Quote`: the last completed bar's close, the
session's open, high and low, and the bar's start), and the session's
first-bar latch (`entry_timing`, which keeps the opening bar's high and
close once the later candles have folded them into the session's high).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# The EMA's span in sessions and the slope's look-back, as the board names them.
EMA_SPAN = 21
SLOPE_SESSIONS = 5
# The 20-session high: the same window `actions.HIGH_WINDOW` builds the
# record's `high_20` from (restated here so this module needs no numpy).
HIGH_WINDOW = 20
# A first-bar high this close under a level counts as reaching it.
TAG_BAND = 0.005
# A daily high this close to a level counts as a session at the level.
NEAR_BAND = 0.01
# The levels a tag can name, in the order they are tried.
LEVELS = ("ema_21", "high_20")
# One candle: the quote's bar starts here and its price is the close of it.
BAR = timedelta(minutes=15)
NEW_YORK = ZoneInfo("America/New_York")


# A finite positive price, or None for anything a level cannot be built on.
def _price(value: object) -> float | None:
    """Return `value` as a finite positive float, else None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


# A timezone-aware instant from an ISO string, or None.
def _instant(value: object) -> datetime | None:
    """Return the aware datetime `value` names, else None."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


# The exponential moving average of `values` with pandas' `adjust=False`
# recursion: the first value seeds it, then e_t = a*v_t + (1-a)*e_{t-1}
# with a = 2/(span+1). One value per input, so a caller can read the EMA
# on any session.
def ema(values: list[float], span: int = EMA_SPAN) -> list[float]:
    """Return the EMA series of `values`, empty when `values` is empty."""
    if span < 1:
        raise ValueError("span must be at least 1")
    alpha = 2.0 / (span + 1.0)
    out: list[float] = []
    for value in values:
        value = float(value)
        out.append(value if not out else alpha * value + (1.0 - alpha) * out[-1])
    return out


# The EMA's slope over `sessions`: today's EMA minus the EMA `sessions`
# earlier, as a fraction of today's, so +0.031 reads as the average having
# risen 3.1% over five sessions. None when the series is too short.
def ema_slope(series: list[float], sessions: int = SLOPE_SESSIONS) -> float | None:
    """Return (ema[-1] - ema[-1-sessions]) / ema[-1], else None."""
    if sessions < 1 or len(series) <= sessions or not series[-1]:
        return None
    return (series[-1] - series[-1 - sessions]) / series[-1]


# The store's bars strictly before `session`, oldest first: the levels are
# read "up to the prior session", so a same-day bar the nightly append has
# already written is left out, and the live candle is compared against
# levels that do not contain it.
def prior_bars(bars, session: date) -> list:
    """Return the bars dated before `session`, in date order."""
    return sorted(
        (b for b in bars if b.session_date < session), key=lambda b: b.session_date
    )


# The 21-EMA and its five-session slope from the prior sessions' adjusted
# closes; both None without a full span of closes.
def ema_levels(prior) -> tuple[float | None, float | None]:
    """Return (ema_21, ema_21_slope_5) from the prior bars."""
    closes = [
        float(b.adjusted_close)
        for b in prior
        if _price(getattr(b, "adjusted_close", None)) is not None
    ]
    if len(closes) < EMA_SPAN:
        return None, None
    series = ema(closes, EMA_SPAN)
    return series[-1], ema_slope(series, SLOPE_SESSIONS)


# The highest daily high of the last `HIGH_WINDOW` prior sessions, or None.
def high_20(prior) -> float | None:
    """Return the 20-session high from the prior bars."""
    highs = [
        float(b.high) for b in prior[-HIGH_WINDOW:] if _price(getattr(b, "high", None))
    ]
    return max(highs) if highs else None


# How many sessions in a row, ending today, a name has sat at a level: today
# counts as one (the tag is at the level), and each earlier session counts
# while its daily high was within `NEAR_BAND` of the level and its close
# stayed under it. The first session that fails ends the count.
def consecutive_sessions(level: float, prior) -> int:
    """Return the run of sessions at `level`, including today."""
    count = 1
    for bar in reversed(prior):
        high = _price(getattr(bar, "high", None))
        close = _price(getattr(bar, "close", None))
        if high is None or close is None:
            break
        if abs(high / level - 1.0) <= NEAR_BAND and close < level:
            count += 1
            continue
        break
    return count


# Whether the session's first bar tagged `level` from below: the prior
# close was under the level and the bar's high reached within `TAG_BAND`
# of it (or through it). Rejected when that bar closed back under the level.
def tag_for(
    name: str,
    level: float | None,
    prior_close: float | None,
    first_bar: dict | None,
    prior,
) -> dict | None:
    """Return the level_tag dict for `name` at `level`, else None."""
    if level is None or prior_close is None or not isinstance(first_bar, dict):
        return None
    bar_high = _price(first_bar.get("high"))
    bar_close = _price(first_bar.get("close"))
    if bar_high is None or bar_close is None:
        return None
    if prior_close >= level or bar_high < level * (1.0 - TAG_BAND):
        return None
    return {
        "level": name,
        "price": level,
        "first_bar_high": bar_high,
        "first_bar_close": bar_close,
        "rejected": bar_close < level,
        "consecutive_sessions": consecutive_sessions(level, prior),
    }


# The one tag for a name, or None: each level is tried, and when the first
# bar reached both, the level nearer its high is the one named.
def level_tag(
    levels: dict[str, float | None],
    prior_close: float | None,
    first_bar: dict | None,
    prior,
) -> dict | None:
    """Return the tag on the level the first bar reached, else None."""
    tags = [
        tag
        for name in LEVELS
        if (tag := tag_for(name, levels.get(name), prior_close, first_bar, prior))
    ]
    if not tags:
        return None
    return min(tags, key=lambda t: abs(t["first_bar_high"] - t["price"]))


# The first bar of the session for a name: the latch's record when it has
# one, else the quote itself when the quote's bar IS the opening bar (its
# session high and last are then the first bar's own).
def first_bar_of(quote: dict | None, latched: dict | None) -> dict | None:
    """Return {high, close} for the session's opening bar, else None."""
    if isinstance(latched, dict) and isinstance(latched.get("first_bar"), dict):
        return latched["first_bar"]
    bar = _instant((quote or {}).get("bar"))
    if bar is None:
        return None
    local = bar.astimezone(NEW_YORK)
    if local.hour != 9 or local.minute != 30:
        return None
    high = _price(quote.get("high"))  # type: ignore[union-attr]
    close = _price(quote.get("last"))  # type: ignore[union-attr]
    if high is None or close is None:
        return None
    return {"high": high, "close": close, "bar": bar.isoformat()}


# When the row's price is from and how old it is at `as_of`: the price is
# the last completed bar's close, so its instant is that bar's end. Both
# None without a dated quote.
def price_age(quote: dict | None, as_of: datetime) -> tuple[str | None, float | None]:
    """Return (price_as_of ISO, price_age_seconds) for the quote."""
    bar = _instant((quote or {}).get("bar"))
    if bar is None:
        return None, None
    if as_of.tzinfo is None:
        raise ValueError("price_age requires a timezone-aware as_of")
    priced = bar + BAR
    return priced.isoformat(timespec="seconds"), (as_of - priced).total_seconds()


# The structure for one name from its daily bars, the session, its quote
# and its first-bar record: the fields the board prints, and nothing else.
def describe(
    bars, session: date, quote: dict | None, first_bar: dict | None, as_of: datetime
) -> dict:
    """Return the structure fields for one name."""
    prior = prior_bars(bars or [], session)
    ema_21, slope = ema_levels(prior)
    high = high_20(prior)
    prior_close = _price(prior[-1].close) if prior else None
    priced_at, age = price_age(quote, as_of)
    return {
        "ema_21": ema_21,
        "ema_21_slope_5": slope,
        "high_20": high,
        "level_tag": level_tag(
            {"ema_21": ema_21, "high_20": high}, prior_close, first_bar, prior
        ),
        "price_as_of": priced_at,
        "price_age_seconds": age,
    }


# The structure for every row, written onto each row and returned by ticker
# for the live snapshot. A name the store cannot read keeps null levels; a
# row's own `high_20` from the record stands when the store gives none.
def annotate(
    rows: list[dict],
    store,
    quotes: dict,
    latch: dict | None,
    session: date,
    as_of: datetime,
) -> dict[str, dict]:
    """Add the structure fields to `rows`; return them by ticker."""
    out: dict[str, dict] = {}
    symbols = (latch or {}).get("symbols") or {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        try:
            history = store.read(ticker)
            bars = list(history.bars) if history is not None else []
        except Exception:  # noqa: BLE001 - a name the store lacks keeps null levels
            bars = []
        quote = quotes.get(ticker) if isinstance(quotes, dict) else None
        fields = describe(
            bars, session, quote, first_bar_of(quote, symbols.get(ticker)), as_of
        )
        if fields["high_20"] is None and _price(row.get("high_20")) is not None:
            fields["high_20"] = float(row["high_20"])
        row.update(fields)
        out[ticker] = dict(fields)
    return out
