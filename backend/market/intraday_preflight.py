"""Causal input preparation for a recorded-session comparison replay.

Research-only, per ``docs/research/intraday-comparison-protocol-2026-09-22.md``
and its input audit. This module is a small PURE preparation boundary between
the reviewed read-only caches (``intraday_cache``), the reviewed dated gates
(``intraday_inputs``) and the reviewed replay (``intraday_replay``). It never
reads or writes disk or network, never calls a model, never recomputes a grade
and never scores anything. Historical scoring stays BLOCKED on the root audit's
corporate-action scale findings; preparing inputs does not authorize scoring,
and a prepared result never asserts cross-provider price compatibility.

For one requested symbol/session opportunity it returns a typed result that the
reviewed ``replay_session`` can consume directly: the replay ``SessionSchedule``
generated from the calendar's full covered years, exactly the preceding 20
exchange sessions via ``intraday_inputs.prior_daily``, only this session's
regular-hours bars (order, duplicates, missing cells and invalid OHLCV
preserved), and a conservative 26-instant eligibility timeline built by calling
``recorded_eligibility`` at each of the fixed observation instants, plus a
per-instant receipt carrying the original record publication times.

Unavailable conditions (unknown/closed/early-close entry sessions, an as-of
before the session closes, a missing cache, a source symbol or declared basis
mismatch, unplaceable eligibility issues, or missing/stale prior daily rows)
are reported as an explicit status with a reason while the requested
opportunity, the retained source caches and their provenance are never dropped.
No grade is fabricated and no price-component mode is invented in this task.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as day_time

from backend.market.intraday_cache import (
    PRICE_BASIS_ADJUSTED,
    DailyCache,
    EligibilityCache,
    IntradayCache,
)
from backend.market.intraday_comparison import DailyRow, Eligibility
from backend.market.intraday_entry import (
    CANDLE,
    NEW_YORK,
    SESSION_OPEN,
    Bar,
    session_close_for,
)
from backend.market.intraday_inputs import (
    RecordedEligibility,
    ResearchCalendar,
    prior_daily,
    recorded_eligibility,
)
from backend.market.intraday_replay import SessionSchedule

# A prepared opportunity is either ready for the reviewed replay, or unavailable.
READY = "ready"
UNAVAILABLE = "unavailable"

# The fixed number of completed bar-end instants in a full session (09:45..16:00).
OBSERVATION_COUNT = 26

# A full session closes at 16:00 New York; an early close is a distinct kind.
_FULL_CLOSE = day_time(16, 0)
_EARLY_CLOSE = day_time(13, 0)


# Coerce a timestamp to New York time; a naive timestamp is taken as New York.
def _ny(dt: datetime) -> datetime:
    """Return ``dt`` as a New York-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NEW_YORK)
    return dt.astimezone(NEW_YORK)


# One observation instant: the selected values and their original publication times.
@dataclass(frozen=True)
class EligibilityReceipt:
    """What one observation instant selected and when the source records published.

    ``instant`` is the fixed observation instant (09:45..16:00). The
    ``*_published_at`` fields are the original desk-record publication times the
    selected values came from, or None when that value was unknown; they are
    never the observation instant itself.
    """

    instant: datetime
    grade: str | None
    grade_published_at: datetime | None
    rejecting_band: bool | None
    rejecting_band_published_at: datetime | None


# The prepared inputs for one symbol/session opportunity, or why it is unavailable.
@dataclass(frozen=True)
class PreparationResult:
    """The prepared replay inputs and the retained source caches/provenance.

    ``status`` is ``ready`` when ``history``, ``session_bars``, ``timeline``
    and ``receipts`` are populated and can be handed to the reviewed replay, or
    ``unavailable`` with a ``reason``. The requested symbol/session opportunity,
    the supplied caches and their provenance are always retained, so an
    unavailable case is reported, never dropped. ``schedule`` always covers the
    calendar's full published covered years.
    """

    symbol: str
    session: date
    data_as_of: datetime
    status: str
    reason: str
    price_basis: str
    schedule: SessionSchedule
    intraday: IntradayCache | None
    daily: DailyCache | None
    eligibility: EligibilityCache | None
    history: tuple[DailyRow, ...]
    session_bars: tuple[Bar, ...]
    timeline: tuple[Eligibility, ...]
    receipts: tuple[EligibilityReceipt, ...]


# Build a replay schedule over the calendar's full covered years.
def session_schedule_from_calendar(calendar: ResearchCalendar) -> SessionSchedule:
    """Return a SessionSchedule covering every year the calendar publishes.

    The schedule spans the calendar's full covered years, not the years some
    price data happened to observe, so a year without bars still yields its
    sessions and an unknown future year stays unknown. Early closes are kept as
    sessions (they count for outcomes) but are never full-session entry dates.
    """
    full: set[date] = set()
    early: dict[date, day_time] = {}
    for year in calendar.years:
        day = date(year, 1, 1)
        while day.year == year:
            close = calendar.close_time(day)
            if close == _FULL_CLOSE:
                full.add(day)
            elif close == _EARLY_CLOSE:
                early[day] = close
            day += timedelta(days=1)
    return SessionSchedule(frozenset(full), early, frozenset(calendar.years))


# The fixed completed bar-end instants of a full session, 09:45 through 16:00.
def _observation_instants(session: date) -> tuple[datetime, ...]:
    """Return the session's 26 observation instants, one per completed bar end."""
    open_ny = datetime.combine(session, SESSION_OPEN, NEW_YORK)
    return tuple(open_ny + CANDLE * n for n in range(1, OBSERVATION_COUNT + 1))


# This session's regular-hours bars, preserved exactly as supplied.
def _session_regular_bars(intraday: IntradayCache, session: date) -> tuple[Bar, ...]:
    """Return only the bars whose New York date is ``session`` in regular hours.

    This is a pure filter: original order, duplicates, missing cells (NaN) and
    invalid OHLCV are all kept intact for the later causal validation, and no
    full-session completeness is required to admit earlier observations.
    """
    selected: list[Bar] = []
    for bar in intraday.bars:
        start_ny = _ny(bar.start)
        if start_ny.date() == session and (
            start_ny.time() >= SESSION_OPEN and start_ny < session_close_for(session)
        ):
            selected.append(bar)
    return tuple(selected)


# The conservative 26-instant eligibility timeline plus original-publication receipts.
def _eligibility_timeline(
    records: tuple[RecordedEligibility, ...],
    session: date,
    calendar: ResearchCalendar,
) -> tuple[tuple[Eligibility, ...], tuple[EligibilityReceipt, ...]]:
    """Return (26-entry stamped timeline, per-instant receipts) for ``session``.

    Each fixed observation instant calls ``recorded_eligibility``, which applies
    the actual publication time and the current/previous-session freshness rule.
    The replay timeline stamps the selected values (including unknown sentinels)
    at that observation instant, so an expired or missing gate overrides any
    earlier good timeline entry; the receipt keeps the original publication
    times, never the observation instants. A grade B or an unknown gate is a
    retained observation, never a deleted opportunity.
    """
    timeline: list[Eligibility] = []
    receipts: list[EligibilityReceipt] = []
    for instant in _observation_instants(session):
        selected = recorded_eligibility(list(records), instant, calendar)
        receipts.append(
            EligibilityReceipt(
                instant=instant,
                grade=selected.grade,
                grade_published_at=selected.grade_available_at,
                rejecting_band=selected.rejecting_band,
                rejecting_band_published_at=selected.rejecting_band_available_at,
            )
        )
        timeline.append(
            Eligibility(selected.grade, instant, selected.rejecting_band, instant)
        )
    return tuple(timeline), tuple(receipts)


# Build an unavailable result that still retains the opportunity and its sources.
def _unavailable(
    *,
    symbol: str,
    session: date,
    data_as_of: datetime,
    schedule: SessionSchedule,
    intraday: IntradayCache | None,
    daily: DailyCache | None,
    eligibility: EligibilityCache | None,
    reason: str,
) -> PreparationResult:
    """Return an unavailable PreparationResult with the reason and all sources kept."""
    return PreparationResult(
        symbol=symbol,
        session=session,
        data_as_of=data_as_of,
        status=UNAVAILABLE,
        reason=reason,
        price_basis=PRICE_BASIS_ADJUSTED,
        schedule=schedule,
        intraday=intraday,
        daily=daily,
        eligibility=eligibility,
        history=(),
        session_bars=(),
        timeline=(),
        receipts=(),
    )


# Prepare one recorded symbol/session opportunity for the reviewed replay.
def prepare_recorded_session(  # noqa: C901 - explicit refusal-order gates
    *,
    symbol: str,
    session: date,
    data_as_of: datetime,
    calendar: ResearchCalendar,
    intraday: IntradayCache | None = None,
    daily: DailyCache | None = None,
    eligibility: EligibilityCache | None = None,
) -> PreparationResult:
    """Return the prepared replay inputs for one symbol/session opportunity.

    ``data_as_of`` is required and must be timezone-aware. The entry session
    must be a known full session on ``calendar`` (unknown, closed and early-close
    sessions are refused) and ``data_as_of`` must be at or after the session's
    close. Supplied cache symbols must match ``symbol`` and price caches must
    declare the adjusted basis; this checks declarations only and never asserts
    cross-provider compatibility. ``EligibilityCache.issues`` are unplaceable
    evidence and make the opportunity unavailable rather than reviving an older
    grade. Missing/stale daily history is unavailable; future bad daily rows do
    not reject a valid prefix. Unavailable conditions keep the opportunity and
    the source provenance in the result with an explicit reason.
    """
    if not symbol:
        raise ValueError("a symbol is required")
    if data_as_of.tzinfo is None or data_as_of.utcoffset() is None:
        raise ValueError("data_as_of must be a timezone-aware datetime")
    schedule = session_schedule_from_calendar(calendar)
    try:
        close_time = calendar.close_time(session)
    except ValueError as exc:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=f"unknown calendar coverage for the entry session: {exc}",
        )
    if close_time is None:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=f"{session.isoformat()} is not an exchange session (closed)",
        )
    if close_time == _EARLY_CLOSE:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                f"{session.isoformat()} is an early close and must be excluded "
                "as an entry session"
            ),
        )
    session_close = datetime.combine(session, close_time, NEW_YORK)
    if _ny(data_as_of) < session_close:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                f"data_as_of {data_as_of.isoformat()} is before the entry "
                f"session closes at {session_close.isoformat()}"
            ),
        )
    if daily is None:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason="missing daily price cache",
        )
    if intraday is None:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason="missing intraday price cache",
        )
    if eligibility is None:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason="missing eligibility cache",
        )
    if intraday.symbol != symbol:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                f"intraday cache symbol {intraday.symbol!r} does not match "
                f"requested {symbol!r}"
            ),
        )
    if intraday.provenance.price_basis != PRICE_BASIS_ADJUSTED:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                f"intraday cache declares price basis "
                f"{intraday.provenance.price_basis!r}, expected "
                f"{PRICE_BASIS_ADJUSTED!r}"
            ),
        )
    if daily.symbol != symbol:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                f"daily cache symbol {daily.symbol!r} does not match "
                f"requested {symbol!r}"
            ),
        )
    if daily.provenance.price_basis != PRICE_BASIS_ADJUSTED:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                f"daily cache declares price basis "
                f"{daily.provenance.price_basis!r}, expected "
                f"{PRICE_BASIS_ADJUSTED!r}"
            ),
        )
    if eligibility.symbol != symbol:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                f"eligibility cache symbol {eligibility.symbol!r} does not "
                f"match requested {symbol!r}"
            ),
        )
    if eligibility.issues:
        detail = "; ".join(issue.reason for issue in eligibility.issues)
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=(
                "unplaceable eligibility publication evidence; a missing newer "
                f"grade must not silently revive an older one: {detail}"
            ),
        )
    try:
        history = tuple(prior_daily(list(daily.rows), session, calendar))
    except ValueError as exc:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=f"prior daily history unavailable: {exc}",
        )
    session_bars = _session_regular_bars(intraday, session)
    try:
        timeline, receipts = _eligibility_timeline(
            eligibility.records, session, calendar
        )
    except ValueError as exc:
        return _unavailable(
            symbol=symbol,
            session=session,
            data_as_of=data_as_of,
            schedule=schedule,
            intraday=intraday,
            daily=daily,
            eligibility=eligibility,
            reason=f"eligibility timeline unavailable: {exc}",
        )
    return PreparationResult(
        symbol=symbol,
        session=session,
        data_as_of=data_as_of,
        status=READY,
        reason="",
        price_basis=PRICE_BASIS_ADJUSTED,
        schedule=schedule,
        intraday=intraday,
        daily=daily,
        eligibility=eligibility,
        history=history,
        session_bars=session_bars,
        timeline=timeline,
        receipts=receipts,
    )
