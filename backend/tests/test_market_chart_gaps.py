"""Keep exchange-session gaps visible in the chart and its indicator windows."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import calendar, ticker_chart
from backend.market.yahoo import DailyBar, TickerHistory


# Supply immutable daily observations without networking or persistence.
class Store:
    # Keep a single synthetic history so the actual chart loader is exercised.
    def __init__(self, bars):
        self.bars = tuple(bars)

    # Return the same dated observations whenever the chart loads its ticker.
    def read(self, ticker):
        return TickerHistory(
            ticker,
            self.bars,
            (),
            self.bars[-1].session_date,
            datetime(2026, 9, 25, 23, tzinfo=UTC),
        )


# Generate real 2026 exchange dates while preserving explicitly omitted observations.
def history(end=date(2026, 9, 25), missing=()):
    _, holidays = calendar._published_sessions()
    bars = []
    day = date(2026, 6, 1)
    while day <= end:
        if np.is_busday(np.datetime64(day), busdaycal=holidays) and day not in missing:
            price = 100.0 + (day - date(2026, 6, 1)).days * 0.1
            bars.append(
                DailyBar(day, price, price + 2, price - 1, price + 1, price + 1, 1000)
            )
        day += timedelta(days=1)
    return Store(bars)


# A missing session remains a null candle and invalidates every dependent band window.
def test_daily_gap_is_explicit_and_cannot_produce_a_band_or_entry_marker():
    payload = ticker_chart.payload(history(missing={date(2026, 9, 22)}), "AAA", 60)
    gap = next(bar for bar in payload["bars"] if bar["date"] == "2026-09-22")
    assert all(
        gap[field] is None for field in ("open", "high", "low", "close", "volume")
    )
    assert payload["data_status"] == "incomplete"
    assert payload["missing_sessions"] == ["2026-09-22"]
    assert payload["overlays"]["band_middle"][-1] is None
    assert payload["overlays"]["ema9"][-1] is None
    assert payload["levels"]["range60_high"][-1] is None
    assert not any(day >= "2026-09-22" for day in payload["entries"])


# A closed week with a missing constituent is unavailable, not a complete OHLC candle.
def test_weekly_gap_is_unavailable_even_after_friday_close():
    payload = ticker_chart.payload(
        history(missing={date(2026, 9, 22)}), "AAA", 12, "weekly"
    )
    assert payload["last_bar_complete"] is False
    assert payload["bars"][-1]["close"] is None
    assert payload["bars"][-1]["high"] is None
    assert payload["overlays"]["ema9"][-1] is None
    assert payload["missing_sessions"] == ["2026-09-22"]


# Scheduled full closures and weekends are not missing market observations.
def test_holiday_week_has_no_false_gap_warning():
    payload = ticker_chart.payload(history(), "AAA", 60)
    dates = [bar["date"] for bar in payload["bars"]]
    assert "2026-09-07" not in dates
    assert "2026-09-20" not in dates
    assert payload["data_status"] == "complete"
    assert payload["missing_sessions"] == []


# A future missing observation cannot alter earlier candles or indicators.
def test_future_gap_does_not_change_earlier_daily_or_weekly_values():
    before = history(end=date(2026, 9, 18))
    after = history(missing={date(2026, 9, 22)})
    for timeframe in ("daily", "weekly"):
        old = ticker_chart.payload(before, "AAA", 200, timeframe)
        new = ticker_chart.payload(after, "AAA", 200, timeframe)
        assert new["bars"][: len(old["bars"])] == old["bars"]
        for key, values in old["overlays"].items():
            assert new["overlays"][key][: len(values)] == values


# A recovered complete band window becomes available only after twenty real sessions.
def test_band_recovers_after_twenty_complete_observations():
    payload = ticker_chart.payload(
        history(end=date(2026, 10, 23), missing={date(2026, 9, 22)}), "AAA", 60
    )
    index = next(
        i for i, bar in enumerate(payload["bars"]) if bar["date"] == "2026-09-22"
    )
    assert payload["overlays"]["band_middle"][index + 19] is None
    assert payload["overlays"]["band_middle"][index + 20] is not None


# A quote far beyond cached history cannot bridge missing sessions with an old average.
def test_long_gap_before_a_live_quote_does_not_carry_the_previous_average():
    payload = ticker_chart.payload(
        history(end=date(2026, 8, 31)),
        "AAA",
        30,
        live_bar={
            "session": "2026-09-25",
            "bar": "2026-09-25T19:45:00+00:00",
            "last": 150,
        },
    )
    assert payload["bars"][-1]["close"] == 150
    assert payload["overlays"]["ema9"][-1] is None
    assert payload["data_status"] == "incomplete"


# A holiday-shortened completed week does not require a nonexistent Friday candle.
def test_good_friday_week_completes_on_thursday_without_a_gap():
    rows = [
        DailyBar(date(2026, 4, day), 100, 102, 99, 101, 101, 1000) for day in (1, 2)
    ]
    payload = ticker_chart.payload(
        Store(rows),
        "AAA",
        30,
        "weekly",
        {
            "session": "2026-04-02",
            "bar": "2026-04-02T19:45:00+00:00",
            "last": 101,
        },
    )
    assert payload["last_bar_complete"] is True
    assert payload["data_status"] == "complete"


# Unsupported requested calendar years are labelled instead of guessing holiday gaps.
def test_calendar_coverage_is_explicit_for_requested_old_history():
    rows = [
        DailyBar(date(2018, 12, day), 100, 102, 99, 101, 101, 1000) for day in (27, 28)
    ]
    payload = ticker_chart.payload(Store(rows), "AAA", 30)
    assert payload["data_status"] == "unavailable"
    assert "2018" in payload["data_reason"]


# Old warm-up outside reviewed years does not taint a fully covered recent display.
def test_old_background_dates_do_not_hide_complete_current_coverage():
    current = history(end=date(2026, 9, 25))
    old = replace(current.bars[0], session_date=date(2018, 12, 28))
    # Keep a long current prefix so every displayed indicator window is covered.
    payload = ticker_chart.payload(Store((old,) + current.bars), "AAA", 20)
    assert payload["data_status"] != "unavailable"
