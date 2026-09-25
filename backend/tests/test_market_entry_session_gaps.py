"""Require real exchange sessions in the live entry's twenty-observation window."""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pytest

from backend.market import calendar, live_technical, ticker_chart
from backend.market.live_quotes import Quote
from backend.market.yahoo import DailyBar, TickerHistory


# Expose immutable synthetic histories to the actual production panel builder.
class Store:
    # Keep both source histories without persistent data or account state.
    def __init__(self, histories):
        self.histories = histories

    # Return an observed history or explicit absence for the real book universe.
    def read(self, ticker, asof=None):
        return self.histories.get(ticker)

    # Keep optional filing evidence absent without bypassing numerical functions.
    def read_frame(self, kind, ticker, asof=None):
        return None


# Prevent a prior test's candle cache from replacing this test's source histories.
@pytest.fixture(autouse=True)
def fresh_live_cache():
    live_technical._cache.update(key=None, value={})
    yield
    live_technical._cache.update(key=None, value={})


# Build matching AAOI/SPY dates while retaining deliberate gaps or invalid sessions.
def make_store(today, missing=(), history_end=None, extra=()):
    end = history_end or today - timedelta(days=1)
    candidates = np.arange(
        np.datetime64(today - timedelta(days=200)),
        np.datetime64(end + timedelta(days=1)),
        dtype="datetime64[D]",
    )
    _, sessions = ticker_chart._chart_calendar()
    dates = {
        value.astype(object)
        for value in candidates[np.is_busday(candidates, busdaycal=sessions)]
        if value.astype(object) not in missing
    } | set(extra)
    histories = {}
    for symbol, base in (("AAOI", 100.0), ("SPY", 400.0)):
        bars = tuple(
            DailyBar(
                day,
                base + i * 0.25 - 0.25,
                base + i * 0.25 + 1,
                base + i * 0.25 - 1,
                base + i * 0.25,
                base + i * 0.25,
                1000,
            )
            for i, day in enumerate(sorted(dates))
        )
        histories[symbol] = TickerHistory(
            symbol,
            bars,
            (),
            bars[-1].session_date,
            datetime.combine(end, time(23), UTC),
            "synthetic",
        )
    return Store(histories)


# Exercise the unchanged live read, including book loading and live-row assembly.
def read_entries(store, today):
    opened = datetime.combine(today, time(9, 30), calendar.NEW_YORK)
    quotes = {
        symbol: Quote(
            symbol,
            history.bars[-1].close + 10,
            history.bars[-1].close,
            history.bars[-1].close + 11,
            history.bars[-1].close - 1,
            opened.isoformat(),
            (opened + timedelta(minutes=15, seconds=1)).isoformat(),
        )
        for symbol, history in store.histories.items()
    }
    return live_technical.entry_now(store, quotes, today)


# Missing data must not leave a numeric trigger that another consumer can reuse.
def assert_unavailable(row):
    assert row["entry_status"] == "unavailable"
    assert row["entry_reason"]
    assert row["band_z"] is None
    assert row["stretch_21"] is None
    assert row["trigger"] is None
    assert row["horizon_sessions"] is None


# A session missing from every ticker cannot vanish from the entry's calendar.
def test_common_missing_session_matches_the_chart_unavailability():
    missing = date(2026, 9, 22)
    today = date(2026, 9, 25)
    store = make_store(today, missing={missing})
    rows = read_entries(store, today)
    for row in rows.values():
        assert_unavailable(row)
        assert row["missing_sessions"] == [missing.isoformat()]
    chart = ticker_chart.payload(store, "AAOI", 60)
    assert chart["data_status"] == "incomplete"
    assert chart["missing_sessions"] == [missing.isoformat()]
    assert chart["overlays"]["band_middle"][-1] is None


# Appending today's quote must not hide the missing sessions since a stale snapshot.
def test_stale_history_to_live_quote_retains_every_missing_session():
    today = date(2026, 9, 25)
    store = make_store(today, history_end=date(2026, 9, 18))
    rows = read_entries(store, today)
    for row in rows.values():
        assert_unavailable(row)
        assert row["missing_sessions"] == [
            "2026-09-21",
            "2026-09-22",
            "2026-09-23",
            "2026-09-24",
        ]


# Holidays are skipped, early closes count, and reviewed year transitions stay usable.
@pytest.mark.parametrize(
    "today", [date(2026, 9, 25), date(2026, 11, 27), date(2026, 1, 6)]
)
def test_complete_reviewed_exchange_windows_remain_available(today):
    rows = read_entries(make_store(today), today)
    for row in rows.values():
        assert row["entry_status"] == "available"
        assert row["entry_reason"] is None
        assert row["missing_sessions"] == []
        assert np.isfinite(row["band_z"])


# The missing date leaves the twenty-session band only on the twentieth later session.
@pytest.mark.parametrize(("offset", "available"), [(19, False), (20, True)])
def test_band_recovers_at_twenty_complete_sessions(offset, available):
    missing = date(2026, 8, 31)
    _, sessions = ticker_chart._chart_calendar()
    today = np.busday_offset(
        np.datetime64(missing), offset, busdaycal=sessions
    ).astype(object)
    rows = read_entries(make_store(today, missing={missing}), today)
    for row in rows.values():
        if available:
            assert row["entry_status"] == "available"
            assert row["missing_sessions"] == []
            assert np.isfinite(row["band_z"])
        else:
            assert_unavailable(row)
            assert row["missing_sessions"] == [missing.isoformat()]


# Unknown holiday coverage cannot be replaced by plausible weekday observations.
def test_unreviewed_calendar_year_is_explicitly_unavailable():
    today = date(2039, 1, 10)
    rows = read_entries(make_store(today), today)
    for row in rows.values():
        assert_unavailable(row)
        assert "calendar" in row["entry_reason"].lower()


# A reviewed January date still needs coverage for the preceding December window.
def test_reviewed_current_year_does_not_invent_prior_year_coverage():
    today = date(2019, 1, 4)
    for row in read_entries(make_store(today), today).values():
        assert_unavailable(row)
        assert "2018" in row["entry_reason"]


# A future cached history must not be presented as an entry reading for today.
def test_future_history_cannot_supply_the_current_session_entry():
    today = date(2026, 9, 25)
    for row in read_entries(
        make_store(today, history_end=date(2026, 9, 28)), today
    ).values():
        assert_unavailable(row)
        assert "current session" in row["entry_reason"]


# A quote assigned to a weekend or exchange holiday cannot create a trading session.
@pytest.mark.parametrize("today", [date(2026, 9, 26), date(2026, 9, 7)])
def test_non_session_live_date_is_unavailable(today):
    for row in read_entries(make_store(today), today).values():
        assert_unavailable(row)


# Extra holiday or weekend rows must not replace a genuine session in a finite band.
@pytest.mark.parametrize("extra", [date(2026, 9, 20), date(2026, 9, 7)])
def test_stray_non_session_row_is_not_a_valid_twenty_session_window(extra):
    today = date(2026, 9, 25)
    for row in read_entries(make_store(today, extra={extra}), today).values():
        assert_unavailable(row)


# Missing values remain specific to one ticker even when every calendar date exists.
def test_missing_close_with_complete_calendar_does_not_block_the_other_ticker():
    today = date(2026, 9, 25)
    store = make_store(today)
    original = store.histories["AAOI"]
    store.histories["AAOI"] = replace(
        original,
        bars=tuple(
            replace(bar, adjusted_close=None)
            if bar.session_date == date(2026, 9, 22)
            else bar
            for bar in original.bars
        ),
    )
    rows = read_entries(store, today)
    assert_unavailable(rows["AAOI"])
    assert rows["AAOI"]["missing_sessions"] == ["2026-09-22"]
    assert rows["SPY"]["entry_status"] == "available"
    assert np.isfinite(rows["SPY"]["band_z"])
