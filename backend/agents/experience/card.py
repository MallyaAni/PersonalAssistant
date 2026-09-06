"""How the experience reviewer reports itself to the workspace."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import AgentFact, AgentStatus, AgentSummary
from backend.agents.experience.world import KIND
from backend.config.settings import settings
from backend.models.agent_run import AgentRun


# Report the reviewer's live state for one person.
async def describe(session: AsyncSession, user_id: str) -> AgentSummary:
    total = int(
        await session.scalar(
            select(func.count(AgentRun.id)).where((AgentRun.user_id == user_id) & (AgentRun.kind == KIND))
        )
        or 0
    )
    open_runs = int(
        await session.scalar(
            select(func.count(AgentRun.id)).where(
                (AgentRun.user_id == user_id)
                & (AgentRun.kind == KIND)
                & (AgentRun.status.in_(("queued", "running", "waiting_approval")))
            )
        )
        or 0
    )
    if not settings.AGENT_EXPERIENCE_REVIEW_ENABLED:
        status: AgentStatus = "needs_setup"
        detail = "Turn on AGENT_EXPERIENCE_REVIEW_ENABLED and it reviews each day's conversations."
    elif open_runs:
        status = "working"
        detail = "Reviewing recent conversations now, or waiting for a yes on a fix."
    else:
        status = "idle"
        detail = f"Reviews each day at {settings.AGENT_EXPERIENCE_REVIEW_HOUR_UTC:02d}:00 UTC."
    facts = []
    if total:
        facts.append(AgentFact("Reviews", str(total)))
    return AgentSummary(
        id="experience",
        name="Experience review",
        role=(
            "Reads each day's conversations for places the assistant let you "
            "down - a picture it never saw, a reminder it mistook for a habit, "
            "a correction it kept ignoring, something it wrongly remembered - "
            "names the cause from the turn's own record, and puts right what it "
            "can: a wrong memory is forgotten once you say yes; anything else "
            "is reported with the exchanges that show it."
        ),
        status=status,
        detail=detail,
        trigger="Daily, and on request",
        setup_needs="nothing beyond being switched on",
        facts=tuple(facts),
    )
