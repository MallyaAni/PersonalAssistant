"""Current entry readiness requires the newest completed observation."""

from datetime import date, timedelta

from backend.market import intraday_entry as entry


# Build a contiguous completed prefix with one unambiguous reclaim event.
def prefix():
    session = date(2026, 9, 8)
    opened = entry.session_open_for(session)
    return session, [
        entry.Bar(opened + i * entry.CANDLE, price, price + 1, price - 1, price, 100)
        for i, price in enumerate((101, 99, 103))
    ]


# The absence of the next completed bar can hide invalidation and removes readiness.
def test_missing_latest_completed_bar_is_not_current_readiness():
    session, bars = prefix()
    result = entry.evaluate(
        "AAA",
        session,
        bars,
        entry.Levels(100, 102, 95),
        as_of=bars[-1].start + 2 * entry.CANDLE,
    )
    assert result.recommendation is False
    assert result.state == entry.UNAVAILABLE
    assert result.trigger_price == 103


# A still-forming next bar does not invalidate a fresh completed observation.
def test_latest_completed_bar_remains_fresh_before_the_next_boundary():
    session, bars = prefix()
    result = entry.evaluate(
        "AAA",
        session,
        bars,
        entry.Levels(100, 102, 95),
        as_of=bars[-1].start + 2 * entry.CANDLE - timedelta(microseconds=1),
    )
    assert result.recommendation is True
    assert result.state == entry.ENTRY_READY


# Filling the missing observation with an invalidation cannot revive the entry.
def test_missing_observation_then_invalidation_keeps_event_identity():
    session, bars = prefix()
    cutoff = bars[-1].start + 2 * entry.CANDLE
    missing = entry.evaluate(
        "AAA", session, bars, entry.Levels(100, 102, 95), as_of=cutoff
    )
    last = entry.Bar(bars[-1].start + entry.CANDLE, 94, 95, 93, 94, 100)
    arrived = entry.evaluate(
        "AAA", session, bars + [last], entry.Levels(100, 102, 95), as_of=cutoff
    )
    assert missing.recommendation is False
    assert arrived.state == entry.INVALIDATED
    assert arrived.recommendation is False
    assert arrived.identity == missing.identity
    assert arrived.trigger_time == missing.trigger_time
