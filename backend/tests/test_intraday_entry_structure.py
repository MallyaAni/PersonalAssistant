"""The 15-minute entry engine keeps the causal sequence, not just the daily OHLC.

What has to hold: two sessions with the same daily OHLC but different
intraday paths reach different states; a decision depends only on the
completed prefix, so future bars never change it (uncompleted bars are
excluded before any validation); a partial bar never triggers; a
close-confirmed trigger is only known at the end of its candle; a setup bar
that already closes through invalidation invalidates immediately; a completed
invalidation after an entry removes readiness while the entry event is
retained; a historical (already-closed) entry is never actionable; an
invalidated, ambiguous, expired or historical setup never resurrects; a bar
touching both the trigger and the invalidation reports ambiguity rather than
a winning fill; gaps, missing opening bars and off-grid bars are rejected;
and duplicate, corrupt or other-date bars raise.
"""

from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time

import pytest

from backend.market.intraday_entry import (
    AMBIGUOUS,
    CANDLE,
    ENTRY_READY,
    EXPIRED,
    HISTORICAL,
    INVALIDATED,
    NEW_YORK,
    SETUP,
    UNAVAILABLE,
    WAIT,
    Bar,
    Levels,
    evaluate,
    session_close_for,
    session_open_for,
)

SESSION = date(2026, 1, 6)

# The one documented candidate rule: reclaim above 100 after a pullback,
# entry on a close at/above 101, invalidation on a close at/below 98.
LEVELS = Levels(level=100.0, entry_level=101.0, invalidation_level=98.0)


# A regular-session bar at `slot` (0 = 09:30, 1 = 09:45, ...) on SESSION.
def _bar(slot: int, o, h, lo, c, volume=100.0) -> Bar:
    start = session_open_for(SESSION) + timedelta(minutes=15 * slot)
    return Bar(start=start, open=o, high=h, low=lo, close=c, volume=volume)


# The instant a bar's 15-minute window has fully elapsed.
def _completed(slot: int) -> datetime:
    return session_open_for(SESSION) + timedelta(minutes=15 * (slot + 1))


# Daily OHLC from a list of bars: the first open, the extremes, the last close.
def _daily_ohlc(bars: list[Bar]):
    return (
        bars[0].open,
        max(b.high for b in bars),
        min(b.low for b in bars),
        bars[-1].close,
    )


# Path A reclaims the retest and reaches entry-ready; the same daily OHLC.
# The pullback bar keeps its range clear of the entry level and above the
# invalidation, so it forms a clean setup rather than resolving at once.
def _reclaim_path() -> list[Bar]:
    return [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),  # pullback breaks the level
        _bar(2, 99.8, 104.0, 99.5, 102.0),  # reclaimed, close at/above entry
        _bar(3, 102.0, 104.0, 101.0, 103.0),
    ]


# Path B rejects the retest and is invalidated; the daily OHLC is identical.
def _reject_path() -> list[Bar]:
    return [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),  # pullback breaks the level
        _bar(2, 99.8, 100.0, 96.0, 96.0),  # rejection, close at/below invalidation
        _bar(3, 96.0, 104.0, 95.0, 103.0),
    ]


# Two sessions with the same daily OHLC but different intraday sequences must
# reach different states, so the engine decides on structure, not the daily bar.
def test_identical_daily_ohlc_with_different_intraday_paths_give_different_states():
    reclaim = evaluate("AAA", SESSION, _reclaim_path(), LEVELS, as_of=_completed(3))
    reject = evaluate("AAA", SESSION, _reject_path(), LEVELS, as_of=_completed(3))
    assert _daily_ohlc(_reclaim_path()) == _daily_ohlc(_reject_path())
    assert _daily_ohlc(_reclaim_path()) == (100.0, 106.0, 94.0, 103.0)
    assert reclaim.state == ENTRY_READY
    assert reclaim.recommendation is True
    assert reject.state == INVALIDATED
    assert reject.recommendation is False


# The engine uses only the completed prefix: evaluating at the end of a bar
# equals evaluating the same prefix within a longer stream, and uncompleted
# later bars cannot change an earlier decision. A later *completed* bar that
# closes through invalidation removes readiness, but the entry event
# (identity, trigger time/price) is retained for replay.
def test_future_bars_cannot_change_an_earlier_decision():
    bars = _reclaim_path()
    at_trigger = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(2))
    assert at_trigger.state == ENTRY_READY
    # The close that confirms the reclaim is only known at the candle's end.
    trigger = _bar(2, 99.8, 104.0, 99.5, 102.0).start + CANDLE
    assert at_trigger.trigger_time == trigger.isoformat()
    assert (
        at_trigger.trigger_bar_start
        == _bar(2, 99.8, 104.0, 99.5, 102.0).start.isoformat()
    )
    assert at_trigger.trigger_price == 102.0

    prefix_only = evaluate("AAA", SESSION, bars[:3], LEVELS, as_of=_completed(2))
    assert prefix_only == at_trigger

    invalidating_future = bars[:3] + [_bar(3, 102.0, 103.0, 95.0, 96.0)]
    with_future = evaluate(
        "AAA", SESSION, invalidating_future, LEVELS, as_of=_completed(2)
    )
    assert with_future == at_trigger  # bar 3 is not completed yet: excluded

    after_future = evaluate(
        "AAA", SESSION, invalidating_future, LEVELS, as_of=_completed(3)
    )
    # The completed invalidation removes readiness, but the entry is retained.
    assert after_future.state == INVALIDATED
    assert after_future.recommendation is False
    assert after_future.trigger_time == at_trigger.trigger_time
    assert after_future.trigger_price == 102.0


# A bar whose 15-minute window has not elapsed is not completed, so its close
# above the entry level cannot trigger anything.
def test_incomplete_bar_cannot_trigger():
    bars = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),
        _bar(2, 99.8, 104.0, 99.5, 102.0),  # would reclaim once completed
    ]
    before = evaluate("AAA", SESSION, bars, LEVELS, as_of=_bar(2, 0, 0, 0, 0).start)
    assert before.state == SETUP
    assert before.trigger_time is None
    assert before.bar_count == 2
    after = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(2))
    assert after.state == ENTRY_READY
    assert after.trigger_price == 102.0


# The same completed prefix read twice, and with more bars appended, keeps one
# stable identity and one trigger: a refresh is the same recommendation, not a
# new one.
def test_repeated_reads_keep_signal_identity():
    first = evaluate("AAA", SESSION, _reclaim_path(), LEVELS, as_of=_completed(3))
    second = evaluate("AAA", SESSION, _reclaim_path(), LEVELS, as_of=_completed(3))
    assert first == second
    assert first.identity == second.identity
    later = evaluate(
        "AAA",
        SESSION,
        _reclaim_path() + [_bar(4, 103.0, 105.0, 100.0, 104.0)],
        LEVELS,
        as_of=_completed(4),
    )
    assert later.identity == first.identity
    assert later.trigger_time == first.trigger_time
    assert later.trigger_bar_start == first.trigger_bar_start
    assert later.trigger_price == first.trigger_price
    assert later.state == ENTRY_READY


# A different session is a different signal: the identity carries the date.
def test_identity_differs_across_sessions():
    other = date(2026, 1, 7)
    one = evaluate("AAA", SESSION, _reclaim_path(), LEVELS, as_of=_completed(3))
    moved = [_bar(0, 100.0, 106.0, 94.0, 103.0), _bar(1, 103.0, 103.0, 99.5, 99.8)]
    two_bars = [
        Bar(
            start=session_open_for(other) + timedelta(minutes=15 * s),
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
        )
        for s, b in enumerate(moved)
    ]
    other_signal = evaluate("AAA", other, two_bars, LEVELS, as_of=_completed(3))
    assert other_signal.identity != one.identity


# Once invalidated, later bars that close back above the entry do not resurrect
# the setup; the rejection stands.
def test_invalidated_setup_does_not_resurrect():
    bars = _reject_path() + [_bar(4, 98.0, 104.0, 97.0, 103.0)]
    result = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(4))
    assert result.state == INVALIDATED
    assert result.invalidation_price == LEVELS.invalidation_level
    assert result.recommendation is False
    again = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(4))
    assert again == result
    assert again.identity == result.identity


# A setup still unresolved at session close expires, and stays expired on
# later reads rather than silently becoming actionable.
def test_expired_setup_does_not_resurrect():
    bars = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),  # setup
        _bar(2, 99.8, 100.5, 99.2, 99.6),  # oscillates, never resolves
        _bar(3, 99.6, 100.5, 99.0, 99.5),
    ]
    at_close = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(3))
    assert at_close.state == SETUP
    assert at_close.bar_count == 4
    expired = evaluate("AAA", SESSION, bars, LEVELS, as_of=session_close_for(SESSION))
    assert expired.state == EXPIRED
    assert expired.recommendation is False
    later = evaluate(
        "AAA",
        SESSION,
        bars,
        LEVELS,
        as_of=session_close_for(SESSION) + timedelta(hours=1),
    )
    assert later.state == EXPIRED
    assert later.identity == expired.identity


# A bar whose range touches both the entry and the invalidation leaves the
# intra-bar order unknown: ambiguity is reported, never a winning fill.
def test_bar_touching_both_trigger_and_invalidation_is_ambiguous():
    bars = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),
        # high reaches entry, low reaches invalidation
        _bar(2, 100.0, 103.0, 97.0, 103.0),
    ]
    result = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(2))
    assert result.state == AMBIGUOUS
    assert result.ambiguity is True
    assert result.recommendation is False
    later = evaluate(
        "AAA",
        SESSION,
        bars + [_bar(3, 100.0, 104.0, 99.0, 103.0)],
        LEVELS,
        as_of=_completed(3),
    )
    assert later.state == AMBIGUOUS  # ambiguity is terminal, not resolved later


# A setup bar whose range already touches both the entry and the invalidation
# is ambiguous at once, even though it is the bar that formed the setup.
def test_setup_bar_touching_both_levels_is_ambiguous():
    bars = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 98.0, 99.0),  # pullback whose range spans both
        _bar(2, 99.0, 104.0, 99.0, 102.0),
    ]
    result = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(2))
    assert result.state == AMBIGUOUS
    assert result.recommendation is False


# A completed bar gap can conceal an invalidation: it is rejected, not bridged.
# (The earlier behaviour bridged the gap and could turn a hidden rejection into
# a readiness claim; that was a demonstrable bug.)
def test_missing_bar_does_not_bridge_an_unobserved_invalidation():
    bars = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),
        _bar(3, 99.8, 104.0, 99.5, 102.0),  # slot 2 is missing
    ]
    with pytest.raises(ValueError, match="gap"):
        evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(3))


# The completed prefix must start at the 09:30 opening bar.
def test_missing_opening_bar_is_rejected():
    bars = [
        _bar(1, 103.0, 103.0, 99.5, 99.8),
        _bar(2, 99.8, 104.0, 99.5, 102.0),
    ]
    with pytest.raises(ValueError, match="opening"):
        evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(2))


# Bars not aligned to the 15-minute grid are not valid completed observations.
def test_off_grid_bar_is_rejected():
    off_grid = Bar(
        start=session_open_for(SESSION) + timedelta(minutes=1),
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=100.0,
    )
    with pytest.raises(ValueError, match="grid"):
        evaluate("AAA", SESSION, [off_grid], LEVELS, as_of=off_grid.start + CANDLE)


# Out-of-order bars are sorted by start before deciding, when the completed
# prefix is contiguous and unique.
def test_out_of_order_bars_are_sorted():
    ordered = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),
    ]
    shuffled = [ordered[1], ordered[0]]
    a = evaluate("AAA", SESSION, ordered, LEVELS, as_of=_completed(1))
    b = evaluate("AAA", SESSION, shuffled, LEVELS, as_of=_completed(1))
    assert a == b
    assert a.state == SETUP


# Two bars sharing a start time are corrupt input: raise rather than guess.
def test_duplicate_bar_start_raises():
    bars = [_bar(1, 103.0, 103.0, 98.0, 99.0), _bar(1, 104.0, 104.0, 97.0, 98.0)]
    with pytest.raises(ValueError, match="duplicate"):
        evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(1))


# A completed bar on another session date is a caller bug: raise rather than
# mix days. An uncompleted next-session bar is excluded before this check.
def test_bar_on_another_session_date_raises():
    other = date(2026, 1, 7)
    stray = Bar(
        start=session_open_for(other),
        open=1.0,
        high=2.0,
        low=1.0,
        close=1.5,
        volume=1.0,
    )
    with pytest.raises(ValueError, match="another session"):
        evaluate(
            "AAA", SESSION, [stray], LEVELS, as_of=session_open_for(other) + CANDLE
        )


# A next-session bar whose window has not elapsed is excluded before any
# validation, so it cannot disturb an earlier decision it was not available to.
def test_uncompleted_next_session_bar_is_excluded():
    other = date(2026, 1, 7)
    stray = Bar(
        start=session_open_for(other),
        open=1.0,
        high=2.0,
        low=1.0,
        close=1.5,
        volume=1.0,
    )
    result = evaluate(
        "AAA",
        SESSION,
        [_bar(0, 100.0, 106.0, 94.0, 103.0), stray],
        LEVELS,
        as_of=_completed(0),
    )
    assert result.state == WAIT
    assert result.bar_count == 1


# Extended-hours bars on the same date are outside the regular-session window
# and are ignored; a corrupt bar raises.
def test_session_and_time_boundaries():
    extended = Bar(
        start=datetime.combine(SESSION, day_time(8, 0), UTC),
        open=1.0,
        high=2.0,
        low=1.0,
        close=1.5,
        volume=1.0,
    )
    result = evaluate(
        "AAA",
        SESSION,
        [extended, _bar(0, 100.0, 106.0, 94.0, 103.0)],
        LEVELS,
        as_of=_completed(0),
    )
    assert result.state == WAIT
    assert result.bar_count == 1  # the extended-hours bar was dropped

    late = Bar(
        start=datetime.combine(SESSION, day_time(16, 15), NEW_YORK),
        open=1.0,
        high=2.0,
        low=1.0,
        close=1.5,
        volume=1.0,
    )
    only_late = evaluate(
        "AAA", SESSION, [late], LEVELS, as_of=session_close_for(SESSION)
    )
    assert only_late.state == UNAVAILABLE

    corrupt = Bar(
        start=_bar(0, 1, 1, 1, 1).start,
        open=2.0,
        high=0.5,
        low=2.0,
        close=1.0,
        volume=1.0,
    )
    with pytest.raises(ValueError, match="high/low"):
        evaluate("AAA", SESSION, [corrupt], LEVELS, as_of=_completed(0))


# Before the session opens no bar is completed, so the decision is unavailable.
def test_no_completed_bar_is_unavailable():
    before_open = session_open_for(SESSION) - timedelta(minutes=1)
    result = evaluate(
        "AAA", SESSION, [_bar(0, 100.0, 106.0, 94.0, 103.0)], LEVELS, as_of=before_open
    )
    assert result.state == UNAVAILABLE
    assert result.bar_count == 0


# The rule's band must be coherent; a caller supplying a broken band is refused.
def test_invalid_levels_raise():
    for bad in (
        Levels(100.0, 100.0, 99.0),  # entry not strictly above the level
        Levels(100.0, 102.0, 100.0),  # invalidation not strictly below the level
        Levels(0.0, 102.0, 98.0),
    ):
        with pytest.raises(ValueError, match="level"):
            evaluate("AAA", SESSION, [], bad, as_of=_completed(0))


# The engine reports the session's evolving OHLC and volume along with the
# decision, all computed from completed bars only, and names the OHLC-proxy
# typical price honestly rather than as traded VWAP.
def test_evolving_session_ohlc_and_volume_are_reported():
    result = evaluate("AAA", SESSION, _reclaim_path(), LEVELS, as_of=_completed(2))
    assert result.session_open == 100.0
    assert result.session_high == 106.0
    assert result.session_low == 94.0
    assert result.session_close == 102.0
    assert result.session_volume == 300.0
    assert result.bar_weighted_typical is not None
    expected_typical = (
        sum((b.high + b.low + b.close) / 3.0 for b in _reclaim_path()[:3]) / 3
    )
    assert abs(result.bar_weighted_typical - expected_typical) < 1e-6


# A completed invalidation after an entry removes readiness; the entry event is
# retained, and a later reclaim does not resurrect it.
def test_post_trigger_invalidation_removes_readiness_and_never_resurrects():
    bars = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),
        _bar(2, 99.8, 104.0, 99.5, 102.0),  # entry
        _bar(3, 102.0, 103.0, 95.0, 96.0),  # closes through invalidation
        _bar(4, 96.0, 104.0, 95.0, 103.0),  # would reclaim, must not resurrect
    ]
    result = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(4))
    assert result.state == INVALIDATED
    assert result.recommendation is False
    assert result.trigger_time is not None  # the entry event is retained
    assert result.trigger_price == 102.0


# The session context keeps developing over all completed observations after
# the first signal; it is never frozen at the trigger bar.
def test_session_context_continues_after_trigger():
    bars = [
        _bar(0, 100.0, 106.0, 94.0, 103.0),
        _bar(1, 103.0, 103.0, 99.5, 99.8),
        _bar(2, 99.8, 104.0, 99.5, 102.0),  # entry
        _bar(3, 102.0, 110.0, 101.0, 109.0),
    ]
    result = evaluate("AAA", SESSION, bars, LEVELS, as_of=_completed(3))
    assert result.state == ENTRY_READY
    assert result.bar_count == 4
    assert result.session_high == 110.0
    assert result.session_close == 109.0
    assert result.session_volume == 400.0


# An entry resolved by an already-closed session is historical: its identity
# and trigger are preserved for replay, but it is never actionable again.
def test_historical_entry_after_close_is_not_actionable():
    result = evaluate(
        "AAA", SESSION, _reclaim_path(), LEVELS, as_of=session_close_for(SESSION)
    )
    assert result.state == HISTORICAL
    assert result.recommendation is False
    assert result.trigger_time is not None
    assert result.trigger_price == 102.0
    later = evaluate(
        "AAA",
        SESSION,
        _reclaim_path(),
        LEVELS,
        as_of=session_close_for(SESSION) + timedelta(days=1),
    )
    assert later.state == HISTORICAL
    assert later.recommendation is False
    assert later.identity == result.identity
