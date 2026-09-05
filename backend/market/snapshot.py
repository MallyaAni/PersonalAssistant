"""Refreshing and auditing the daily market snapshot.

Two operations. `refresh` fetches the universe from the data source and
stores the bars; a refused or unparseable ticker is recorded per-ticker
rather than failing the whole run. `status` reports, per ticker, whether
it has rows, how recent the newest is, and whether that is stale — so a
snapshot that stopped updating is visible instead of silently old. Returns
are computed by `daily_returns` from adjusted close, which is what makes a
split incapable of manufacturing a return.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from backend.market import repository
from backend.market.universe import STALE_AFTER_DAYS
from backend.market.yahoo import DailyBar, MarketDataUnavailable, fetch_daily_bars

# How much history a default refresh pulls per ticker, in calendar days.
DEFAULT_LOOKBACK_DAYS = 730


@dataclass(frozen=True, slots=True)
class TickerStatus:
    """What the store currently holds for one ticker."""

    ticker: str
    bar_count: int
    latest_session: date | None
    missing: bool
    stale: bool


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """The outcome of refreshing one ticker."""

    ticker: str
    bars_stored: int
    error: str | None


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """The outcome of refreshing a whole set of tickers."""

    results: tuple[RefreshResult, ...]

    @property
    def ok(self) -> bool:
        return all(result.error is None for result in self.results)

    @property
    def failed_tickers(self) -> tuple[str, ...]:
        return tuple(result.ticker for result in self.results if result.error)


# The log return between consecutive sessions, from adjusted close.
#
# Deterministic and split-safe: a 2:1 split changes the raw close by half
# overnight but leaves the adjusted close continuous, so the return series
# is identical with or without the split event. Bars whose adjusted close is
# unknown are skipped, never treated as a zero price.
def daily_returns(bars: Sequence[DailyBar]) -> list[tuple[date, float]]:
    """Return oldest-first (session_date, log return) pairs from adjusted close."""
    prices = [(bar.session_date, bar.adjusted_close) for bar in bars if bar.adjusted_close is not None]
    returns: list[tuple[date, float]] = []
    for (previous_date, previous), (current_date, current) in zip(prices, prices[1:]):
        if previous > 0 and current > 0:
            returns.append((current_date, _log(current / previous)))
    return returns


# A fixed-formula log, so a run is bit-for-bit reproducible and never drifts
# with a stdlib or platform change.
def _log(value: float) -> float:
    import math

    return math.log(value)


# Fetch and store one ticker's recent bars. A failure is captured, not raised.
async def _refresh_one(
    session: AsyncSession, ticker: str, lookback_days: int
) -> RefreshResult:
    try:
        bars = fetch_daily_bars(ticker, days=lookback_days)
    except MarketDataUnavailable as exc:
        return RefreshResult(ticker=ticker, bars_stored=0, error=str(exc))
    stored = await repository.upsert_bars(session, ticker, bars)
    return RefreshResult(ticker=ticker, bars_stored=stored, error=None)


# Refresh every requested ticker and report per-ticker outcomes.
async def refresh(
    session: AsyncSession,
    tickers: Sequence[str],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> RefreshReport:
    """Fetch and store daily bars for each ticker, capturing failures."""
    results: list[RefreshResult] = []
    for ticker in tickers:
        results.append(await _refresh_one(session, ticker, lookback_days))
    return RefreshReport(results=tuple(results))


# The status of one ticker in the store, judged against `today`.
async def _status_one(
    session: AsyncSession, ticker: str, today: date
) -> TickerStatus:
    latest = await repository.latest_session(session, ticker)
    bars = await repository.bars_for(session, ticker)
    if latest is None or not bars:
        return TickerStatus(ticker, 0, None, missing=True, stale=True)
    stale = latest < today - timedelta(days=STALE_AFTER_DAYS)
    return TickerStatus(ticker, len(bars), latest, missing=False, stale=stale)


# Report the store's state for every requested ticker, oldest-looking first.
async def status(
    session: AsyncSession, tickers: Sequence[str], today: date | None = None
) -> list[TickerStatus]:
    """Return one TickerStatus per requested ticker, stale and missing flagged."""
    if today is None:
        today = date.today()
    rows = [await _status_one(session, ticker, today) for ticker in tickers]
    rows.sort(key=lambda row: (row.latest_session or date.min, row.ticker))
    return rows
