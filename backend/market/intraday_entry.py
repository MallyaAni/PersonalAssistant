"""Isolated research-only 15-minute entry engine; no broker, no orders.

This module decides, from a session's *completed* 15-minute bars and an
externally supplied daily setup, when a pullback-and-retest of a level has
been reclaimed, and reports an entry state with its trigger and invalidation.
It is research-only: it never reads a portfolio, never places an order, and
is not wired into any production caller. The daily setup/levels come from the
existing strategy and are never refitted here.

The engine retains the ordered completed OHLCV bars, not just the daily
OHLC, and walks them causally. A bar counts only once its 15-minute window
has elapsed (start + 15 minutes at or before ``as_of``); a partial bar can
never trigger anything. The decision at any time is a pure function of the
completed prefix, so future bars can never change an earlier decision —
uncompleted bars are excluded *before* any validation, so a future bar that
is corrupt, duplicated or on another session date cannot disturb an earlier
decision it was not yet available to influence.

The one documented candidate rule (locked; see
``docs/research/intraday-entry-contract-2026-09-22.md``):

    Reclaim above a level after a pullback.

    - ``level``            the reference level the daily strategy supplies.
    - ``entry_level``      a completed bar must close at or above this to
                           trigger an entry (strictly above ``level``).
    - ``invalidation_level`` a completed bar closing at or below this
                           invalidates the setup (strictly below ``level``).

    The sequence is causal, read bar by bar:

    - **setup** (pullback/retest): a completed bar closes at or below
      ``level`` while the immediately preceding completed close was strictly
      above it. The level was being held from above and was broken. If that
      same bar's range touches both ``entry_level`` and
      ``invalidation_level`` it is ``ambiguous`` at once, and if it closes at
      or below ``invalidation_level`` the setup is ``invalidated``
      immediately — the next reclaim cannot resurrect a pullback that already
      closed through its invalidation.
    - **reclaim** (entry-ready): a later completed bar closes at or above
      ``entry_level``. Trigger time is the end of that bar's window (when the
      close that confirms it becomes knowable); trigger price its close. The
      trigger candle's start is kept separately as ``trigger_bar_start``.
    - **rejection / failed break** (invalidated): a later completed bar
      closes at or below ``invalidation_level``. The retest failed; the
      setup is invalidated. A completed invalidation *after* an entry also
      removes current readiness, while the entry event (identity, trigger
      time/price) is retained for replay.
    - **ambiguous**: a bar in the setup whose range touches both
      ``entry_level`` (high) and ``invalidation_level`` (low) leaves the
      intra-bar order of the reclaim and the rejection unknown. The engine
      reports ambiguity instead of inventing a winning fill.

    A setup resolves exactly once per session: entry-ready, invalidated,
    ambiguous and expired never resurrect (an entry followed by a completed
    invalidation becomes invalidated, not a new entry). An entry resolved by
    a session that is already closed — replayed later or read the next
    session — is reported as ``historical``: its identity and trigger are
    preserved for replay but it is not actionable. This is what stops
    repeated refreshes from becoming repeated recommendations - the signal's
    ``identity`` is stable for the same setup, and a caller records it plus
    its own consumption state to dedupe. The identity alone never records
    acceptance: it is a dedupe key, and callers still need to track what they
    have acted on.

States: ``unavailable`` (no usable input), ``wait`` (no setup formed),
``setup`` (retest underway), ``entry_ready`` (actionable signal),
``invalidated``, ``ambiguous``, ``historical`` (an entry resolved by an
already-closed session), and ``expired`` (a setup still unresolved at
session close). The completed prefix must be contiguous and unique on the
15-minute grid and start at the 09:30 opening bar: a gap or off-grid bar is
rejected because a missing bar can conceal an invalidation; out-of-order
bars are still sorted first. Corrupt bars (non-finite or envelope-breaking
prices, invalid volume) raise rather than guess; duplicate bar starts and
bars on another session date raise; bars outside the regular session window
are ignored. Session timestamps are New York wall-clock; a naive timestamp
is treated as New York local (``America/New_York``).
During the session an unresolved or entry-ready prefix must reach the latest
completed candle. If that observation is missing, readiness is unavailable;
the captured event and identity remain available for a later complete read.
"""

import hashlib
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

from backend.market import calendar

NEW_YORK = ZoneInfo("America/New_York")
SESSION_OPEN = day_time(9, 30)
# The regular close. A session's actual close comes from the published
# calendar (13:00 on an early-close day); this is the full-session clock
# that callers compare a schedule against, not the close of any given date.
SESSION_CLOSE = day_time(16, 0)
BAR_MINUTES = 15
CANDLE = timedelta(minutes=BAR_MINUTES)

RULE_NAME = "reclaim_above_level"
RULE_VERSION = "1"

UNAVAILABLE = "unavailable"
WAIT = "wait"
SETUP = "setup"
ENTRY_READY = "entry_ready"
INVALIDATED = "invalidated"
AMBIGUOUS = "ambiguous"
HISTORICAL = "historical"
EXPIRED = "expired"


# One completed 15-minute bar: time, OHLC and volume.
@dataclass(frozen=True)
class Bar:
    """One 15-minute bar.

    ``start`` is the bar's New York wall-clock start. A naive ``start`` is
    taken as New York local time (``America/New_York``); an aware one is
    converted to New York. Timestamps are thus unambiguous: they always mean
    the New York session's clock, never UTC or the host's timezone.
    """

    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


# The daily setup/levels the existing strategy supplies for the rule.
@dataclass(frozen=True)
class Levels:
    """The daily setup/levels supplied by the existing strategy, never fitted."""

    level: float
    entry_level: float
    invalidation_level: float


# The engine's decision for one symbol/session at one time.
@dataclass(frozen=True)
class EntrySignal:
    """The engine's decision for one symbol/session at one time."""

    symbol: str
    session: date
    rule: str
    state: str
    identity: str
    recommendation: bool
    reason: str
    setup_bar: str | None
    trigger_time: str | None
    trigger_bar_start: str | None
    trigger_price: float | None
    invalidation_time: str | None
    invalidation_bar_start: str | None
    invalidation_price: float | None
    ambiguity: bool
    bar_count: int
    session_open: float | None
    session_high: float | None
    session_low: float | None
    session_close: float | None
    session_volume: float | None
    bar_weighted_typical: float | None
    as_of: str | None


# Coerce a timestamp to New York time; a naive timestamp is taken as New York.
def _ny(dt: datetime) -> datetime:
    """Return ``dt`` as a New York-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NEW_YORK)
    return dt.astimezone(NEW_YORK)


# Reject supplied levels that do not form a usable reclaim band.
def _validate_levels(levels: Levels) -> None:
    """Raise unless invalidation < level < entry and all levels are finite prices."""
    values = (levels.level, levels.entry_level, levels.invalidation_level)
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("levels must be finite positive prices")
    if not levels.invalidation_level < levels.level < levels.entry_level:
        raise ValueError(
            "the reclaim rule needs invalidation_level < level < entry_level"
        )


# Reject a bar whose OHLCV cannot be a real print.
def _valid_bar(bar: Bar) -> None:
    """Raise when a bar's OHLCV is corrupt rather than deciding on it."""
    prices = (bar.open, bar.high, bar.low, bar.close)
    if any(not math.isfinite(v) or v <= 0 for v in prices):
        raise ValueError(f"non-finite or non-positive price in bar at {bar.start}")
    if not math.isfinite(bar.volume) or bar.volume < 0:
        raise ValueError(f"invalid volume in bar at {bar.start}")
    # open and close must lie inside the reported high/low envelope.
    if not bar.low <= bar.open <= bar.high:
        raise ValueError(f"open outside high/low in bar at {bar.start}")
    if not bar.low <= bar.close <= bar.high:
        raise ValueError(f"close outside high/low in bar at {bar.start}")


# The session's regular-window bars, ordered, deduplicated, and completed.
def _completed_bars(
    bars: list[Bar],
    session: date,
    as_of: datetime | None,
    close: day_time | None = None,
) -> list[Bar]:
    """Return the sorted, duplicate-checked, contiguous completed bars.

    Uncompleted bars (start + 15 min after ``as_of``) and bars whose start is
    outside the session's regular clock window (09:30 to its close: 16:00, or
    13:00 on a published early close) are dropped *first*, before any
    validation, so a future bar cannot disturb an earlier decision it was not
    yet available to influence. The surviving completed prefix is then checked
    structurally (see ``_validate_completed``): duplicate starts and corrupt
    bars raise, a completed bar on another date raises rather than mix days,
    and the prefix must be contiguous on the 15-minute grid starting at the
    09:30 opening bar — a gap or missing opening bar could conceal an
    invalidation and is rejected rather than bridged. With ``as_of`` None every
    supplied in-window bar is treated as completed (a closed-session replay).
    ``close`` overrides the published calendar for a caller that carries its
    own session schedule.
    """
    close = close or calendar.session_close(session)
    eligible: list[Bar] = []
    for bar in bars:
        start = _ny(bar.start)
        if as_of is not None and start + CANDLE > as_of:
            continue  # window not elapsed; cannot have influenced any decision
        if not SESSION_OPEN <= start.time() < close:
            continue  # extended-hours bar; the regular session is the contract
        eligible.append(Bar(start, bar.open, bar.high, bar.low, bar.close, bar.volume))
    eligible.sort(key=lambda b: b.start)
    session_open = datetime.combine(session, SESSION_OPEN, NEW_YORK)
    _validate_completed(eligible, session, session_open)
    return eligible


# Reject a completed prefix that could conceal a decision or mix sessions.
def _validate_completed(
    eligible: list[Bar], session: date, session_open: datetime
) -> None:
    """Raise unless the completed prefix is unique, valid, on-grid and contiguous."""
    _validate_unique_and_clean(eligible, session)
    _validate_regular(eligible, session_open)


# Reject duplicate starts and any corrupt or other-date completed bar.
def _validate_unique_and_clean(eligible: list[Bar], session: date) -> None:
    """Raise on a duplicate start or a corrupt/other-date bar in the prefix."""
    for i in range(1, len(eligible)):
        if eligible[i - 1].start == eligible[i].start:
            raise ValueError(f"duplicate 15-minute bar start {eligible[i].start}")
    for bar in eligible:
        _valid_bar(bar)
        if bar.start.date() != session:
            raise ValueError(
                f"bar at {bar.start.isoformat()} belongs to another session date"
            )


# Reject a completed prefix that is off-grid, opening-less or gapped.
def _validate_regular(eligible: list[Bar], session_open: datetime) -> None:
    """Raise unless the prefix is contiguous on the 15-minute grid from 09:30."""
    if not eligible:
        return
    for bar in eligible:
        if (bar.start - session_open) % CANDLE != timedelta(0):
            raise ValueError(
                f"bar at {bar.start.isoformat()} is off the 15-minute grid"
            )
    if eligible[0].start != session_open:
        raise ValueError("the session's opening bar (09:30) is missing")
    for i in range(1, len(eligible)):
        if eligible[i - 1].start + CANDLE != eligible[i].start:
            raise ValueError(
                "gap between completed bars at "
                f"{eligible[i - 1].start.isoformat()} and "
                f"{eligible[i].start.isoformat()}"
            )


# A stable per-setup identity so repeated refreshes are recognised as the same.
def _identity(
    symbol: str, session: date, levels: Levels, setup_start: datetime | None
) -> str:
    """Return a hash of symbol, session, rule, levels and the setup's first bar."""
    setup = setup_start.isoformat() if setup_start is not None else "no_setup"
    blob = (
        f"{symbol}|{session.isoformat()}|{RULE_NAME}|{RULE_VERSION}"
        f"|{levels.invalidation_level!r}|{levels.level!r}|{levels.entry_level!r}|{setup}"
    )
    return hashlib.sha256(blob.encode()).hexdigest()


# The engine's resolved decision plus the full completed-session context.
@dataclass(frozen=True)
class _Walk:
    """The causal resolution plus session aggregates over every completed bar."""

    state: str
    setup_start: datetime | None
    trigger_time: datetime | None
    trigger_bar_start: datetime | None
    trigger_price: float | None
    invalidation_time: datetime | None
    invalidation_bar_start: datetime | None
    ambiguity: bool
    bar_count: int
    session_open: float | None
    session_high: float | None
    session_low: float | None
    session_close: float | None
    session_volume: float
    bar_weighted_typical: float | None


# How a bar in an open setup resolves it, if at all.
def _resolve(bar: Bar, levels: Levels) -> str | None:
    """Return the state a bar resolves an open setup to, or None if unresolved.

    Ambiguity is decided first so an intra-bar reclaim-and-rejection (range
    touching both the entry and the invalidation) is never assumed a fill.
    """
    if bar.high >= levels.entry_level and bar.low <= levels.invalidation_level:
        return AMBIGUOUS
    if bar.close >= levels.entry_level:
        return ENTRY_READY
    if bar.close <= levels.invalidation_level:
        return INVALIDATED
    return None


# Whether a completed bar forms the pullback setup against the prior close.
def _forms_setup(bar: Bar, prev_close: float | None, levels: Levels) -> bool:
    """Return True when a close breaks the level from a prior close above it."""
    return (
        prev_close is not None
        and prev_close > levels.level
        and bar.close <= levels.level
    )


# The session's bar-weighted typical price, an OHLCV proxy, never traded VWAP.
def _typical_price(typical_sum: float, volume_sum: float) -> float | None:
    """Return the volume-weighted mean of (H+L+C)/3, or None with no volume."""
    return typical_sum / volume_sum if volume_sum > 0 else None


# Walk the completed bars causally and return the resolved state and captures.
def _walk(completed: list[Bar], levels: Levels) -> _Walk:
    """Walk the completed prefix causally and accumulate the session context.

    The state resolution follows the rule; once resolved, later completed
    bars can only remove entry readiness (a completed invalidation), never
    change an earlier resolution back, and never resurrect an invalidated,
    ambiguous or expired setup. Session aggregates (open, high, low, latest
    close, volume, bar-weighted typical price) continue over *all* completed
    observations, including after the trigger, so the daily context keeps
    evolving rather than freezing at the entry bar.
    """
    state = WAIT
    prev_close: float | None = None
    setup_start: datetime | None = None
    trigger_time: datetime | None = None
    trigger_bar_start: datetime | None = None
    trigger_price: float | None = None
    invalidation_time: datetime | None = None
    invalidation_bar_start: datetime | None = None
    ambiguity = False
    bar_count = 0
    session_high: float | None = None
    session_low: float | None = None
    session_volume = 0.0
    typical_sum = 0.0
    volume_sum = 0.0
    session_open = completed[0].open if completed else None
    session_close = completed[0].close if completed else None

    for bar in completed:
        bar_count += 1
        session_high = bar.high if session_high is None else max(session_high, bar.high)
        session_low = bar.low if session_low is None else min(session_low, bar.low)
        session_volume += bar.volume
        typical_sum += ((bar.high + bar.low + bar.close) / 3.0) * bar.volume
        volume_sum += bar.volume
        session_close = bar.close

        if state in (INVALIDATED, AMBIGUOUS):
            continue
        if state == ENTRY_READY:
            # A later completed close through invalidation removes readiness,
            # but the entry event (identity and trigger) is retained.
            if bar.close <= levels.invalidation_level:
                state = INVALIDATED
                invalidation_time = bar.start + CANDLE
                invalidation_bar_start = bar.start
            prev_close = bar.close
            continue
        if state == WAIT and not _forms_setup(bar, prev_close, levels):
            prev_close = bar.close
            continue
        if state == WAIT:
            state = SETUP
            setup_start = bar.start
        # In a setup, the current bar may resolve it at once (including the
        # setup bar itself: a close already through invalidation must
        # invalidate immediately rather than wait for the next reclaim).
        resolved = _resolve(bar, levels)
        if resolved == AMBIGUOUS:
            state = AMBIGUOUS
            ambiguity = True
            trigger_time = bar.start + CANDLE
            trigger_bar_start = bar.start
        elif resolved == ENTRY_READY:
            state = ENTRY_READY
            trigger_time = bar.start + CANDLE
            trigger_bar_start = bar.start
            trigger_price = bar.close
        elif resolved == INVALIDATED:
            state = INVALIDATED
            invalidation_time = bar.start + CANDLE
            invalidation_bar_start = bar.start
        prev_close = bar.close

    return _Walk(
        state,
        setup_start,
        trigger_time,
        trigger_bar_start,
        trigger_price,
        invalidation_time,
        invalidation_bar_start,
        ambiguity,
        bar_count,
        session_open,
        session_high,
        session_low,
        session_close,
        session_volume,
        _typical_price(typical_sum, volume_sum),
    )


# Explain the resolved state in the causal vocabulary of the rule.
def _reason(
    state: str,
    session_over: bool,
    levels: Levels,
    setup_start: datetime | None,
    trigger_bar_start: datetime | None,
    trigger_time: datetime | None,
    trigger_price: float | None,
    invalidation_bar_start: datetime | None,
    invalidation_time: datetime | None,
) -> str:
    """Return a plain-language summary of the decision for the signal."""
    if state == UNAVAILABLE:
        return (
            "latest completed 15-minute bar is missing; current readiness unavailable"
        )
    if state == WAIT:
        return (
            "no completed bar closed above the level and then broke it, "
            "so no pullback setup formed"
            + (" by session close" if session_over else "")
        )
    if state == SETUP:
        assert setup_start is not None
        return (
            "pullback underway after a close broke the level at "
            f"{setup_start.isoformat()}; awaiting a close at/above "
            f"{levels.entry_level:.4f} or at/below "
            f"{levels.invalidation_level:.4f}"
        )
    if state == EXPIRED:
        return "setup expired unresolved at session close; no entry triggered"
    if state == ENTRY_READY:
        assert trigger_bar_start is not None
        assert trigger_time is not None
        assert trigger_price is not None
        return (
            "retest reclaimed: completed bar starting at "
            f"{trigger_bar_start.isoformat()} closed {trigger_price:.4f} at/above "
            f"entry {levels.entry_level:.4f}, known at {trigger_time.isoformat()}"
        )
    if state == HISTORICAL:
        assert trigger_bar_start is not None
        assert trigger_price is not None
        return (
            "entry was reclaimed at "
            f"{trigger_bar_start.isoformat()} (close {trigger_price:.4f}), but "
            "the session is already closed: the event is recorded, not actionable"
        )
    if state == INVALIDATED:
        assert invalidation_bar_start is not None
        return (
            "rejection / failed break: completed bar starting at "
            f"{invalidation_bar_start.isoformat()} closed at/below invalidation "
            f"{levels.invalidation_level:.4f}"
        )
    assert trigger_bar_start is not None
    return (
        "bar starting at "
        f"{trigger_bar_start.isoformat()} touched both entry "
        f"{levels.entry_level:.4f} and invalidation "
        f"{levels.invalidation_level:.4f}; intra-bar order unknown, "
        "no fill assumed"
    )


# Decide one symbol/session from its completed 15-minute bars.
def evaluate(
    symbol: str,
    session: date,
    bars: list[Bar],
    levels: Levels,
    as_of: datetime | None = None,
) -> EntrySignal:
    """Return the entry decision from the completed prefix, causally.

    ``as_of`` (New York) decides which bars are complete; bars whose window
    has not elapsed are ignored, so a partial bar can never trigger. Pass
    ``as_of`` for live refreshes and None to replay a closed session (every
    supplied bar is then complete and the session is treated as closed).
    """
    if not symbol:
        raise ValueError("a symbol is required")
    _validate_levels(levels)
    rule = f"{RULE_NAME}/{RULE_VERSION}"
    if as_of is None:
        completed = _completed_bars(bars, session, None)
        session_over = True
        as_of_value = None
    else:
        as_of_value = _ny(as_of)
        completed = _completed_bars(bars, session, as_of_value)
        session_over = session_close_for(session) <= as_of_value

    if not completed:
        return EntrySignal(
            symbol=symbol,
            session=session,
            rule=rule,
            state=UNAVAILABLE,
            identity=_identity(symbol, session, levels, None),
            recommendation=False,
            reason="no completed regular-session bar by as_of",
            setup_bar=None,
            trigger_time=None,
            trigger_bar_start=None,
            trigger_price=None,
            invalidation_time=None,
            invalidation_bar_start=None,
            invalidation_price=None,
            ambiguity=False,
            bar_count=0,
            session_open=None,
            session_high=None,
            session_low=None,
            session_close=None,
            session_volume=None,
            bar_weighted_typical=None,
            as_of=as_of_value.isoformat(timespec="seconds") if as_of_value else None,
        )

    walk = _walk(completed, levels)

    if walk.state == SETUP and session_over:
        walk = replace(walk, state=EXPIRED)
    elif walk.state == ENTRY_READY and session_over:
        # The entry event is historical: recorded for replay but not actionable.
        walk = replace(walk, state=HISTORICAL)
    elif (
        not session_over
        and as_of_value is not None
        and walk.state in (WAIT, SETUP, ENTRY_READY)
        and completed[-1].start + 2 * CANDLE <= as_of_value
    ):
        # An absent newest completed bar can conceal a failed setup. Keep the
        # historical trigger, but never carry its readiness across a feed gap.
        walk = replace(walk, state=UNAVAILABLE)

    return EntrySignal(
        symbol=symbol,
        session=session,
        rule=rule,
        state=walk.state,
        identity=_identity(symbol, session, levels, walk.setup_start),
        recommendation=walk.state == ENTRY_READY,
        reason=_reason(
            walk.state,
            session_over,
            levels,
            walk.setup_start,
            walk.trigger_bar_start,
            walk.trigger_time,
            walk.trigger_price,
            walk.invalidation_bar_start,
            walk.invalidation_time,
        ),
        setup_bar=walk.setup_start.isoformat() if walk.setup_start else None,
        trigger_time=walk.trigger_time.isoformat() if walk.trigger_time else None,
        trigger_bar_start=(
            walk.trigger_bar_start.isoformat() if walk.trigger_bar_start else None
        ),
        trigger_price=walk.trigger_price,
        invalidation_time=(
            walk.invalidation_time.isoformat() if walk.invalidation_time else None
        ),
        invalidation_bar_start=(
            walk.invalidation_bar_start.isoformat()
            if walk.invalidation_bar_start
            else None
        ),
        invalidation_price=(
            levels.invalidation_level if walk.state == INVALIDATED else None
        ),
        ambiguity=walk.ambiguity,
        bar_count=walk.bar_count,
        session_open=walk.session_open,
        session_high=walk.session_high,
        session_low=walk.session_low,
        session_close=walk.session_close,
        session_volume=walk.session_volume,
        bar_weighted_typical=walk.bar_weighted_typical,
        as_of=as_of_value.isoformat(timespec="seconds") if as_of_value else None,
    )


# The New York session's close on a given date, from the published calendar:
# 16:00, or 13:00 on an early-close day, so the day after Thanksgiving is
# reported closed after 13:00 rather than open until a 16:00 that never comes.
def session_close_for(session: date) -> datetime:
    """Return the session's scheduled New York close on ``session``."""
    return datetime.combine(session, calendar.session_close(session), NEW_YORK)


# A New York datetime for a session's opening, for callers that need it.
def session_open_for(session: date) -> datetime:
    """Return the session's 09:30 New York open on ``session``."""
    return datetime.combine(session, SESSION_OPEN, NEW_YORK)
