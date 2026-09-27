"""Early closes in the fifteen-minute readers.

On a published 13:00 early close the regular session is 14 bars, 09:30 to
12:45 by start time. The IEX cache still holds the afternoon's after-hours
prints, and until 2026-09-26 every reader used a fixed 16:00 window, so
those prints filled slots 14..25 and a liquid name passed the 26-bar
completeness check with an after-hours "close". What has to hold now: the
window ends at `calendar.session_close(day)`, a 14-slot early-close session
is complete, the after-hours bars are excluded, the day's last close is its
12:45 bar, and a normal day is untouched.
"""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.market import alpaca, intraday, tape

EARLY = date(2025, 11, 28)  # the day after Thanksgiving: closes 13:00
NORMAL = date(2025, 12, 1)  # the Monday after: closes 16:00
WINTER_OPEN_UTC = 14 * 60 + 30  # 09:30 EST


# Bar columns for one winter day from 09:30 New York: `count` bars at
# fifteen-minute steps, so 26 reaches 15:45 and covers the afternoon of an
# early-close day with after-hours prints.
def _day_columns(day: date, base: float, count: int = 26) -> dict[str, list]:
    out: dict[str, list] = {
        k: [] for k in ("start", "open", "close", "high", "low", "volume")
    }
    for slot in range(count):
        minute = WINTER_OPEN_UTC + 15 * slot
        out["start"].append(f"{day.isoformat()}T{minute // 60:02d}:{minute % 60:02d}")
        price = base + slot
        out["open"].append(price)
        out["close"].append(price)
        out["high"].append(price + 0.5)
        out["low"].append(price - 0.5)
        out["volume"].append(100.0)
    return out


# Concatenate day columns into one frame.
def _columns(*days: dict[str, list]) -> dict[str, list]:
    out: dict[str, list] = {k: [] for k in days[0]}
    for d in days:
        for k, v in d.items():
            out[k].extend(v)
    return out


# IntradayBars for one winter day from 09:30 New York, `count` of them.
def _bars(day: date, base: float, count: int = 26) -> list[alpaca.IntradayBar]:
    start = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
    return [
        alpaca.IntradayBar(
            start + timedelta(minutes=15 * i),
            base + i,
            base + i + 0.5,
            base + i - 0.5,
            base + i,
            100.0,
        )
        for i in range(count)
    ]


# The calendar says 14 slots on the early close and 26 on the normal day.
def test_slots_expected_follow_the_calendar_close():
    assert intraday.slots_expected(EARLY) == 14
    assert intraday.slots_expected(np.datetime64(NORMAL)) == 26
    assert alpaca.bars_expected(EARLY) == 14


# The after-hours bars of an early-close day are excluded from its
# session, its last close is the 12:45 bar, and the normal day keeps 26.
def test_sessions_from_bounds_the_window_by_the_calendar_close():
    columns = _columns(_day_columns(EARLY, 100.0), _day_columns(NORMAL, 200.0))
    day, slot, fields, last_close = intraday.sessions_from(columns)
    early_key = np.datetime64(EARLY)
    normal_key = np.datetime64(NORMAL)
    assert sorted(slot[day == early_key].tolist()) == list(range(14))
    assert sorted(slot[day == normal_key].tolist()) == list(range(26))
    assert last_close[early_key] == 100.0 + 13  # the 12:45 bar, not 15:45
    assert last_close[normal_key] == 200.0 + 25


# A complete early-close session is not a 26-bar episode by default (the
# arrays are 26 wide), but its true close still feeds the next day's
# previous close; asked to pad, it is kept with NaN after the close.
def test_episodes_drop_or_pad_an_early_close_session():
    columns = _columns(_day_columns(EARLY, 100.0), _day_columns(NORMAL, 200.0))
    parts = intraday.sessions_from(columns)
    days, close, *_rest, prev = intraday.episodes_from(*parts)
    assert days.astype(str).tolist() == [NORMAL.isoformat()]
    assert prev.tolist() == [113.0]  # Friday's 12:45 close, not an after-hours print
    days, close, high, low, volume, open0, prev = intraday.episodes_from(
        *parts, early_closes="pad"
    )
    assert days.astype(str).tolist() == [EARLY.isoformat(), NORMAL.isoformat()]
    assert close.shape == (2, intraday.BARS)
    assert np.isfinite(close[0, :14]).all()
    assert np.isnan(close[0, 14:]).all()
    assert np.isfinite(close[1]).all()
    assert volume[0, :14].sum() == 1400.0
    with pytest.raises(ValueError, match="early_closes"):
        intraday.episodes_from(*parts, early_closes="keep")


# An early-close day with only 14 bars is complete and is padded; the same
# day with a bar missing is not.
def test_fourteen_bars_complete_an_early_close_session():
    full = intraday.sessions_from(_day_columns(EARLY, 100.0, count=14))
    days, *_ = intraday.episodes_from(*full, early_closes="pad")
    assert days.astype(str).tolist() == [EARLY.isoformat()]
    short = intraday.sessions_from(_day_columns(EARLY, 100.0, count=13))
    assert intraday.episodes_from(*short, early_closes="pad") is None


# The tape of an early-close day uses slots 0..13 only: the afternoon
# after-hours bars are ignored, the slots after the close stay flat at
# the 12:45 close with zero volume, and the sparsity floor is 7 of 14.
def test_session_tape_ends_at_the_early_close():
    t = tape.session_tape(_bars(EARLY, 100.0))
    assert t is not None
    assert t.shape == (26, 5)
    assert t[13, 3] == pytest.approx(np.log(113.0 / 100.0), abs=1e-6)
    assert (t[14:, 3] == t[13, 3]).all()  # flat after the close
    assert (t[14:, 4] == 0.0).all()  # no after-hours volume in the session
    assert t[:14, 4].sum() == pytest.approx(1.0, abs=1e-6)
    assert tape.session_tape(_bars(EARLY, 100.0, count=7)) is not None
    assert tape.session_tape(_bars(EARLY, 100.0, count=6)) is None


# A normal day's tape is exactly what it was: every slot real, the last
# close at 15:45, and thirteen bars still the floor.
def test_session_tape_on_a_normal_day_is_unchanged():
    t = tape.session_tape(_bars(NORMAL, 200.0))
    assert t is not None
    assert t[25, 3] == pytest.approx(np.log(225.0 / 200.0), abs=1e-6)
    assert t[:, 4].sum() == pytest.approx(1.0, abs=1e-6)
    assert (t[:, 4] > 0).all()
    assert tape.session_tape(_bars(NORMAL, 200.0, count=13)) is not None
    assert tape.session_tape(_bars(NORMAL, 200.0, count=12)) is None
