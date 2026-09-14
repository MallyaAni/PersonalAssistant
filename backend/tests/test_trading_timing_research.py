"""Chart timing observes completed candles and fills only after its signal."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from backend.agents.trading.desk import timing_research
from backend.market.alpaca import IntradayBar
from backend.market.yahoo import DailyBar, TickerHistory


# Supply enough earlier daily observations for the shared EMA50 to be defined.
def history():
    end = date(2026, 9, 11)
    bars = tuple(
        DailyBar(
            end - timedelta(days=80 - i),
            100 + i,
            102 + i,
            99 + i,
            101 + i,
            101 + i,
            100,
        )
        for i in range(80)
    )
    return TickerHistory("AAA", bars, (), end, datetime(2026, 9, 12, tzinfo=UTC))


# Generate complete, exchange-anchored candles with stable ascending prices.
def candles():
    start = datetime(2026, 8, 31, 13, 30, tzinfo=UTC)
    out = []
    for day in range(12):
        stamp = start + timedelta(days=day)
        if stamp.weekday() >= 5:
            continue
        for slot in range(26):
            price = 180 + len(out) * 0.01
            out.append(
                IntradayBar(
                    stamp + timedelta(minutes=slot * 15),
                    price,
                    price + 0.2,
                    price - 0.2,
                    price + 0.1,
                    100,
                )
            )
    return out


# The 09:45 reading uses yesterday's completed hour until today's first hour ends.
def test_hourly_confirmation_never_uses_an_unfinished_hour():
    bars, rows = timing_research.readings(candles(), history())
    morning = next(
        row for row in rows if row["at"] == datetime(2026, 9, 11, 13, 45, tzinfo=UTC)
    )
    assert morning["hourly_at"] < datetime(2026, 9, 11, 13, 30, tzinfo=UTC)
    assert all(
        row["hourly_at"] is None or row["hourly_at"] <= row["at"] for row in rows
    )
    assert len(bars) == len(rows)


# Changing future bars cannot alter earlier technical readings or their timestamps.
def test_future_prices_cannot_repaint_a_chart_reading():
    bars = candles()
    _, before = timing_research.readings(bars, history())
    split = len(bars) - 10
    changed = bars[:split] + [
        replace(b, close=b.close * 2, high=b.high * 2) for b in bars[split:]
    ]
    _, after = timing_research.readings(changed, history())
    # Compare warmed readings, where the indicators have finite values.
    for left, right in zip(before[150:split], after[150:split], strict=True):
        assert left == right


# A confirmed structure exit is executed at the following bar, never the signal close.
def test_structure_exit_uses_next_bar_and_costs():
    bars = candles()[-5:]
    rows = [
        {
            "at": b.start + timedelta(minutes=15),
            "close": 90,
            "ema21": 100,
            "hourly_close": 90,
            "hourly_ema21": 100,
        }
        for b in bars
    ]
    result = timing_research.evaluate(
        bars, rows, bars[0].start, "first_open", "structure"
    )
    assert result["exits"][0]["filled_at"] == bars[1].start
    expected = bars[1].open * 0.999 / (bars[0].open * 1.001) - 1
    assert result["return"] == pytest.approx(expected)


# Missing constituent bars do not silently form a complete hour.
def test_hourly_candle_requires_all_of_its_constituents():
    bars = candles()[:4]
    assert len(timing_research.hourly(bars)) == 1
    assert timing_research.hourly(bars[:3]) == []


# A band reversal can trim once while the completed hourly trend still holds.
def test_band_rejection_trims_once_without_becoming_a_fixed_profit_target():
    row = {
        "close": 94,
        "ema21": 90,
        "ema9": 96,
        "hourly_close": 105,
        "hourly_ema21": 100,
        "bearish": True,
        "high": 110,
        "upper_band": 109,
    }
    fraction, reason = timing_research.exit_fraction(
        row, "band_trim_then_structure", False
    )
    assert fraction == 0.5
    assert "upper-band" in reason
    assert timing_research.exit_fraction(row, "band_trim_then_structure", True)[0] == 0
