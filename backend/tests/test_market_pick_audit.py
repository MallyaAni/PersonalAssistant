"""Timing evaluation must start after publication and refuse hindsight profits."""

from datetime import UTC, date, datetime

import pytest

from backend.cli.market_pick_audit import after_publication, daily_result, timing_cases
from backend.market.alpaca import IntradayBar
from backend.market.yahoo import DailyBar, TickerHistory


# Construct an observation with an explicit UTC start time.
def candle(stamp, opened=100, high=101, low=99, close=100):
    return IntradayBar(datetime.fromisoformat(stamp), opened, high, low, close, 100)


# The bar already forming when a pick appears cannot supply its entry price.
def test_publication_time_excludes_earlier_and_extended_hours_bars():
    bars = [
        candle("2026-09-11T13:30:00+00:00"),
        candle("2026-09-11T13:45:00+00:00"),
        candle("2026-09-11T20:00:00+00:00"),
    ]
    eligible = after_publication(bars, datetime(2026, 9, 11, 13, 37, tzinfo=UTC))
    assert eligible == [bars[1]]


# A pick written on Saturday cannot earn Friday's rally.
def test_after_close_record_has_no_same_day_forward_return():
    history = TickerHistory(
        "AAA",
        (DailyBar(date(2026, 9, 11), 100, 120, 99, 119, 119, 1),),
        (),
        date(2026, 9, 11),
        datetime(2026, 9, 12, tzinfo=UTC),
    )
    result = daily_result(
        history, datetime(2026, 9, 12, 2, tzinfo=UTC), date(2026, 9, 11)
    )
    assert result["status"] == "no post-publication session in sample"


# The entry bar may have peaked before an entry, so its high cannot trigger a profit.
def test_take_profit_never_uses_the_entry_bars_unknown_ordering():
    cases = timing_cases(
        [
            candle("2026-09-11T13:30:00+00:00", high=120),
            candle("2026-09-11T13:45:00+00:00", high=103, close=102),
        ]
    )
    first = cases["first_open"]
    assert first["five_percent_take_profit_at"] is None
    assert first["hold_net_20bp"] == pytest.approx(0.018)
    assert "two_percent_limit_until_sample_end" not in cases


# Put the open on the adjusted close's basis before comparing returns.
def test_daily_comparison_uses_a_consistent_adjusted_price_basis():
    history = TickerHistory(
        "AAA",
        (DailyBar(date(2026, 9, 11), 100, 104, 99, 102, 51, 1),),
        (),
        date(2026, 9, 11),
        datetime(2026, 9, 12, tzinfo=UTC),
    )
    result = daily_result(
        history, datetime(2026, 9, 10, 23, tzinfo=UTC), date(2026, 9, 11)
    )
    assert result["adjusted_return"] == pytest.approx(0.02)
