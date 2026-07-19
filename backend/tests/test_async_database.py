import asyncio
from time import perf_counter

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, TimeoutError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.database.session import ASYNC_DATABASE_URL


# Verify the production pool stays bounded without blocking the event loop.
@pytest.mark.asyncio
async def test_bounded_async_pool_preserves_event_loop_responsiveness() -> None:
    local_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,
    )
    session_factory = async_sessionmaker(local_engine, expire_on_commit=False)
    active_connections = 0
    peak_connections = 0
    heartbeat_count = 0

    # Record each checked-out connection to measure peak pool use.
    @event.listens_for(local_engine.sync_engine, "checkout")
    def record_checkout(*_: object) -> None:
        nonlocal active_connections, peak_connections
        active_connections += 1
        peak_connections = max(peak_connections, active_connections)

    # Record each returned connection to verify the pool drains cleanly.
    @event.listens_for(local_engine.sync_engine, "checkin")
    def record_checkin(*_: object) -> None:
        nonlocal active_connections
        active_connections -= 1

    # Hold one pooled connection briefly through a real PostgreSQL query.
    async def run_slow_query() -> None:
        async with session_factory() as session:
            await session.execute(text("SELECT pg_sleep(0.1)"))

    # Count scheduler progress while database work is pending.
    async def run_heartbeat() -> None:
        nonlocal heartbeat_count
        deadline = perf_counter() + 0.12
        while perf_counter() < deadline:
            heartbeat_count += 1
            await asyncio.sleep(0.01)

    try:
        await asyncio.gather(
            *(run_slow_query() for _ in range(6)),
            run_heartbeat(),
        )
        assert peak_connections == 2
        assert active_connections == 0
        assert heartbeat_count >= 5
        assert local_engine.sync_engine.pool.checkedout() == 0
    finally:
        await local_engine.dispose()


# Verify an aborted transaction can roll back and reuse its async session.
@pytest.mark.asyncio
async def test_async_session_recovers_after_database_statement_failure() -> None:
    local_engine = create_async_engine(ASYNC_DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(local_engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(text("SELECT 1 / 0"))
            await session.rollback()
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await local_engine.dispose()


# Verify pool exhaustion times out, releases, and accepts a later query.
@pytest.mark.asyncio
async def test_async_pool_recovers_after_checkout_timeout() -> None:
    local_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.05,
    )
    try:
        async with local_engine.connect() as held_connection:
            assert await held_connection.scalar(text("SELECT 1")) == 1
            with pytest.raises(TimeoutError):
                async with local_engine.connect():
                    pass
        async with local_engine.connect() as recovered_connection:
            assert await recovered_connection.scalar(text("SELECT 1")) == 1
        assert local_engine.sync_engine.pool.checkedout() == 0
    finally:
        await local_engine.dispose()
