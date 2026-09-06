"""How the trading analyst reports itself to the workspace.

The trading agent has two capabilities. The desk grades the AI-and-software
book every session and needs nothing from the person: its state is the
record `market_daily` wrote, and it belongs to the operator alone. The
autopsy reads the person's own history (statements, journals, notes) from
the shared knowledge store to name what their trading keeps doing; that
history is optional and only the autopsy needs it.
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import AgentFact, AgentStatus, AgentSummary, count_rows
from backend.config.settings import settings
from backend.market import deskrecord
from backend.models.agent_memory import KnowledgeDocument


# Report the trading agent's live state for one user: the desk's latest
# record for the operator, and how much history the autopsy has to read.
async def describe(session: AsyncSession, user_id: str) -> AgentSummary:
    documents = await count_rows(session, KnowledgeDocument, user_id)
    status: AgentStatus = "idle"
    detail = "Ready. Ask it to analyze your trading."
    facts: tuple[AgentFact, ...] = (
        (AgentFact("Documents", str(documents)),) if documents else ()
    )
    opens_view = None
    # The desk's latest record, for the operator only: the session, the grade
    # counts and the book, read from the file the desk wrote so the card
    # cannot claim a book the desk does not hold.
    latest = None
    if user_id == settings.MARKET_DESK_USER:
        latest, _previous = deskrecord.latest_pair(Path(settings.MARKET_DATA_ROOT))
    if latest is not None:
        headline = deskrecord.summary(latest)
        counts = headline["counts"]
        facts = facts + (
            AgentFact("Desk session", str(headline["session"])),
            AgentFact(
                "Grades",
                f"{counts.get('A+', 0)} A+, {counts.get('A', 0)} A, "
                f"{counts.get('B', 0)} B, {counts.get('C', 0)} C",
            ),
            AgentFact(
                "Book",
                f"{len(headline['names'])} names, gross {headline['gross']:.2f}",
            ),
        )
        detail = f"Desk as of {headline['session']}: " + (
            ", ".join(headline["names"][:5]) or "nothing held"
        )
        opens_view = "desk"
    elif user_id == settings.MARKET_DESK_USER:
        detail = "No desk record yet; the after-close run writes one each session."

    return AgentSummary(
        id="trading",
        name="Trading",
        role=(
            "The trading desk: it grades the AI-and-software names every "
            "session on filings, the tape and what companies say in their "
            "releases, sizes a book by risk, and explains each grade. It also "
            "reads your own history when you share it, to name what your "
            "trading keeps doing. It places no orders."
        ),
        status=status,
        detail=detail,
        trigger="After each close, and on request",
        # Nothing is required: statements or a journal are optional and only
        # feed the autopsy of past trades.
        setup_needs="",
        facts=facts,
        opens_view=opens_view,
    )
