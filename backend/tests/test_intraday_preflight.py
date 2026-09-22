"""Synthetic coverage of the causal input preparation boundary.

Per `docs/research/intraday-comparison-protocol-2026-09-22.md`, its input audit
and COMPARISON_PREFLIGHT_TASK.md. What has to hold on small synthetic fixture
caches and prices: a late 09-14 publication at 09-15 10:18 stays unknown before
10:30; a stale 09-11 grade cannot revive; a newer missing grade overrides an
earlier one; history gaps are unavailable while future daily poison is ignored;
a full calendar schedule covers the published years and refuses mourning
closures, early closes and unknown years as entry sessions; an as-of before the
entry session closes is refused; cache symbol and declared-basis mismatches and
missing caches are unavailable; unplaceable eligibility issues are unavailable
evidence; a future bad intraday bar is preserved and never disturbs earlier
replay observations; and the timeline stamps the observation instants while the
receipts carry the original publication times. The prepared outputs are
exercised through the reviewed ``replay_session``, never scored.
"""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pyarrow as pa
import pyarrow.parquet as pq

from backend.market.intraday_cache import (
    PRICE_BASIS_ADJUSTED,
    load_daily,
    load_intraday,
    load_recorded_eligibility,
)
from backend.market.intraday_comparison import CANDIDATE, INCUMBENT, DailyRow
from backend.market.intraday_entry import NEW_YORK, session_open_for
from backend.market.intraday_inputs import ResearchCalendar, load_calendar
from backend.market.intraday_preflight import (
    OBSERVATION_COUNT,
    READY,
    UNAVAILABLE,
    prepare_recorded_session,
    session_schedule_from_calendar,
)
from backend.market.intraday_replay import (
    RECORDED_ELIGIBILITY,
    SessionKind,
    replay_session,
)

SESSION = date(2026, 9, 15)
SESSION2 = date(2026, 9, 16)
CALENDAR = load_calendar()


# The UTC iso text of a New York regular-session bar start at ``slot`` on ``day``.
def _ny_utc(day: date, slot: int) -> str:
    """Return the aware UTC iso text of the NY bar-start instant at ``slot``."""
    return (
        (session_open_for(day) + timedelta(minutes=15 * slot))
        .astimezone(UTC)
        .isoformat()
    )


# One bars_15m row dict with an aware UTC start on ``day`` at ``slot``.
def _bar_row(day, slot, o, h, lo, c, volume=100.0):
    """Return a bars_15m row dict for ``day``/``slot`` with the given OHLCV."""
    return {
        "start": _ny_utc(day, slot),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": volume,
    }


# The adjusted-scale reclaim path for ``day`` (level ~121.03, entry ~122.19).
def _reclaim_rows(day, trigger_close=123.0, corrupt_close_slot=None):
    """Return bars forming the standard reclaim path, optionally one corrupt close."""
    rows = [
        _bar_row(day, 0, 121.5, 121.5, 120.5, 121.5),
        _bar_row(day, 1, 121.5, 121.5, 117.0, 118.0),
        _bar_row(
            day,
            2,
            trigger_close,
            trigger_close + 1.0,
            trigger_close - 1.0,
            trigger_close,
        ),
        _bar_row(
            day,
            3,
            trigger_close + 1.0,
            trigger_close + 2.0,
            trigger_close,
            trigger_close + 2.0,
        ),
    ]
    rows.extend(_bar_row(day, s, 121.5, 121.5, 121.5, 121.5) for s in range(4, 26))
    if corrupt_close_slot is not None:
        rows[corrupt_close_slot] = _bar_row(
            day, corrupt_close_slot, 121.5, 121.5, 121.5, "corrupt"
        )
    return rows


# Twenty DailyRows on the real calendar's prior exchange sessions.
def _prior_rows(session):
    """Return 20 DailyRows on the calendar's preceding exchange sessions."""
    dates = [CALENDAR.offset(session, -n) for n in range(20, 0, -1)]
    return [DailyRow(d, 100.0 + i, 100.0 + i) for i, d in enumerate(dates)]


# Write a bars_15m parquet for one symbol; close and volume are stored as text.
def _write_intraday(path, rows):
    """Write a bars_15m-style parquet with string close/volume cells."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("start", pa.string()),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.string()),
            ("volume", pa.string()),
        ],
        metadata={b"source": b"alpaca-iex"},
    )
    table = pa.table(
        {
            "start": [r["start"] for r in rows],
            "open": [r["open"] for r in rows],
            "high": [r["high"] for r in rows],
            "low": [r["low"] for r in rows],
            "close": [str(r["close"]) for r in rows],
            "volume": [str(r["volume"]) for r in rows],
        },
        schema=schema,
    )
    pq.write_table(table, path)
    return path


# Write a daily-bars parquet for one symbol.
def _write_daily(path, rows):
    """Write a daily-bars-style parquet for one symbol."""
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            ("session_date", pa.date32()),
            ("open", pa.float64()),
            ("high", pa.float64()),
            ("low", pa.float64()),
            ("close", pa.float64()),
            ("adjusted_close", pa.float64()),
            ("volume", pa.int64()),
        ],
        metadata={b"source": b"yahoo", b"asof": b"2026-09-20"},
    )
    table = pa.table(
        {
            "session_date": [r.date for r in rows],
            "open": [r.close for r in rows],
            "high": [r.close for r in rows],
            "low": [r.close for r in rows],
            "close": [r.close for r in rows],
            "adjusted_close": [r.adj_close for r in rows],
            "volume": [10] * len(rows),
        },
        schema=schema,
    )
    pq.write_table(table, path)
    return path


# Write one desk.json eligibility record and return its path.
def _write_desk(path, session_text, written, grades, levels):
    """Write a desk.json record carrying session, written, grades and levels."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "session": session_text,
        "written": written,
        "grades": grades,
        "levels": levels,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# Desk grades/levels payloads for symbol AAA.
def _grade_aaa(grade="A+", rejecting=False):
    """Return (grades, levels) payloads for symbol AAA."""
    return {"AAA": {"grade": grade}}, {"AAA": {"rejecting_band": rejecting}}


# The standard desk record: the 09-14 grade published 09-15 10:18 New York.
def _default_desks():
    """Return the default desk record, 09-14 published 09-15 10:18:21 New York."""
    grades, levels = _grade_aaa()
    return [("2026-09-14", "2026-09-15T14:18:21+00:00", grades, levels)]


# Write and load the three fixture caches for one symbol/session.
def _load(tmp_path, *, rows=None, prior=None, desks=None, session=SESSION):
    """Return the loaded (intraday, daily, eligibility) fixture caches."""
    prior = prior if prior is not None else _prior_rows(session)
    rows = rows if rows is not None else _reclaim_rows(session)
    if desks is None:
        desks = _default_desks()
    intraday_part = tmp_path / "bars_15m" / "asof=2026-09-20"
    daily_part = tmp_path / "bars" / "asof=2026-09-20"
    _write_intraday(intraday_part / "AAA.parquet", rows)
    _write_daily(daily_part / "AAA.parquet", prior)
    desk_paths = []
    for index, (session_text, written, grades, levels) in enumerate(desks):
        desk_paths.append(
            _write_desk(
                tmp_path / f"desk{index}" / f"asof={session_text}" / "desk.json",
                session_text,
                written,
                grades,
                levels,
            )
        )
    intraday = load_intraday("AAA", intraday_part, price_basis=PRICE_BASIS_ADJUSTED)
    daily = load_daily("AAA", daily_part, price_basis=PRICE_BASIS_ADJUSTED)
    eligibility = load_recorded_eligibility("AAA", desk_paths)
    return intraday, daily, eligibility


# Call prepare_recorded_session with the standard after-close data_as_of.
def _prepare(*, session=SESSION, asof=None, calendar=CALENDAR, **kwargs):
    """Return the preparation result for the fixture caches and after-close as-of."""
    return prepare_recorded_session(
        symbol="AAA",
        session=session,
        data_as_of=(
            asof
            if asof is not None
            else datetime.combine(session, time(16, 5), NEW_YORK)
        ),
        calendar=calendar,
        **kwargs,
    )


# Replay a prepared result directly through the reviewed replay boundary.
def _replay(prepared):
    """Return the replay_session result over the prepared outputs."""
    return replay_session(
        symbol=prepared.symbol,
        session=prepared.session,
        bars=prepared.session_bars,
        history=prepared.history,
        price_basis=prepared.price_basis,
        eligibility_timeline=prepared.timeline,
        schedule=prepared.schedule,
        mode=RECORDED_ELIGIBILITY,
    )


# The late 09-14 publication at 09-15 10:18 is unknown before 10:30; the prepared
# timeline stamps the observation instants while the receipt keeps the original
# publication time, and the prepared outputs replay to a 10:30 event.
def test_late_publication_is_unknown_until_published_then_replays(tmp_path):
    intraday, daily, eligibility = _load(tmp_path)
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == READY
    assert prepared.reason == ""
    assert prepared.symbol == "AAA"
    assert prepared.session == SESSION
    assert prepared.price_basis == PRICE_BASIS_ADJUSTED
    assert prepared.schedule.kind(SESSION) is SessionKind.FULL
    assert len(prepared.history) == 20
    assert len(prepared.session_bars) == 26
    assert len(prepared.timeline) == OBSERVATION_COUNT == 26
    assert len(prepared.receipts) == OBSERVATION_COUNT
    # Unknown before 10:30, then the published A+ with its original 10:18 time.
    for index in range(3):
        assert prepared.receipts[index].grade is None
        assert prepared.receipts[index].grade_published_at is None
    assert prepared.receipts[3].grade == "A+"
    assert prepared.receipts[3].grade_published_at == datetime(
        2026, 9, 15, 10, 18, 21, tzinfo=NEW_YORK
    )
    # The timeline stamps are the observation instants, never the publication time.
    assert prepared.timeline[0].grade_available_at.minute == 45
    assert prepared.timeline[3].grade_available_at == prepared.receipts[3].instant
    assert (
        prepared.timeline[3].grade_available_at
        != prepared.receipts[3].grade_published_at
    )
    assert prepared.timeline[-1].grade_available_at == datetime.combine(
        SESSION, time(16, 0), NEW_YORK
    )
    assert prepared.timeline[-1].grade == "A+"
    # The prepared inputs replay directly: no readiness before the gate is known.
    result = _replay(prepared)
    assert len(result.observations) == OBSERVATION_COUNT
    for index in range(3):
        assert not result.observations[index].comparison.candidate.readiness
        assert not result.observations[index].comparison.incumbent.readiness
    at_1030 = result.observations[3]
    assert at_1030.time == datetime.combine(SESSION, time(10, 30), NEW_YORK)
    assert at_1030.comparison.candidate.readiness
    assert at_1030.comparison.incumbent.readiness
    for method in (INCUMBENT, CANDIDATE):
        assert result.events[method].observation_time == (
            datetime.combine(SESSION, time(10, 30), NEW_YORK).isoformat(
                timespec="seconds"
            )
        )


# A stale 09-11 grade is expired on 09-15 and cannot revive before the 09-14
# record is published.
def test_stale_prior_grade_does_not_revive_on_a_later_session(tmp_path):
    grades, levels = _grade_aaa()
    stale = ("2026-09-11", "2026-09-12T02:00:00+00:00", grades, levels)
    late = ("2026-09-14", "2026-09-15T14:18:21+00:00", grades, levels)
    intraday, daily, eligibility = _load(tmp_path, desks=[stale, late])
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == READY
    for index in range(3):
        assert prepared.receipts[index].grade is None
    assert prepared.receipts[3].grade == "A+"
    assert prepared.timeline[0].grade is None
    result = _replay(prepared)
    assert result.events[CANDIDATE].observation_time == (
        datetime.combine(SESSION, time(10, 30), NEW_YORK).isoformat(timespec="seconds")
    )


# A newer record whose grade is missing overrides an earlier grade instead of
# reviving it, and is still a retained (unknown) observation, not a deletion.
def test_newer_missing_grade_overrides_an_earlier_grade(tmp_path):
    grades, levels = _grade_aaa()
    older = ("2026-09-15", "2026-09-15T21:00:00+00:00", grades, levels)
    missing = ("2026-09-15", "2026-09-16T02:00:00+00:00", {}, levels)
    intraday, daily, eligibility = _load(
        tmp_path, desks=[older, missing], session=SESSION2
    )
    prepared = _prepare(
        session=SESSION2, intraday=intraday, daily=daily, eligibility=eligibility
    )
    assert prepared.status == READY
    assert prepared.receipts[0].grade is None
    assert prepared.timeline[0].grade is None
    # Without the newer record the older grade is still fresh on 09-16.
    intraday, daily, eligibility = _load(
        tmp_path / "only", desks=[older], session=SESSION2
    )
    prepared_only = _prepare(
        session=SESSION2, intraday=intraday, daily=daily, eligibility=eligibility
    )
    assert prepared_only.receipts[0].grade == "A+"


# A history gap is unavailable; future bad daily rows never reject a valid prefix.
def test_history_gap_is_unavailable_and_future_poison_is_ignored(tmp_path):
    prior = _prior_rows(SESSION)
    prior.pop(5)
    prior.append(DailyRow(CALENDAR.offset(SESSION, -21), 90.0, 90.0))
    intraday, daily, eligibility = _load(tmp_path, prior=prior)
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == UNAVAILABLE
    assert "prior daily history" in prepared.reason
    assert prepared.symbol == "AAA"
    assert prepared.session == SESSION
    assert prepared.intraday is not None
    assert prepared.daily is not None
    poisoned = _prior_rows(SESSION) + [
        DailyRow(SESSION, float("nan"), -5.0),
        DailyRow(date(2026, 9, 16), 0.0, float("nan")),
    ]
    intraday, daily, eligibility = _load(tmp_path / "poison", prior=poisoned)
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == READY
    assert len(prepared.history) == 20
    assert prepared.history[0].date == CALENDAR.offset(SESSION, -20)


# The generated schedule covers the calendar's full published years; entry
# sessions refuse closures, early closes and unknown years, while early closes
# still count for outcome horizons.
def test_full_calendar_schedule_and_bad_entry_session_exclusion():
    schedule = session_schedule_from_calendar(CALENDAR)
    assert schedule.covered_years == CALENDAR.years
    assert schedule.kind(date(2028, 1, 4)) is SessionKind.FULL
    assert schedule.kind(date(2029, 1, 2)) is SessionKind.UNKNOWN
    assert schedule.is_session(date(2026, 11, 27))
    assert schedule.kind(date(2026, 11, 27)) is SessionKind.EARLY_CLOSE
    assert schedule.kind(date(2026, 9, 7)) is SessionKind.CLOSED
    synthetic = ResearchCalendar(
        frozenset({2026}),
        frozenset({date(2026, 1, 1), date(2026, 1, 9)}),
        frozenset({date(2026, 1, 15)}),
    )
    closed = _prepare(
        session=date(2026, 1, 9),
        calendar=synthetic,
        asof=datetime(2026, 1, 9, 17, 0, tzinfo=NEW_YORK),
    )
    assert closed.status == UNAVAILABLE
    assert "not an exchange session" in closed.reason
    early = _prepare(
        session=date(2026, 1, 15),
        calendar=synthetic,
        asof=datetime(2026, 1, 15, 17, 0, tzinfo=NEW_YORK),
    )
    assert early.status == UNAVAILABLE
    assert "early close" in early.reason
    unknown = _prepare(
        session=date(2027, 1, 4),
        calendar=synthetic,
        asof=datetime(2027, 1, 4, 17, 0, tzinfo=NEW_YORK),
    )
    assert unknown.status == UNAVAILABLE
    assert "unknown calendar coverage" in unknown.reason
    full = _prepare(
        session=date(2026, 1, 16),
        calendar=synthetic,
        asof=datetime(2026, 1, 16, 17, 0, tzinfo=NEW_YORK),
    )
    assert full.status == UNAVAILABLE
    assert "missing daily price cache" in full.reason


# An as-of before the entry session closes is refused; the close itself is fine.
def test_data_as_of_must_be_after_the_entry_session_close(tmp_path):
    intraday, daily, eligibility = _load(tmp_path)
    before = _prepare(
        intraday=intraday,
        daily=daily,
        eligibility=eligibility,
        asof=datetime(2026, 9, 15, 14, 0, tzinfo=NEW_YORK),
    )
    assert before.status == UNAVAILABLE
    assert "before the entry session closes" in before.reason
    at_close = _prepare(
        intraday=intraday,
        daily=daily,
        eligibility=eligibility,
        asof=datetime(2026, 9, 15, 16, 0, tzinfo=NEW_YORK),
    )
    assert at_close.status == READY


# The supplied cache symbols and declared adjusted basis must agree; both price
# provenance and limitation records are retained on success.
def test_source_symbol_and_declared_basis_must_agree(tmp_path):
    intraday, daily, eligibility = _load(tmp_path)
    wrong_intraday = replace(intraday, symbol="BBB")
    prepared = _prepare(intraday=wrong_intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == UNAVAILABLE
    assert "intraday cache symbol" in prepared.reason
    wrong_daily = replace(daily, symbol="BBB")
    prepared = _prepare(intraday=intraday, daily=wrong_daily, eligibility=eligibility)
    assert prepared.status == UNAVAILABLE
    assert "daily cache symbol" in prepared.reason
    wrong_eligibility = replace(eligibility, symbol="BBB")
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=wrong_eligibility)
    assert prepared.status == UNAVAILABLE
    assert "eligibility cache symbol" in prepared.reason
    wrong_basis = replace(
        intraday, provenance=replace(intraday.provenance, price_basis="raw")
    )
    prepared = _prepare(intraday=wrong_basis, daily=daily, eligibility=eligibility)
    assert prepared.status == UNAVAILABLE
    assert "price basis" in prepared.reason
    assert prepared.intraday is not None
    assert prepared.daily is not None
    assert prepared.eligibility is not None


# Both price caches' provenance and limitation records are carried when ready.
def test_ready_result_retains_both_price_cache_provenance_limitations(tmp_path):
    intraday, daily, eligibility = _load(tmp_path)
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == READY
    assert "adjustment=all" in prepared.intraday.provenance.limitation
    assert "adjustment=all" in prepared.daily.provenance.limitation
    assert "does not itself authorize" in prepared.intraday.provenance.limitation
    assert prepared.intraday.provenance.sha256
    assert prepared.daily.provenance.sha256
    assert prepared.eligibility.provenance[0].sha256


# A missing price or eligibility cache is an unavailable, retained opportunity.
def test_missing_price_or_eligibility_cache_is_unavailable(tmp_path):
    intraday, daily, eligibility = _load(tmp_path)
    no_daily = _prepare(intraday=intraday, eligibility=eligibility)
    assert no_daily.status == UNAVAILABLE
    assert "missing daily price cache" in no_daily.reason
    assert no_daily.session == SESSION
    assert no_daily.symbol == "AAA"
    assert no_daily.intraday is not None
    assert no_daily.eligibility is not None
    no_intraday = _prepare(daily=daily, eligibility=eligibility)
    assert no_intraday.status == UNAVAILABLE
    assert "missing intraday price cache" in no_intraday.reason
    no_eligibility = _prepare(intraday=intraday, daily=daily)
    assert no_eligibility.status == UNAVAILABLE
    assert "missing eligibility cache" in no_eligibility.reason


# Unplaceable eligibility publication errors are unavailable evidence and never
# silently revive an older grade.
def test_unplaceable_eligibility_issues_are_unavailable_evidence(tmp_path):
    grades, levels = _grade_aaa()
    bad = ("2026-09-15", "not-a-datetime", grades, levels)
    intraday, daily, eligibility = _load(tmp_path, desks=[bad])
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == UNAVAILABLE
    assert "unplaceable eligibility publication evidence" in prepared.reason
    assert "publication" in prepared.reason
    assert len(prepared.eligibility.issues) == 1
    assert prepared.eligibility.records == ()


# A future bad intraday bar is preserved intact and never changes the earlier
# replay observations or the recorded event.
def test_future_bad_intraday_bar_keeps_earlier_replay_observations(tmp_path):
    corrupt = _reclaim_rows(SESSION, corrupt_close_slot=10)
    intraday, daily, eligibility = _load(tmp_path, rows=corrupt)
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == READY
    assert len(prepared.session_bars) == 26
    assert prepared.session_bars[10].close != prepared.session_bars[10].close
    result = _replay(prepared)
    clean_intraday, clean_daily, clean_eligibility = _load(tmp_path / "clean")
    clean = _replay(
        _prepare(
            intraday=clean_intraday,
            daily=clean_daily,
            eligibility=clean_eligibility,
        )
    )
    assert result.events == clean.events
    for index in range(10):
        assert (
            result.observations[index].comparison
            == clean.observations[index].comparison
        )
    assert not result.observations[10].comparison.candidate.readiness
    assert clean.observations[10].comparison.candidate.readiness
    assert result.events[CANDIDATE].observation_time == (
        datetime.combine(SESSION, time(10, 30), NEW_YORK).isoformat(timespec="seconds")
    )


# A grade B is retained as an observation, not deleted, and still replays.
def test_grade_b_is_a_retained_observation(tmp_path):
    grades_b, levels_b = _grade_aaa(grade="B")
    desks = [("2026-09-14", "2026-09-15T14:18:21+00:00", grades_b, levels_b)]
    intraday, daily, eligibility = _load(tmp_path, desks=desks)
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == READY
    assert prepared.receipts[3].grade == "B"
    assert prepared.timeline[3].grade == "B"
    result = _replay(prepared)
    assert len(result.observations) == OBSERVATION_COUNT


# Preserve duplicates and their ordering so the replay rejects only affected prefixes.
def test_duplicate_is_not_cleaned_or_allowed_to_change_earlier_observations(tmp_path):
    intraday, daily, eligibility = _load(tmp_path)
    baseline = _replay(
        _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    )
    duplicate_bars = intraday.bars[:10] + (intraday.bars[10],) + intraday.bars[10:]
    prepared = _prepare(
        intraday=replace(intraday, bars=duplicate_bars),
        daily=daily,
        eligibility=eligibility,
    )
    assert prepared.session_bars == duplicate_bars
    result = _replay(prepared)
    assert result.events == baseline.events
    for index in range(10):
        assert (
            result.observations[index].comparison
            == baseline.observations[index].comparison
        )
    assert not result.observations[10].comparison.candidate.readiness
    assert baseline.observations[10].comparison.candidate.readiness


# Keep a session with no bars in the replay denominator and never borrow another day.
def test_other_session_bars_do_not_fill_a_missing_requested_session(tmp_path):
    intraday, daily, eligibility = _load(tmp_path, rows=_reclaim_rows(SESSION2))
    prepared = _prepare(intraday=intraday, daily=daily, eligibility=eligibility)
    assert prepared.status == READY
    assert prepared.session == SESSION
    assert prepared.session_bars == ()
    result = _replay(prepared)
    assert len(result.observations) == 26
    assert not result.events
    assert all(not obs.comparison.candidate.readiness for obs in result.observations)
