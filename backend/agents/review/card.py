"""How the code reviewer reports itself to the workspace.

Its state is read from the run rows it leaves behind: how many reviews it
has run for this person, whether one is running now, and how many findings
the last completed one kept.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import AgentFact, AgentStatus, AgentSummary
from backend.models.agent_run import AgentRun

KIND = "code_review"


# Report the reviewer's live state for one user, from its own run rows.
async def describe(session: AsyncSession, user_id: str) -> AgentSummary:
    total = int(
        await session.scalar(
            select(func.count(AgentRun.id)).where(
                (AgentRun.user_id == user_id) & (AgentRun.kind == KIND)
            )
        )
        or 0
    )
    running = int(
        await session.scalar(
            select(func.count(AgentRun.id)).where(
                (AgentRun.user_id == user_id)
                & (AgentRun.kind == KIND)
                & (AgentRun.status.in_(("queued", "running", "waiting_approval")))
            )
        )
        or 0
    )
    latest = await session.scalar(
        select(AgentRun)
        .where((AgentRun.user_id == user_id) & (AgentRun.kind == KIND) & (AgentRun.status == "completed"))
        .order_by(AgentRun.completed_at.desc())
        .limit(1)
    )
    status: AgentStatus = "working" if running else "idle"
    detail = (
        "Reviewing a commit now."
        if running
        else "Ready. Point it at a commit and it reads the change and reports what is wrong."
    )
    facts: list[AgentFact] = [AgentFact("Reviews", str(total))] if total else []
    if latest is not None and latest.result:
        import json

        try:
            evidence: dict[str, Any] = json.loads(latest.result).get("evidence") or {}
            facts.append(AgentFact("Last findings", str(len(evidence.get("findings") or []))))
        except ValueError:
            pass
    return AgentSummary(
        id="review",
        name="Reviewer",
        role=(
            "A code reviewer. Given one commit, it reads the change and the "
            "files around it through a read-only window onto the repository, "
            "reports the defects it can point at - file, line, and the line "
            "of code that shows it - and drops any finding whose evidence is "
            "not actually there. It changes nothing in the repository."
        ),
        status=status,
        detail=detail,
        trigger="On request, per commit",
        setup_needs="a repository the read-only repo server is rooted at",
        facts=tuple(facts),
        last_active_at=latest.completed_at if latest is not None else None,
    )
