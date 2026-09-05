"""Daily market bars: one row per (ticker, session, source).

Raw daily OHLCV plus the source's adjusted close, the close a split or
dividend correction leaves continuous. Returns are always computed from
adjusted close so a split never manufactures a return. Source and
retrieved_at are stored so corrections are traceable: a bar can be re-fetched
and compared against what a previous run recorded.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base


class MarketDailyBar(Base):
    """One trading session of raw daily data for one ticker from one source."""

    __tablename__ = "market_daily_bars"
    __table_args__ = (
        UniqueConstraint(
            "ticker", "session_date", "source", name="uq_market_daily_bars_row"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjusted_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yahoo")
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
