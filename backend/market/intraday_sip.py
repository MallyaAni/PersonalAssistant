"""Consolidated (SIP, delayed) fifteen-minute bars on a raw basis, per session.

The IEX cache (`bars_15m`) cannot support the fifteen-minute engine: its
volume is one venue's share, a thin name loses whole sessions, and it was
fetched with `adjustment=all`, which rescales history on every corporate
action so it can never be appended to. The 2026-09-22 audit found AVGO's
cached closes about ten times the daily close before its 2024-07-15 split
(`docs/research/intraday-price-basis-reconciliation-2026-09-22.md`), and
historical scoring on that cache is blocked.

This store holds what the tape printed, and nothing derived:

    <root>/bars_15m_sip/asof=<session date>/<TICKER>.parquet

- **Raw prices** (`adjustment=raw`): a bar written in 2024 is the same
  bytes forever, so a session can be appended without rewriting the past.
  A reader that needs a split-adjusted series applies the daily store's
  corporate actions itself.
- **One partition per ticker per New York session date.** The label is
  the session the bars belong to, never the UTC date of the fetch (the
  IEX cache labels by UTC date, which after 20:00 Eastern is tomorrow).
- **Regular hours only, bounded by the calendar.** Bars from 09:30 up to
  `calendar.session_close(day)` by start time: 26 on a normal day, 14 on
  a 13:00 early close. After-hours prints are left out, so an early
  close can never hold an afternoon "close".
- **Provenance in the schema metadata**: feed, adjustment, timeframe,
  fetched_at (UTC), source_revision (git SHA when available), the
  session date and its scheduled close, the bar count, the count the
  calendar expects, and `complete`.

`reconcile` is the acceptance gate: the session's first open, last close,
high, low and summed volume against the daily store's bar for the same
session, on the raw basis. The daily store's close is split-adjusted as of
its fetch (Yahoo returns no unadjusted series), so the daily close is
multiplied, and its volume divided, by the product of the split ratios
dated after the session before the comparison. The tolerances are
defaults chosen round and frozen before any run; they are not measured.
"""

from __future__ import annotations

import math
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.market import calendar
from backend.market.alpaca import (
    IntradayBar,
    bars_expected,
    bars_frame,
    bars_from_frame,
)
from backend.market.store import MarketStore
from backend.market.yahoo import TickerHistory

KIND = "bars_15m_sip"
FEED = "sip"
ADJUSTMENT = "raw"
TIMEFRAME = "15Min"
SOURCE = "alpaca-sip"
NEW_YORK = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
BAR_MINUTES = 15

# Acceptance-gate tolerances. Defaults: chosen round and frozen on
# 2026-09-26 before any SIP session was fetched, not measured.
DEFAULT_CLOSE_TOLERANCE = 0.005  # |log(close_sip / close_daily_raw)|
DEFAULT_VOLUME_TOLERANCE = 0.20  # |volume_sip / volume_daily_raw - 1|

# The repository root, for the source revision.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class SipStoreError(RuntimeError):
    """A write would overwrite a complete partition, or a read is malformed."""


@dataclass(frozen=True, slots=True)
class Provenance:
    """What every partition of this store records about its fetch."""

    fetched_at: str  # UTC ISO instant of the fetch
    source_revision: str  # git SHA of the fetching code, or ""
    feed: str = FEED
    adjustment: str = ADJUSTMENT
    timeframe: str = TIMEFRAME


@dataclass(frozen=True, slots=True)
class AppendResult:
    """What one `append_missing` run did for one ticker."""

    ticker: str
    requested: int  # sessions asked for
    already_stored: int  # sessions that had a partition and were left alone
    to_fetch: tuple[date, ...]  # sessions this run fetches (or would, dry run)
    fetch_ranges: tuple[tuple[date, date], ...]  # contiguous runs, one request each
    written: tuple[date, ...]  # sessions written this run
    incomplete: tuple[date, ...]  # written sessions the calendar says are short
    no_bars: tuple[date, ...]  # fetched sessions the feed had nothing for


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """One session's SIP bars against the daily store's bar, raw basis."""

    ticker: str
    session: date
    stored: bool
    complete: bool
    daily_found: bool
    split_factor: float  # product of split ratios dated after the session
    open_diff: float  # log(open_sip / open_daily_raw), NaN when unavailable
    close_diff: float
    high_diff: float
    low_diff: float
    volume_diff: float  # volume_sip / volume_daily_raw - 1, NaN when unavailable
    close_tolerance: float
    volume_tolerance: float
    passed: bool
    reason: str  # "" when passed, else why not


# The git SHA of the checkout doing the fetching, or "" when git or the
# checkout is unavailable; never raises.
def source_revision(root: Path = _REPO_ROOT) -> str:
    """Return the HEAD commit SHA of the repository at ``root``, or ""."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


# A Provenance for a fetch happening now, with the current source revision.
def provenance_now(
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Provenance:
    """Return the provenance of a fetch made at ``clock()`` by this checkout."""
    return Provenance(
        fetched_at=clock().astimezone(UTC).isoformat(),
        source_revision=source_revision(),
    )


# The path of one ticker's partition for one session, mirroring the
# store's layout (<root>/<kind>/asof=<date>/<ticker>.parquet).
def _partition_path(store: MarketStore, ticker: str, session: date) -> Path:
    return store.root / KIND / f"asof={session.isoformat()}" / f"{ticker}.parquet"


# The slot of a bar within its session: minutes since 09:30 New York over
# fifteen, or None when the bar is outside the regular session of ``day``.
def _slot(bar: IntradayBar, day: date) -> int | None:
    local = bar.start.astimezone(NEW_YORK)
    if local.date() != day:
        return None
    minutes = local.hour * 60 + local.minute
    opening = REGULAR_OPEN.hour * 60 + REGULAR_OPEN.minute
    close = calendar.session_close(day)
    if minutes < opening or minutes >= close.hour * 60 + close.minute:
        return None
    return (minutes - opening) // BAR_MINUTES


# The regular-session bars of one New York day, by start time, one per
# slot, bounded by the calendar close so after-hours prints never enter.
def regular_bars(bars: Iterable[IntradayBar], day: date) -> list[IntradayBar]:
    """Return ``day``'s regular-session bars in slot order, one per slot."""
    by_slot: dict[int, IntradayBar] = {}
    for bar in bars:
        slot = _slot(bar, day)
        if slot is not None and slot not in by_slot:
            by_slot[slot] = bar
    return [by_slot[s] for s in sorted(by_slot)]


# Whether a session's regular bars fill every slot the calendar schedules:
# 26 on a normal day, 14 on a 13:00 early close.
def is_complete(bars: Sequence[IntradayBar], day: date) -> bool:
    """Return True when ``bars`` hold every regular slot of ``day``."""
    slots = {_slot(b, day) for b in bars}
    slots.discard(None)
    return slots == set(range(bars_expected(day)))


# Group a fetch's bars by the New York session date they belong to.
def by_session(bars: Iterable[IntradayBar]) -> dict[date, list[IntradayBar]]:
    """Return {New York date: bars on that date, in order} for every bar."""
    out: dict[date, list[IntradayBar]] = {}
    for bar in bars:
        out.setdefault(bar.start.astimezone(NEW_YORK).date(), []).append(bar)
    return out


# Write one session's bars as one immutable partition with provenance.
# Only the regular-session bars are kept. An existing complete partition
# is never overwritten (SipStoreError); an existing incomplete one is
# replaced, since a fuller fetch of the same raw bars supersedes it.
def write_session(
    store: MarketStore,
    ticker: str,
    session: date,
    bars: Iterable[IntradayBar],
    meta: Provenance,
) -> bool:
    """Store ``session``'s regular bars for ``ticker``; True when written."""
    regular = regular_bars(bars, session)
    complete = is_complete(regular, session)
    path = _partition_path(store, ticker, session)
    if path.exists():
        existing = read_session(store, ticker, session)
        if existing is not None and existing[1].get("complete") == "true":
            raise SipStoreError(
                f"{ticker} {session}: refusing to overwrite a complete partition"
            )
        path.unlink()
    metadata = {
        "ticker": ticker,
        "kind": KIND,
        "source": SOURCE,
        "feed": meta.feed,
        "adjustment": meta.adjustment,
        "timeframe": meta.timeframe,
        "fetched_at": meta.fetched_at,
        "source_revision": meta.source_revision,
        "session_date": session.isoformat(),
        "session_close": calendar.session_close(session).isoformat(),
        "bars_expected": str(bars_expected(session)),
        "bar_count": str(len(regular)),
        "complete": "true" if complete else "false",
    }
    return store.write_frame(KIND, session, ticker, bars_frame(regular), metadata)


# Read exactly one session's partition: the bars and their metadata, or
# None when that session is not stored. Never falls back to an earlier
# session the way the store's newest-on-or-before lookup would.
def read_session(
    store: MarketStore, ticker: str, session: date
) -> tuple[list[IntradayBar], dict[str, str]] | None:
    """Return (bars, metadata) of ``ticker``'s partition for ``session``."""
    if not store.has_frame(KIND, session, ticker):
        return None
    frame = store.read_frame(KIND, ticker, session)
    if frame is None:
        return None
    columns, metadata = frame
    if metadata.get("session_date") != session.isoformat():
        raise SipStoreError(
            f"{ticker} {session}: partition declares session "
            f"{metadata.get('session_date')!r}"
        )
    return bars_from_frame(columns), metadata


# Every session date with a partition for the ticker, oldest first.
def sessions_available(store: MarketStore, ticker: str) -> list[date]:
    """Return the session dates stored for ``ticker``."""
    base = store.root / KIND
    if not base.exists():
        return []
    out: list[date] = []
    for partition in base.iterdir():
        if not partition.is_dir() or not partition.name.startswith("asof="):
            continue
        if not (partition / f"{ticker}.parquet").exists():
            continue
        try:
            out.append(date.fromisoformat(partition.name[len("asof=") :]))
        except ValueError:
            continue
    return sorted(out)


# The sessions the store holds and whether each is complete, read from
# the partitions' metadata only.
def completeness(store: MarketStore, ticker: str) -> dict[date, bool]:
    """Return {stored session: complete flag} for ``ticker``."""
    import pyarrow.parquet as pq

    out: dict[date, bool] = {}
    for session in sessions_available(store, ticker):
        meta = pq.read_table(_partition_path(store, ticker, session)).schema.metadata
        flag = (meta or {}).get(b"complete", b"false").decode()
        out[session] = flag == "true"
    return out


# Contiguous runs of the sessions to fetch, as (first, last) date pairs,
# where contiguity is adjacency in the requested list.
def _runs(missing: Sequence[date], ordered: Sequence[date]) -> list[tuple[date, date]]:
    index = {d: i for i, d in enumerate(ordered)}
    runs: list[tuple[date, date]] = []
    for d in missing:
        if runs and index[d] == index[runs[-1][1]] + 1:
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs


# Fetch and store only the requested sessions that have no partition yet
# (and, on request, the ones stored incomplete), one paged request per
# contiguous run rather than one per session. `fetch(ticker, start, end)`
# returns the bars over the inclusive date range, extended hours included;
# they are split by New York date and each requested session is written
# on its own. A session the feed returned nothing for is not written, so
# it stays missing and is reported. With `dry_run` nothing is fetched or
# written; the result says what would be.
def append_missing(
    store: MarketStore,
    ticker: str,
    sessions: Sequence[date],
    fetch: Callable[[str, date, date], list[IntradayBar]],
    meta: Provenance | None = None,
    *,
    include_incomplete: bool = False,
    dry_run: bool = False,
) -> AppendResult:
    """Fetch and store ``ticker``'s sessions that are not stored yet."""
    ordered = sorted(set(sessions))
    stored = completeness(store, ticker) if include_incomplete else None
    have = set(stored) if stored is not None else set(sessions_available(store, ticker))
    wanted = [
        d
        for d in ordered
        if d not in have
        or (include_incomplete and stored is not None and not stored[d])
    ]
    ranges = tuple(_runs(wanted, ordered))
    if dry_run or not wanted:
        return AppendResult(
            ticker,
            len(ordered),
            len(ordered) - len(wanted),
            tuple(wanted),
            ranges,
            (),
            (),
            (),
        )
    meta = meta or provenance_now()
    written: list[date] = []
    incomplete: list[date] = []
    no_bars: list[date] = []
    for first, last in ranges:
        grouped = by_session(fetch(ticker, first, last))
        for day in wanted:
            if not first <= day <= last:
                continue
            bars = regular_bars(grouped.get(day, ()), day)
            if not bars:
                no_bars.append(day)
                continue
            write_session(store, ticker, day, bars, meta)
            written.append(day)
            if not is_complete(bars, day):
                incomplete.append(day)
    return AppendResult(
        ticker,
        len(ordered),
        len(ordered) - len(wanted),
        tuple(wanted),
        ranges,
        tuple(written),
        tuple(incomplete),
        tuple(no_bars),
    )


# The product of the daily store's split ratios dated after a session:
# the factor that takes the store's split-adjusted close back to the raw
# dollars the tape printed on that session.
def split_factor(history: TickerHistory, session: date) -> float:
    """Return the cumulative split ratio applied to ``session`` since it."""
    factor = 1.0
    for action in history.actions:
        if action.kind == "split" and action.action_date > session and action.value > 0:
            factor *= float(action.value)
    return factor


# The log difference of two positive prices, NaN when either is unusable.
def _log_diff(a: float | None, b: float | None) -> float:
    if a is None or b is None or not (a > 0 and b > 0):
        return math.nan
    return math.log(a / b)


# The acceptance gate for one session: the SIP session's first open, last
# close, high, low and summed volume against the daily store's bar on the
# raw basis. Passes when the session is stored and complete, the daily bar
# exists, and the close and volume are within the (default, frozen)
# tolerances. `daily` may be passed to avoid re-reading the daily store
# for every session of a ticker.
def reconcile(
    store: MarketStore,
    ticker: str,
    session: date,
    *,
    daily: TickerHistory | None = None,
    close_tolerance: float = DEFAULT_CLOSE_TOLERANCE,
    volume_tolerance: float = DEFAULT_VOLUME_TOLERANCE,
) -> Reconciliation:
    """Compare ``ticker``'s SIP session with the daily store's bar for it."""
    nan = math.nan
    stored = read_session(store, ticker, session)
    if stored is None:
        return Reconciliation(
            ticker,
            session,
            False,
            False,
            False,
            1.0,
            nan,
            nan,
            nan,
            nan,
            nan,
            close_tolerance,
            volume_tolerance,
            False,
            "session not stored",
        )
    bars, metadata = stored
    complete = metadata.get("complete") == "true"
    history = daily if daily is not None else store.read(ticker)
    row = None
    if history is not None:
        row = next((b for b in history.bars if b.session_date == session), None)
    if history is None or row is None:
        return Reconciliation(
            ticker,
            session,
            True,
            complete,
            False,
            1.0,
            nan,
            nan,
            nan,
            nan,
            nan,
            close_tolerance,
            volume_tolerance,
            False,
            "no daily bar for the session",
        )
    factor = split_factor(history, session)
    daily_open = row.open * factor if row.open is not None else None
    daily_close = row.close * factor if row.close is not None else None
    daily_high = row.high * factor if row.high is not None else None
    daily_low = row.low * factor if row.low is not None else None
    daily_volume = row.volume / factor if row.volume else None
    if bars:
        sip_volume = float(sum(b.volume for b in bars))
        open_diff = _log_diff(bars[0].open, daily_open)
        close_diff = _log_diff(bars[-1].close, daily_close)
        high_diff = _log_diff(max(b.high for b in bars), daily_high)
        low_diff = _log_diff(min(b.low for b in bars), daily_low)
        volume_diff = (
            sip_volume / daily_volume - 1.0
            if daily_volume and daily_volume > 0
            else nan
        )
    else:
        open_diff = close_diff = high_diff = low_diff = volume_diff = nan
    reason = ""
    if not complete:
        reason = "session incomplete"
    elif not (np.isfinite(close_diff) and np.isfinite(volume_diff)):
        reason = "close or volume unavailable"
    elif abs(close_diff) > close_tolerance:
        reason = f"close differs by {close_diff:+.4f} (tolerance {close_tolerance})"
    elif abs(volume_diff) > volume_tolerance:
        reason = f"volume differs by {volume_diff:+.3f} (tolerance {volume_tolerance})"
    return Reconciliation(
        ticker,
        session,
        True,
        complete,
        True,
        factor,
        open_diff,
        close_diff,
        high_diff,
        low_diff,
        volume_diff,
        close_tolerance,
        volume_tolerance,
        reason == "",
        reason,
    )


# A reconciliation as a JSON-ready dict.
def reconciliation_record(record: Reconciliation) -> dict[str, Any]:
    """Return the reconciliation as plain JSON-serialisable values."""
    out = asdict(record)
    out["session"] = record.session.isoformat()
    for key in ("open_diff", "close_diff", "high_diff", "low_diff", "volume_diff"):
        if not math.isfinite(out[key]):
            out[key] = None
    return out


# The reviewed exchange sessions between two dates, and the years in the
# range the calendar has not reviewed (their sessions cannot be counted).
def calendar_sessions(since: date, until: date) -> tuple[list[date], list[int]]:
    """Return (session dates in [since, until], unreviewed years in range)."""
    years, busdays = calendar.reviewed_sessions()
    unreviewed = [y for y in range(since.year, until.year + 1) if y not in years]
    if since > until:
        return [], unreviewed
    days = np.arange(
        np.datetime64(since), np.datetime64(until) + 1, dtype="datetime64[D]"
    )
    sessions = days[np.is_busday(days, busdaycal=busdays)]
    return [d for d in sessions.astype(object) if d.year in years], unreviewed


# Coverage of one ticker between two dates: sessions the calendar has,
# sessions stored, how many are complete, and the reconcile pass rate
# over the stored sessions (each against the daily store).
def coverage(
    store: MarketStore,
    ticker: str,
    since: date,
    until: date,
    *,
    reconcile_sessions: bool = True,
) -> dict[str, Any]:
    """Return the coverage summary of ``ticker`` over [since, until]."""
    expected, unreviewed = calendar_sessions(since, until)
    flags = {
        d: ok for d, ok in completeness(store, ticker).items() if since <= d <= until
    }
    stored = sorted(flags)
    complete = sum(1 for ok in flags.values() if ok)
    passed = failed = 0
    if reconcile_sessions and stored:
        history = store.read(ticker)
        for session in stored:
            if reconcile(store, ticker, session, daily=history).passed:
                passed += 1
            else:
                failed += 1
    return {
        "ticker": ticker,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "sessions_in_calendar": len(expected),
        "calendar_unreviewed_years": unreviewed,
        "sessions_stored": len(stored),
        "sessions_missing": len(set(expected) - set(stored)),
        "complete": complete,
        "complete_share": (complete / len(stored)) if stored else None,
        "reconciled": passed + failed,
        "reconcile_passed": passed,
        "reconcile_pass_rate": (
            (passed / (passed + failed)) if passed + failed else None
        ),
        "first_session": stored[0].isoformat() if stored else None,
        "last_session": stored[-1].isoformat() if stored else None,
    }
