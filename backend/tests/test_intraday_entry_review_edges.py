"""Acceptance boundaries for a causal entry signal, independent of rule tuning."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from backend.market import intraday_entry as entry

SESSION = date(2026, 9, 8)
LEVELS = entry.Levels(level=100.0, entry_level=102.0, invalidation_level=95.0)


# Make a valid bar with prices that fit inside its reported range.
def bar(index, close, *, low=None, high=None):
    return entry.Bar(
        start=entry.session_open_for(SESSION) + index * entry.CANDLE,
        open=close,
        high=high if high is not None else close + 1,
        low=low if low is not None else close - 1,
        close=close,
        volume=100.0,
    )


# A supplied prefix must not depend on future bars that were unavailable then.
@pytest.mark.parametrize("future_kind", ["nan", "duplicate", "next_session"])
def test_unavailable_future_data_does_not_change_an_earlier_decision(future_kind):
    prefix = [bar(0, 101), bar(1, 99)]
    cutoff = prefix[-1].start + entry.CANDLE
    future = [bar(2, 103)]
    if future_kind == "nan":
        future = [replace(future[0], high=float("nan"))]
    elif future_kind == "duplicate":
        future = future * 2
    else:
        future = [replace(future[0], start=future[0].start + timedelta(days=1))]
    expected = entry.evaluate("AAA", SESSION, prefix, LEVELS, as_of=cutoff)
    actual = entry.evaluate("AAA", SESSION, prefix + future, LEVELS, as_of=cutoff)
    assert actual == expected


# A pullback that already closes through invalidation cannot later become a buy.
def test_setup_bar_already_below_invalidation_does_not_resurrect():
    bars = [bar(0, 101), bar(1, 94), bar(2, 103)]
    result = entry.evaluate(
        "AAA", SESSION, bars, LEVELS, as_of=bars[-1].start + entry.CANDLE
    )
    assert result.state == entry.INVALIDATED
    assert result.recommendation is False


# A close-confirmed trigger only becomes known at the end of its candle.
def test_trigger_timestamp_is_when_the_confirmation_is_available():
    bars = [bar(0, 101), bar(1, 99), bar(2, 103)]
    available = bars[-1].start + entry.CANDLE
    result = entry.evaluate("AAA", SESSION, bars, LEVELS, as_of=available)
    assert result.state == entry.ENTRY_READY
    assert result.trigger_time == available.isoformat()


# Corrupt completed bars cannot be treated as price or volume evidence.
@pytest.mark.parametrize(
    "changes",
    [
        {"high": float("inf")},
        {"volume": float("inf")},
        {"close": 110.0},
        {"open": 110.0},
    ],
)
def test_rejects_invalid_completed_ohlcv(changes):
    first = replace(bar(0, 101), **changes)
    with pytest.raises(ValueError, match="non-finite|invalid volume|outside high/low"):
        entry.evaluate(
            "AAA", SESSION, [first], LEVELS, as_of=first.start + entry.CANDLE
        )


# A completed-bar gap can hide an invalidation and must not produce readiness.
def test_missing_bar_does_not_bridge_an_unobserved_invalidation():
    bars = [bar(0, 101), bar(1, 99), bar(3, 103)]
    with pytest.raises(ValueError, match="gap between completed bars"):
        entry.evaluate(
            "AAA", SESSION, bars, LEVELS, as_of=bars[-1].start + entry.CANDLE
        )


# Bars outside the regular 15-minute grid are not valid completed observations.
def test_off_grid_bars_are_rejected():
    first = replace(bar(0, 101), start=bar(0, 101).start + timedelta(minutes=1))
    with pytest.raises(ValueError, match="off the 15-minute grid"):
        entry.evaluate(
            "AAA", SESSION, [first], LEVELS, as_of=first.start + entry.CANDLE
        )


# Daily context must continue to develop after the first trigger is recorded.
def test_session_context_includes_all_completed_bars_after_trigger():
    bars = [bar(0, 101), bar(1, 99), bar(2, 103), bar(3, 109)]
    result = entry.evaluate(
        "AAA", SESSION, bars, LEVELS, as_of=bars[-1].start + entry.CANDLE
    )
    assert result.bar_count == 4
    assert result.session_high == 110
    assert result.session_volume == 400


# An old session's historical trigger must not advertise readiness tomorrow.
def test_old_session_signal_is_not_a_current_recommendation():
    bars = [bar(0, 101), bar(1, 99), bar(2, 103)]
    result = entry.evaluate(
        "AAA",
        SESSION,
        bars,
        LEVELS,
        as_of=entry.session_open_for(SESSION + timedelta(days=1)),
    )
    assert result.recommendation is False
