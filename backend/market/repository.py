"""Storage for daily market bars.

One row per (ticker, session date, source), upserted so a re-fetch on the
same day refreshes a row rather than duplicating it — that is what makes a
snapshot reproducible: rerunning a date lands on the same rows. Bars are
read back as DailyBar values, the same shape the fetcher produces, so
nothing downstream sees a live ORM object.
"""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.market.yahoo import DailyBar
from backend.models.market_bar import MarketDailyBar


# Upsert one ticker's bars and return how many rows now exist for it.
#
# ON CONFLICT refreshes the price columns and retrieved_at so the stored row
# is always the latest fetch, while the unique key keeps a repeated run from
# creating a second row for the same session.
async def upsert_bars(
    session: AsyncSession,
    ticker: str,
    bars: Sequence[DailyBar],
    source: str = "yahoo",
) -> int:
    """Store (or refresh) one ticker's daily bars and return the row count."""
    if not bars:
        return await _row_count(session, ticker)
    statement = insert(MarketDailyBar).values(
        [
            {
                "ticker": ticker,
                "session_date": bar.session_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adjusted_close": bar.adjusted_close,
                "volume": bar.volume,
                "source": source,
            }
            for bar in bars
        ]
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_market_daily_bars_row",
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "adjusted_close": statement.excluded.adjusted_close,
            "volume": statement.excluded.volume,
            "retrieved_at": func.now(),
        },
    )
    await session.execute(statement)
    await session.commit()
    return await _row_count(session, ticker)


async def _row_count(session: AsyncSession, ticker: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(MarketDailyBar).where(
            MarketDailyBar.ticker == ticker
        )
    )
    return int(result.scalar_one())


# The most recent stored session for a ticker, or None if it has none.
async def latest_session(session: AsyncSession, ticker: str) -> date | None:
    """Return the newest stored session date for one ticker, or None."""
    result = await session.execute(
        select(func.max(MarketDailyBar.session_date)).where(
            MarketDailyBar.ticker == ticker
        )
    )
    return result.scalar_one()


# Every stored bar for one ticker, oldest-first, as DailyBar values.
async def bars_for(
    session: AsyncSession,
    ticker: str,
    since: date | None = None,
) -> list[DailyBar]:
    """Return one ticker's stored bars, oldest-first, as DailyBar values."""
    statement = (
        select(MarketDailyBar)
        .where(MarketDailyBar.ticker == ticker)
        .order_by(MarketDailyBar.session_date)
    )
    if since is not None:
        statement = statement.where(MarketDailyBar.session_date >= since)
    rows = (await session.execute(statement)).scalars().all()
    return [
        DailyBar(
            session_date=row.session_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            adjusted_close=row.adjusted_close,
            volume=row.volume,
        )
        for row in rows
    ]


# Remove every stored bar for one ticker. Used by tests on synthetic tickers
# and by an operator who wants to force a clean re-fetch.
async def delete_for(session: AsyncSession, ticker: str) -> int:
    """Delete all stored bars for one ticker and return the deleted count."""
    result = await session.execute(
        delete(MarketDailyBar).where(MarketDailyBar.ticker == ticker)
    )
    await session.commit()
    return int(result.rowcount or 0)
