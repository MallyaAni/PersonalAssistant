"""The fifteen-minute bars as clean regular sessions on the New York clock.

`market_intraday` stores each name's bars as one immutable frame, in UTC.
Everything that learns from them - the intraday signal test, the
execution test - needs the same preparation: the bars of the regular
session only, placed by the New York clock so that a bar at 09:30 is the
first of the day in January and in July alike, and only the sessions that
are complete and free of bad prints.

The trap this exists to hold: a fixed UTC window selects 22 bars in
winter and 26 in summer, and the first of them in January is pre-market.
That was the first version of the intraday experiment, and it inflated
every result that leaned on the open.

The second trap, held since 2026-09-26: the window used to end at a fixed
16:00, so on a 13:00 early close (the day after Thanksgiving, Christmas
Eve) the afternoon's after-hours prints landed in slots 14..25 and a
liquid name passed the 26-bar completeness check with an after-hours
"close". The window now ends at `calendar.session_close(day)`, a session
is complete when it holds every slot up to that close (14 on an early
close, 26 otherwise), and the last close of an early-close day is its
12:45 bar. The episode arrays stay rectangular at `BARS` columns, which
every consumer indexes by slot; an early-close session is left out of
them by default (`early_closes="drop"`) or, on request, kept with NaN in
the slots after the close (`early_closes="pad"`).
"""

from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow.parquet as pq

from backend.market import calendar

ROOT = Path("data/market/bars_15m")
NEW_YORK = ZoneInfo("America/New_York")
BARS = 26  # 09:30 to 16:00 in fifteen-minute bars
OPEN_LOCAL = 9 * 60 + 30  # minutes after midnight, New York
BAD_BAR = 0.30  # a bar-to-bar log move past this is a bad print
LONG_WEEKEND_DAYS = 4
EARLY_CLOSE_MODES = ("drop", "pad")


# The number of regular-session slots on a New York day: 14 on a 13:00
# early close, 26 otherwise. Takes a numpy day or a date.
def slots_expected(day) -> int:
    """Return how many fifteen-minute slots the regular session has on ``day``."""
    if not isinstance(day, date):
        day = day.astype("datetime64[D]").astype(object)
    close = calendar.session_close(day)
    return (close.hour * 60 + close.minute - OPEN_LOCAL) // 15


# The newest partition of fifteen-minute bars.
def partition(root: Path = ROOT) -> Path:
    """Return the newest as-of partition under `root`."""
    parts = sorted(p for p in root.glob("asof=*") if p.is_dir())
    if not parts:
        raise SystemExit("no bars_15m partition; run market_intraday --refresh")
    return parts[-1]


# Minutes after midnight New York for each bar, from its UTC start. The
# offset is looked up once per calendar day, since it only changes on a
# Sunday and no session spans one.
def local_minutes(start: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (New York calendar day, minutes after midnight) per bar."""
    day = start.astype("datetime64[D]")
    utc_minute = (start - day).astype(int)
    offsets = {}
    for d in np.unique(day):
        noon = datetime.fromtimestamp(
            int(d.astype("datetime64[s]").astype(int)) + 12 * 3600, tz=UTC
        )
        offsets[d] = int(noon.astimezone(NEW_YORK).utcoffset().total_seconds() // 60)
    offset = np.array([offsets[d] for d in day])
    local = utc_minute + offset
    # A bar before New York midnight in UTC terms lands on the previous day.
    day = day + (local // (24 * 60)).astype("timedelta64[D]")
    return day, local % (24 * 60)


# One name's regular-session bars on the New York clock, with the slot
# each occupies, and the last close of every day regardless of
# completeness (for the overnight gap of the day after).
def load(root: Path, ticker: str):
    """Return (day, slot, fields, last close by day) for one name."""
    d = pq.read_table(root / f"{ticker}.parquet").to_pydict()
    return sessions_from(d)


# The same, from the columns already in memory, so a test needs no file.
def sessions_from(columns: dict):
    """Return (day, slot, fields, last close by day) from bar columns."""
    start = np.array(columns["start"], dtype="datetime64[m]")
    day, local = local_minutes(start)
    # The close is looked up once per day: a fixed 16:00 kept after-hours
    # bars on early-close days.
    close_by_day = {d: OPEN_LOCAL + slots_expected(d) * 15 for d in np.unique(day)}
    close_local = np.array([close_by_day[d] for d in day]) if len(day) else local
    keep = (local >= OPEN_LOCAL) & (local < close_local)
    fields = {
        k: np.array(columns[k], dtype=float)[keep]
        for k in ("open", "close", "high", "low", "volume")
    }
    slot = ((local[keep] - OPEN_LOCAL) // 15).astype(int)
    day = day[keep]
    last_close: dict = {}
    for dd in np.unique(day):
        m = day == dd
        last_close[dd] = float(fields["close"][m][np.argmax(slot[m])])
    return day, slot, fields, last_close


# The full, clean sessions of one name as aligned arrays, plus each
# session's opening print and the close of the trading day before it.
def episodes(root: Path, ticker: str):
    """Return (days, close, high, low, volume, open0, prev) or None."""
    return episodes_from(*load(root, ticker))


# The same, from what `sessions_from` returned. A session is complete when
# it holds every slot up to the day's calendar close; an early-close
# session (14 slots) is dropped by default because the arrays are BARS
# wide, or padded with NaN after its close when `early_closes="pad"`.
def episodes_from(day, slot, f, last_close, early_closes: str = "drop"):
    """Return (days, close, high, low, volume, open0, prev) or None."""
    if early_closes not in EARLY_CLOSE_MODES:
        raise ValueError(f"early_closes must be one of {EARLY_CLOSE_MODES}")
    days_seen = np.array(sorted(last_close))
    kept: dict[str, list] = {
        k: [] for k in ("days", "close", "high", "low", "volume", "open0", "prev")
    }
    for i, d in enumerate(days_seen):
        m = day == d
        n = slots_expected(d)
        if m.sum() != n or not np.array_equal(np.sort(slot[m]), np.arange(n)):
            continue
        if n != BARS and early_closes == "drop":
            continue
        order = np.argsort(slot[m])
        c = f["close"][m][order]
        if not np.all(np.isfinite(c)) or np.any(c <= 0):
            continue
        if np.abs(np.diff(np.log(c))).max() > BAD_BAR:
            continue
        # The previous trading day's close, if that day is on file and
        # within a long weekend of this one; otherwise the gap is unknown.
        prev = np.nan
        if i > 0 and (d - days_seen[i - 1]).astype(int) <= LONG_WEEKEND_DAYS:
            prev = last_close[days_seen[i - 1]]
        kept["days"].append(d)
        kept["close"].append(_padded(c, n))
        kept["open0"].append(float(f["open"][m][order][0]))
        kept["prev"].append(prev)
        for k in ("high", "low", "volume"):
            kept[k].append(_padded(f[k][m][order], n))
    if not kept["days"]:
        return None
    stacked = [np.stack(kept[k]) for k in ("close", "high", "low", "volume")]
    return (
        np.array(kept["days"]),
        *stacked,
        np.array(kept["open0"]),
        np.array(kept["prev"]),
    )


# A session's slot values widened to BARS columns: an early-close session
# gets NaN in the slots after its close, a normal one is returned as is.
def _padded(values: np.ndarray, n: int) -> np.ndarray:
    """Return ``values`` (n slots) as a BARS-wide row, NaN past the close."""
    if n == BARS:
        return values
    out = np.full(BARS, np.nan)
    out[:n] = values
    return out
