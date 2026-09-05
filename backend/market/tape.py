"""The tape as a tensor: 15-minute bars of the last sessions, for a sequence model.

The operator reads a 15-minute chart against daily context. The session
features in `alpaca.py` summarise that tape in ten numbers; this module
keeps the tape itself so a network can read it: for every (session, name)
the 26 regular-hours bars of that session, each bar as five numbers
relative to the session's open — log(open/open0), log(high/open0),
log(low/open0), log(close/open0), and the bar's share of the session's
volume — so the tensor is scale-free across names and years.

Shape: (sessions, names, 26, 5) float32, NaN where a session has no bars.
A model that wants the last K sessions gathers K rows at batch time, so
the stored tensor is one session deep and a ten-year, 500-name panel is
under a gigabyte.
"""

from collections.abc import Mapping

import numpy as np

from backend.market.alpaca import IntradayBar, sessions
from backend.market.panel import Panel

BARS_PER_SESSION = 26
TAPE_CHANNELS = 5
MIN_SLOTS = 13


# The (26, 5) tape of one session from its bars, or None if too sparse.
#
# Bars are placed by their time slot (minutes since 09:30 New York divided
# by fifteen), because the IEX feed has no bar for a slot with no IEX trade
# and a thin name in 2016 has many such slots. A missing slot is a flat bar
# at the previous close with zero volume, which is what the tape showed.
# A session with fewer than `MIN_SLOTS` real bars is treated as absent.
def session_tape(bars: list[IntradayBar]) -> np.ndarray | None:
    """Return the session's bars as (26, 5) relative to the session's open."""
    if len(bars) < MIN_SLOTS:
        return None
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    slots: dict[int, IntradayBar] = {}
    for bar in bars:
        local = bar.start.astimezone(zone)
        slot = (local.hour * 60 + local.minute - 9 * 60 - 30) // 15
        if 0 <= slot < BARS_PER_SESSION and slot not in slots:
            slots[slot] = bar
    if len(slots) < MIN_SLOTS:
        return None
    first = slots[min(slots)]
    open0 = first.open
    if not open0 or open0 <= 0:
        return None
    total = sum(max(b.volume, 0.0) for b in slots.values()) or 1.0
    out = np.zeros((BARS_PER_SESSION, TAPE_CHANNELS), dtype=np.float32)
    last_close = open0
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(BARS_PER_SESSION):
            bar = slots.get(i)
            if bar is None:
                level = float(np.log(last_close / open0))
                out[i] = (level, level, level, level, 0.0)
                continue
            out[i] = (
                np.log(bar.open / open0),
                np.log(bar.high / open0),
                np.log(bar.low / open0),
                np.log(bar.close / open0),
                max(bar.volume, 0.0) / total,
            )
            last_close = bar.close
    return out if np.isfinite(out).all() else None


# Build the (T, N, 26, 5) tape tensor for a panel.
def tape_tensor(
    panel: Panel, bars_by_ticker: Mapping[str, list[IntradayBar]]
) -> np.ndarray:
    """Return the tape tensor aligned to the panel, NaN where absent."""
    out = np.full(
        (len(panel.dates), len(panel.tickers), BARS_PER_SESSION, TAPE_CHANNELS),
        np.nan,
        dtype=np.float32,
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
            tape = session_tape(rows)
            if tape is not None:
                out[t, column] = tape
    return out
