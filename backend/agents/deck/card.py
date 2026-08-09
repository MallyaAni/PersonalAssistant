"""How Deck reports itself to the workspace.

Deck is request-driven, so "scheduled" is never one of its states.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import AgentFact, AgentStatus, AgentSummary
from backend.config.settings import settings
from backend.models.presentation import PresentationJob


# Report Deck's live state for one user, read from its own job table.
async def describe(session: AsyncSession, user_id: str) -> AgentSummary:
    active = await session.scalar(
        select(func.count(PresentationJob.id)).where(
            PresentationJob.user_id == user_id,
            PresentationJob.status.in_(("queued", "running")),
        )
    )
    latest = await session.scalar(
        select(PresentationJob)
        .where(PresentationJob.user_id == user_id)
        .order_by(PresentationJob.created_at.desc())
        .limit(1)
    )
    completed = await session.scalar(
        select(func.count(PresentationJob.id)).where(
            PresentationJob.user_id == user_id,
            PresentationJob.status == "ready",
        )
    )

    facts = [AgentFact("Decks built", str(completed or 0))]
    if latest is not None:
        facts.append(AgentFact("Last job", latest.status))
    # What the agent is actually configured to do, read from settings rather
    # than described, so the card cannot claim a behaviour it does not have.
    facts.append(
        AgentFact(
            "Auto images",
            (
                f"up to {settings.PRESENTATION_AUTO_IMAGE_MAX}"
                if settings.PRESENTATION_AUTO_IMAGE_MAX
                else "off"
            ),
        )
    )

    if active:
        status: AgentStatus = "working"
        detail = f"Building {active} deck{'s' if active > 1 else ''} now."
    elif latest is not None and latest.status == "failed":
        status = "idle"
        detail = "The last deck failed. Ask again to retry."
    else:
        status = "idle"
        detail = "Ready. Ask for a deck in chat."

    return AgentSummary(
        id="presentation",
        name="Deck",
        role=(
            "Plans and builds editable presentations in its own worker, so a "
            "long build never blocks the conversation."
        ),
        status=status,
        detail=detail,
        trigger="Delegated from chat",
        last_active_at=latest.created_at if latest else None,
        facts=tuple(facts),
        # Agents is a control surface; a deck is an artifact you keep, edit, and
        # download. The card points at that workspace rather than nesting an
        # editor inside an agent listing.
        opens_view="presentations",
    )
