from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


# Serialize a transaction around a stable key built from the supplied parts.
async def transaction_advisory_lock(session: AsyncSession, *parts: str) -> None:
    """Serialize a PostgreSQL natural-key mutation, including its first insert."""
    lock_key = "".join(f"{len(part)}:{part}" for part in parts)
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0)))
    )
