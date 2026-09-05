"""Daily market bars, the raw material of the stock-analysis research.

Revision ID: 20260905_0018
Revises: 20260902_0017

A new table only; nothing the running system reads is changed, so this is
safe to apply ahead of a deploy whose gate will start exercising it. Stores
one row per (ticker, session date, source) of raw daily OHLCV plus the
adjusted close the research pipeline computes returns from.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0018"
down_revision: str | Sequence[str] | None = "20260902_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_daily_bars",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("adjusted_close", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "ticker", "session_date", "source", name="uq_market_daily_bars_row"
        ),
    )
    op.create_index("ix_market_daily_bars_ticker", "market_daily_bars", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_market_daily_bars_ticker", table_name="market_daily_bars")
    op.drop_table("market_daily_bars")
