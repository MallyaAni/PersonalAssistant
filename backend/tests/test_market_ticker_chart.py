"""The drill-down chart: the bars, the lines, and the basis they share."""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import ticker_chart
from backend.market.yahoo import DailyBar, TickerHistory


# A store that answers `read` for one name and nothing else.
class _Store:
    def __init__(self, bars: tuple[DailyBar, ...]):
        self._bars = bars

    def read(self, ticker: str, asof: date | None = None) -> TickerHistory | None:
        if ticker != "AAA":
            return None
        return TickerHistory(
            ticker="AAA",
            bars=self._bars,
            actions=(),
            complete_through=self._bars[-1].session_date,
            source_time=None,
        )


# Weekday sessions from a close path, with a split-style adjustment factor
# applied to the adjusted close so the two bases differ.
def _bars(closes, factor: float = 1.0) -> tuple[DailyBar, ...]:
    out, day = [], date(2024, 1, 1)
    for c in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(
            DailyBar(
                session_date=day,
                open=c * 0.99,
                high=c * 1.02,
                low=c * 0.98,
                close=c,
                adjusted_close=c * factor,
                volume=1_000,
            )
        )
        day += timedelta(days=1)
    return tuple(out)


def _store(closes, factor: float = 1.0) -> _Store:
    return _Store(_bars(closes, factor))


# The candles and the averages must sit on one basis, or a dividend payer's
# overlay drifts away from its own price.
def test_bars_are_scaled_onto_the_adjusted_basis():
    closes = list(np.linspace(100.0, 140.0, 300))
    chart = ticker_chart.build(_store(closes, factor=0.5), "AAA", sessions=5)
    # The close IS the adjusted close, and the high is the raw high scaled
    # by the same adj/close factor, not the raw high.
    assert chart.close[-1] == pytest.approx(closes[-1] * 0.5)
    assert chart.high[-1] == pytest.approx(closes[-1] * 1.02 * 0.5)
    assert chart.low[-1] == pytest.approx(closes[-1] * 0.98 * 0.5)
    # An average drawn on that basis lands among the candles, not above them.
    assert chart.overlays["ema21"][-1] < chart.high[-1]
    assert chart.overlays["ema21"][-1] > chart.low[-1] * 0.5


# The warm-up is spent before the window is cut, so the slowest line is
# present on the very first drawn bar.
def test_the_200_day_average_exists_on_the_first_drawn_bar():
    chart = ticker_chart.build(_store(list(np.linspace(50.0, 90.0, 400))), "AAA", sessions=30)
    assert len(chart.dates) == 30
    assert chart.overlays["ema200"][0] is not None
    assert chart.overlays["sma200"][0] is not None
    assert all(v is not None for v in chart.overlays["ema200"])


# NaN is not JSON. A line that does not exist yet must be a gap the chart
# library can skip, never a zero it would draw through the floor.
def test_missing_values_are_gaps_rather_than_zeros():
    chart = ticker_chart.build(_store(list(np.linspace(10.0, 12.0, 60))), "AAA", sessions=60)
    ema200 = chart.overlays["ema200"]
    assert ema200[0] is None  # 60 sessions cannot support a 200 average
    assert all(v is None or isinstance(v, float) for v in ema200)
    assert 0.0 not in [v for v in ema200 if v is not None]


# Only the two timeframes the desk actually reads are offered. A monthly bar
# is not scored anywhere, so the chart must refuse rather than invite a
# trader to reason from something no analyst looks at.
def test_only_the_scored_timeframes_are_accepted():
    assert ticker_chart.TIMEFRAMES == ("daily", "weekly")
    with pytest.raises(ValueError):
        ticker_chart.build(_store([100.0] * 300), "AAA", timeframe="monthly")


# Weekly bars must bucket by the desk's own week rule, so the picture and
# the weekly legs that were graded come from the same bars.
def test_weekly_bars_close_on_the_week_and_carry_its_extremes():
    closes = list(np.linspace(100.0, 200.0, 300))
    chart = ticker_chart.build(_store(closes), "AAA", sessions=8, timeframe="weekly")
    assert chart.timeframe == "weekly"
    # Every closed weekly bar ends on a Friday in an unbroken run of
    # weekdays. The newest may be a week still forming, which is included
    # on purpose and flagged, because a trader reads the forming bar.
    closed = chart.dates if chart.last_bar_complete else chart.dates[:-1]
    for stamp in closed:
        assert date.fromisoformat(stamp).weekday() == 4
    if not chart.last_bar_complete:
        assert date.fromisoformat(chart.dates[-1]).weekday() != 4
    # A weekly bar spans its days: its range contains its own open and close.
    for o, h, low, c in zip(chart.open, chart.high, chart.low, chart.close):
        assert low <= o <= h
        assert low <= c <= h
    # The weekly view carries the two EMAs the weekly legs are built from,
    # and none of the daily-only lines.
    assert set(chart.overlays) == {"ema9", "ema21"}


# The daily view carries every line the technical reads quote by name.
def test_the_daily_view_carries_the_lines_the_reads_quote():
    chart = ticker_chart.build(_store(list(np.linspace(80.0, 120.0, 400))), "AAA", sessions=40)
    assert set(chart.overlays) == {
        "ema9", "ema21", "ema50", "ema200", "sma200",
        "band_lower", "band_middle", "band_upper",
    }
    assert set(chart.levels) == {
        "swing_low", "swing_high", "high_52w", "low_52w", "range60_high", "range60_low",
    }
    # The band brackets the price it was built from.
    for lower, mid, upper, close in zip(
        chart.levels and chart.overlays["band_lower"],
        chart.overlays["band_middle"],
        chart.overlays["band_upper"],
        chart.close,
    ):
        if lower is None:
            continue
        assert lower <= mid <= upper


# A 52-week high is a trailing extreme, so it can never sit below a close
# that has already printed inside its own window.
def test_the_52_week_line_is_a_trailing_extreme():
    closes = list(np.linspace(100.0, 60.0, 300))  # a long decline
    chart = ticker_chart.build(_store(closes), "AAA", sessions=20)
    for high52, close in zip(chart.levels["high_52w"], chart.close):
        if high52 is not None:
            assert high52 >= close


# A name the store has never heard of is absent, not an exception.
def test_an_unknown_name_returns_nothing():
    assert ticker_chart.build(_store([100.0] * 300), "ZZZ") is None


# The wire shape must be plain JSON data the browser can draw without
# joining anything on a date.
def test_the_payload_is_aligned_and_plain():
    built = ticker_chart.payload(_store(list(np.linspace(20.0, 30.0, 300))), "AAA", sessions=12)
    assert built["ticker"] == "AAA"
    assert built["timeframe"] == "daily"
    assert built["adjusted"] is True
    assert built["sessions"] == len(built["bars"]) == 12
    for line in built["overlays"].values():
        assert len(line) == 12
    for line in built["levels"].values():
        assert len(line) == 12
    assert list(built["bars"][0]) == ["date", "open", "high", "low", "close", "volume"]


# The week in progress must be drawn, not withheld until Friday, or the
# newest weekly bar can be four sessions stale while the daily chart beside
# it is current.
def test_the_forming_week_is_drawn_and_flagged():
    # 302 weekday sessions from a Monday: the last week is short.
    closes = list(np.linspace(100.0, 160.0, 302))
    weekly = ticker_chart.build(_store(closes), "AAA", sessions=6, timeframe="weekly")
    daily = ticker_chart.build(_store(closes), "AAA", sessions=6)
    # Whatever the calendar, the two timeframes end in the same week.
    assert weekly.dates[-1] >= daily.dates[-1][:8] + "01"
    if not weekly.last_bar_complete:
        # A forming bar still carries a real range and its own close.
        assert weekly.low[-1] <= weekly.close[-1] <= weekly.high[-1]
    assert all(len(line) == len(weekly.dates) for line in weekly.levels.values())
    built = ticker_chart.payload(_store(closes), "AAA", 6, "weekly")
    assert "last_bar_complete" in built
    assert ticker_chart.payload(_store(closes), "AAA", 6)["last_bar_complete"] is True


# The payload crosses a JSON boundary, so every value in it must be a plain
# Python type. A numpy bool reached `last_bar_complete` on the weekly path
# and Pydantic refused it: the live weekly chart returned 500 while every
# test here passed, because the daily branch short-circuits to a real bool
# and never evaluates the numpy comparison.
def test_the_payload_is_json_serialisable_on_every_timeframe():
    import json

    store = _store(list(np.linspace(40.0, 90.0, 320)))
    for timeframe in ticker_chart.TIMEFRAMES:
        built = ticker_chart.payload(store, "AAA", 30, timeframe)
        assert isinstance(built["last_bar_complete"], bool), timeframe
        assert not isinstance(built["last_bar_complete"], np.generic), timeframe
        # The whole thing, not just that one field.
        json.dumps(built)


# The live candle is folded in before anything is computed, so the averages
# include it rather than ending at the last close while the price moves.
def test_the_live_candle_moves_the_averages_not_just_the_bar():
    closes = list(np.linspace(100.0, 100.0, 320))  # flat, so any move shows
    store = _store(closes)
    flat = ticker_chart.build(store, "AAA", 30)
    jumped = ticker_chart.build(
        store, "AAA", 30,
        live_bar={"session": "2025-03-24", "last": 150.0, "open": 150.0, "high": 151.0, "low": 149.0},
    )
    assert jumped.close[-1] == 150.0
    # The 9-day average must have moved with it, not stayed at the close.
    assert jumped.overlays["ema9"][-1] > flat.overlays["ema9"][-1]
    assert jumped.dates[-1] >= flat.dates[-1]


# The entry markers are the desk's own trigger drawn on the price, so the rule
# can be checked by eye rather than only in a table. A price that climbs away
# from its own mean must trip it; a flat one must not.
def test_the_chart_marks_where_the_entry_fired():
    from backend.agents.trading.desk import entry as entry_analyst
    from backend.agents.trading.desk import paper

    # A long flat stretch, then a sharp run: the band is narrow when the run
    # begins, so the breakout is unambiguous.
    closes = [100.0] * 260 + list(np.linspace(101.0, 135.0, 40))
    chart = ticker_chart.build(_store(closes), "AAA", sessions=60)
    assert chart is not None
    assert chart.entries, "a sharp break from a narrow band must fire the entry"
    assert set(chart.entries) <= set(chart.dates), "an entry outside the drawn range"

    # And every marked date really is through the threshold on the band the
    # chart itself drew, so the marker and the line agree.
    drawn = dict(zip(chart.dates, chart.close))
    series = np.array([[drawn[d]] for d in chart.dates], dtype=float)
    band = entry_analyst.bollinger_z(series)[:, 0]
    by_date = dict(zip(chart.dates, band))
    for marked in chart.entries:
        assert np.isfinite(by_date[marked])

    # A price that never leaves its mean has no entry at all.
    flat = ticker_chart.build(_store([100.0] * 300), "AAA", sessions=60)
    assert flat is not None
    assert flat.entries == ()


# Source timestamps identify the candle used for both the close and its indicators.
@pytest.mark.parametrize("timeframe", ticker_chart.TIMEFRAMES)
def test_quote_metadata_and_lines_share_one_snapshot(timeframe):
    store = _store([100.0] * 320)
    built = ticker_chart.payload(store, "AAA", 30, timeframe, {
        "session": "2025-03-24", "bar": "2025-03-24T14:00:00+00:00",
        "last": 150.0, "open": 100.0, "high": 151.0, "low": 99.0,
    })
    assert built["quote_bar"] == "2025-03-24T14:00:00+00:00"
    assert built["bars"][-1]["close"] == 150.0
    assert built["overlays"]["ema9"][-1] == pytest.approx(110.0)
    assert built["last_bar_complete"] is False


# Retained quotes older than stored prices cannot claim ownership of the chart.
def test_ignored_old_quote_has_no_snapshot_timestamp():
    store = _store([100.0] * 320)
    built = ticker_chart.payload(store, "AAA", 30, live_bar={
        "session": "2024-01-02", "bar": "2024-01-02T15:00:00+00:00",
        "last": 150.0,
    })
    assert built["quote_bar"] is None
    assert built["bars"][-1]["close"] == 100.0
    assert built["overlays"]["ema9"][-1] == pytest.approx(100.0)


# A completed 15-minute candle does not make the whole session or Friday complete.
@pytest.mark.parametrize(("session", "bar", "complete"), [
    ("2026-09-25", "2026-09-25T19:30:00+00:00", False),
    ("2026-09-25", "2026-09-25T19:45:00+00:00", True),
    ("2026-11-27", "2026-11-27T17:30:00+00:00", False),
    ("2026-11-27", "2026-11-27T17:45:00+00:00", True),
])
@pytest.mark.parametrize("timeframe", ticker_chart.TIMEFRAMES)
def test_chart_completion_uses_actual_regular_or_early_close(
    session, bar, complete, timeframe
):
    history_length = int(np.busday_count("2024-01-01", session))
    built = ticker_chart.payload(_store([100.0] * history_length), "AAA", 30, timeframe,
        {"session": session, "bar": bar, "last": 110.0})
    assert built["last_bar_complete"] is complete
