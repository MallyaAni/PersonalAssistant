"""How the security agent reports itself to the workspace.

Read from its run rows and from the operator's list of authorized assets:
with no asset authorized it needs setup, because a run naming anything is
refused before a tool is called.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import AgentFact, AgentStatus, AgentSummary
from backend.agents.security.world import KIND, authorized_assets
from backend.models.agent_run import AgentRun


# Report the security agent's live state for one user.
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
    assets = authorized_assets()
    if not assets:
        status: AgentStatus = "needs_setup"
        detail = "Name the assets it may investigate (SECURITY_AUTHORIZED_ASSETS) and it can start."
    elif running:
        status = "working"
        detail = "Investigating a commit now."
    else:
        status = "idle"
        detail = f"Ready for {len(assets)} authorized asset{'s' if len(assets) != 1 else ''}."
    facts = [AgentFact("Authorized assets", ", ".join(sorted(assets)) or "none")]
    if total:
        facts.append(AgentFact("Investigations", str(total)))
    return AgentSummary(
        id="security",
        name="Security",
        role=(
            "A security investigator. Given one commit of an authorized "
            "repository, it reads the change through a read-only window, "
            "searches it for lines shaped like secrets and dangerous calls, "
            "judges each with the code around it, and reports the weaknesses "
            "it can point at - file, line, and the line that shows it. It "
            "refuses anything outside the assets it was given and changes "
            "nothing."
        ),
        status=status,
        detail=detail,
        trigger="On request, per commit of an authorized asset",
        setup_needs="the assets it may investigate, named by the operator",
        facts=tuple(facts),
    )
