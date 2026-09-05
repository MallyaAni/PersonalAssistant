"""Retention for runs: finished runs and their records age out.

A run's actions, approvals and events are the audit trail of what an agent
did under a person's authority. They are kept long enough to be read back
and no longer: a terminal run older than the retention window is deleted
with everything under it (the foreign keys cascade). Open runs are never
touched, whatever their age - a run waiting for a person's approval for a
month is a run that still needs an answer, not a row to sweep.

Reports by default and deletes only when asked, like the storage sweep
(`backend.cli.collect_storage`), so a wrong window is a number in a log
rather than a loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_run import AgentRun
from backend.runs.repository import TERMINAL_STATUSES


@dataclass(frozen=True, slots=True)
class RetentionReport:
    """What a sweep found, and what it did."""

    cutoff: datetime
    expired: int
    deleted: int


# Count, and when asked delete, terminal runs that finished before the cutoff.
async def sweep_runs(
    session: AsyncSession,
    *,
    keep_days: int,
    apply: bool = False,
    now: datetime | None = None,
) -> RetentionReport:
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(days=max(0, int(keep_days)))
    condition = (
        AgentRun.status.in_(tuple(TERMINAL_STATUSES))
        & AgentRun.completed_at.is_not(None)
        & (AgentRun.completed_at < cutoff)
    )
    expired = int(await session.scalar(select(func.count(AgentRun.id)).where(condition)) or 0)
    deleted = 0
    if apply and expired:
        rows = list((await session.execute(select(AgentRun).where(condition))).scalars())
        for run in rows:
            await session.delete(run)
            deleted += 1
        await session.commit()
    return RetentionReport(cutoff, expired, deleted)
