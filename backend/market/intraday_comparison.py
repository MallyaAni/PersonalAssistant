"""Pure causal comparison between the incumbent price entry and the reclaim candidate.

Research-only, per `docs/research/intraday-comparison-protocol-2026-09-22.md`:
no broker, no orders, no portfolio, no disk writes, no historical scoring, no
fitting. This adapter turns one session's completed 15-minute bars, the daily
history, and one eligibility reading into two observations - the incumbent
price-entry component and the fixed-level reclaim candidate - plus a
deterministic per-method/symbol/session event ledger, so a later reviewed
replay runner can compare them on identical causal observations and dedupe
without any acceptance state of its own.

Both methods receive the same observed completed prefix, the same fixed levels
and the same eligibility. The incumbent is the existing price-entry component
reproduced: the dynamic 20-day band position from the existing ``bollinger_z``
over the last 19 prior adjusted daily closes followed by the current completed
intraday close converted from the explicitly declared price basis, gated by the existing
``entry_action`` grade/rejection/name-cap rule. The candidate runs the reviewed
reclaim engine (``intraday_entry.evaluate``) on the fixed daily levels with no
reimplementation of the engine. Full-day completeness never filters a prefix,
and a close-time signal never fabricates a next-session execution.

Scope: regular full sessions only (09:30-16:00 New York). Exchange-calendar
early closes and extended hours are not handled here; a known early-close
schedule is a separate input for the later replay runner.
"""

import hashlib
import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

import numpy as np

from backend.agents.trading.desk import paper
from backend.agents.trading.desk.entry import bollinger_z
from backend.market.intraday_entry import (
    CANDLE,
    ENTRY_READY,
    HISTORICAL,
    NEW_YORK,
    UNAVAILABLE,
    WAIT,
    Bar,
    EntrySignal,
    Levels,
    _completed_bars,
    evaluate,
    session_close_for,
)

RULE_NAME = "entry-comparison"
RULE_VERSION = "1"
# The most recent daily sessions strictly before the evaluated session that
# fix the candidate's band and the incumbent's window.
PRIOR_OBSERVATIONS = 20
# The incumbent's dynamic band window: the last 19 prior adjusted daily closes
# followed by the current completed intraday close times the adjustment ratio.
INCUMBENT_WINDOW = 19

INCUMBENT = "incumbent"
CANDIDATE = "candidate"
NOT_ELIGIBLE = "not_eligible"

# The scope is a design constant, surfaced so a replay runner cannot quietly
# treat an early close or an extended-hours read as a regular full session.
SCOPE = (
    "regular full sessions only (09:30-16:00 New York); exchange early closes "
    "and extended hours are out of scope for this adapter"
)


# One daily observation: its date, its raw close and its adjusted close.
@dataclass(frozen=True)
class DailyRow:
    """Daily date, dividend-unadjusted close and adjusted close supplied by caller.

    Historical sources may already split-adjust their close. The caller must
    establish compatibility with the intraday basis; this class cannot infer it.
    """

    date: date
    close: float
    adj_close: float


# When each common-gate input became known, so a later discovery cannot enable
# an earlier decision it was not available to.
@dataclass(frozen=True)
class Eligibility:
    """The common grade/rejection inputs and when each became known.

    ``grade`` is the daily grade the desk assigns (for example "A" or "A+"),
    ``rejecting_band`` whether the daily rejects its upper Bollinger band. A
    None input is unknown; an input whose ``*_available_at`` is after the
    observation time is treated as not yet known. Unknown or late inputs block
    a recommendation for both methods.
    """

    grade: str | None
    grade_available_at: datetime | None
    rejecting_band: bool | None
    rejecting_band_available_at: datetime | None


# The fixed daily band, the mean/std it came from and the adjustment ratio.
@dataclass(frozen=True)
class DailyContext:
    """The fixed levels plus the statistics and ratio that produced them."""

    levels: Levels
    mean: float
    std: float
    ratio: float
    observations: int


# One method's decision for one symbol/session at one observation time.
@dataclass(frozen=True)
class MethodObservation:
    """Everything a later replay runner needs about one method's decision."""

    method: str
    symbol: str
    session: date
    as_of: str | None
    readiness: bool
    state: str
    reason: str
    identity: str
    observed_close: float | None
    levels: Levels | None
    band_z: float | None
    trigger_time: str | None = None
    trigger_bar_start: str | None = None
    trigger_price: float | None = None
    price_basis: str | None = None


# The two observations for one session, with the shared context beside them.
@dataclass(frozen=True)
class Comparison:
    """The incumbent and candidate observations for one session at one time."""

    symbol: str
    session: date
    as_of: str | None
    levels: Levels | None
    observed_close: float | None
    band_z: float | None
    incumbent: MethodObservation
    candidate: MethodObservation
    price_basis: str | None = None


# One recorded first-eligible-entry event, keyed by method/symbol/session.
@dataclass(frozen=True)
class EventRecord:
    """The first eligible entry event for one method/symbol/session."""

    method: str
    symbol: str
    session: date
    observation_time: str | None
    identity: str
    state: str
    observed_close: float | None
    band_z: float | None
    trigger_time: str | None
    trigger_bar_start: str | None
    trigger_price: float | None
    levels: Levels | None
    price_basis: str | None = None


# Pure per-method/symbol/session event ledger, passed in and returned.
@dataclass(frozen=True)
class EventLedger:
    """The recorded first-eligible-entry events, keyed by (method, symbol, session)."""

    events: dict[tuple[str, str, date], EventRecord] = field(default_factory=dict)


# Coerce a timestamp to New York time; a naive timestamp is taken as New York.
def _ny(dt: datetime) -> datetime:
    """Return ``dt`` as a New York-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NEW_YORK)
    return dt.astimezone(NEW_YORK)


# A stable per-method/symbol/session identity, a dedupe key not an acceptance.
def _identity(method: str, symbol: str, session: date) -> str:
    """Return a hash of method, symbol, session and the rule, stable across reads."""
    blob = (
        f"{method}|{symbol}|{session.isoformat()}|{RULE_NAME}|{RULE_VERSION}"
        f"|{paper.ENTRY_BAND_Z}"
    )
    return hashlib.sha256(blob.encode()).hexdigest()


# The daily history strictly before the session, sorted and de-duplicated.
def _prior_history(history: list[DailyRow], session: date) -> list[DailyRow]:
    """Return the daily rows with date strictly before ``session``, sorted ascending."""
    return sorted((r for r in history if r.date < session), key=lambda r: r.date)


# Validate a single used daily row as a finite positive price on both scales.
def _valid_row(row: DailyRow) -> None:
    """Raise unless the row's raw and adjusted closes are finite positive prices."""
    if not (math.isfinite(row.close) and row.close > 0):
        raise ValueError(f"invalid raw close on {row.date.isoformat()}")
    if not (math.isfinite(row.adj_close) and row.adj_close > 0):
        raise ValueError(f"invalid adjusted close on {row.date.isoformat()}")


# Reject missing or unsupported units rather than infer them from price values.
def _checked_basis(price_basis: str | None) -> str:
    if price_basis not in ("raw", "adjusted"):
        raise ValueError("price basis must be explicitly raw or adjusted")
    return price_basis


# Map the most recent 20 prior sessions into the declared intraday price units.
def fixed_levels(
    history: list[DailyRow], session: date, *, price_basis: str = "raw"
) -> DailyContext:
    """Return the fixed daily levels and their statistics, or raise.

    Future daily observations (date >= ``session``) are removed before any
    value validation, so a corrupt future row can never change a prior setup.
    The most recent 20 strictly-prior rows must be unique dates with finite
    positive raw and adjusted closes, nonzero population standard deviation
    and a finite positive prior-session adjustment ratio; anything less is
    unavailable and raises ``ValueError``. Levels are supplied in raw prices:
    reference level (m + 2*s)/r, entry (m + 2*s*ENTRY_BAND_Z)/r, invalidation
    m/r, with m the mean, s the population standard deviation of the 20
    adjusted closes and r the latest prior adjusted close divided by its raw
    close. In adjusted mode the levels remain in adjusted units with no division.
    """
    basis = _checked_basis(price_basis)
    prior = _prior_history(history, session)
    if len(prior) < PRIOR_OBSERVATIONS:
        raise ValueError(f"need {PRIOR_OBSERVATIONS} prior sessions, have {len(prior)}")
    dates = [row.date for row in prior]
    if len(set(dates)) != len(dates):
        raise ValueError("duplicate dates in the prior daily history")
    window = prior[-PRIOR_OBSERVATIONS:]
    for row in window:
        _valid_row(row)
    adj = [row.adj_close for row in window]
    mean = sum(adj) / len(adj)
    std = math.sqrt(sum((x - mean) ** 2 for x in adj) / len(adj))
    if not (math.isfinite(std) and std > 0):
        raise ValueError("zero or invalid population standard deviation")
    latest = window[-1]
    ratio = latest.adj_close / latest.close
    if not (math.isfinite(ratio) and ratio > 0):
        raise ValueError("invalid prior-session adjustment ratio")
    two_sigma = 2.0 * std
    divisor = ratio if basis == "raw" else 1.0
    levels = Levels(
        level=(mean + two_sigma) / divisor,
        entry_level=(mean + two_sigma * paper.ENTRY_BAND_Z) / divisor,
        invalidation_level=mean / divisor,
    )
    return DailyContext(levels, mean, std, ratio, len(window))


# The incumbent's dynamic band position from the last 19 priors and the close.
def incumbent_band_z(
    history: list[DailyRow],
    session: date,
    observed_close: float | None,
    *,
    price_basis: str = "raw",
) -> float | None:
    """Return the incumbent's dynamic 20-day band position, or None.

    Calls the existing ``bollinger_z`` on the last 19 prior adjusted daily
    closes followed by the current completed intraday close times the latest
    prior-session adjustment ratio for raw bars; adjusted bars are used directly.
    Returns the last element, or None when
    the history, the ratio or the observed close cannot support a reading.
    """
    basis = _checked_basis(price_basis)
    prior = _prior_history(history, session)
    if len(prior) < INCUMBENT_WINDOW:
        return None
    latest = prior[-1]
    if not (math.isfinite(latest.close) and latest.close > 0):
        return None
    if not math.isfinite(latest.adj_close):
        return None
    ratio = latest.adj_close / latest.close
    if not (math.isfinite(ratio) and ratio > 0):
        return None
    if observed_close is None or not (
        math.isfinite(observed_close) and observed_close > 0
    ):
        return None
    tail = [row.adj_close for row in prior[-INCUMBENT_WINDOW:]]
    if any(not math.isfinite(v) or v <= 0 for v in tail):
        return None
    multiplier = ratio if basis == "raw" else 1.0
    series = np.array(tail + [observed_close * multiplier], dtype=float)
    z = bollinger_z(series.reshape(-1, 1))[-1, 0]
    return float(z) if math.isfinite(z) else None


# Whether the common eligibility inputs were all known by the decision time.
def eligibility_known(eligibility: Eligibility, as_of: datetime) -> tuple[bool, str]:
    """Return (True, "") when every eligibility input is known by ``as_of``.

    An unknown input or one that became known after ``as_of`` returns
    (False, reason) and blocks a recommendation for both methods; a later
    discovery is never retroactively enabled.
    """
    if eligibility.grade is None or eligibility.grade_available_at is None:
        return False, "grade is unknown"
    if _ny(eligibility.grade_available_at) > _ny(as_of):
        return False, "grade was learned after the observation time"
    if eligibility.rejecting_band is None or (
        eligibility.rejecting_band_available_at is None
    ):
        return False, "daily band rejection is unknown"
    if _ny(eligibility.rejecting_band_available_at) > _ny(as_of):
        return False, "daily band rejection was learned after the observation time"
    return True, ""


# The existing entry_action gate, reused, with its Action vocabulary.
def _entry_result(
    row: dict[str, bool], band: float, grade_live: str
) -> tuple[Any, bool]:
    """Return (entry_action result, whether it is a Buy) using the existing gate."""
    from backend.market.decision_view import Action, entry_action

    # The existing gate is untyped; direct parity tests pin this narrow boundary.
    result = entry_action(row, band, grade_live, 0.0)  # type: ignore[no-untyped-call]
    buy = result is not None and result[0] == Action.BUY
    return result, buy


# A plain-language reason for a non-Buy entry_action result.
def _entry_reason(result: Any) -> str:
    """Return the reason text for a non-Buy entry_action result."""
    if result is None:
        return "the common entry gate did not fire (band or grade eligibility)"
    return str(result[2])


# The shared common gate: grade, rejection and name cap via the existing rule.
def common_gate(eligibility: Eligibility, as_of: datetime) -> tuple[bool, str]:
    """Return (True, "") when the common grade/rejection/name-cap gate passes.

    Reuses the existing ``entry_action`` with its band-threshold axis held at
    the threshold so only the grade requirement, the rejecting-band flag and
    the name cap decide, and only when the inputs were known by ``as_of``.
    """
    ok, reason = eligibility_known(eligibility, as_of)
    if not ok:
        return False, reason
    row = {"rejecting_band": bool(eligibility.rejecting_band)}
    result, buy = _entry_result(row, paper.ENTRY_BAND_Z, eligibility.grade or "")
    if not buy:
        return False, _entry_reason(result)
    return True, ""


# Whether the completed prefix is fresh: the newest completed candle is present.
def _prefix_fresh(
    completed: list[Bar], as_of_ny: datetime | None, session_over: bool
) -> bool:
    """Return True unless a completed bar is missing before the observation time."""
    if not completed or as_of_ny is None or session_over:
        return True
    return not (completed[-1].start + 2 * CANDLE <= as_of_ny)


# The incumbent observation from the shared prefix, band and common gate.
def _incumbent_observation(
    symbol: str,
    session: date,
    as_of_ny: datetime | None,
    levels: Levels,
    observed_close: float | None,
    band_z: float | None,
    eligibility: Eligibility,
    decision_time: datetime,
    freshness_ok: bool,
    completed: list[Bar],
) -> MethodObservation:
    """Return the incumbent price-entry observation for this prefix and time."""
    as_of_text = as_of_ny.isoformat(timespec="seconds") if as_of_ny else None
    identity = _identity(INCUMBENT, symbol, session)
    if not completed:
        return MethodObservation(
            method=INCUMBENT,
            symbol=symbol,
            session=session,
            as_of=as_of_text,
            readiness=False,
            state=UNAVAILABLE,
            reason="no completed regular-session bar by the observation time",
            identity=identity,
            observed_close=observed_close,
            levels=levels,
            band_z=band_z,
        )
    if not freshness_ok:
        return MethodObservation(
            method=INCUMBENT,
            symbol=symbol,
            session=session,
            as_of=as_of_text,
            readiness=False,
            state=UNAVAILABLE,
            reason="newest completed bar missing; current readiness unavailable",
            identity=identity,
            observed_close=observed_close,
            levels=levels,
            band_z=band_z,
        )
    if band_z is None:
        return MethodObservation(
            method=INCUMBENT,
            symbol=symbol,
            session=session,
            as_of=as_of_text,
            readiness=False,
            state=UNAVAILABLE,
            reason="incumbent band cannot be computed",
            identity=identity,
            observed_close=observed_close,
            levels=levels,
            band_z=band_z,
        )
    ok, reason = eligibility_known(eligibility, decision_time)
    if not ok:
        return MethodObservation(
            method=INCUMBENT,
            symbol=symbol,
            session=session,
            as_of=as_of_text,
            readiness=False,
            state=NOT_ELIGIBLE,
            reason=reason,
            identity=identity,
            observed_close=observed_close,
            levels=levels,
            band_z=band_z,
        )
    row = {"rejecting_band": bool(eligibility.rejecting_band)}
    result, buy = _entry_result(row, band_z, eligibility.grade or "")
    if buy and result is not None:
        return MethodObservation(
            method=INCUMBENT,
            symbol=symbol,
            session=session,
            as_of=as_of_text,
            readiness=True,
            state=ENTRY_READY,
            reason=str(result[2]),
            identity=identity,
            observed_close=observed_close,
            levels=levels,
            band_z=band_z,
        )
    if band_z < paper.ENTRY_BAND_Z:
        return MethodObservation(
            method=INCUMBENT,
            symbol=symbol,
            session=session,
            as_of=as_of_text,
            readiness=False,
            state=WAIT,
            reason="incumbent close is below its band threshold",
            identity=identity,
            observed_close=observed_close,
            levels=levels,
            band_z=band_z,
        )
    return MethodObservation(
        method=INCUMBENT,
        symbol=symbol,
        session=session,
        as_of=as_of_text,
        readiness=False,
        state=NOT_ELIGIBLE,
        reason=_entry_reason(result),
        identity=identity,
        observed_close=observed_close,
        levels=levels,
        band_z=band_z,
    )


# The candidate observation from the engine and the shared common gate.
def _candidate_observation(
    symbol: str,
    session: date,
    as_of_ny: datetime | None,
    levels: Levels,
    observed_close: float | None,
    band_z: float | None,
    signal: EntrySignal,
    common_ok: bool,
    common_reason: str,
) -> MethodObservation:
    """Return the reclaim-candidate observation, matching the reviewed engine."""
    as_of_text = as_of_ny.isoformat(timespec="seconds") if as_of_ny else None
    if not common_ok:
        return MethodObservation(
            method=CANDIDATE,
            symbol=symbol,
            session=session,
            as_of=as_of_text,
            readiness=False,
            state=NOT_ELIGIBLE,
            reason=common_reason,
            identity=signal.identity,
            observed_close=observed_close,
            levels=levels,
            band_z=band_z,
            trigger_time=signal.trigger_time,
            trigger_bar_start=signal.trigger_bar_start,
            trigger_price=signal.trigger_price,
        )
    return MethodObservation(
        method=CANDIDATE,
        symbol=symbol,
        session=session,
        as_of=as_of_text,
        readiness=signal.recommendation,
        state=signal.state,
        reason=signal.reason,
        identity=signal.identity,
        observed_close=observed_close,
        levels=levels,
        band_z=band_z,
        trigger_time=signal.trigger_time,
        trigger_bar_start=signal.trigger_bar_start,
        trigger_price=signal.trigger_price,
    )


# Both methods when shared inputs cannot support any decision.
def _unavailable_comparison(
    symbol: str, session: date, as_of_ny: datetime | None, reason: str
) -> Comparison:
    """Return a Comparison with both methods unavailable for the given reason."""
    as_of_text = as_of_ny.isoformat(timespec="seconds") if as_of_ny else None
    incumbent = MethodObservation(
        method=INCUMBENT,
        symbol=symbol,
        session=session,
        as_of=as_of_text,
        readiness=False,
        state=UNAVAILABLE,
        reason=reason,
        identity=_identity(INCUMBENT, symbol, session),
        observed_close=None,
        levels=None,
        band_z=None,
    )
    candidate = MethodObservation(
        method=CANDIDATE,
        symbol=symbol,
        session=session,
        as_of=as_of_text,
        readiness=False,
        state=UNAVAILABLE,
        reason=reason,
        identity=_identity(CANDIDATE, symbol, session),
        observed_close=None,
        levels=None,
        band_z=None,
    )
    return Comparison(
        symbol=symbol,
        session=session,
        as_of=as_of_text,
        levels=None,
        observed_close=None,
        band_z=None,
        incumbent=incumbent,
        candidate=candidate,
    )


# Stamp units onto both observations and namespace identities against unit mixing.
def _with_basis(result: Comparison, basis: str) -> Comparison:
    incumbent = replace(
        result.incumbent,
        price_basis=basis,
        identity=f"{basis}:{result.incumbent.identity}",
    )
    candidate = replace(
        result.candidate,
        price_basis=basis,
        identity=f"{basis}:{result.candidate.identity}",
    )
    return replace(result, price_basis=basis, incumbent=incumbent, candidate=candidate)


# Compare both methods in declared price units with identical causal availability.
def compare(
    symbol: str,
    session: date,
    bars: list[Bar],
    history: list[DailyRow],
    eligibility: Eligibility,
    as_of: datetime | None = None,
    *,
    price_basis: str | None = None,
) -> Comparison:
    """Return the incumbent and candidate observations on identical inputs.

    The completed prefix, fixed levels and eligibility are shared by both
    methods. ``price_basis`` must explicitly declare raw or adjusted intraday
    prices; the caller remains responsible for truthful, consistent provenance.
    ``as_of`` (New York) decides which bars are complete; pass it for
    a live read and None to replay a closed session (every supplied bar is
    then complete and the session is treated as closed). An invalid daily
    context or an invalid/gapped completed prefix leaves both methods
    unavailable; it never recommends either method.
    """
    basis = _checked_basis(price_basis)
    as_of_ny = _ny(as_of) if as_of is not None else None
    decision_time = as_of_ny if as_of_ny is not None else session_close_for(session)
    try:
        context = fixed_levels(history, session, price_basis=basis)
    except ValueError as exc:
        return _with_basis(
            _unavailable_comparison(
                symbol, session, as_of_ny, f"daily context unavailable: {exc}"
            ),
            basis,
        )
    try:
        completed = _completed_bars(bars, session, as_of_ny)
    except ValueError as exc:
        return _with_basis(
            _unavailable_comparison(
                symbol, session, as_of_ny, f"invalid completed prefix: {exc}"
            ),
            basis,
        )
    observed_close = completed[-1].close if completed else None
    session_over = as_of_ny is not None and session_close_for(session) <= as_of_ny
    freshness_ok = _prefix_fresh(completed, as_of_ny, session_over)
    band_z = incumbent_band_z(history, session, observed_close, price_basis=basis)
    signal = evaluate(symbol, session, bars, context.levels, as_of_ny)
    common_ok, common_reason = common_gate(eligibility, decision_time)
    incumbent = _incumbent_observation(
        symbol,
        session,
        as_of_ny,
        context.levels,
        observed_close,
        band_z,
        eligibility,
        decision_time,
        freshness_ok,
        completed,
    )
    candidate = _candidate_observation(
        symbol,
        session,
        as_of_ny,
        context.levels,
        observed_close,
        band_z,
        signal,
        common_ok,
        common_reason,
    )
    if (as_of_ny is None or session_over) and incumbent.readiness:
        incumbent = replace(
            incumbent,
            readiness=False,
            state=HISTORICAL,
            reason="session is closed; observation is historical",
        )
    return _with_basis(
        Comparison(
            symbol=symbol,
            session=session,
            as_of=as_of_ny.isoformat(timespec="seconds") if as_of_ny else None,
            levels=context.levels,
            observed_close=observed_close,
            band_z=band_z,
            incumbent=incumbent,
            candidate=candidate,
        ),
        basis,
    )


# The deterministic per-method/symbol/session event reducer.
def record_event(
    ledger: EventLedger, observation: MethodObservation
) -> tuple[EventLedger, EventRecord | None, bool]:
    """Return (new ledger, event, whether it was newly recorded).

    Records only the first eligible entry per method/symbol/session. A
    repeated read returns the already-recorded event without a new one; a
    later invalidation never erases a recorded event; a new session is an
    independently eligible key. No disk is ever written.
    """
    key = (observation.method, observation.symbol, observation.session)
    existing = ledger.events.get(key)
    if existing is not None:
        if existing.price_basis != observation.price_basis:
            raise ValueError("cannot mix price basis in an event ledger")
        return ledger, existing, False
    if not observation.readiness:
        return ledger, None, False
    event = EventRecord(
        method=observation.method,
        symbol=observation.symbol,
        session=observation.session,
        observation_time=observation.as_of,
        identity=observation.identity,
        state=observation.state,
        observed_close=observation.observed_close,
        band_z=observation.band_z,
        trigger_time=observation.trigger_time,
        trigger_bar_start=observation.trigger_bar_start,
        trigger_price=observation.trigger_price,
        levels=observation.levels,
        price_basis=observation.price_basis,
    )
    return EventLedger(events={**ledger.events, key: event}), event, True
