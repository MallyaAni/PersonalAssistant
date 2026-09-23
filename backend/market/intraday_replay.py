"""Pure causal replay and outcome accounting on caller-supplied records.

Research-only, per `docs/research/intraday-comparison-protocol-2026-09-22.md`:
no broker, no orders, no portfolio, no disk writes, no historical scoring run
and no model calls. This module replays one full-session day's completed
15-minute observations at their ends through the reviewed
``intraday_comparison.compare`` and ``record_event``, then computes the
protocol's execution proxy and its 20/5-session outcome labels on caller
supplied bars and exchange sessions.

Every input is supplied by the caller: the symbol/session bars, the dated daily
context, an explicit raw/adjusted price basis, a chronological eligibility
timeline whose records carry their actual availability times, and an
exchange-session schedule that names full sessions, early closes, closures and
the covered years. Nothing is read from disk and no calendar is inferred from
missing bars. A known early close or closure is excluded before replay, unknown
calendar coverage is explicit unavailable, an unknown or late-published
eligibility record blocks a recommendation instead of being retroactively
enabled, and a missing next bar is ``execution_unknown`` rather than filled at
a later bar or session. Past events are never revised by a later invalidation,
and repeated readiness never buys a second time.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as day_time
from enum import Enum

from backend.market.intraday_comparison import (
    CANDIDATE,
    INCUMBENT,
    Comparison,
    DailyRow,
    Eligibility,
    EventLedger,
    EventRecord,
    compare,
    record_event,
)
from backend.market.intraday_entry import (
    BAR_MINUTES,
    CANDLE,
    NEW_YORK,
    SESSION_OPEN,
    Bar,
    _completed_bars,
    session_close_for,
)

# Outcome horizons, exactly the frozen protocol: 20 sessions for the primary
# portfolio-entry diagnostic, 5 for the secondary precision diagnostic.
PRIMARY_HORIZON = 20
SECONDARY_HORIZON = 5

# The mode label is never defaulted: recorded eligibility or an explicit
# price-only component diagnostic, so no run silently invents historical grades.
RECORDED_ELIGIBILITY = "recorded_eligibility"
PRICE_DIAGNOSTIC = "price_diagnostic"

# Execution-proxy statuses and endpoint-label statuses a reviewer can audit.
EXECUTED = "executed"
EXECUTION_UNKNOWN = "execution_unknown"
ENDPOINT_COMPLETE = "complete"
ENDPOINT_IMMATURE = "immature"
ENDPOINT_MISSING = "missing_endpoint"
ENDPOINT_UNAVAILABLE = "unavailable"
ENDPOINT_NO_EVENT = "no_event"
EXCURSION_AVAILABLE = "available"
EXCURSION_UNAVAILABLE = "unavailable"


# Coerce a timestamp to New York time; a naive timestamp is taken as New York.
def _ny(dt: datetime) -> datetime:
    """Return ``dt`` as a New York-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NEW_YORK)
    return dt.astimezone(NEW_YORK)


# Reject missing or unsupported units rather than infer them from price values.
def _checked_basis(price_basis: str | None) -> str:
    """Return the basis after requiring it to be explicitly raw or adjusted."""
    if price_basis not in ("raw", "adjusted"):
        raise ValueError("price basis must be explicitly raw or adjusted")
    return price_basis


# Reject a missing or unrecognised mode rather than silently choosing one.
def _checked_mode(mode: str | None) -> str:
    """Return the mode after requiring a declared recorded or diagnostic label."""
    if mode not in (RECORDED_ELIGIBILITY, PRICE_DIAGNOSTIC):
        raise ValueError(
            "mode must be recorded_eligibility or price_diagnostic, never defaulted"
        )
    return mode


# The kind of exchange session a date belongs to on the supplied schedule.
class SessionKind(Enum):
    """Whether a date is a full session, an early close, closed or unknown."""

    FULL = "full"
    EARLY_CLOSE = "early_close"
    CLOSED = "closed"
    UNKNOWN = "unknown"


# Caller-supplied exchange sessions: full days, early closes and covered years.
@dataclass(frozen=True)
class SessionSchedule:
    """The supplied exchange sessions, with explicit per-year coverage.

    ``full_sessions`` are dates of regular full sessions, ``early_closes`` maps
    an early-close date to its session close time and ``covered_years`` names
    the years whose schedules are complete. A date in an uncovered year is
    ``SessionKind.UNKNOWN``: the replay never infers a session from a missing
    bar, so unknown coverage is explicit unavailable.
    """

    full_sessions: frozenset[date]
    early_closes: Mapping[date, day_time]
    covered_years: frozenset[int]

    # What kind of session a date is on the supplied schedule.
    def kind(self, day: date) -> SessionKind:
        """Return the supplied kind of ``day`` (unknown when not covered)."""
        if day.year not in self.covered_years:
            return SessionKind.UNKNOWN
        if day in self.early_closes:
            return SessionKind.EARLY_CLOSE
        if day in self.full_sessions:
            return SessionKind.FULL
        return SessionKind.CLOSED

    # Whether a date is any kind of trading session (full or early close).
    def is_session(self, day: date) -> bool:
        """Return whether ``day`` is a trading session (full or early close)."""
        kind = self.kind(day)
        return kind in (SessionKind.FULL, SessionKind.EARLY_CLOSE)

    # The supplied close time of a session day: the early close where the
    # schedule names one, else the regular 16:00.
    def session_close_time(self, day: date) -> day_time:
        """Return the scheduled close time of ``day`` on this schedule."""
        return self.early_closes[day] if day in self.early_closes else day_time(16, 0)

    # The New York start of the day's last regular bar, close-aware.
    def session_close_bar_start(self, day: date) -> datetime:
        """Return the New York start of the day's last regular bar.

        A full session's closing bar starts at 15:45 and an early close's at
        12:45, so the endpoint close is checked against the right clock.
        """
        return datetime.combine(day, self.session_close_time(day), NEW_YORK) - CANDLE


# One observed decision instant and the adapter's comparison at that instant.
@dataclass(frozen=True)
class ObservationRecord:
    """One replayed observation: the instant and both methods' comparison."""

    time: datetime
    comparison: Comparison


# The causal walk of one full-session day.
@dataclass(frozen=True)
class ReplayResult:
    """Every observation, the raw readiness counts and the first events.

    ``observations`` preserves every replayed decision instant in order.
    ``readiness_counts`` counts every ready observation per method/symbol/
    session (including repeats), and ``events`` holds only the first accepted
    entry event per method, so raw readiness and first events are separate.
    """

    symbol: str
    session: date
    price_basis: str
    mode: str
    observations: tuple[ObservationRecord, ...]
    readiness_counts: Mapping[str, int]
    events: Mapping[str, EventRecord]


# The zero-latency next-bar-open execution proxy, labelled honestly.
@dataclass(frozen=True)
class ExecutionProxy:
    """The next consecutive regular-session bar open after confirmation.

    ``status`` is ``executed`` only when that bar is present and valid; anything
    else is ``execution_unknown`` and never jumps to a later bar or session.
    """

    method: str
    status: str
    price: float | None
    time: datetime | None
    reason: str


# One horizon's outcome label, with its availability and reason.
@dataclass(frozen=True)
class EndpointLabel:
    """The close at a declared session horizon, or why it is not available.

    ``status`` distinguishes a complete label from an immature horizon (the
    endpoint date lies beyond the supplied data or the dataset as-of has not
    reached its close), a missing endpoint session, unavailable calendar
    coverage and a method that never entered. ``available_at`` is the
    scheduled endpoint close datetime (early closes included) or None when
    there is no endpoint to schedule.
    """

    horizon: int
    endpoint_date: date | None
    status: str
    endpoint_close: float | None
    forward_return: float | None
    reason: str
    available_at: datetime | None = None


# Post-entry adverse/favorable excursion through the endpoint.
@dataclass(frozen=True)
class ExcursionLabel:
    """Post-entry extremes from the execution bar through the endpoint.

    Both excursions are fractions of the execution price. ``unavailable`` when
    any post-entry observation is missing, so a misleading extreme is never
    reported over an observed subset.
    """

    status: str
    adverse: float | None
    favorable: float | None
    reason: str


# One method's full replay plus execution and both outcome labels.
@dataclass(frozen=True)
class OutcomeRecord:
    """Everything a reviewer needs for one method/symbol/session result."""

    method: str
    symbol: str
    session: date
    price_basis: str
    mode: str
    event: EventRecord | None
    execution: ExecutionProxy
    primary: EndpointLabel
    secondary: EndpointLabel
    excursion: ExcursionLabel


# A session's two method outcomes sharing the replayed observations.
@dataclass(frozen=True)
class SessionOutcome:
    """The incumbent and candidate outcome records for one replayed session."""

    symbol: str
    session: date
    price_basis: str
    mode: str
    replay: ReplayResult
    incumbent: OutcomeRecord
    candidate: OutcomeRecord


# A conditional forward return with its exact denominator.
@dataclass(frozen=True)
class ConditionalReturn:
    """Mean forward return over a counted set of complete labels."""

    horizon: int
    count: int
    mean: float | None


# The aggregate, audit-oriented summary over a set of replayed sessions.
@dataclass(frozen=True)
class ReplaySummary:
    """The common opportunity counts, readiness, coverage and returns.

    Every entry count uses the common opportunity denominator
    ``session_count``. A session where the incumbent entered but the waiting
    candidate did not is a missed waiting opportunity and is reported with the
    incumbent's own outcomes; candidate-only outcomes stay separate
    diagnostics and are never presented as what waiting missed, nor as a
    portfolio profitability claim. ``paired_entry_price_diff`` is an absolute
    currency difference that is explicitly not comparable across stock price
    scales; ``paired_entry_price_improvement`` is the same paired comparison
    in relative (fraction of the incumbent open) units and is the comparable
    metric. Neither is portfolio alpha.
    """

    mode: str
    price_basis: str
    session_count: int
    both_entries: int
    incumbent_only: int
    candidate_only: int
    neither_entries: int
    repeated_readiness: int
    missing_execution_count: int
    missing_outcome_count: int
    immature_outcome_count: int
    paired_entry_count: int
    paired_entry_price_diff: float | None
    paired_entry_price_improvement: float | None
    incumbent_primary: ConditionalReturn
    incumbent_secondary: ConditionalReturn
    candidate_primary: ConditionalReturn
    candidate_secondary: ConditionalReturn
    paired_primary_incumbent: ConditionalReturn
    paired_primary_candidate: ConditionalReturn
    paired_secondary_incumbent: ConditionalReturn
    paired_secondary_candidate: ConditionalReturn
    missed_opportunity_count: int
    missed_opportunity_incumbent_primary: ConditionalReturn
    missed_opportunity_incumbent_secondary: ConditionalReturn
    missed_opportunity_candidate_primary: ConditionalReturn
    missed_opportunity_candidate_secondary: ConditionalReturn
    missed_opportunity_incumbent_context: str


# The eligibility state already available at an instant, newest publication wins.
def eligibility_at(timeline: Sequence[Eligibility], at: datetime) -> Eligibility | None:
    """Return the newest eligibility record published by ``at``, or None.

    A record is selectable once either common input has a known publication
    time at or before ``at``. An unavailable grade must not revive an older
    ready record when a newer rejection input is already known. Among
    selectable records the newest observed publication wins, and
    an equal-time conflict resolves to the record that arrived later in the
    timeline. A partially known record (a grade without a known rejecting
    band, or a rejecting band learned after ``at``) is still selected so it
    never silently falls back to an older good record; the adapter blocks
    missing or future common inputs. A None return means nothing was published
    by that instant, which blocks a recommendation for both methods.
    """
    instant = _ny(at)
    candidates: list[tuple[datetime, int, Eligibility]] = []
    for index, record in enumerate(timeline):
        observed = [
            _ny(stamp)
            for stamp in (record.grade_available_at, record.rejecting_band_available_at)
            if stamp is not None and _ny(stamp) <= instant
        ]
        if not observed:
            continue
        published = max(observed)
        candidates.append((published, index, record))
    if not candidates:
        return None
    return max(candidates, key=lambda pair: (pair[0], pair[1]))[2]


# The fixed regular-session observation clock for a full session day.
def _session_observation_times(session: date) -> tuple[datetime, ...]:
    """Return the session's 26 completed bar-end instants, 09:45 through 16:00.

    The observation clock is a property of the full session, never of which
    bars happened to arrive: every one of the 26 expected bar ends is an
    observation even when a feed bar is empty or missing, and no instant is
    ever generated from another session or from an off-grid bar. Early-close
    and closed entry sessions are refused before replay, so only the full
    26-slot clock is used here.
    """
    open_ny = datetime.combine(session, SESSION_OPEN, NEW_YORK)
    return tuple(open_ny + CANDLE * n for n in range(1, 27))


# This session's own bars, so another session's bars cannot form instants.
def _session_bars(bars: Sequence[Bar], session: date) -> list[Bar]:
    """Return only the bars whose date is the replayed ``session``."""
    return [b for b in bars if _ny(b.start).date() == session]


# A blank eligibility: nothing known at this instant, blocks both methods.
def _blank_eligibility() -> Eligibility:
    """Return an Eligibility with no known inputs, which blocks a recommendation."""
    return Eligibility(None, None, None, None)


# Replay one full-session day's observations through the reviewed adapter.
def replay_session(
    *,
    symbol: str,
    session: date,
    bars: Sequence[Bar],
    history: Sequence[DailyRow],
    price_basis: str,
    eligibility_timeline: Sequence[Eligibility],
    schedule: SessionSchedule,
    mode: str,
) -> ReplayResult:
    """Walk every completed observation at its end and return the events.

    ``session`` must be a known full session on ``schedule``: an early close or
    closure is excluded before replay and unknown coverage is refused, never
    inferred from missing bars. Each observation selects only the eligibility
    already available at that instant, so a late-published record never appears
    at an earlier decision. ``price_basis`` and ``mode`` are required and never
    defaulted. Future bars and future eligibility records cannot change an
    earlier decision, and an earlier valid prefix is never discarded by a later
    gap or corrupt bar. Readiness is counted per observation while the first
    accepted entry event is recorded once per method/symbol/session.
    """
    basis = _checked_basis(price_basis)
    _checked_mode(mode)
    kind = schedule.kind(session)
    if kind is SessionKind.UNKNOWN:
        raise ValueError(
            "unknown calendar coverage for the entry session; do not infer it "
            "from missing bars"
        )
    if kind is SessionKind.CLOSED:
        raise ValueError(f"{session.isoformat()} is not an exchange session")
    if kind is SessionKind.EARLY_CLOSE:
        raise ValueError(
            f"{session.isoformat()} is an early close and must be excluded "
            "before replay"
        )

    ledger: EventLedger = EventLedger()
    observations: list[ObservationRecord] = []
    readiness: dict[str, int] = {}
    events: dict[str, EventRecord] = {}
    session_bars = _session_bars(bars, session)
    for instant in _session_observation_times(session):
        selected = eligibility_at(eligibility_timeline, instant)
        eligibility = selected if selected is not None else _blank_eligibility()
        result = compare(
            symbol,
            session,
            session_bars,
            list(history),
            eligibility,
            as_of=instant,
            price_basis=basis,
        )
        observations.append(ObservationRecord(time=instant, comparison=result))
        for method, method_observation in (
            (INCUMBENT, result.incumbent),
            (CANDIDATE, result.candidate),
        ):
            if method_observation.readiness:
                readiness[method] = readiness.get(method, 0) + 1
            ledger, event, _new = record_event(ledger, method_observation)
            if event is not None and method not in events:
                events[method] = event
    return ReplayResult(
        symbol=symbol,
        session=session,
        price_basis=basis,
        mode=mode,
        observations=tuple(observations),
        readiness_counts=readiness,
        events=events,
    )


# Parse an event's observation time as a New York datetime.
def _event_time(event: EventRecord) -> datetime | None:
    """Return the event's observation instant as a New York datetime, or None."""
    if not event.observation_time:
        return None
    try:
        return _ny(datetime.fromisoformat(event.observation_time))
    except ValueError:
        return None


# The next consecutive regular-session bar's open after confirmation.
def execution_proxy(bars: Sequence[Bar], event: EventRecord) -> ExecutionProxy:
    """Return the next consecutive bar open after the event's observation time.

    The confirmation is known at ``event.observation_time``; the next bar
    begins at that same instant and its open is the zero-latency, zero-cost
    optimistic proxy (never a midpoint fill). Execution happens only when there
    is exactly one bar at that instant, on the event's own session date, in
    regular hours before 16:00 and on the 15-minute grid, and that bar is
    valid. A duplicate bar, a missing bar, an extended-hours or off-grid
    observation time, or an invalid bar is ``execution_unknown`` and is never
    replaced by a later bar or the next session. The event's observation time,
    not an earlier candidate trigger time, fixes the proxy.
    """
    method = event.method
    observation_time = _event_time(event)
    if observation_time is None:
        return ExecutionProxy(
            method, EXECUTION_UNKNOWN, None, None, "no observation time on the event"
        )
    start_ny = _ny(observation_time)
    if start_ny.date() != event.session:
        return ExecutionProxy(
            method,
            EXECUTION_UNKNOWN,
            None,
            observation_time,
            "the observation time is not on the event's session date",
        )
    if not (
        start_ny.time() >= SESSION_OPEN and start_ny < session_close_for(event.session)
    ):
        return ExecutionProxy(
            method,
            EXECUTION_UNKNOWN,
            None,
            observation_time,
            "the observation time is outside regular session hours",
        )
    if (
        start_ny.minute % BAR_MINUTES != 0
        or start_ny.second != 0
        or start_ny.microsecond != 0
    ):
        return ExecutionProxy(
            method,
            EXECUTION_UNKNOWN,
            None,
            observation_time,
            "the observation time is off the 15-minute grid",
        )
    matches = [bar for bar in bars if _ny(bar.start) == start_ny]
    if not matches:
        return ExecutionProxy(
            method,
            EXECUTION_UNKNOWN,
            None,
            observation_time,
            "no next consecutive regular-session bar after the observation time",
        )
    if len(matches) > 1:
        return ExecutionProxy(
            method,
            EXECUTION_UNKNOWN,
            None,
            observation_time,
            "duplicate next consecutive bars at the observation time",
        )
    candidate = matches[0]
    if not _valid_bar(candidate):
        return ExecutionProxy(
            method,
            EXECUTION_UNKNOWN,
            None,
            observation_time,
            "the next bar is invalid",
        )
    return ExecutionProxy(
        method,
        EXECUTED,
        candidate.open,
        observation_time,
        "next consecutive regular-session bar open, zero added costs",
    )


# Reject a bar whose OHLCV cannot be a real print.
def _valid_bar(bar: Bar) -> bool:
    """Return whether the bar's OHLCV is a finite, positive, consistent print."""
    prices = (bar.open, bar.high, bar.low, bar.close)
    if any(not _finite_price(p) for p in prices):
        return False
    if not (math.isfinite(bar.volume) and bar.volume >= 0):
        return False
    return bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high


# A finite positive price.
def _finite_price(value: float) -> bool:
    """Return whether ``value`` is a finite positive price."""
    return math.isfinite(value) and value > 0


# The date n sessions after a session, advancing on the supplied schedule.
def session_after(
    schedule: SessionSchedule, start: date, n: int
) -> tuple[date | None, str]:
    """Return the date ``n`` sessions after ``start``, or (None, reason).

    Sessions advance on the supplied exchange sessions, never by counting
    available rows. Stepping into an uncovered year is explicit unavailable,
    and an unreachable calendar is unavailable rather than guessed.
    """
    if n < 0:
        return None, "negative horizon"
    day = start
    count = 0
    guard = 0
    while count < n:
        day = day + timedelta(days=1)
        guard += 1
        if day.year not in schedule.covered_years:
            return None, "unknown calendar coverage before the horizon"
        if schedule.is_session(day):
            count += 1
        if guard > 10 * n + 30:
            return None, "the supplied calendar does not reach the horizon"
    return day, "ok"


# The validated complete bars of one session, or None when incomplete.
def _validated_complete(
    bars: Sequence[Bar], session: date, schedule: SessionSchedule
) -> list[Bar] | None:
    """Return the session's validated bars through its close, or None.

    Reuses the reviewed engine's structural validation (grid, opening bar,
    contiguity, uniqueness and OHLCV), then requires the final bar to be the
    session's closing bar on the schedule, so an early close is not mistaken
    for an incomplete full day.
    """
    try:
        # Bound the regular window by the schedule's own close, so an early
        # close's afternoon bars do not displace its 12:45 closing bar.
        completed = _completed_bars(
            list(bars), session, None, close=schedule.session_close_time(session)
        )
    except ValueError:
        return None
    if not completed or _ny(completed[-1].start) != schedule.session_close_bar_start(
        session
    ):
        return None
    return completed


# The close price of one endpoint session, or None when not present/completed.
def _endpoint_close(
    bars: Sequence[Bar], session: date, schedule: SessionSchedule
) -> float | None:
    """Return the session's closing bar close, or None when incomplete."""
    completed = _validated_complete(bars, session, schedule)
    return completed[-1].close if completed else None


# The scheduled New York close datetime of a session, early closes included.
def _session_close_datetime(schedule: SessionSchedule, day: date) -> datetime:
    """Return the scheduled close datetime (16:00, or the early-close time)."""
    return datetime.combine(day, schedule.session_close_time(day), NEW_YORK)


# One horizon's label for a method's execution.
def endpoint_label(
    *,
    schedule: SessionSchedule,
    outcome_bars: Mapping[date, Sequence[Bar]],
    entry_session: date,
    horizon: int,
    execution_price: float | None,
    data_as_of: datetime | None = None,
) -> EndpointLabel:
    """Return the close at ``horizon`` sessions after entry, or its status.

    The endpoint date advances on the supplied exchange sessions, and
    ``available_at`` is the scheduled endpoint close datetime (early closes
    included) or None when the calendar cannot reach a horizon. With an
    explicit ``data_as_of`` (the dataset's observation instant, which the root
    historical runner must supply), a label before the endpoint close is
    ``immature`` even if bars exist — future bars cannot manufacture a mature
    label — while a date whose close has passed without endpoint observations
    is ``missing_endpoint``. Without ``data_as_of`` the data end is inferred
    from the supplied outcome bars (a weaker assumption, clearly labelled in
    the reason) for synthetic callers. Unknown calendar coverage is
    ``unavailable``; all these stay explicit records and are never zero
    returns or dropped rows. The forward return needs both the execution price
    and the endpoint close; without an execution the label still reports the
    endpoint.
    """
    endpoint_date, reason = session_after(schedule, entry_session, horizon)
    if endpoint_date is None:
        return EndpointLabel(
            horizon, None, ENDPOINT_UNAVAILABLE, None, None, reason, None
        )
    available_at = _session_close_datetime(schedule, endpoint_date)
    if data_as_of is not None:
        if _ny(data_as_of) < available_at:
            return EndpointLabel(
                horizon,
                endpoint_date,
                ENDPOINT_IMMATURE,
                None,
                None,
                "the endpoint session has not closed by the dataset as-of",
                available_at,
            )
        close = _endpoint_close(
            outcome_bars.get(endpoint_date, ()), endpoint_date, schedule
        )
        if close is None:
            return EndpointLabel(
                horizon,
                endpoint_date,
                ENDPOINT_MISSING,
                None,
                None,
                "endpoint session bars are missing or incomplete after the as-of",
                available_at,
            )
        forward_return = (
            close / execution_price - 1.0 if execution_price is not None else None
        )
        return EndpointLabel(
            horizon,
            endpoint_date,
            ENDPOINT_COMPLETE,
            close,
            forward_return,
            "ok",
            available_at,
        )
    if not outcome_bars:
        return EndpointLabel(
            horizon,
            endpoint_date,
            ENDPOINT_MISSING,
            None,
            None,
            "no outcome bars were supplied; data end inferred from supplied bars",
            available_at,
        )
    data_end = max(outcome_bars)
    if endpoint_date > data_end:
        return EndpointLabel(
            horizon,
            endpoint_date,
            ENDPOINT_IMMATURE,
            None,
            None,
            "the horizon lies beyond the supplied outcome bars; data end "
            "inferred from supplied bars",
            available_at,
        )
    close = _endpoint_close(
        outcome_bars.get(endpoint_date, ()), endpoint_date, schedule
    )
    if close is None:
        return EndpointLabel(
            horizon,
            endpoint_date,
            ENDPOINT_MISSING,
            None,
            None,
            "endpoint session bars are missing or incomplete",
            available_at,
        )
    forward_return = (
        close / execution_price - 1.0 if execution_price is not None else None
    )
    return EndpointLabel(
        horizon,
        endpoint_date,
        ENDPOINT_COMPLETE,
        close,
        forward_return,
        "ok",
        available_at,
    )


# The ordered post-entry bars from the execution bar through the endpoint.
def _post_entry_bars(
    *,
    schedule: SessionSchedule,
    entry_bars: Sequence[Bar],
    outcome_bars: Mapping[date, Sequence[Bar]],
    entry_session: date,
    endpoint_date: date,
    execution_time: datetime,
) -> list[Bar] | None:
    """Return the contiguous post-entry bars through the endpoint, or None.

    Starts at the execution bar (whose open is the entry price) in the entry
    session and runs through the endpoint session's closing bar. Every session
    in that range must have complete bars on the schedule; any gap returns None
    so the excursion is unavailable rather than an extreme over a subset.
    """
    collected: list[Bar] = []
    day = entry_session
    while True:
        if not schedule.is_session(day):
            day = day + timedelta(days=1)
            if day > endpoint_date:
                break
            continue
        source = entry_bars if day == entry_session else outcome_bars.get(day, ())
        completed = _validated_complete(source, day, schedule)
        if completed is None:
            return None
        if day == entry_session:
            start_index = next(
                (i for i, b in enumerate(completed) if _ny(b.start) == execution_time),
                None,
            )
            if start_index is None:
                return None
            collected.extend(completed[start_index:])
        else:
            collected.extend(completed)
        if day == endpoint_date:
            break
        day = day + timedelta(days=1)
        if day > endpoint_date:
            return None
    return collected


# The post-entry adverse and favorable excursions through the endpoint.
def excursion(
    *,
    schedule: SessionSchedule,
    entry_bars: Sequence[Bar],
    outcome_bars: Mapping[date, Sequence[Bar]],
    entry_session: date,
    execution_price: float,
    execution_time: datetime,
    endpoint_date: date,
) -> ExcursionLabel:
    """Return the post-entry adverse/favorable excursions, or unavailable.

    Uses only post-entry observations through the endpoint, never the entry
    day's pre-entry high/low. Missing coverage anywhere in that range makes the
    excursion unavailable rather than reporting an extreme over the observed
    subset.
    """
    if execution_price <= 0:
        return ExcursionLabel(
            EXCURSION_UNAVAILABLE, None, None, "invalid execution price"
        )
    post = _post_entry_bars(
        schedule=schedule,
        entry_bars=entry_bars,
        outcome_bars=outcome_bars,
        entry_session=entry_session,
        endpoint_date=endpoint_date,
        execution_time=execution_time,
    )
    if post is None:
        return ExcursionLabel(
            EXCURSION_UNAVAILABLE,
            None,
            None,
            "post-entry coverage through the endpoint is incomplete",
        )
    adverse = min(b.low for b in post) / execution_price - 1.0
    favorable = max(b.high for b in post) / execution_price - 1.0
    return ExcursionLabel(EXCURSION_AVAILABLE, adverse, favorable, "ok")


# One method's outcome from the replayed events.
def _method_outcome(
    *,
    method: str,
    replay: ReplayResult,
    entry_bars: Sequence[Bar],
    outcome_bars: Mapping[date, Sequence[Bar]],
    schedule: SessionSchedule,
    primary: int,
    secondary: int,
    data_as_of: datetime | None,
) -> OutcomeRecord:
    """Return the execution, endpoint labels and excursion for one method."""
    event = replay.events.get(method)
    if event is None:
        no_event = ExecutionProxy(
            method, EXECUTION_UNKNOWN, None, None, "no entry event recorded"
        )
        return OutcomeRecord(
            method=method,
            symbol=replay.symbol,
            session=replay.session,
            price_basis=replay.price_basis,
            mode=replay.mode,
            event=None,
            execution=no_event,
            primary=EndpointLabel(
                primary, None, ENDPOINT_NO_EVENT, None, None, "no entry event"
            ),
            secondary=EndpointLabel(
                secondary, None, ENDPOINT_NO_EVENT, None, None, "no entry event"
            ),
            excursion=ExcursionLabel(
                EXCURSION_UNAVAILABLE, None, None, "no entry event"
            ),
        )
    execution = execution_proxy(entry_bars, event)
    price = execution.price
    when = execution.time
    primary_label = endpoint_label(
        schedule=schedule,
        outcome_bars=outcome_bars,
        entry_session=replay.session,
        horizon=primary,
        execution_price=price,
        data_as_of=data_as_of,
    )
    secondary_label = endpoint_label(
        schedule=schedule,
        outcome_bars=outcome_bars,
        entry_session=replay.session,
        horizon=secondary,
        execution_price=price,
        data_as_of=data_as_of,
    )
    if (
        execution.status != EXECUTED
        or primary_label.status != ENDPOINT_COMPLETE
        or primary_label.endpoint_date is None
        or price is None
        or when is None
    ):
        excursion_label = ExcursionLabel(
            EXCURSION_UNAVAILABLE,
            None,
            None,
            "no executed entry with a complete endpoint",
        )
    else:
        excursion_label = excursion(
            schedule=schedule,
            entry_bars=entry_bars,
            outcome_bars=outcome_bars,
            entry_session=replay.session,
            execution_price=price,
            execution_time=when,
            endpoint_date=primary_label.endpoint_date,
        )
    return OutcomeRecord(
        method=method,
        symbol=replay.symbol,
        session=replay.session,
        price_basis=replay.price_basis,
        mode=replay.mode,
        event=event,
        execution=execution,
        primary=primary_label,
        secondary=secondary_label,
        excursion=excursion_label,
    )


# Replay one session and compute both methods' outcomes.
def replay_session_outcome(
    *,
    symbol: str,
    session: date,
    bars: Sequence[Bar],
    history: Sequence[DailyRow],
    price_basis: str,
    eligibility_timeline: Sequence[Eligibility],
    schedule: SessionSchedule,
    mode: str,
    outcome_bars: Mapping[date, Sequence[Bar]],
    primary: int = PRIMARY_HORIZON,
    secondary: int = SECONDARY_HORIZON,
    data_as_of: datetime | None = None,
) -> SessionOutcome:
    """Replay one full-session day and produce both methods' outcome records.

    ``outcome_bars`` must supply the entry session and every subsequent session
    through the data end; endpoint and excursion labels read from it. Both
    methods share the identical replayed observations, execution proxy rule,
    outcome horizons and excursion coverage. The outcome horizons are fixed at
    20 (primary) and 5 (secondary) exactly as the protocol defines them; any
    other supplied value is rejected rather than silently relabelling a
    different-session result as a 20/5 outcome. An explicit ``data_as_of`` is
    the dataset's observation instant: a label whose endpoint close lies after
    it is ``immature`` and a date whose close has passed without endpoint
    observations is ``missing_endpoint``. The root historical runner must
    supply it; synthetic callers may omit it, which infers the data end from
    ``outcome_bars`` (a weaker assumption, labelled in the label's reason).
    """
    if primary != PRIMARY_HORIZON or secondary != SECONDARY_HORIZON:
        raise ValueError(
            "outcome horizons are fixed at 20 and 5; a different horizon "
            "cannot be relabelled as a 20/5 outcome"
        )
    if (
        data_as_of is not None
        and schedule.kind(session) is SessionKind.FULL
        and _ny(data_as_of) < _session_close_datetime(schedule, session)
    ):
        raise ValueError("the entry session must have closed by data_as_of")
    replay = replay_session(
        symbol=symbol,
        session=session,
        bars=bars,
        history=history,
        price_basis=price_basis,
        eligibility_timeline=eligibility_timeline,
        schedule=schedule,
        mode=mode,
    )
    incumbent = _method_outcome(
        method=INCUMBENT,
        replay=replay,
        entry_bars=bars,
        outcome_bars=outcome_bars,
        schedule=schedule,
        primary=primary,
        secondary=secondary,
        data_as_of=data_as_of,
    )
    candidate = _method_outcome(
        method=CANDIDATE,
        replay=replay,
        entry_bars=bars,
        outcome_bars=outcome_bars,
        schedule=schedule,
        primary=primary,
        secondary=secondary,
        data_as_of=data_as_of,
    )
    return SessionOutcome(
        symbol=symbol,
        session=session,
        price_basis=replay.price_basis,
        mode=replay.mode,
        replay=replay,
        incumbent=incumbent,
        candidate=candidate,
    )


# The mean of a list of forward returns, or None when empty.
def _mean(values: Sequence[float]) -> float | None:
    """Return the arithmetic mean of finite values, or None when empty."""
    if not values:
        return None
    return sum(values) / len(values)


# The horizon-specific forward return of an outcome record.
def _forward(outcome: OutcomeRecord, horizon: int) -> float | None:
    """Return the outcome's forward return at the given horizon."""
    label = outcome.primary if horizon == PRIMARY_HORIZON else outcome.secondary
    return label.forward_return if label.status == ENDPOINT_COMPLETE else None


# Whether an outcome is a complete, executed entry at a horizon.
def _entered_complete(outcome: OutcomeRecord, horizon: int) -> bool:
    """Return whether the method entered, executed and has a complete label."""
    if outcome.event is None or outcome.execution.status != EXECUTED:
        return False
    label = outcome.primary if horizon == PRIMARY_HORIZON else outcome.secondary
    return label.status == ENDPOINT_COMPLETE and label.forward_return is not None


# The conditional return over complete labels for one method.
def _method_conditional(
    outcomes: Sequence[OutcomeRecord], horizon: int
) -> ConditionalReturn:
    """Return the mean forward return over a method's complete executed labels."""
    values = [
        value
        for value in (
            _forward(o, horizon) for o in outcomes if _entered_complete(o, horizon)
        )
        if value is not None
    ]
    return ConditionalReturn(horizon, len(values), _mean(values))


# The paired conditional returns over sessions where both methods entered.
def _paired_conditional(
    sessions: Sequence[SessionOutcome],
    method: str,
    horizon: int,
) -> ConditionalReturn:
    """Return the mean forward return for ``method`` where both entered complete."""
    values = [
        value
        for value in (
            _forward(getattr(s, method), horizon)
            for s in sessions
            if (
                _entered_complete(getattr(s, INCUMBENT), horizon)
                and _entered_complete(getattr(s, CANDIDATE), horizon)
            )
        )
        if value is not None
    ]
    return ConditionalReturn(horizon, len(values), _mean(values))


# The per-session entry-count quadruple over the common opportunity set.
def _entry_counts(
    sessions: Sequence[SessionOutcome],
) -> tuple[int, int, int, int]:
    """Return (both, incumbent_only, candidate_only, neither) entry counts."""
    both = incumbent_only = candidate_only = neither = 0
    for s in sessions:
        inc = s.incumbent.event is not None
        cand = s.candidate.event is not None
        both += inc and cand
        incumbent_only += inc and not cand
        candidate_only += not inc and cand
        neither += not inc and not cand
    return both, incumbent_only, candidate_only, neither


# The total repeated readiness beyond each method's first event.
def _repeated_readiness(sessions: Sequence[SessionOutcome]) -> int:
    """Return how many ready observations repeat a method's first event."""
    repeated = 0
    for s in sessions:
        for method, count in s.replay.readiness_counts.items():
            repeated += max(0, count - (1 if method in s.replay.events else 0))
    return repeated


# The coverage counts: missing execution, missing outcome and immature labels.
def _coverage_counts(
    sessions: Sequence[SessionOutcome],
) -> tuple[int, int, int]:
    """Return (missing execution, missing outcome, immature) over entered events."""
    missing_execution = missing_outcome = immature = 0
    for s in sessions:
        for method in (INCUMBENT, CANDIDATE):
            outcome = getattr(s, method)
            if outcome.event is None:
                continue
            if outcome.execution.status != EXECUTED:
                missing_execution += 1
            elif outcome.primary.status == ENDPOINT_IMMATURE:
                immature += 1
            elif outcome.primary.status in (ENDPOINT_MISSING, ENDPOINT_UNAVAILABLE):
                missing_outcome += 1
    return missing_execution, missing_outcome, immature


# The paired incumbent-minus-candidate execution-price differences.
def _paired_price_diffs(sessions: Sequence[SessionOutcome]) -> list[float]:
    """Return execution-price differences over sessions where both executed."""
    diffs: list[float] = []
    for s in sessions:
        incumbent_price = s.incumbent.execution.price
        candidate_price = s.candidate.execution.price
        if (
            s.incumbent.execution.status == EXECUTED
            and s.candidate.execution.status == EXECUTED
            and incumbent_price is not None
            and candidate_price is not None
        ):
            diffs.append(incumbent_price - candidate_price)
    return diffs


# The paired relative entry-price improvement, comparable across stock scales.
def _paired_price_improvements(sessions: Sequence[SessionOutcome]) -> list[float]:
    """Return (incumbent_open - candidate_open) / incumbent_open when both execute.

    The relative units are comparable across stock price scales, unlike the
    absolute currency difference; no portfolio alpha is inferred from either.
    """
    improvements: list[float] = []
    for s in sessions:
        incumbent_price = s.incumbent.execution.price
        candidate_price = s.candidate.execution.price
        if (
            s.incumbent.execution.status == EXECUTED
            and s.candidate.execution.status == EXECUTED
            and incumbent_price is not None
            and candidate_price is not None
            and incumbent_price > 0
        ):
            improvements.append((incumbent_price - candidate_price) / incumbent_price)
    return improvements


# The aggregate summary over a set of replayed sessions.
def summarize(
    sessions: Sequence[SessionOutcome],
    *,
    mode: str,
    price_basis: str,
) -> ReplaySummary:
    """Return the audit summary over the replayed sessions.

    ``mode`` and ``price_basis`` are required and must match every session, so
    a run can never silently mix a diagnostic mode or an unknown price basis.
    A repeated symbol/session opportunity is rejected rather than inflating the
    common denominator. Counts use the common opportunity denominator; a
    session where the incumbent entered and the waiting candidate did not is a
    missed waiting opportunity reported with the incumbent's own primary and
    secondary outcomes, while candidate-only outcomes remain separate
    diagnostics. The paired entry-price difference is the absolute mean of
    incumbent-minus-candidate execution prices over sessions where both
    executed and is explicitly not comparable across stock scales; the paired
    entry-price improvement is the same comparison relative to the incumbent
    open. Neither is portfolio alpha.
    """
    _checked_mode(mode)
    _checked_basis(price_basis)
    seen: set[tuple[str, date]] = set()
    for s in sessions:
        if s.mode != mode:
            raise ValueError("summarize cannot mix modes across sessions")
        if s.price_basis != price_basis:
            raise ValueError("summarize cannot mix price bases across sessions")
        key = (s.symbol, s.session)
        if key in seen:
            raise ValueError(
                f"duplicate symbol/session opportunity {key[0]} "
                f"{key[1].isoformat()} would inflate the common denominator"
            )
        seen.add(key)

    session_count = len(sessions)
    both, incumbent_only, candidate_only, neither = _entry_counts(sessions)
    repeated = _repeated_readiness(sessions)
    missing_execution, missing_outcome, immature = _coverage_counts(sessions)
    diffs = _paired_price_diffs(sessions)
    improvements = _paired_price_improvements(sessions)

    incumbent_outcomes = [s.incumbent for s in sessions]
    candidate_outcomes = [s.candidate for s in sessions]
    incumbent_only_sessions = [
        s
        for s in sessions
        if s.incumbent.event is not None and s.candidate.event is None
    ]
    candidate_only_sessions = [
        s
        for s in sessions
        if s.candidate.event is not None and s.incumbent.event is None
    ]
    missed_incumbent_outcomes = [s.incumbent for s in incumbent_only_sessions]
    missed_candidate_outcomes = [s.candidate for s in candidate_only_sessions]

    return ReplaySummary(
        mode=mode,
        price_basis=price_basis,
        session_count=session_count,
        both_entries=both,
        incumbent_only=incumbent_only,
        candidate_only=candidate_only,
        neither_entries=neither,
        repeated_readiness=repeated,
        missing_execution_count=missing_execution,
        missing_outcome_count=missing_outcome,
        immature_outcome_count=immature,
        paired_entry_count=len(diffs),
        paired_entry_price_diff=_mean(diffs),
        paired_entry_price_improvement=_mean(improvements),
        incumbent_primary=_method_conditional(incumbent_outcomes, PRIMARY_HORIZON),
        incumbent_secondary=_method_conditional(incumbent_outcomes, SECONDARY_HORIZON),
        candidate_primary=_method_conditional(candidate_outcomes, PRIMARY_HORIZON),
        candidate_secondary=_method_conditional(candidate_outcomes, SECONDARY_HORIZON),
        paired_primary_incumbent=_paired_conditional(
            sessions, INCUMBENT, PRIMARY_HORIZON
        ),
        paired_primary_candidate=_paired_conditional(
            sessions, CANDIDATE, PRIMARY_HORIZON
        ),
        paired_secondary_incumbent=_paired_conditional(
            sessions, INCUMBENT, SECONDARY_HORIZON
        ),
        paired_secondary_candidate=_paired_conditional(
            sessions, CANDIDATE, SECONDARY_HORIZON
        ),
        missed_opportunity_count=len(incumbent_only_sessions),
        missed_opportunity_incumbent_primary=_method_conditional(
            missed_incumbent_outcomes, PRIMARY_HORIZON
        ),
        missed_opportunity_incumbent_secondary=_method_conditional(
            missed_incumbent_outcomes, SECONDARY_HORIZON
        ),
        missed_opportunity_candidate_primary=_method_conditional(
            missed_candidate_outcomes, PRIMARY_HORIZON
        ),
        missed_opportunity_candidate_secondary=_method_conditional(
            missed_candidate_outcomes, SECONDARY_HORIZON
        ),
        missed_opportunity_incumbent_context=(
            "on incumbent-only sessions the waiting candidate had no entry "
            "event, so the incumbent's own outcome is what waiting missed; "
            "candidate-only outcomes are separate diagnostics and are not a "
            "portfolio profitability claim"
        ),
    )
