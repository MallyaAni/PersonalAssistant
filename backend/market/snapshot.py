"""Refreshing and auditing the daily market snapshot.

`refresh` fetches every requested ticker into one as-of partition of the
store, paced, skipping tickers that partition already holds, and captures a
refused or unparseable ticker per ticker rather than failing the run. A
refresh that was throttled halfway is simply run again. `status` reports,
per ticker, whether it is stored at all and whether its newest completed
session is stale, so a snapshot that stopped updating is visible instead of
silently old. `daily_returns` computes the log return from adjusted close,
which is what makes a split incapable of manufacturing a return.
"""

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market.store import MarketStore
from backend.market.universe import STALE_AFTER_DAYS
from backend.market.yahoo import (
    DailyBar,
    MarketDataUnavailableError,
    Pacer,
    TickerHistory,
    fetch_history,
)

# The default first session a refresh asks for. Ten years covers several
# regimes; parquet makes the size a non-issue.
DEFAULT_START = date(2015, 1, 1)


@dataclass(frozen=True, slots=True)
class TickerStatus:
    """What the store currently holds for one ticker."""

    ticker: str
    asof: date | None
    bar_count: int
    first_session: date | None
    complete_through: date | None
    missing: bool
    stale: bool


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """The outcome of refreshing one ticker."""

    ticker: str
    bars_stored: int
    skipped: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """The outcome of refreshing a whole set of tickers into one partition."""

    asof: date
    results: tuple[RefreshResult, ...]

    @property
    def ok(self) -> bool:
        return all(result.error is None for result in self.results)

    @property
    def failed_tickers(self) -> tuple[str, ...]:
        return tuple(result.ticker for result in self.results if result.error)

    @property
    def stored_count(self) -> int:
        return sum(
            1 for result in self.results if result.error is None and not result.skipped
        )


# A fetcher takes (ticker, start, end) and returns a TickerHistory. It is a
# parameter so the refresh path is tested with no network.
Fetcher = Callable[[str, date, date], TickerHistory]


# The log return between consecutive sessions, from adjusted close.
#
# Split-safe: a 2:1 split halves the raw close overnight but leaves the
# adjusted close continuous, so the series is identical with or without the
# event. Bars whose adjusted close is unknown are skipped, never zero.
def daily_returns(bars: Sequence[DailyBar]) -> list[tuple[date, float]]:
    """Return oldest-first (session_date, log return) pairs from adjusted close."""
    prices = [
        (bar.session_date, bar.adjusted_close)
        for bar in bars
        if bar.adjusted_close is not None
    ]
    returns: list[tuple[date, float]] = []
    for (_, previous), (current_date, current) in zip(prices, prices[1:], strict=False):
        if previous > 0 and current > 0:
            returns.append((current_date, math.log(current / previous)))
    return returns


# Retry one incomplete response; never store a snapshot that loses known sessions.
def _fetch_preserving_sessions(store, ticker, start, asof, fetcher):
    known = store.observed_sessions(ticker, start, asof, asof - timedelta(days=1))
    missing = frozenset()
    for _attempt in range(2):
        history = fetcher(ticker, start, asof)
        present = {bar.session_date for bar in history.bars}
        missing = known - present
        if not missing:
            return history
    try:
        return _reconcile_missing_sessions(store, ticker, asof, history, missing)
    except (MarketDataUnavailableError, OSError, ValueError) as exc:
        reason = str(exc)
    first = min(missing)
    raise MarketDataUnavailableError(
        f"{ticker} history omits {len(missing)} previously observed sessions "
        f"(first {first}); incomplete response repeated, snapshot not stored: {reason}"
    )


# Fingerprint a parsed source or reconstructed output without fitting price ratios.
def _history_hash(history):
    payload = json.dumps(asdict(history), sort_keys=True, default=str, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


# Validate a provider's explicit action list before treating no events as evidence.
def _action_signature(history):
    if not isinstance(history.actions, tuple):
        raise MarketDataUnavailableError("action evidence is unavailable")
    rows = []
    for action in history.actions:
        if (
            type(action.action_date) is not date
            or action.kind not in ("split", "dividend")
            or not isinstance(action.value, (int, float))
            or not math.isfinite(action.value)
            or action.value <= 0
        ):
            raise MarketDataUnavailableError("action evidence is invalid")
        rows.append((action.action_date, action.kind, action.value))
    return sorted(rows)


# Reject malformed bars before they can satisfy an exchange-session coverage check.
def _valid_daily_bar(bar):
    values = (bar.open, bar.high, bar.low, bar.close, bar.adjusted_close)
    return (
        all(
            value is not None and math.isfinite(value) and value > 0 for value in values
        )
        and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        and bar.volume is not None
        and math.isfinite(bar.volume)
        and bar.volume >= 0
    )


# Require today's completed exchange session before publishing a recovered vintage.
def _repair_sessions(history, asof):
    from backend.market import calendar

    stamp = history.source_time
    if (
        not isinstance(stamp, datetime)
        or stamp.tzinfo is None
        or stamp.utcoffset() is None
    ):
        raise MarketDataUnavailableError("fresh source time is undated")
    status = calendar.exchange_status(stamp)
    if status["session"] != asof.isoformat() or status["phase"] != "post-market":
        raise MarketDataUnavailableError(
            "repair requires today's completed exchange session"
        )
    years, holidays = calendar._published_sessions()
    days = []
    day = asof
    while len(days) < 20:
        if day.year not in years:
            raise MarketDataUnavailableError(
                "exchange calendar coverage is unavailable"
            )
        if np.is_busday(np.datetime64(day), busdaycal=holidays):
            days.append(day)
        day -= timedelta(days=1)
    if (
        history.complete_through != asof
        or not history.bars
        or history.bars[-1].session_date != asof
    ):
        raise MarketDataUnavailableError("fresh history does not include today's close")
    return frozenset(days)


# Preserve a content-addressed prepared receipt before publishing its matching bars.
def _write_reconciliation_receipt(store, asof, ticker, receipt):
    folder = store.root / "bar_reconciliations" / f"asof={asof}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ticker}-{receipt['output_history_sha256']}.json"
    content = json.dumps(
        receipt, sort_keys=True, indent=2, default=str, allow_nan=False
    )
    try:
        with path.open("x") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_text() != content:
            raise MarketDataUnavailableError(
                "reconciliation receipt conflicts"
            ) from None


# Require identity prices around the gap even when an events block omits an action.
def _check_gap_identity(fresh_rows, missing):
    first_missing = min(missing)
    preceding = [day for day in fresh_rows if day < first_missing]
    if not preceding:
        raise MarketDataUnavailableError(
            "no fresh observation precedes the missing gap"
        )
    boundary = max(preceding)
    for day, bar in fresh_rows.items():
        if day >= boundary and (
            not _valid_daily_bar(bar) or bar.adjusted_close != bar.close
        ):
            raise MarketDataUnavailableError(
                "fresh gap-neighborhood basis is not identity"
            )


# Check fresh provider identity, action evidence and the gap's adjustment basis.
def _fresh_repair_evidence(ticker, asof, fresh, missing):
    if fresh.ticker != ticker or fresh.source != "yahoo":
        raise MarketDataUnavailableError("same-provider source identity is unavailable")
    required = _repair_sessions(fresh, asof)
    fresh_rows = {bar.session_date: bar for bar in fresh.bars}
    if len(fresh_rows) != len(fresh.bars) or sorted(fresh_rows) != [
        bar.session_date for bar in fresh.bars
    ]:
        raise MarketDataUnavailableError(
            "fresh history has duplicate or unordered sessions"
        )
    _check_gap_identity(fresh_rows, missing)
    actions = _action_signature(fresh)
    if any(day >= min(missing) for day, _kind, _value in actions):
        raise MarketDataUnavailableError(
            "an action intersects the missing-session basis"
        )
    return required, fresh_rows, actions


# Require the retained source to agree without inferring a scale from price ratios.
def _check_retained_evidence(old, fresh, old_rows, fresh_rows, action_path, actions):
    if len(old_rows) != len(old.bars) or sorted(old_rows) != [
        bar.session_date for bar in old.bars
    ]:
        raise MarketDataUnavailableError(
            "retained history has duplicate or unordered sessions"
        )
    if (
        not action_path.exists()
        or old.source != fresh.source
        or old.ticker != fresh.ticker
    ):
        raise MarketDataUnavailableError(
            "retained provider/action evidence is unavailable"
        )
    if (
        not isinstance(old.source_time, datetime)
        or old.source_time.tzinfo is None
        or old.source_time.utcoffset() is None
        or not old.source_time <= fresh.source_time
    ):
        raise MarketDataUnavailableError("retained source time is invalid")
    if _action_signature(old) != actions:
        raise MarketDataUnavailableError("provider action lists disagree")
    common = set(old_rows) & set(fresh_rows)
    if not common:
        raise MarketDataUnavailableError(
            "provider vintages have no comparable observations"
        )
    raw_fields = ("open", "high", "low", "close", "volume")
    for day in common:
        if any(
            getattr(old_rows[day], field) != getattr(fresh_rows[day], field)
            for field in raw_fields
        ):
            raise MarketDataUnavailableError("overlapping raw observations changed")


# Find original identity-basis observations and keep their source fingerprints.
def _retained_repair_rows(store, ticker, asof, fresh, missing, fresh_rows, actions):
    sources = []
    insertions = {}
    for vintage in reversed(store.asofs()):
        if vintage >= asof or not store.has(vintage, ticker):
            continue
        old = store.read(ticker, vintage)
        old_rows = {bar.session_date: bar for bar in old.bars}
        candidates = (missing - set(insertions)) & set(old_rows)
        if not candidates:
            continue
        action_path = store._path("actions", vintage, ticker)
        _check_retained_evidence(old, fresh, old_rows, fresh_rows, action_path, actions)
        for day in candidates:
            bar = old_rows[day]
            if not _valid_daily_bar(bar) or bar.adjusted_close != bar.close:
                raise MarketDataUnavailableError(
                    "retained missing bar has unsupported price basis"
                )
            insertions[day] = bar
        sources.append(
            {
                "vintage": vintage.isoformat(),
                "source_time": old.source_time.isoformat(),
                "bars_sha256": hashlib.sha256(
                    store._path("bars", vintage, ticker).read_bytes()
                ).hexdigest(),
                "actions_sha256": hashlib.sha256(action_path.read_bytes()).hexdigest(),
                "sessions": sorted(day.isoformat() for day in candidates),
            }
        )
        if set(insertions) == missing:
            break
    if set(insertions) != missing:
        raise MarketDataUnavailableError(
            "retained observations do not cover every missing session"
        )
    return insertions, sources


# Restore only an observed unadjusted bar when both dated provider vintages agree.
def _reconcile_missing_sessions(store, ticker, asof, fresh, missing):
    required, fresh_rows, actions = _fresh_repair_evidence(ticker, asof, fresh, missing)
    insertions, sources = _retained_repair_rows(
        store, ticker, asof, fresh, missing, fresh_rows, actions
    )
    combined = {**fresh_rows, **insertions}
    if not required <= set(combined) or any(
        not _valid_daily_bar(combined[day]) for day in required
    ):
        raise MarketDataUnavailableError(
            "recovered recent exchange grid is incomplete or invalid"
        )
    recovered = replace(fresh, bars=tuple(combined[day] for day in sorted(combined)))
    receipt = {
        "version": "same-provider-identity-bar-reconciliation/1",
        "state": "prepared; verify output history hash before treating as published",
        "ticker": ticker,
        "asof": asof.isoformat(),
        "provider": fresh.source,
        "fresh_source_time": fresh.source_time.isoformat(),
        "fresh_parsed_history_sha256": _history_hash(fresh),
        "output_history_sha256": _history_hash(recovered),
        "retained_sources": sources,
        "restored_rows": [asdict(insertions[day]) for day in sorted(insertions)],
        "basis": "Identity basis; exact raw overlap/actions; no intervening action",
    }
    _write_reconciliation_receipt(store, asof, ticker, receipt)
    return recovered


# Fetch every requested ticker into the `asof` partition, capturing failures.
#
# Tickers the partition already holds are skipped, so a rerun is idempotent
# and a throttled run resumes where it stopped. `on_result` is called after
# each ticker so a CLI can print progress on a run that takes minutes.
def refresh(
    store: MarketStore,
    tickers: Sequence[str],
    asof: date | None = None,
    start: date = DEFAULT_START,
    *,
    fetcher: Fetcher | None = None,
    on_result: Callable[[RefreshResult], None] | None = None,
) -> RefreshReport:
    """Fetch and store daily history for each ticker into one as-of partition."""
    asof = asof or datetime.now(tz=UTC).date()
    if fetcher is None:
        pacer = Pacer()

        # The default fetcher: Yahoo, paced across the whole run.
        def fetcher(ticker: str, start_date: date, end_date: date) -> TickerHistory:
            return fetch_history(
                ticker, start_date, end_date, pacer=pacer, sleep=time.sleep
            )

    results: list[RefreshResult] = []
    for ticker in tickers:
        if store.has(asof, ticker):
            result = RefreshResult(
                ticker=ticker, bars_stored=0, skipped=True, error=None
            )
        else:
            try:
                history = _fetch_preserving_sessions(
                    store, ticker, start, asof, fetcher
                )
            except MarketDataUnavailableError as exc:
                result = RefreshResult(
                    ticker=ticker, bars_stored=0, skipped=False, error=str(exc)
                )
            else:
                store.write(asof, history)
                result = RefreshResult(
                    ticker=ticker,
                    bars_stored=len(history.bars),
                    skipped=False,
                    error=None,
                )
        results.append(result)
        if on_result is not None:
            on_result(result)
    return RefreshReport(asof=asof, results=tuple(results))


# The status of every requested ticker, judged against `today`: missing when
# no partition holds it, stale when its newest completed session is older
# than the staleness window.
def status(
    store: MarketStore,
    tickers: Sequence[str],
    today: date | None = None,
    asof: date | None = None,
) -> list[TickerStatus]:
    """Return one TickerStatus per requested ticker, stale and missing flagged."""
    today = today or datetime.now(tz=UTC).date()
    rows: list[TickerStatus] = []
    for ticker, stored in zip(tickers, store.describe(tickers, asof), strict=True):
        if stored is None:
            rows.append(
                TickerStatus(ticker, None, 0, None, None, missing=True, stale=True)
            )
            continue
        complete = stored.complete_through
        stale = complete is None or complete < today - timedelta(days=STALE_AFTER_DAYS)
        rows.append(
            TickerStatus(
                ticker,
                stored.asof,
                stored.bar_count,
                stored.first_session,
                complete,
                missing=False,
                stale=stale,
            )
        )
    rows.sort(key=lambda row: (row.complete_through or date.min, row.ticker))
    return rows
