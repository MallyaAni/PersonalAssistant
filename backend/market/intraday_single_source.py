"""Pure single-source price-component diagnostic over supplied Alpaca pages.

Research-only, per ``docs/research/intraday-comparison-protocol-2026-09-22.md``
and the input audit: no broker, no orders, no portfolio, no disk writes, no
model calls and no scoring of real data in this session. This module is a small
PURE diagnostic boundary that turns one supplied JSON snapshot of fresh Alpaca
``15Min`` IEX ``adjustment=all`` response pages into a causal price-component
replay cohort. It is deliberately named ``single_source_price_component``: daily
reference closes are derived ONLY from those SAME regular-hours bars, so Yahoo
and old cached intraday units are never mixed, and the output is a price-only
component diagnostic, never an exact live reconstruction or a portfolio P&L.

The caller (root) supplies the snapshot and the exchange calendar. The module
validates the snapshot metadata, the exact unique symbol set, every page's
status/hash and the pagination chain, then parses the raw payload bars itself
(``alpaca.parse_bars_page`` is not used because it silently drops malformed
rows). A naive or invalid timestamp has unplaceable causality and makes that
sample unavailable; numeric invalids become ``NaN`` bars that are retained for
causal validation. Row order and duplicates are preserved and missing bars are
never forward-filled.

For every requested symbol/full-session opportunity the module derives one
``DailyRow(close=adj_close=last regular close)`` from each COMPLETE, unique,
correctly gridded, valid regular session (26 bars on a full session, 14 on an
early close), requires exactly the preceding 20 exchange sessions via the
reviewed ``prior_daily`` gate, then replays through the EXISTING
``replay_session_outcome`` and ``summarize`` in the replay's price-diagnostic
mode with an adjusted price basis, an assumed common eligibility timeline, the
full calendar schedule, an explicit ``data_as_of`` and the fixed 20/5-session
horizons. Unavailable opportunities are retained with their reasons and their
original per-symbol source hashes; the total requested/unavailable/ready
denominators are reported outside the replay summary so missing inputs never
disappear.

Because the snapshot carries no recorded grades, the replay runs under a
CONTROLLED CONDITIONAL scenario predeclared by root BEFORE real outcomes: a
single assumed grade A with ``rejecting_band=False``, effective at each
requested session open, for both methods. These are assumed diagnostic
conditions only - NEVER recorded historical grades or actual eligibility - and
the limitations name them as such; the shared common gate and the recorded
eligibility/replay/production gates are untouched. This lets a synthetic
reclaim path exercise both methods without pretending the snapshot held dated
eligibility evidence it never carried.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from backend.market.intraday_comparison import DailyRow, Eligibility
from backend.market.intraday_entry import (
    NEW_YORK,
    Bar,
    _completed_bars,
    session_open_for,
)
from backend.market.intraday_inputs import ResearchCalendar, prior_daily
from backend.market.intraday_preflight import session_schedule_from_calendar
from backend.market.intraday_replay import (
    PRICE_DIAGNOSTIC,
    PRIMARY_HORIZON,
    SECONDARY_HORIZON,
    ReplaySummary,
    SessionKind,
    SessionOutcome,
    SessionSchedule,
    replay_session_outcome,
    summarize,
)

# The diagnostic is a price-only component of the incumbent entry, never the
# full live strategy and never portfolio P&L.
DIAGNOSTIC_NAME = "single_source_price_component"

# The only snapshot schema this module understands.
SCHEMA_VERSION = 1

# The exact declared provider/feed metadata of the supplied snapshot.
REQUIRED_FEED = "iex"
REQUIRED_TIMEFRAME = "15Min"
REQUIRED_ADJUSTMENT = "all"

# The predeclared cohort: the four known adjustment-failure specimens first,
# then the two benchmarks, in this exact order. Never reordered after outcomes.
SYMBOLS = ("AVGO", "WRB", "WDC", "APTV", "SPY", "QQQ")

# The declared cohort/window bounds (root predeclared, fixed).
SOURCE_START = date(2026, 6, 29)
SOURCE_END = date(2026, 9, 18)
ENTRY_START = date(2026, 8, 3)
ENTRY_END = date(2026, 9, 18)

# The dataset's explicit observation instant: the 2026-09-18 New York close.
DATA_AS_OF = datetime(2026, 9, 18, 16, 0, tzinfo=NEW_YORK)

# Replay mode and price basis: the reviewed replay's price-diagnostic mode with
# an adjusted basis, so levels stay m+2s/m+2s*Z/m with no raw/Yahoo conversion.
MODE = PRICE_DIAGNOSTIC
PRICE_BASIS = "adjusted"

# The assumed common eligibility for the price-component diagnostic: a fixed
# grade A with rejecting_band=False, effective at every requested session open.
# Root predeclared these assumed diagnostic conditions BEFORE real outcomes; they
# are NEVER reported as recorded historical grades or actual eligibility, and
# they add no strategy rule. The recorded-eligibility/replay/production gates
# are unchanged.
ASSUMED_GRADE = "A"
ASSUMED_REJECTING_BAND = False

# A complete regular session has 26 bars; an early close has 14 (09:30-12:45).
FULL_SESSION_BARS = 26
EARLY_CLOSE_BARS = 14

# Opportunity and sample statuses.
READY = "ready"
UNAVAILABLE = "unavailable"
SAMPLE_AVAILABLE = "available"


# A page or an opportunity is either good, or unavailable with an exact reason.
@dataclass(frozen=True)
class Sample:
    """One symbol's validated source: hashes, parsed bars and availability.

    ``hashes`` preserves the raw per-symbol source page hashes even when the
    sample is unavailable. ``bars`` holds the parsed regular/extended bars in
    original order with duplicates and NaN numeric invalids intact; it is empty
    when the sample is unavailable.
    """

    symbol: str
    hashes: tuple[str, ...]
    status: str
    reason: str
    bars: tuple[Bar, ...]


# The validated whole snapshot handed to the diagnostic run.
@dataclass(frozen=True)
class Snapshot:
    """The validated snapshot metadata and its per-symbol samples."""

    schema_version: int
    feed: str
    timeframe: str
    adjustment: str
    start: date
    end: date
    fetched_at: datetime
    samples: tuple[Sample, ...]


# One requested symbol/full-session opportunity's outcome or its reason.
@dataclass(frozen=True)
class Opportunity:
    """One requested opportunity: ready with a replay, or unavailable retained.

    ``source_hashes`` preserves the raw per-symbol page hashes whether or not
    the opportunity is ready. ``session_outcome`` is the reviewed
    ``SessionOutcome`` when ready; the compact counts mirror it for JSON.
    """

    symbol: str
    session: date
    status: str
    reason: str
    source_hashes: tuple[str, ...]
    session_outcome: SessionOutcome | None
    observation_count: int
    readiness_counts: Mapping[str, int]
    events: Mapping[str, str]
    execution_status: Mapping[str, str]
    primary_status: Mapping[str, str]
    secondary_status: Mapping[str, str]


# The requested/unavailable/ready denominators, reported outside the summary.
@dataclass(frozen=True)
class Totals:
    """Total requested, ready and unavailable opportunities, with reasons.

    ``by_reason`` counts unavailable opportunities by their explicit reason so
    missing inputs are reported, never silently dropped.
    """

    requested: int
    ready: int
    unavailable: int
    by_reason: Mapping[str, int]


# The typed result of one diagnostic run over one snapshot.
@dataclass(frozen=True)
class DiagnosticResult:
    """The whole cohort result: every requested opportunity and the summary.

    ``opportunities`` covers every requested symbol/full-session opportunity
    with its status, reason, source hashes and replay output. ``totals`` is the
    requested/unavailable/ready denominator outside ``summary``. ``summary`` is
    the reviewed ``ReplaySummary`` over the ready opportunities (None when
    none are ready). ``limitations`` names the source-change limitations of
    this single-source price-component diagnostic.
    """

    name: str
    schema_version: int
    feed: str
    timeframe: str
    adjustment: str
    source_start: date
    source_end: date
    data_as_of: datetime
    primary_horizon: int
    secondary_horizon: int
    price_basis: str
    mode: str
    symbols: tuple[str, ...]
    requested_sessions: tuple[date, ...]
    opportunities: tuple[Opportunity, ...]
    totals: Totals
    summary: ReplaySummary | None
    limitations: tuple[str, ...]


# Coerce a timestamp to New York time; a naive timestamp is taken as New York.
def _ny(dt: datetime) -> datetime:
    """Return ``dt`` as a New York-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=NEW_YORK)
    return dt.astimezone(NEW_YORK)


# Parse a snapshot date field, rejecting anything that is not an ISO date.
def _parse_date(value: Any, field: str) -> date:
    """Return the ISO date of ``value``, or raise for the named field."""
    if not isinstance(value, str):
        raise ValueError(f"snapshot {field} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"snapshot {field} is not a valid date: {value!r}") from exc


# Parse a snapshot timestamp field as a timezone-aware datetime.
def _parse_aware_dt(value: Any, field: str) -> datetime:
    """Return the aware datetime of ``value``, or raise for the named field."""
    if not isinstance(value, str):
        raise ValueError(f"snapshot {field} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"snapshot {field} is not a valid datetime: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"snapshot {field} must be timezone-aware")
    return parsed


# A missing/non-numeric OHLCV cell becomes NaN, retained for causal validation.
def _numeric(value: Any) -> float:
    """Return ``value`` as a float, or NaN when it is not a finite number."""
    if isinstance(value, bool):
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else float("nan")
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return float("nan")
        return parsed if math.isfinite(parsed) else float("nan")
    return float("nan")


# Check one stored page for shape, status, hash and JSON integrity.
def _check_page(page: Any) -> str | None:
    """Return a page problem, or None when the page is structurally valid."""
    if not isinstance(page, Mapping):
        return "a page is not an object"
    status = page.get("status")
    sha = page.get("sha256")
    body = page.get("body")
    if not isinstance(status, int):
        return "page status is missing or not an integer"
    if not isinstance(sha, str) or not sha:
        return "page sha256 is missing"
    if not isinstance(body, str):
        return "page body is missing or not text"
    if status != 200:
        return f"page status {status} is not 200"
    if sha != hashlib.sha256(body.encode("utf-8")).hexdigest():
        return "page sha256 does not match the body bytes"
    try:
        payload = json.loads(body)
    except ValueError:
        return "page body is not valid JSON (truncated)"
    if not isinstance(payload, dict):
        return "page body is not a JSON object"
    return None


# Parse one Alpaca bars row into a Bar, preserving order and NaN numerics.
def _parse_row(row: Any) -> tuple[Bar | None, str | None]:
    """Return (Bar, None) or (None, reason) for one payload bar row.

    A naive or invalid timestamp has unplaceable causality and is reported; a
    valid timestamp with non-numeric OHLCV becomes a NaN bar that is retained
    for the later causal validation rather than being dropped or zero-filled.
    """
    if not isinstance(row, Mapping):
        return None, "bar row is not an object"
    stamp = row.get("t")
    if not isinstance(stamp, str) or not stamp:
        return None, "bar timestamp is missing"
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None, f"invalid timestamp {stamp!r}"
    if parsed.tzinfo is None:
        return None, f"naive timestamp {stamp!r} has unplaceable causality"
    return (
        Bar(
            start=_ny(parsed),
            open=_numeric(row.get("o")),
            high=_numeric(row.get("h")),
            low=_numeric(row.get("l")),
            close=_numeric(row.get("c")),
            volume=_numeric(row.get("v")),
        ),
        None,
    )


# Build one symbol's Sample from its stored pages, or an unavailable one.
def _build_sample(symbol: str, entry: Any) -> Sample:  # noqa: C901 - ordered refusal gates
    """Return the parsed Sample for ``symbol`` from its page list.

    Every page is checked for shape, status, hash and JSON integrity, then the
    explicit ``request_page_token`` chain must be continuous: the first page
    carries a null request token, each later page's request token is exactly the
    previous page's response ``next_page_token``, a repeated or cyclic token is
    rejected, a non-string non-null token is rejected, a page ending pagination
    before the final page is rejected and a non-null final response token is
    rejected. A page whose bars payload names any symbol other than ``symbol``
    is rejected as contamination. Any page problem, a naive/invalid bar
    timestamp or an unparseable row makes the whole sample unavailable with an
    explicit reason while the hashes so far are retained; source bars are never
    silently sorted or deduped.
    """
    pages = entry.get("pages")
    if not isinstance(pages, list) or not pages:
        return Sample(symbol, (), UNAVAILABLE, "no pages supplied for symbol", ())
    hashes: list[str] = []
    rows: list[Any] = []
    previous_next: str | None = None
    seen_tokens: set[str] = set()
    for index, page in enumerate(pages):
        problem = _check_page(page)
        if problem:
            return Sample(
                symbol, tuple(hashes), UNAVAILABLE, f"page {index}: {problem}", ()
            )
        hashes.append(page["sha256"])
        payload = json.loads(page["body"])
        if "request_page_token" not in page:
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                f"page {index}: request_page_token is missing",
                (),
            )
        request = page["request_page_token"]
        if index == 0:
            if request is not None:
                return Sample(
                    symbol,
                    tuple(hashes),
                    UNAVAILABLE,
                    f"page {index}: the first page must carry a null "
                    "request_page_token",
                    (),
                )
        else:
            if not isinstance(request, str):
                return Sample(
                    symbol,
                    tuple(hashes),
                    UNAVAILABLE,
                    f"page {index}: request_page_token must be a string when non-null",
                    (),
                )
            if previous_next is None:
                return Sample(
                    symbol,
                    tuple(hashes),
                    UNAVAILABLE,
                    "pagination ended before the final page (previous page had "
                    "no next_page_token)",
                    (),
                )
            if request != previous_next:
                return Sample(
                    symbol,
                    tuple(hashes),
                    UNAVAILABLE,
                    f"page {index}: request_page_token {request!r} does not "
                    f"match the previous page's next_page_token "
                    f"{previous_next!r}",
                    (),
                )
        response_next = payload.get("next_page_token")
        if response_next is not None and not isinstance(response_next, str):
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                f"page {index}: next_page_token must be a string when non-null",
                (),
            )
        if response_next is not None and response_next in seen_tokens:
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                f"page {index}: repeated/cyclic next_page_token {response_next!r}",
                (),
            )
        is_last = index == len(pages) - 1
        if not is_last and (response_next is None or response_next == ""):
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                "pagination ended before the final page (missing next_page_token)",
                (),
            )
        if is_last and response_next is not None:
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                "last page has a non-null next_page_token; pages are truncated",
                (),
            )
        if response_next is not None:
            seen_tokens.add(response_next)
            previous_next = response_next
        bars_dict = payload.get("bars")
        if not isinstance(bars_dict, dict):
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                f"page {index}: bars field is missing or not an object",
                (),
            )
        unexpected = sorted(key for key in bars_dict if key != symbol)
        if unexpected:
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                f"page {index}: bars payload contains unexpected symbols {unexpected}",
                (),
            )
        symbol_rows = bars_dict.get(symbol)
        if symbol_rows is None:
            symbol_rows = []
        if not isinstance(symbol_rows, list):
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                f"page {index}: bars for {symbol} is not a list",
                (),
            )
        rows.extend(symbol_rows)
    bars: list[Bar] = []
    for index, row in enumerate(rows):
        bar, problem = _parse_row(row)
        if problem is not None or bar is None:
            return Sample(
                symbol,
                tuple(hashes),
                UNAVAILABLE,
                f"bar {index}: {problem or 'unparseable row'}",
                (),
            )
        bars.append(bar)
    return Sample(symbol, tuple(hashes), SAMPLE_AVAILABLE, "", tuple(bars))


# Validate the whole snapshot against the declared cohort and metadata.
def validate_snapshot(snapshot: Mapping[str, Any]) -> Snapshot:  # noqa: C901 - ordered refusal gates
    """Return the validated Snapshot, or raise for unsupported metadata.

    Rejects an unsupported schema version, feed, timeframe or adjustment,
    mismatched source bounds, an unparseable/naive fetched_at, an unknown
    symbol outside the declared cohort, or a duplicate sample symbol. A
    required symbol absent from the snapshot is allowed here and stays a
    requested-but-unavailable opportunity in the run.
    """
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a JSON object")
    schema = snapshot.get("schema")
    if schema != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema version {schema!r}; expected {SCHEMA_VERSION}"
        )
    feed = snapshot.get("feed")
    if feed != REQUIRED_FEED:
        raise ValueError(f"unsupported feed {feed!r}; expected {REQUIRED_FEED}")
    timeframe = snapshot.get("timeframe")
    if timeframe != REQUIRED_TIMEFRAME:
        raise ValueError(
            f"unsupported timeframe {timeframe!r}; expected {REQUIRED_TIMEFRAME}"
        )
    adjustment = snapshot.get("adjustment")
    if adjustment != REQUIRED_ADJUSTMENT:
        raise ValueError(
            f"wrong adjustment {adjustment!r}; expected {REQUIRED_ADJUSTMENT} "
            "(no double adjustment)"
        )
    start = _parse_date(snapshot.get("start"), "start")
    end = _parse_date(snapshot.get("end"), "end")
    if (start, end) != (SOURCE_START, SOURCE_END):
        raise ValueError(
            f"source bounds must be {SOURCE_START}..{SOURCE_END}, got {start}..{end}"
        )
    fetched_at = _parse_aware_dt(snapshot.get("fetched_at"), "fetched_at")
    raw_samples = snapshot.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise ValueError("samples must be a non-empty list")
    seen: set[str] = set()
    samples: list[Sample] = []
    for entry in raw_samples:
        if not isinstance(entry, Mapping):
            raise ValueError("each sample must be an object")
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("each sample requires a symbol")
        if symbol not in SYMBOLS:
            raise ValueError(f"sample symbol {symbol!r} is outside the declared cohort")
        if symbol in seen:
            raise ValueError(f"duplicate sample symbol {symbol!r}")
        seen.add(symbol)
        samples.append(_build_sample(symbol, entry))
    return Snapshot(
        schema_version=schema,
        feed=feed,
        timeframe=timeframe,
        adjustment=adjustment,
        start=start,
        end=end,
        fetched_at=fetched_at,
        samples=tuple(samples),
    )


# The requested full-session entry dates within the declared cohort window.
def _requested_sessions(schedule: SessionSchedule) -> tuple[date, ...]:
    """Return every full session in [ENTRY_START, ENTRY_END] on the schedule."""
    sessions: list[date] = []
    day = ENTRY_START
    while day <= ENTRY_END:
        if schedule.kind(day) is SessionKind.FULL:
            sessions.append(day)
        day += timedelta(days=1)
    return tuple(sessions)


# The assumed common eligibility timeline, one record per requested session.
def _assumed_eligibility_timeline(schedule: SessionSchedule) -> tuple[Eligibility, ...]:
    """Return one assumed grade-A, non-rejecting eligibility per requested session.

    Each requested session open gets an Eligibility with the fixed assumed grade
    and rejecting_band, both known at that open, so the reviewed common gate can
    decide for both methods on a synthetic reclaim path. These are assumed
    diagnostic conditions, never recorded historical grades or actual
    eligibility; the limitations say so.
    """
    timeline: list[Eligibility] = []
    for day in _requested_sessions(schedule):
        open_at = session_open_for(day)
        timeline.append(
            Eligibility(ASSUMED_GRADE, open_at, ASSUMED_REJECTING_BAND, open_at)
        )
    return tuple(timeline)


# Derive one DailyRow for one session from complete, unique, valid bars.
def _daily_row(
    day: date, bars: Sequence[Bar], schedule: SessionSchedule
) -> DailyRow | None:
    """Return the session's single-source DailyRow, or None when incomplete.

    Only a COMPLETE, unique, correctly gridded, valid regular session yields a
    row: the reviewed ``_completed_bars`` validates the opening bar, grid,
    contiguity, uniqueness and OHLCV envelope (extended hours excluded), and the
    bar count must be exactly 26 on a full session or 14 on an early close. The
    row's close equals its adjusted close (the last regular close), so the
    single source is never combined with a raw/Yahoo conversion.
    """
    kind = schedule.kind(day)
    if kind not in (SessionKind.FULL, SessionKind.EARLY_CLOSE):
        return None
    try:
        completed = _completed_bars(list(bars), day, None)
    except ValueError:
        return None
    expected = (
        EARLY_CLOSE_BARS if kind is SessionKind.EARLY_CLOSE else FULL_SESSION_BARS
    )
    if len(completed) != expected:
        return None
    close = completed[-1].close
    if not (math.isfinite(close) and close > 0):
        return None
    return DailyRow(day, close, close)


# Map every session date with a complete session to its single-source DailyRow.
def _daily_rows_by_date(
    bars: Sequence[Bar], schedule: SessionSchedule
) -> dict[date, DailyRow]:
    """Return {session date: DailyRow} for every complete valid session."""
    by_date: dict[date, list[Bar]] = {}
    for bar in bars:
        by_date.setdefault(_ny(bar.start).date(), []).append(bar)
    rows: dict[date, DailyRow] = {}
    for day, day_bars in by_date.items():
        row = _daily_row(day, day_bars, schedule)
        if row is not None:
            rows[day] = row
    return rows


# The exact preceding 20 daily sessions for an entry, or why they are missing.
def _history_for(
    entry: date, daily_by_date: Mapping[date, DailyRow], calendar: ResearchCalendar
) -> tuple[tuple[DailyRow, ...], str | None]:
    """Return (history, None) or ((), reason) via the reviewed prior_daily gate.

    Only daily rows strictly before ``entry`` are candidates, and exactly the
    preceding 20 exchange sessions must be present with valid prices; anything
    less returns an explicit reason so the opportunity is retained unavailable.
    """
    history = sorted(
        (row for row in daily_by_date.values() if row.date < entry),
        key=lambda row: row.date,
    )
    try:
        selected = prior_daily(history, entry, calendar)
    except ValueError as exc:
        return (), str(exc)
    return tuple(selected), None


# Group every bar by its New York session date, order and duplicates preserved.
def _group_by_date(bars: Sequence[Bar]) -> dict[date, tuple[Bar, ...]]:
    """Return {session date: bars} preserving order, duplicates and NaN bars."""
    by_date: dict[date, list[Bar]] = {}
    for bar in bars:
        by_date.setdefault(_ny(bar.start).date(), []).append(bar)
    return {day: tuple(day_bars) for day, day_bars in by_date.items()}


# The compact per-method event times, for the JSON-safe opportunity view.
def _event_times(outcome: SessionOutcome) -> dict[str, str]:
    """Return {method: event observation time iso or ''} from the replay."""
    return {
        method: (record.observation_time or "")
        for method, record in outcome.replay.events.items()
    }


# The compact per-method execution statuses, for the JSON-safe opportunity view.
def _execution_statuses(outcome: SessionOutcome) -> dict[str, str]:
    """Return {method: execution proxy status} for the two methods."""
    return {
        "incumbent": outcome.incumbent.execution.status,
        "candidate": outcome.candidate.execution.status,
    }


# The compact per-method endpoint statuses at a horizon, for the JSON view.
def _endpoint_statuses(outcome: SessionOutcome, horizon: int) -> dict[str, str]:
    """Return {method: endpoint label status} at ``horizon`` for the two methods."""
    return {
        "incumbent": getattr(
            outcome.incumbent, "primary" if horizon == PRIMARY_HORIZON else "secondary"
        ).status,
        "candidate": getattr(
            outcome.candidate, "primary" if horizon == PRIMARY_HORIZON else "secondary"
        ).status,
    }


# Build one requested opportunity, replaying it when every input is available.
def _opportunity(
    symbol: str,
    session: date,
    sample: Sample | None,
    daily_by_date: Mapping[date, DailyRow],
    schedule: SessionSchedule,
    calendar: ResearchCalendar,
    eligibility_timeline: Sequence[Eligibility],
) -> Opportunity:
    """Return the ready or unavailable Opportunity for one symbol/session.

    A missing sample, an unavailable sample or a missing preceding-20-session
    daily history makes the opportunity unavailable with an explicit reason and
    the raw source hashes retained. Otherwise the session is replayed through
    the reviewed ``replay_session_outcome`` in price-diagnostic mode with an
    adjusted basis, the assumed common eligibility timeline, the full calendar
    schedule, the explicit data_as_of and the fixed 20/5 horizons; all entry
    bars are kept even if incomplete and outcome bars retain malformed/gapped
    bars.
    """
    if sample is None:
        return Opportunity(
            symbol,
            session,
            UNAVAILABLE,
            "no sample supplied for symbol",
            (),
            None,
            0,
            {},
            {},
            {},
            {},
            {},
        )
    if sample.status == UNAVAILABLE:
        return Opportunity(
            symbol,
            session,
            UNAVAILABLE,
            sample.reason,
            sample.hashes,
            None,
            0,
            {},
            {},
            {},
            {},
            {},
        )
    history, history_err = _history_for(session, daily_by_date, calendar)
    if history_err:
        return Opportunity(
            symbol,
            session,
            UNAVAILABLE,
            f"prior daily history unavailable: {history_err}",
            sample.hashes,
            None,
            0,
            {},
            {},
            {},
            {},
            {},
        )
    outcome_bars = _group_by_date(sample.bars)
    entry_bars = outcome_bars.get(session, ())
    try:
        outcome = replay_session_outcome(
            symbol=symbol,
            session=session,
            bars=entry_bars,
            history=list(history),
            price_basis=PRICE_BASIS,
            eligibility_timeline=eligibility_timeline,
            schedule=schedule,
            mode=MODE,
            outcome_bars=outcome_bars,
            data_as_of=DATA_AS_OF,
        )
    except ValueError as exc:
        return Opportunity(
            symbol,
            session,
            UNAVAILABLE,
            f"replay unavailable: {exc}",
            sample.hashes,
            None,
            0,
            {},
            {},
            {},
            {},
            {},
        )
    return Opportunity(
        symbol,
        session,
        READY,
        "",
        sample.hashes,
        outcome,
        len(outcome.replay.observations),
        dict(outcome.replay.readiness_counts),
        _event_times(outcome),
        _execution_statuses(outcome),
        _endpoint_statuses(outcome, PRIMARY_HORIZON),
        _endpoint_statuses(outcome, SECONDARY_HORIZON),
    )


# The requested/unavailable/ready denominators, with a reason breakdown.
def _totals(opportunities: Sequence[Opportunity]) -> Totals:
    """Return the requested/ready/unavailable totals and unavailable reasons."""
    ready = sum(1 for opp in opportunities if opp.status == READY)
    requested = len(opportunities)
    by_reason: dict[str, int] = {}
    for opp in opportunities:
        if opp.status == UNAVAILABLE:
            by_reason[opp.reason] = by_reason.get(opp.reason, 0) + 1
    return Totals(requested, ready, requested - ready, by_reason)


# The source-change limitations every single-source result must carry.
def _limitations() -> tuple[str, ...]:
    """Return the explicit limitations of this single-source diagnostic."""
    return (
        f"{DIAGNOSTIC_NAME} is a price-only component diagnostic over fresh "
        "single-source Alpaca IEX 15Min adjustment=all response pages; it is "
        "NOT an exact live reconstruction of the full strategy and NOT "
        "portfolio P&L.",
        "Daily reference closes are derived only from those same regular-hours "
        "bars (close == adjusted close), so Yahoo and old cached intraday units "
        "are never mixed; there is no raw/Yahoo conversion and no double "
        "adjustment.",
        "The snapshot carries no recorded historical grades or eligibility, so "
        "the replay runs under an assumed common eligibility: a fixed grade A "
        "with rejecting_band=False, effective at each requested session open "
        "for both methods. These are assumed diagnostic conditions, never "
        "recorded grades or actual eligibility; the recorded "
        "eligibility/replay/production gates are unchanged.",
        "Execution is the optimistic zero-latency next-consecutive-regular-bar "
        "open proxy with zero added costs, not a verified fill.",
        f"Outcome horizons are fixed at {PRIMARY_HORIZON} (primary) and "
        f"{SECONDARY_HORIZON} (secondary) sessions; labels whose endpoint lies "
        "past data_as_of are reported immature, never shortened.",
        "No strategy or threshold changes were made; this is a diagnostic "
        "cohort over the declared symbols, not a universe performance estimate.",
    )


# Run the whole single-source price-component diagnostic over one snapshot.
def run_diagnostic(
    snapshot: Mapping[str, Any], calendar: ResearchCalendar
) -> DiagnosticResult:
    """Return the DiagnosticResult over the requested cohort of the snapshot.

    Validates the snapshot (raising on unsupported metadata), builds the full
    calendar schedule via the reviewed helper, then replays every requested
    symbol/full-session opportunity through the reviewed replay, retaining
    unavailable opportunities with their reasons and source hashes. The result
    carries the totals outside the summary and the explicit limitations.
    """
    validated = validate_snapshot(snapshot)
    schedule = session_schedule_from_calendar(calendar)
    samples_by_symbol = {sample.symbol: sample for sample in validated.samples}
    requested_sessions = _requested_sessions(schedule)
    eligibility_timeline = _assumed_eligibility_timeline(schedule)
    daily_by_symbol: dict[str, dict[date, DailyRow]] = {}
    for sample in validated.samples:
        if sample.status == SAMPLE_AVAILABLE:
            daily_by_symbol[sample.symbol] = _daily_rows_by_date(sample.bars, schedule)
    opportunities: list[Opportunity] = []
    for symbol in SYMBOLS:
        matched_sample = samples_by_symbol.get(symbol)
        daily = daily_by_symbol.get(symbol, {})
        for session in requested_sessions:
            opportunities.append(
                _opportunity(
                    symbol,
                    session,
                    matched_sample,
                    daily,
                    schedule,
                    calendar,
                    eligibility_timeline,
                )
            )
    ready_outcomes = [
        opp.session_outcome for opp in opportunities if opp.session_outcome is not None
    ]
    summary = (
        summarize(ready_outcomes, mode=MODE, price_basis=PRICE_BASIS)
        if ready_outcomes
        else None
    )
    return DiagnosticResult(
        name=DIAGNOSTIC_NAME,
        schema_version=validated.schema_version,
        feed=validated.feed,
        timeframe=validated.timeframe,
        adjustment=validated.adjustment,
        source_start=validated.start,
        source_end=validated.end,
        data_as_of=DATA_AS_OF,
        primary_horizon=PRIMARY_HORIZON,
        secondary_horizon=SECONDARY_HORIZON,
        price_basis=PRICE_BASIS,
        mode=MODE,
        symbols=SYMBOLS,
        requested_sessions=requested_sessions,
        opportunities=tuple(opportunities),
        totals=_totals(opportunities),
        summary=summary,
        limitations=_limitations(),
    )


# Flatten one endpoint label into a JSON-safe dict.
def _label_to_dict(label: Any) -> dict[str, Any]:
    """Return a JSON-safe view of one reviewed EndpointLabel."""
    return {
        "horizon": label.horizon,
        "endpoint_date": label.endpoint_date.isoformat()
        if label.endpoint_date
        else None,
        "status": label.status,
        "endpoint_close": label.endpoint_close,
        "forward_return": label.forward_return,
        "reason": label.reason,
        "available_at": label.available_at.isoformat() if label.available_at else None,
    }


# Flatten one method's outcome record into a JSON-safe dict.
def _outcome_record_to_dict(record: Any) -> dict[str, Any]:
    """Return a JSON-safe view of one reviewed OutcomeRecord."""
    return {
        "method": record.method,
        "event": (
            {
                "observation_time": record.event.observation_time,
                "state": record.event.state,
                "identity": record.event.identity,
                "trigger_time": record.event.trigger_time,
                "trigger_price": record.event.trigger_price,
            }
            if record.event is not None
            else None
        ),
        "execution": {
            "status": record.execution.status,
            "price": record.execution.price,
            "time": record.execution.time.isoformat()
            if record.execution.time
            else None,
            "reason": record.execution.reason,
        },
        "primary": _label_to_dict(record.primary),
        "secondary": _label_to_dict(record.secondary),
        "excursion": {
            "status": record.excursion.status,
            "adverse": record.excursion.adverse,
            "favorable": record.excursion.favorable,
            "reason": record.excursion.reason,
        },
    }


# Flatten one opportunity into a JSON-safe dict.
def _opportunity_to_dict(opp: Opportunity) -> dict[str, Any]:
    """Return a JSON-safe view of one Opportunity, including its replay output."""
    replay_view = None
    if opp.session_outcome is not None:
        outcome = opp.session_outcome
        replay_view = {
            "price_basis": outcome.price_basis,
            "mode": outcome.mode,
            "observation_count": len(outcome.replay.observations),
            "readiness_counts": dict(outcome.replay.readiness_counts),
            "events": {
                method: record.observation_time
                for method, record in outcome.replay.events.items()
            },
            "incumbent": _outcome_record_to_dict(outcome.incumbent),
            "candidate": _outcome_record_to_dict(outcome.candidate),
        }
    return {
        "symbol": opp.symbol,
        "session": opp.session.isoformat(),
        "status": opp.status,
        "reason": opp.reason,
        "source_hashes": list(opp.source_hashes),
        "replay": replay_view,
    }


# Flatten the totals into a JSON-safe dict.
def _totals_to_dict(totals: Totals) -> dict[str, Any]:
    """Return a JSON-safe view of the requested/ready/unavailable totals."""
    return {
        "requested": totals.requested,
        "ready": totals.ready,
        "unavailable": totals.unavailable,
        "by_reason": dict(totals.by_reason),
    }


# Flatten the whole diagnostic result into a JSON-safe dict.
def to_dict(result: DiagnosticResult) -> dict[str, Any]:
    """Return a JSON-safe dict of the DiagnosticResult for persistence/review."""
    return {
        "name": result.name,
        "schema_version": result.schema_version,
        "feed": result.feed,
        "timeframe": result.timeframe,
        "adjustment": result.adjustment,
        "source_start": result.source_start.isoformat(),
        "source_end": result.source_end.isoformat(),
        "data_as_of": result.data_as_of.isoformat(),
        "primary_horizon": result.primary_horizon,
        "secondary_horizon": result.secondary_horizon,
        "price_basis": result.price_basis,
        "mode": result.mode,
        "symbols": list(result.symbols),
        "requested_sessions": [day.isoformat() for day in result.requested_sessions],
        "opportunities": [_opportunity_to_dict(opp) for opp in result.opportunities],
        "totals": _totals_to_dict(result.totals),
        "summary": _summary_to_dict(result.summary)
        if result.summary is not None
        else None,
        "limitations": list(result.limitations),
    }


# Flatten the reviewed ReplaySummary into a JSON-safe dict.
def _summary_to_dict(summary: ReplaySummary) -> dict[str, Any]:
    """Return a JSON-safe view of the reviewed ReplaySummary."""
    return {
        "mode": summary.mode,
        "price_basis": summary.price_basis,
        "session_count": summary.session_count,
        "both_entries": summary.both_entries,
        "incumbent_only": summary.incumbent_only,
        "candidate_only": summary.candidate_only,
        "neither_entries": summary.neither_entries,
        "repeated_readiness": summary.repeated_readiness,
        "missing_execution_count": summary.missing_execution_count,
        "missing_outcome_count": summary.missing_outcome_count,
        "immature_outcome_count": summary.immature_outcome_count,
        "paired_entry_count": summary.paired_entry_count,
        "paired_entry_price_diff": summary.paired_entry_price_diff,
        "paired_entry_price_improvement": summary.paired_entry_price_improvement,
        "incumbent_primary": _conditional_to_dict(summary.incumbent_primary),
        "incumbent_secondary": _conditional_to_dict(summary.incumbent_secondary),
        "candidate_primary": _conditional_to_dict(summary.candidate_primary),
        "candidate_secondary": _conditional_to_dict(summary.candidate_secondary),
        "paired_primary_incumbent": _conditional_to_dict(
            summary.paired_primary_incumbent
        ),
        "paired_primary_candidate": _conditional_to_dict(
            summary.paired_primary_candidate
        ),
        "paired_secondary_incumbent": _conditional_to_dict(
            summary.paired_secondary_incumbent
        ),
        "paired_secondary_candidate": _conditional_to_dict(
            summary.paired_secondary_candidate
        ),
        "missed_opportunity_count": summary.missed_opportunity_count,
        "missed_opportunity_incumbent_primary": _conditional_to_dict(
            summary.missed_opportunity_incumbent_primary
        ),
        "missed_opportunity_incumbent_secondary": _conditional_to_dict(
            summary.missed_opportunity_incumbent_secondary
        ),
        "missed_opportunity_candidate_primary": _conditional_to_dict(
            summary.missed_opportunity_candidate_primary
        ),
        "missed_opportunity_candidate_secondary": _conditional_to_dict(
            summary.missed_opportunity_candidate_secondary
        ),
        "missed_opportunity_incumbent_context": (
            summary.missed_opportunity_incumbent_context
        ),
    }


# Flatten one conditional forward return into a JSON-safe dict.
def _conditional_to_dict(conditional: Any) -> dict[str, Any]:
    """Return a JSON-safe view of one ConditionalReturn."""
    return {
        "horizon": conditional.horizon,
        "count": conditional.count,
        "mean": conditional.mean,
    }
