"""The fifteen-minute bars as clean sessions on the New York clock.

What has to hold: a bar is placed by New York time whatever the season,
so 09:30 is the first slot in January and in July; a pre-market bar is
not a session bar; a day with a missing bar, or a bad print, is not a
session; and each kept session carries its opening print and the close
of the trading day before it when that day is within a long weekend.
"""

import numpy as np

from backend.market import intraday


# The same wall-clock bar is 14:30 UTC in January and 13:30 UTC in July,
# and both land in the 09:30 slot; a 13:30 UTC bar in January is pre-market.
def test_bars_are_placed_by_new_york_time_in_both_seasons():
    start = np.array(
        ["2026-01-06T14:30", "2026-07-06T13:30", "2026-01-06T13:30"],
        dtype="datetime64[m]",
    )
    day, local = intraday.local_minutes(start)
    assert local.tolist() == [570, 570, 510]
    assert day.astype(str).tolist() == ["2026-01-06", "2026-07-06", "2026-01-06"]


# A January day's 26 bars from 14:30 UTC, optionally with a pre-market bar
# in front, a bar removed, or a bad print inserted.
def _day(date: str, base: float, pre_market=False, drop=None, spike=None):
    starts, opens, closes, highs, lows, volumes = [], [], [], [], [], []
    if pre_market:
        starts.append(f"{date}T13:30")
        opens.append(1.0)
        closes.append(1.0)
        highs.append(1.0)
        lows.append(1.0)
        volumes.append(1.0)
    for slot in range(intraday.BARS):
        if slot == drop:
            continue
        minute = 14 * 60 + 30 + 15 * slot
        starts.append(f"{date}T{minute // 60:02d}:{minute % 60:02d}")
        price = base + slot
        if slot == spike:
            price = base * 3
        opens.append(price)
        closes.append(price)
        highs.append(price + 0.5)
        lows.append(price - 0.5)
        volumes.append(100.0)
    return starts, opens, closes, highs, lows, volumes


def _columns(*days):
    keys = ("start", "open", "close", "high", "low", "volume")
    out = {k: [] for k in keys}
    for parts in days:
        for k, values in zip(keys, parts, strict=True):
            out[k].extend(values)
    return out


# A complete session is kept with its opening print; a pre-market bar is
# ignored; a short session and one with a bad print are dropped; and the
# previous close carries across a weekend but not across a longer gap.
def test_only_complete_clean_sessions_are_episodes():
    columns = _columns(
        _day("2026-01-05", 100.0, pre_market=True),
        _day("2026-01-06", 200.0, drop=7),
        _day("2026-01-07", 300.0, spike=12),
        _day("2026-01-12", 400.0),  # the Monday after a weekend from Jan 7
        _day("2026-01-20", 500.0),  # more than a long weekend after Jan 12
    )
    days, close, high, low, volume, open0, prev = intraday.episodes_from(
        *intraday.sessions_from(columns)
    )
    assert days.astype(str).tolist() == ["2026-01-05", "2026-01-12", "2026-01-20"]
    assert close.shape == (3, intraday.BARS)
    assert open0.tolist() == [100.0, 400.0, 500.0]  # the 09:30 bar's open
    assert close[0, 0] == 100.0  # not the pre-market bar
    assert np.isnan(prev[0])  # nothing before the first day
    # Jan 12's previous session on file is Jan 7, five days back: too far.
    assert np.isnan(prev[1])
    assert np.isnan(prev[2])


# Consecutive sessions carry the previous close, which is the overnight gap's
# other end, even when the previous day was itself incomplete.
def test_previous_close_comes_from_the_day_before_even_if_incomplete():
    columns = _columns(_day("2026-01-06", 200.0, drop=3), _day("2026-01-07", 300.0))
    days, *_rest, prev = intraday.episodes_from(*intraday.sessions_from(columns))
    assert days.astype(str).tolist() == ["2026-01-07"]
    # Jan 6's last bar closed at 200 + 25.
    assert prev.tolist() == [225.0]
