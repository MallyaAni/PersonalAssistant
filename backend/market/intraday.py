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
"""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow.parquet as pq

ROOT = Path("data/market/bars_15m")
NEW_YORK = ZoneInfo("America/New_York")
BARS = 26  # 09:30 to 16:00 in fifteen-minute bars
OPEN_LOCAL = 9 * 60 + 30  # minutes after midnight, New York
BAD_BAR = 0.30  # a bar-to-bar log move past this is a bad print
LONG_WEEKEND_DAYS = 4


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
    keep = (local >= OPEN_LOCAL) & (local < OPEN_LOCAL + BARS * 15)
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


# The same, from what `sessions_from` returned.
def episodes_from(day, slot, f, last_close):
    """Return (days, close, high, low, volume, open0, prev) or None."""
    days_seen = np.array(sorted(last_close))
    kept: dict[str, list] = {
        k: [] for k in ("days", "close", "high", "low", "volume", "open0", "prev")
    }
    for i, d in enumerate(days_seen):
        m = day == d
        if m.sum() != BARS or not np.array_equal(np.sort(slot[m]), np.arange(BARS)):
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
        kept["close"].append(c)
        kept["open0"].append(float(f["open"][m][order][0]))
        kept["prev"].append(prev)
        for k in ("high", "low", "volume"):
            kept[k].append(f[k][m][order])
    if not kept["days"]:
        return None
    stacked = [np.stack(kept[k]) for k in ("close", "high", "low", "volume")]
    return (
        np.array(kept["days"]),
        *stacked,
        np.array(kept["open0"]),
        np.array(kept["prev"]),
    )
