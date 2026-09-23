"""The causal replay and outcome accounting library: synthetic acceptance.

Per `docs/research/intraday-comparison-protocol-2026-09-22.md` and
COMPARISON_REPLAY_TASK.md. What has to hold on small synthetic cases: a late
eligibility record never changes earlier decisions; future poisoned bars,
eligibility or labels never change earlier decisions; a missing next bar is
``execution_unknown`` and never fills at a later bar; an endpoint that lies
beyond the supplied bars is immature while a missing endpoint session is
explicit; exchange holidays and early closes are excluded before replay and
skipped when advancing horizons; excursions never use the entry day's pre-entry
extrema and are unavailable when coverage is incomplete; a later invalidation
never erases a recorded event; repeated readiness records one event; missing
execution and outcome labels are retained rather than dropped; the summary
keeps common opportunity denominators, paired entry-price differences and exact
conditional-return denominators; the zero-cost proxy is labelled; and unknown
calendar coverage or price basis is never silently chosen.
"""

from datetime import date, datetime, timedelta
from datetime import time as day_time

import pytest

from backend.market.intraday_comparison import (
    CANDIDATE,
    INCUMBENT,
    Eligibility,
    EventRecord,
)
from backend.market.intraday_entry import NEW_YORK, Bar, session_open_for
from backend.market.intraday_replay import (
    ENDPOINT_COMPLETE,
    ENDPOINT_IMMATURE,
    ENDPOINT_MISSING,
    ENDPOINT_NO_EVENT,
    EXCURSION_AVAILABLE,
    EXCURSION_UNAVAILABLE,
    EXECUTED,
    EXECUTION_UNKNOWN,
    PRICE_DIAGNOSTIC,
    PRIMARY_HORIZON,
    RECORDED_ELIGIBILITY,
    SECONDARY_HORIZON,
    SessionKind,
    SessionSchedule,
    eligibility_at,
    excursion,
    execution_proxy,
    replay_session,
    replay_session_outcome,
    session_after,
    summarize,
)
from backend.tests.test_intraday_comparison import (
    SESSION,
    _eligibility,
    _history,
)

# The single fixed early close and closure used by the synthetic schedule.
EARLY_CLOSE_DAY = date(2026, 1, 15)
HOLIDAY_DAY = date(2026, 1, 19)


# An after-close bar cannot become a proxy fill on the early-close session.
def test_early_close_proxy_rejects_after_close_bar():
    day = date(2026, 11, 27)
    bar = _bar(day, 14, 100.0, 101.0, 99.0, 100.0)
    event = EventRecord(
        CANDIDATE,
        "AAA",
        day,
        bar.start.isoformat(),
        "id",
        "ready",
        100.0,
        None,
        None,
        None,
        None,
        None,
    )
    assert execution_proxy([bar], event).status == EXECUTION_UNKNOWN


# A supplied 2026 exchange-session schedule with one early close and one closure.
def _schedule() -> SessionSchedule:
    """Return the 2026 schedule: weekdays minus one closure, one early close."""
    weekdays = set()
    day = date(2026, 1, 1)
    while day.year == 2026:
        if day.weekday() < 5:
            weekdays.add(day)
        day += timedelta(days=1)
    return SessionSchedule(
        full_sessions=frozenset(weekdays - {HOLIDAY_DAY, EARLY_CLOSE_DAY}),
        early_closes={EARLY_CLOSE_DAY: day_time(13, 0)},
        covered_years=frozenset({2026}),
    )


# One 15-minute bar on ``day`` at ``slot`` (0 = 09:30) with the given OHLC.
def _bar(day: date, slot: int, o: float, h: float, lo: float, c: float) -> Bar:
    """Return a regular-window 15-minute Bar at the given slot and OHLC."""
    start = session_open_for(day) + timedelta(minutes=15 * slot)
    return Bar(start=start, open=o, high=h, low=lo, close=c, volume=100.0)


# A full benign 26-bar session at a constant price.
def _full_day(day: date, price: float) -> list[Bar]:
    """Return a complete regular session whose bars all sit at ``price``."""
    return [_bar(day, s, price, price, price, price) for s in range(26)]


# The standard reclaim entry path for a day, with an optional invalidation.
def _entry_bars(
    day: date,
    trigger_close: float,
    *,
    invalidate: bool = False,
    trigger_open: float | None = None,
) -> list[Bar]:
    """Return a path that breaks the level, reclaims, then optionally invalidates.

    All closes stay at or below 248 so the incumbent's dynamic band stays below
    its threshold on this path; only ``trigger_close`` at 249+ makes both fire.
    The bar after the trigger is the zero-latency execution bar whose open is
    the proxy price.
    """
    trigger_open = trigger_open if trigger_open is not None else trigger_close
    bars = [
        _bar(day, 0, 245.0, 245.0, 243.0, 245.0),
        _bar(day, 1, 245.0, 245.0, 238.0, 240.0),
        _bar(
            day,
            2,
            trigger_open,
            trigger_close + 1.0,
            trigger_open - 1.0,
            trigger_close,
        ),
    ]
    if invalidate:
        bars.append(_bar(day, 3, trigger_open + 1.0, trigger_open + 2.0, 217.0, 218.0))
    else:
        bars.append(
            _bar(
                day,
                3,
                trigger_open + 1.0,
                trigger_open + 2.0,
                trigger_open,
                trigger_open + 2.0,
            )
        )
    bars.extend(_full_day(day, 245.0)[4:])
    return bars


# Outcome bars for every session from entry through the primary endpoint.
def _bars_through(
    entry: date,
    schedule: SessionSchedule,
    closes: dict[date, float] | None = None,
    default: float = 260.0,
) -> dict[date, list[Bar]]:
    """Return full-day bars for every session from entry through horizon 20."""
    closes = closes or {}
    end = session_after(schedule, entry, PRIMARY_HORIZON)[0]
    out: dict[date, list[Bar]] = {}
    day = entry
    while day <= end:
        if schedule.is_session(day):
            out[day] = _full_day(day, closes.get(day, default))
        day += timedelta(days=1)
    return out


# The eligibility timeline used by most tests: grade A known at the open.
def _timeline() -> list[Eligibility]:
    """Return a single grade-A eligibility record known at the session open."""
    return [_eligibility()]


# A replayed session whose candidate (and maybe incumbent) enters at 10:15.
def _ready_outcome(
    day: date,
    trigger_close: float,
    *,
    timeline: list[Eligibility] | None = None,
    invalidate: bool = False,
    closes: dict[date, float] | None = None,
) -> object:
    """Return a SessionOutcome over the standard reclaim path on ``day``."""
    return replay_session_outcome(
        symbol="AAA",
        session=day,
        bars=_entry_bars(day, trigger_close, invalidate=invalidate),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=timeline if timeline is not None else _timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(day, _schedule(), closes),
    )


# The eligibility already available at an instant is the newest fully-known one.
def test_eligibility_at_selects_only_records_available_at_an_instant():
    early = _eligibility(grade="A")
    instant = session_open_for(SESSION) + timedelta(minutes=30)
    late = Eligibility(
        grade="B",
        grade_available_at=instant + timedelta(minutes=30),
        rejecting_band=False,
        rejecting_band_available_at=instant + timedelta(minutes=30),
    )
    assert eligibility_at([early, late], instant) == early
    assert eligibility_at([late], instant) is None
    assert eligibility_at([early, late], instant + timedelta(minutes=30)) == late
    # A record whose value is unknown (grade None) is still selected and blocks.
    unknown = Eligibility(None, instant, False, instant)
    assert eligibility_at([unknown], instant) == unknown
    # A known new rejection input blocks rather than reviving the older grade.
    malformed = Eligibility("A", None, False, instant)
    assert eligibility_at([early, malformed], instant) == malformed


# A late-published eligibility record cannot change the first two decisions.
def test_late_eligibility_record_does_not_change_earlier_decisions():
    published = session_open_for(SESSION) + timedelta(minutes=50)
    late = Eligibility(
        grade="B",
        grade_available_at=published,
        rejecting_band=False,
        rejecting_band_available_at=published,
    )
    with_late = _ready_outcome(SESSION, 245.0, timeline=[_eligibility(), late])
    without = _ready_outcome(SESSION, 245.0, timeline=[_eligibility()])
    assert with_late.replay.observations[0].time.minute == 45
    assert with_late.replay.observations[1].time.minute == 0
    assert (
        with_late.replay.observations[0].comparison
        == without.replay.observations[0].comparison
    )
    assert (
        with_late.replay.observations[1].comparison
        == without.replay.observations[1].comparison
    )
    # The candidate entered at 10:15 while the late record was still future.
    event = with_late.replay.events[CANDIDATE]
    assert event.observation_time == (
        session_open_for(SESSION) + timedelta(minutes=45)
    ).isoformat(timespec="seconds")


# An event is recorded at the observation time eligibility became known, not
# at the earlier candidate trigger time.
def test_event_uses_observation_time_not_trigger_time():
    known = session_open_for(SESSION) + timedelta(minutes=75)
    delayed = Eligibility(
        grade="A",
        grade_available_at=known,
        rejecting_band=False,
        rejecting_band_available_at=known,
    )
    outcome = _ready_outcome(SESSION, 245.0, timeline=[delayed])
    event = outcome.replay.events[CANDIDATE]
    assert event.trigger_time is not None
    assert event.observation_time == known.isoformat(timespec="seconds")
    assert event.trigger_time != event.observation_time
    # The execution proxy uses the observation time, not the trigger time.
    assert outcome.candidate.execution.time is not None
    assert outcome.candidate.execution.time == known


# A corrupt future bar cannot change an earlier decision or event.
def test_future_poisoned_bars_do_not_change_earlier_decisions():
    clean = _ready_outcome(SESSION, 245.0)
    poisoned_bars = _entry_bars(SESSION, 245.0)
    poisoned_bars[20] = _bar(SESSION, 20, float("nan"), -1.0, -2.0, -3.0)
    poisoned = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=poisoned_bars,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(SESSION, _schedule()),
    )
    assert clean.replay.events == poisoned.replay.events
    for index, (clean_obs, poisoned_obs) in enumerate(
        zip(clean.replay.observations, poisoned.replay.observations, strict=True)
    ):
        if index < 20:
            # The corrupt bar is not yet completed: the prefixes are identical.
            assert clean_obs.comparison == poisoned_obs.comparison
        else:
            # Once the corrupt bar is completed the prefix is unavailable, but
            # the recorded event is untouched.
            assert not poisoned_obs.comparison.candidate.readiness


# A future-published eligibility record cannot change an earlier decision.
def test_future_poisoned_eligibility_does_not_change_earlier_decisions():
    clean = _ready_outcome(SESSION, 245.0)
    future = Eligibility(
        grade="F",
        grade_available_at=session_open_for(SESSION) + timedelta(minutes=120),
        rejecting_band=False,
        rejecting_band_available_at=session_open_for(SESSION) + timedelta(minutes=120),
    )
    poisoned = _ready_outcome(SESSION, 245.0, timeline=[_eligibility(), future])
    assert clean.replay.events == poisoned.replay.events
    assert (
        clean.replay.observations[2].comparison
        == poisoned.replay.observations[2].comparison
    )


# A future poisoned label (an absurd far-future bar) cannot change the entry.
def test_future_poisoned_labels_do_not_change_earlier_decisions():
    clean = _ready_outcome(SESSION, 245.0)
    far_future = session_after(_schedule(), SESSION, PRIMARY_HORIZON)[0]
    poisoned_bars = _bars_through(SESSION, _schedule())
    poisoned_bars[far_future] = _full_day(far_future, -999.0)
    poisoned = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=_entry_bars(SESSION, 245.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=poisoned_bars,
    )
    assert clean.replay.events == poisoned.replay.events


# A missing next bar is execution_unknown and never fills at a later bar.
def test_missing_next_bar_is_execution_unknown_never_a_later_bar():
    bars = _entry_bars(SESSION, 245.0)
    missing_third = [bars[0], bars[1], bars[2], bars[4], *bars[5:]]
    outcome = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=missing_third,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(SESSION, _schedule()),
    )
    event = outcome.replay.events[CANDIDATE]
    assert event.observation_time == (
        session_open_for(SESSION) + timedelta(minutes=45)
    ).isoformat(timespec="seconds")
    assert outcome.candidate.execution.status == EXECUTION_UNKNOWN
    assert outcome.candidate.execution.price is None
    # The later bar at 10:30 exists but was never used to fill the entry.
    assert "no next consecutive" in outcome.candidate.execution.reason


# The execution proxy is the next bar open, explicitly zero-cost.
def test_execution_is_next_bar_open_with_zero_costs():
    outcome = _ready_outcome(SESSION, 245.0, invalidate=False)
    event = outcome.replay.events[CANDIDATE]
    assert event.observation_time == (
        session_open_for(SESSION) + timedelta(minutes=45)
    ).isoformat(timespec="seconds")
    execution = outcome.candidate.execution
    assert execution.status == EXECUTED
    assert execution.time == session_open_for(SESSION) + timedelta(minutes=45)
    # The bar after 10:15 is the 10:15 bar; its open is the proxy price.
    assert execution.price == pytest.approx(246.0)
    assert "zero added costs" in execution.reason


# An endpoint beyond the supplied bars is immature; a missing endpoint session
# is explicit, and the two are distinguished.
def test_endpoint_missing_vs_horizon_immature():
    schedule = _schedule()
    secondary = session_after(schedule, SESSION, SECONDARY_HORIZON)[0]
    # Bars stop just before the secondary endpoint: both horizons are immature.
    truncated = {}
    day = SESSION
    while day < secondary:
        if schedule.is_session(day):
            truncated[day] = _full_day(day, 260.0)
        day += timedelta(days=1)
    immature = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=_entry_bars(SESSION, 245.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=truncated,
    )
    assert immature.candidate.primary.status == ENDPOINT_IMMATURE
    assert immature.candidate.primary.forward_return is None
    assert immature.candidate.secondary.status == ENDPOINT_IMMATURE
    # Bars run through the primary endpoint but omit the secondary endpoint:
    # the secondary becomes missing while the primary is complete.
    complete = _bars_through(SESSION, schedule)
    del complete[secondary]
    missing = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=_entry_bars(SESSION, 245.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=complete,
    )
    assert missing.candidate.secondary.status == ENDPOINT_MISSING
    assert missing.candidate.primary.status == ENDPOINT_COMPLETE


# Unknown calendar coverage is explicit unavailable, never inferred.
def test_unknown_calendar_coverage_is_unavailable():
    schedule = _schedule()
    covered = SessionSchedule(
        full_sessions=schedule.full_sessions,
        early_closes=schedule.early_closes,
        covered_years=frozenset({2025}),
    )
    with pytest.raises(ValueError, match="unknown calendar coverage"):
        replay_session(
            symbol="AAA",
            session=SESSION,
            bars=_entry_bars(SESSION, 245.0),
            history=_history(),
            price_basis="raw",
            eligibility_timeline=_timeline(),
            schedule=covered,
            mode=RECORDED_ELIGIBILITY,
        )
    endpoint, status = session_after(covered, SESSION, SECONDARY_HORIZON)
    assert endpoint is None
    assert "unknown calendar coverage" in status


# Early close and holiday entry sessions are excluded before replay.
def test_early_close_and_holiday_entry_sessions_are_excluded():
    schedule = _schedule()
    assert schedule.kind(EARLY_CLOSE_DAY) is SessionKind.EARLY_CLOSE
    assert schedule.kind(HOLIDAY_DAY) is SessionKind.CLOSED
    for bad_day, message in (
        (EARLY_CLOSE_DAY, "early close"),
        (HOLIDAY_DAY, "not an exchange session"),
    ):
        with pytest.raises(ValueError, match=message):
            replay_session(
                symbol="AAA",
                session=bad_day,
                bars=_entry_bars(bad_day, 245.0),
                history=_history(),
                price_basis="raw",
                eligibility_timeline=_timeline(),
                schedule=schedule,
                mode=RECORDED_ELIGIBILITY,
            )


# Outcome dates advance on supplied sessions; early closes count as sessions
# and full closures never do.
def test_horizon_advances_on_supplied_sessions_skipping_closures():
    schedule = _schedule()
    secondary = session_after(schedule, SESSION, SECONDARY_HORIZON)[0]
    primary = session_after(schedule, SESSION, PRIMARY_HORIZON)[0]
    assert secondary == date(2026, 1, 13)
    assert primary == date(2026, 2, 4)
    assert schedule.is_session(secondary)
    assert schedule.is_session(primary)
    # An early close is still a trading session; a full closure is not.
    assert schedule.is_session(EARLY_CLOSE_DAY)
    assert schedule.kind(EARLY_CLOSE_DAY) is SessionKind.EARLY_CLOSE
    assert not schedule.is_session(HOLIDAY_DAY)


# Excursions use only post-entry observations, never the entry-day pre-entry
# high, and are exact fractions of the execution price.
def test_excursion_never_uses_pre_entry_extrema():
    schedule = _schedule()
    endpoint = session_after(schedule, SESSION, SECONDARY_HORIZON)[0]
    entry_bars = [
        _bar(SESSION, 0, 260.0, 1000.0, 258.0, 260.0),
        _bar(SESSION, 1, 260.0, 260.0, 238.0, 240.0),
        _bar(SESSION, 2, 245.0, 245.0, 243.0, 245.0),
        _bar(SESSION, 3, 245.0, 260.0, 240.0, 250.0),
    ]
    entry_bars.extend(_full_day(SESSION, 250.0)[4:])
    label = excursion(
        schedule=schedule,
        entry_bars=entry_bars,
        outcome_bars=_bars_through(SESSION, schedule),
        entry_session=SESSION,
        execution_price=245.0,
        execution_time=session_open_for(SESSION) + timedelta(minutes=45),
        endpoint_date=endpoint,
    )
    assert label.status == EXCURSION_AVAILABLE
    assert label.favorable == pytest.approx((260.0 - 245.0) / 245.0)
    assert label.adverse == pytest.approx((240.0 - 245.0) / 245.0)
    assert label.favorable != pytest.approx((1000.0 - 245.0) / 245.0)


# Missing excursion coverage makes the excursion unavailable, never a partial
# extreme over the observed subset.
def test_missing_excursion_coverage_is_unavailable():
    schedule = _schedule()
    endpoint = session_after(schedule, SESSION, SECONDARY_HORIZON)[0]
    incomplete = _bars_through(SESSION, schedule)
    missing_day = session_after(schedule, SESSION, 2)[0]
    del incomplete[missing_day]
    label = excursion(
        schedule=schedule,
        entry_bars=_entry_bars(SESSION, 245.0, invalidate=True),
        outcome_bars=incomplete,
        entry_session=SESSION,
        execution_price=246.0,
        execution_time=session_open_for(SESSION) + timedelta(minutes=45),
        endpoint_date=endpoint,
    )
    assert label.status == EXCURSION_UNAVAILABLE
    assert label.adverse is None
    assert label.favorable is None


# A later invalidation never erases a recorded event.
def test_event_retained_after_later_invalidation():
    outcome = _ready_outcome(SESSION, 245.0, invalidate=True)
    event = outcome.replay.events[CANDIDATE]
    assert event is not None
    assert event.observation_time == (
        session_open_for(SESSION) + timedelta(minutes=45)
    ).isoformat(timespec="seconds")
    later = outcome.replay.observations[3]
    assert not later.comparison.candidate.readiness
    assert later.comparison.candidate.state == "invalidated"
    # The retained event still executes at the next bar's open.
    assert outcome.candidate.execution.status == EXECUTED


# Repeated ready observations record exactly one event per method.
def test_repeated_readiness_records_one_event():
    bars = [
        _bar(SESSION, 0, 245.0, 245.0, 243.0, 245.0),
        _bar(SESSION, 1, 245.0, 245.0, 238.0, 240.0),
        _bar(SESSION, 2, 245.0, 246.0, 244.0, 245.0),
        _bar(SESSION, 3, 245.0, 246.0, 244.0, 245.0),
        _bar(SESSION, 4, 245.0, 246.0, 244.0, 245.0),
    ]
    bars.extend(_full_day(SESSION, 245.0)[5:])
    result = replay_session(
        symbol="AAA",
        session=SESSION,
        bars=bars,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
    )
    # The candidate stays ready from 10:15 through the penultimate bar, yet
    # only the first accepted entry is recorded as one event.
    assert result.readiness_counts[CANDIDATE] == 23
    assert len(result.events) == 1
    event = result.events[CANDIDATE]
    assert event.observation_time == (
        session_open_for(SESSION) + timedelta(minutes=45)
    ).isoformat(timespec="seconds")


# Every observation is preserved, and raw readiness is counted separately from
# the first event.
def test_replay_preserves_every_observation_and_counts_readiness_separately():
    bars = _entry_bars(SESSION, 245.0, invalidate=True)
    result = replay_session(
        symbol="AAA",
        session=SESSION,
        bars=bars,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
    )
    assert len(result.observations) == len(bars)
    assert result.observations[0].time == session_open_for(SESSION) + timedelta(
        minutes=15
    )
    assert result.readiness_counts[CANDIDATE] == 1
    assert result.events[CANDIDATE] is not None
    assert result.events.get(INCUMBENT) is None


# Missing execution and missing outcome labels stay explicit records.
def test_missing_execution_and_outcome_are_retained():
    bars = _entry_bars(SESSION, 245.0)
    missing_third = [bars[0], bars[1], bars[2], bars[4], *bars[5:]]
    outcome = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=missing_third,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
        outcome_bars={},
    )
    assert outcome.candidate.event is not None
    assert outcome.candidate.execution.status == EXECUTION_UNKNOWN
    assert outcome.candidate.primary.status == ENDPOINT_MISSING
    assert outcome.candidate.primary.forward_return is None
    assert outcome.candidate.secondary.status == ENDPOINT_MISSING
    assert outcome.candidate.execution.price is None
    # A method that never entered reports no_event rather than a fake return.
    assert outcome.incumbent.event is None
    assert outcome.incumbent.primary.status == ENDPOINT_NO_EVENT


# The summary keeps common denominators, paired price differences and exact
# conditional-return denominators over the constructed sessions. A session
# where the candidate entered but the incumbent did not is a candidate-only
# diagnostic, not a missed waiting opportunity: waiting followed the candidate
# and entered, so it missed nothing there.
def test_summary_common_denominators_and_paired_counts():
    schedule = _schedule()
    both_day = SESSION
    candidate_day = date(2026, 1, 7)
    neither_day = date(2026, 1, 8)
    both_sec = session_after(schedule, both_day, SECONDARY_HORIZON)[0]
    both_pri = session_after(schedule, both_day, PRIMARY_HORIZON)[0]
    cand_sec = session_after(schedule, candidate_day, SECONDARY_HORIZON)[0]
    cand_pri = session_after(schedule, candidate_day, PRIMARY_HORIZON)[0]
    both = _ready_outcome(
        both_day,
        250.0,
        invalidate=True,
        closes={both_sec: 260.0, both_pri: 280.0},
    )
    candidate_only = _ready_outcome(
        candidate_day,
        245.0,
        invalidate=True,
        closes={cand_sec: 250.0, cand_pri: 255.0},
    )
    neither = replay_session_outcome(
        symbol="AAA",
        session=neither_day,
        bars=_full_day(neither_day, 230.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(neither_day, schedule),
    )
    summary = summarize(
        [both, candidate_only, neither], mode=RECORDED_ELIGIBILITY, price_basis="raw"
    )
    assert summary.session_count == 3
    assert summary.both_entries == 1
    assert summary.incumbent_only == 0
    assert summary.candidate_only == 1
    assert summary.neither_entries == 1
    assert summary.repeated_readiness == 0
    assert summary.missing_execution_count == 0
    assert summary.missing_outcome_count == 0
    assert summary.immature_outcome_count == 0
    assert summary.paired_entry_count == 1
    assert summary.paired_entry_price_diff == pytest.approx(0.0)
    assert summary.paired_entry_price_improvement == pytest.approx(0.0)
    assert summary.incumbent_primary.count == 1
    assert summary.incumbent_primary.mean == pytest.approx(280.0 / 251.0 - 1.0)
    assert summary.incumbent_secondary.count == 1
    assert summary.incumbent_secondary.mean == pytest.approx(260.0 / 251.0 - 1.0)
    assert summary.candidate_primary.count == 2
    assert summary.candidate_primary.mean == pytest.approx(
        (280.0 / 251.0 - 1.0 + 255.0 / 246.0 - 1.0) / 2.0
    )
    assert summary.candidate_secondary.count == 2
    assert summary.candidate_secondary.mean == pytest.approx(
        (260.0 / 251.0 - 1.0 + 250.0 / 246.0 - 1.0) / 2.0
    )
    assert summary.paired_primary_incumbent.count == 1
    assert summary.paired_primary_incumbent.mean == pytest.approx(280.0 / 251.0 - 1.0)
    assert summary.paired_primary_candidate.mean == pytest.approx(280.0 / 251.0 - 1.0)
    assert summary.paired_secondary_incumbent.count == 1
    assert summary.paired_secondary_incumbent.mean == pytest.approx(260.0 / 251.0 - 1.0)
    assert summary.paired_secondary_candidate.mean == pytest.approx(260.0 / 251.0 - 1.0)
    # The candidate-only session is a diagnostic, not what waiting missed: the
    # waiting candidate entered there, so nothing was missed.
    assert summary.missed_opportunity_count == 0
    assert summary.missed_opportunity_incumbent_primary.count == 0
    assert summary.missed_opportunity_candidate_primary.count == 1
    assert summary.missed_opportunity_candidate_primary.mean == pytest.approx(
        255.0 / 246.0 - 1.0
    )
    assert summary.missed_opportunity_candidate_secondary.mean == pytest.approx(
        250.0 / 246.0 - 1.0
    )
    assert "no entry" in summary.missed_opportunity_incumbent_context
    assert "not a portfolio" in summary.missed_opportunity_incumbent_context


# Waiting misses the incumbent-only entries, carrying the incumbent's own
# primary and secondary outcomes; the candidate (the waiting path) had no entry
# there, so its context is never presented as what waiting missed.
def test_missed_waiting_opportunities_are_incumbent_only_with_incumbent_outcomes():
    schedule = _schedule()
    incumbent_only = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=_full_day(SESSION, 260.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(SESSION, schedule),
    )
    assert incumbent_only.incumbent.event is not None
    assert incumbent_only.candidate.event is None
    summary = summarize([incumbent_only], mode=RECORDED_ELIGIBILITY, price_basis="raw")
    assert summary.session_count == 1
    assert summary.incumbent_only == 1
    assert summary.missed_opportunity_count == 1
    assert summary.missed_opportunity_incumbent_primary.count == 1
    assert summary.missed_opportunity_incumbent_primary.mean == pytest.approx(0.0)
    assert summary.missed_opportunity_incumbent_secondary.count == 1
    assert summary.missed_opportunity_incumbent_secondary.mean == pytest.approx(0.0)
    assert summary.missed_opportunity_candidate_primary.count == 0
    assert (
        "waiting candidate had no entry" in summary.missed_opportunity_incumbent_context
    )


# The summary retains the declared mode and rejects a silently mixed one.
def test_summary_retains_mode_and_rejects_mixing():
    outcome = _ready_outcome(SESSION, 245.0)
    summary = summarize([outcome], mode=RECORDED_ELIGIBILITY, price_basis="raw")
    assert summary.mode == RECORDED_ELIGIBILITY
    assert summary.price_basis == "raw"
    with pytest.raises(ValueError, match="mode"):
        summarize([outcome], mode=PRICE_DIAGNOSTIC, price_basis="raw")
    with pytest.raises(ValueError, match="price base"):
        summarize([outcome], mode=RECORDED_ELIGIBILITY, price_basis="adjusted")


# Unknown eligibility blocks every observation and never produces an event.
def test_unknown_eligibility_blocks_all_observations():
    result = replay_session(
        symbol="AAA",
        session=SESSION,
        bars=_entry_bars(SESSION, 250.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=[],
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
    )
    assert result.events == {}
    assert all(not obs.comparison.candidate.readiness for obs in result.observations)
    assert all(not obs.comparison.incumbent.readiness for obs in result.observations)


# The replay refuses an unlabelled basis, an unknown mode and an uncovered
# calendar rather than silently choosing one.
@pytest.mark.parametrize("bad_basis", [None, "mixed", "unadjusted_guess"])
def test_replay_rejects_unknown_basis(bad_basis):
    with pytest.raises(ValueError, match="basis"):
        replay_session(
            symbol="AAA",
            session=SESSION,
            bars=_entry_bars(SESSION, 245.0),
            history=_history(),
            price_basis=bad_basis,
            eligibility_timeline=_timeline(),
            schedule=_schedule(),
            mode=RECORDED_ELIGIBILITY,
        )


# The replay also rejects an unknown mode rather than defaulting it.
def test_replay_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        replay_session(
            symbol="AAA",
            session=SESSION,
            bars=_entry_bars(SESSION, 245.0),
            history=_history(),
            price_basis="raw",
            eligibility_timeline=_timeline(),
            schedule=_schedule(),
            mode="guess",
        )


# An uncovered calendar is refused rather than inferred from missing bars.
def test_replay_rejects_uncovered_calendar():
    schedule = SessionSchedule(
        full_sessions=frozenset(),
        early_closes={},
        covered_years=frozenset({2027}),
    )
    with pytest.raises(ValueError, match="unknown calendar coverage"):
        replay_session(
            symbol="AAA",
            session=SESSION,
            bars=_entry_bars(SESSION, 245.0),
            history=_history(),
            price_basis="raw",
            eligibility_timeline=_timeline(),
            schedule=schedule,
            mode=RECORDED_ELIGIBILITY,
        )


# The zero-cost proxy and the endpoint statuses are auditable on a result.
def test_outcome_record_is_auditable():
    schedule = _schedule()
    secondary = session_after(schedule, SESSION, SECONDARY_HORIZON)[0]
    primary = session_after(schedule, SESSION, PRIMARY_HORIZON)[0]
    outcome = _ready_outcome(SESSION, 245.0, closes={secondary: 250.0, primary: 280.0})
    assert outcome.price_basis == "raw"
    assert outcome.mode == RECORDED_ELIGIBILITY
    assert outcome.candidate.event is not None
    assert outcome.candidate.execution.status == EXECUTED
    assert outcome.candidate.primary.status == ENDPOINT_COMPLETE
    assert outcome.candidate.primary.endpoint_close == pytest.approx(280.0)
    assert outcome.candidate.primary.forward_return == pytest.approx(
        280.0 / 246.0 - 1.0
    )
    assert outcome.candidate.secondary.endpoint_close == pytest.approx(250.0)
    assert outcome.candidate.secondary.forward_return == pytest.approx(
        250.0 / 246.0 - 1.0
    )


# The dataset as-of threads through the public session outcome: a label whose
# endpoint close lies after the as-of is immature even when bars exist, and the
# scheduled endpoint close is reported as the label's availability instant.
def test_data_as_of_threads_through_session_outcome():
    schedule = _schedule()
    end = session_after(schedule, SESSION, SECONDARY_HORIZON)[0]
    before_close = datetime.combine(end, datetime.min.time(), NEW_YORK) + timedelta(
        hours=15
    )
    outcome = replay_session_outcome(
        symbol="AAA",
        session=SESSION,
        bars=_entry_bars(SESSION, 245.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=_timeline(),
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(SESSION, schedule),
        data_as_of=before_close,
    )
    assert outcome.candidate.secondary.status == ENDPOINT_IMMATURE
    assert outcome.candidate.secondary.forward_return is None
    assert outcome.candidate.secondary.available_at == (
        datetime.combine(end, datetime.min.time(), NEW_YORK) + timedelta(hours=16)
    )
    # With the primary horizon the endpoint still lies past the as-of, so a
    # future bar cannot manufacture a mature 20-session label either.
    assert outcome.candidate.primary.status == ENDPOINT_IMMATURE


# An early close's endpoint close is its 12:45 bar even when the feed also
# returns the afternoon's extended-hours bars: the regular window is bounded
# by the schedule's close, not by a hard-coded 16:00 that would have read the
# 15:45 print as the closing bar and rejected the session as incomplete.
def test_early_close_endpoint_close_ignores_afternoon_bars():
    from backend.market.intraday_replay import _endpoint_close

    schedule = _schedule()
    morning = [_bar(EARLY_CLOSE_DAY, s, 100.0, 100.5, 99.5, 100.0) for s in range(13)]
    closing = [_bar(EARLY_CLOSE_DAY, 13, 100.0, 101.0, 99.5, 101.0)]
    afternoon = [
        _bar(EARLY_CLOSE_DAY, s, 101.0, 106.0, 100.0, 105.0) for s in range(14, 26)
    ]
    assert _endpoint_close(
        morning + closing + afternoon, EARLY_CLOSE_DAY, schedule
    ) == (101.0)
    # Without its closing bar the session is incomplete, afternoon or not.
    assert _endpoint_close(morning + afternoon, EARLY_CLOSE_DAY, schedule) is None
    # A full session still needs its 15:45 bar.
    full = date(2026, 1, 16)
    assert _endpoint_close(_full_day(full, 100.0)[:-1], full, schedule) is None
    assert _endpoint_close(_full_day(full, 100.0), full, schedule) == 100.0
