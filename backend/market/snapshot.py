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

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

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
                history = fetcher(ticker, start, asof)
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
