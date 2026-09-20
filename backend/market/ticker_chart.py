"""One name's price history with the lines the desk actually scores on.

The board tells a trader what the desk concluded. It never showed them the
picture the conclusion was drawn from, so a grade that moved for a good
reason and one that moved for a broken reason looked identical on screen.

TIMEFRAMES. The desk reads two and only two: daily and weekly. The daily
stack is `technical.technical_features` (9/21/50/200 EMAs, the 200 simple,
the three MACD pairs, the candle patterns) with the 20-session Bollinger
band from `bands`, and the longer daily lookbacks the reads quote by name:
the 52-week extremes, the 60-session range, and the swing levels confirmed
inside `levels.LEVEL_LOOKBACK`. The weekly stack is the 9 and 21 EMAs on
weekly closes, which is what `weekly_trend` and `weekly_stack` are built
from. There is no monthly reading anywhere in the desk, so this module
offers no monthly timeframe: a chart that let a trader reason from a bar
size no analyst looks at would invite exactly the disagreement between the
picture and the grade that the chart exists to remove.

The weekly bars here are bucketed by `_week_ends`, which reproduces the
rule in `technical._weekly_ema` exactly, shift and holiday-short weeks and
all. If that rule ever changes, this must change with it, or the weekly
picture stops being the one the weekly legs were scored from.

BASIS. Everything is on the adjusted basis, because that is what the
analysts read: `technical.technical_features` works from `panel.adj_close`,
and `levels` scales the high and the low by `adj_close / close` before it
looks for swing points. A chart drawn from raw prices would put the candles
and the averages on two different scales for any name that has paid a
dividend or split. So the open, high and low are scaled by that same factor
and the result is an adjusted-price chart, labelled as one.

Causal throughout: session t uses sessions up to t and no further, so a
replayed history shows what was knowable that night and not what came
after. The swing levels carry the same `SWING`-session confirmation delay
the desk grades on, so a level appears on the chart the day the desk could
first have used it, not the day it formed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.market import bands, levels
from backend.market.store import MarketStore
from backend.market.technical import ema, sma

# Enough sessions for a 200-day average to exist across the whole drawn
# window, plus about a year of it to look at.
DEFAULT_SESSIONS = 260
DAILY, WEEKLY = "daily", "weekly"
TIMEFRAMES = (DAILY, WEEKLY)

# The daily averages the desk's own stack is built from.
EMA_SPANS = (9, 21, 50, 200)
# The weekly ones behind `weekly_trend` and `weekly_stack`.
WEEKLY_EMA_SPANS = (9, 21)
# The two daily lookbacks the technical reads quote in words.
RANGE_SESSIONS = 60
YEAR_SESSIONS = 252


@dataclass(frozen=True, slots=True)
class Chart:
    """One name's drawable history: bars, overlay lines, and their dates."""

    ticker: str
    timeframe: str
    # False when the newest bar is a week still forming. Daily bars are
    # always complete here: today's session arrives from the live quote in
    # the browser, not from the store.
    last_bar_complete: bool
    dates: tuple[str, ...]
    open: tuple[float | None, ...]
    high: tuple[float | None, ...]
    low: tuple[float | None, ...]
    close: tuple[float | None, ...]
    volume: tuple[float | None, ...]
    overlays: dict[str, tuple[float | None, ...]]
    levels: dict[str, tuple[float | None, ...]]
    # The sessions the desk's price trigger fired on, within the drawn range.
    entries: tuple[str, ...] = ()


# NaN and numpy scalars are not JSON, and a chart library wants a gap rather
# than a zero where a value does not exist yet.
def _clean(values: np.ndarray) -> tuple[float | None, ...]:
    """Return the column as plain floats with NaN turned into None."""
    return tuple(
        None if not np.isfinite(v) else round(float(v), 6) for v in np.asarray(values)
    )


# Which sessions end a trading week, by the same rule `technical._weekly_ema`
# uses: a Friday, or the last session on file before the week number turns.
# Kept a separate function so the weekly bars and the weekly EMAs the desk
# scored cannot drift apart.
def _week_ends(dates: np.ndarray) -> np.ndarray:
    """Return the row indices that close a trading week."""
    days = dates.astype("datetime64[D]").astype(int)
    weeks = (days + 3) // 7
    friday = (days + 3) % 7 == 4
    rows = len(days)
    ends = [
        bool(friday[t]) or (t + 1 < rows and weeks[t + 1] != weeks[t])
        for t in range(rows)
    ]
    return np.flatnonzero(np.array(ends))


# Roll daily bars up into weekly ones: the week's first open, its extremes,
# its closing close, and its total volume.
def _weekly_bars(
    dates: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
) -> tuple[np.ndarray, ...]:
    """Return (dates, open, high, low, close, volume) resampled to weeks."""
    ends = _week_ends(dates)
    # The week in progress has no Friday yet, so `_week_ends` does not close
    # it and the newest bar would be up to a week old. A trader reads the
    # forming bar on every other platform, so it is included and the caller
    # is told the last one is not complete.
    if not len(ends) or ends[-1] != len(dates) - 1:
        ends = np.append(ends, len(dates) - 1)
    starts = np.concatenate([[0], ends[:-1] + 1]) if len(ends) else np.array([], int)
    keep = [i for i, (a, b) in enumerate(zip(starts, ends)) if b >= a]
    starts, ends = starts[keep], ends[keep]
    with np.errstate(all="ignore"):
        return (
            dates[ends],
            np.array([open_[a, 0] for a in starts]).reshape(-1, 1),
            np.array([np.nanmax(high[a : b + 1, 0]) for a, b in zip(starts, ends)]).reshape(-1, 1),
            np.array([np.nanmin(low[a : b + 1, 0]) for a, b in zip(starts, ends)]).reshape(-1, 1),
            close[ends],
            np.array([np.nansum(volume[a : b + 1, 0]) for a, b in zip(starts, ends)]).reshape(-1, 1),
        )


# A trailing extreme over `length` bars, NaN until that many exist. The
# 52-week and 60-session lines the technical reads quote are both this.
def _rolling(values: np.ndarray, length: int, highest: bool) -> np.ndarray:
    """Return the trailing max (or min) over `length` bars, causal."""
    out = np.full(values.shape, np.nan)
    pick = np.nanmax if highest else np.nanmin
    for t in range(length - 1, values.shape[0]):
        with np.errstate(all="ignore"):
            out[t] = pick(values[t - length + 1 : t + 1], axis=0)
    return out


# Build one name's chart straight from the store, without assembling the
# whole 93-name panel: a single drill-down should not pay for the book.
def build(
    store: MarketStore,
    ticker: str,
    sessions: int = DEFAULT_SESSIONS,
    timeframe: str = DAILY,
    live_bar: dict | None = None,
) -> Chart | None:
    """Return the drawable history for `ticker`, or None when it has none."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {TIMEFRAMES}, not {timeframe!r}")
    entry_fired: np.ndarray | None = None
    history = store.read(ticker.upper())
    if history is None or not history.bars:
        return None
    bars = sorted(history.bars, key=lambda b: b.session_date)

    def column(name: str) -> np.ndarray:
        raw = [getattr(b, name) for b in bars]
        return np.array(
            [np.nan if v is None else float(v) for v in raw], dtype=float
        ).reshape(-1, 1)

    open_, high, low = column("open"), column("high"), column("low")
    close, adj_close, volume = column("close"), column("adjusted_close"), column("volume")
    dates = np.array([np.datetime64(b.session_date, "D") for b in bars])

    # Today's session, from the same quote the board reads, appended before
    # anything is computed. Without it the candle moved while every average
    # and band beside it stayed at the last close, which is the one thing a
    # chart must not do: the picture would say price is far under its 21-day
    # average using a 21-day average that had not seen today. Appending here
    # rather than in the browser keeps one implementation of the maths.
    #
    # No adjustment factor applies to a bar that has not closed, so the raw
    # and adjusted prices are the same for it.
    if live_bar:
        session = live_bar.get("session")
        last = live_bar.get("last")
        if session is not None and last is not None and np.isfinite(float(last)):
            stamp = np.datetime64(str(session), "D")
            price = float(last)
            fields = (
                float(live_bar.get("open") or price),
                float(live_bar.get("high") or price),
                float(live_bar.get("low") or price),
                price,
            )
            if stamp > dates[-1]:
                dates = np.append(dates, stamp)
                open_ = np.vstack([open_, [[fields[0]]]])
                high = np.vstack([high, [[fields[1]]]])
                low = np.vstack([low, [[fields[2]]]])
                close = np.vstack([close, [[price]]])
                adj_close = np.vstack([adj_close, [[price]]])
                volume = np.vstack([volume, [[np.nan]]])
            elif stamp == dates[-1]:
                open_[-1, 0], high[-1, 0], low[-1, 0] = fields[0], fields[1], fields[2]
                close[-1, 0] = adj_close[-1, 0] = price

    # The same adjustment levels.py applies, so the candles sit on the line
    # the averages are computed from.
    with np.errstate(all="ignore"):
        factor = np.where(close > 0, adj_close / close, np.nan)
    open_, high, low = open_ * factor, high * factor, low * factor

    all_dates = dates
    # Swing levels are found on daily bars whatever the drawn timeframe,
    # because that is where the desk finds them.
    swing_low, swing_high = levels.swing_points(high, low)

    overlays: dict[str, np.ndarray] = {}
    level_lines: dict[str, np.ndarray] = {}
    if timeframe == WEEKLY:
        w_dates, w_open, w_high, w_low, w_close, w_volume = _weekly_bars(
            dates, open_, high, low, adj_close, volume
        )
        # Forward-fill the daily swing levels onto the week they close in,
        # so a weekly chart still shows the levels the desk is grading by.
        ends = _week_ends(dates)
        keep = [i for i in range(len(ends))]
        for name, series in (("swing_low", swing_low), ("swing_high", swing_high)):
            level_lines[name] = np.array(
                [
                    np.nanmax(series[max(0, ends[i] - 4) : ends[i] + 1, 0])
                    if np.isfinite(series[max(0, ends[i] - 4) : ends[i] + 1, 0]).any()
                    else np.nan
                    for i in keep
                ]
            ).reshape(-1, 1)
        for span in WEEKLY_EMA_SPANS:
            overlays[f"ema{span}"] = ema(w_close, span)
        dates, open_, high, low, adj_close, volume = (
            w_dates,
            w_open,
            w_high,
            w_low,
            w_close,
            w_volume,
        )
    else:
        for span in EMA_SPANS:
            overlays[f"ema{span}"] = ema(adj_close, span)
        overlays["sma200"] = sma(adj_close, 200)
        lower, middle, upper = bands.edges(adj_close)
        overlays["band_lower"] = lower
        overlays["band_middle"] = middle
        overlays["band_upper"] = upper
        # Where the desk's own entry fired. The rule is a band position, and
        # the band is already on the chart, so a marker on the bar that
        # triggered lets the operator check the rule against the price
        # instead of taking a backtest's word for it. The grade condition is
        # not applied here - the chart has prices, not grades - so this is
        # the price half of the trigger, and the grade markers the page
        # already draws are the other half.
        from backend.agents.trading.desk import entry as entry_analyst
        from backend.agents.trading.desk import paper as paper_rules

        band_z = entry_analyst.bollinger_z(adj_close)[:, 0]
        with np.errstate(invalid="ignore"):
            fired = np.isfinite(band_z) & (band_z >= paper_rules.ENTRY_BAND_Z)
        # band_z is a ratio around 1.0, not a price. It is deliberately NOT
        # an overlay: on a chart scaled to a $180 stock it would be a flat
        # line at the bottom, and any attempt to draw it would wreck the
        # axis. The dates it crossed are what the chart needs.
        entry_fired = fired
        level_lines["swing_low"] = swing_low
        level_lines["swing_high"] = swing_high
        level_lines["high_52w"] = _rolling(high, YEAR_SESSIONS, True)
        level_lines["low_52w"] = _rolling(low, YEAR_SESSIONS, False)
        level_lines["range60_high"] = _rolling(high, RANGE_SESSIONS, True)
        level_lines["range60_low"] = _rolling(low, RANGE_SESSIONS, False)

    # Trim only after every line is computed, so a 200-day average is
    # present on the first drawn bar rather than a third of the way across.
    keep_n = max(1, min(len(dates), sessions))
    cut = slice(len(dates) - keep_n, len(dates))
    return Chart(
        ticker=ticker.upper(),
        timeframe=timeframe,
        # bool() around the whole thing, not just the length: a numpy
        # comparison yields numpy.bool_, which Pydantic refuses to
        # serialise. The daily branch short-circuits to a Python bool and
        # hid it, so only the weekly timeframe returned a 500 in
        # production while every test passed.
        last_bar_complete=bool(
            timeframe == DAILY
            or (
                len(_week_ends(all_dates))
                and _week_ends(all_dates)[-1] == len(all_dates) - 1
            )
        ),
        dates=tuple(str(d) for d in dates[cut]),
        open=_clean(open_[cut, 0]),
        high=_clean(high[cut, 0]),
        low=_clean(low[cut, 0]),
        close=_clean(adj_close[cut, 0]),
        volume=_clean(volume[cut, 0]),
        entries=tuple(
            str(d)
            for d, hit in zip(dates[cut], (entry_fired[cut] if entry_fired is not None else []))
            if hit
        ),
        overlays={k: _clean(v[cut, 0]) for k, v in overlays.items()},
        levels={k: _clean(v[cut, 0]) for k, v in level_lines.items()},
    )


# The wire shape: one object the frontend hands straight to the chart, with
# the rows already aligned so the browser never has to join on a date.
def payload(
    store: MarketStore,
    ticker: str,
    sessions: int = DEFAULT_SESSIONS,
    timeframe: str = DAILY,
    live_bar: dict | None = None,
) -> dict[str, object] | None:
    """Return `build`'s chart as plain JSON-ready data, or None."""
    chart = build(store, ticker, sessions, timeframe, live_bar)
    if chart is None:
        return None
    return {
        "ticker": chart.ticker,
        "timeframe": chart.timeframe,
        "last_bar_complete": chart.last_bar_complete,
        "timeframes": list(TIMEFRAMES),
        "adjusted": True,
        "basis": "adjusted for splits and dividends, the basis the desk grades on",
        "sessions": len(chart.dates),
        "bars": [
            {"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v}
            for d, o, h, lo, c, v in zip(
                chart.dates, chart.open, chart.high, chart.low, chart.close, chart.volume
            )
        ],
        "entries": list(chart.entries),
        "overlays": {k: list(v) for k, v in chart.overlays.items()},
        "levels": {k: list(v) for k, v in chart.levels.items()},
    }
