"""How the trading analyst reports itself to the workspace.

The trading agent reads the person's own history — uploaded statements,
journals, notes — from the shared knowledge store, so its state is read from
that store rather than from a table of its own. The one thing that changes
whether it can work is whether the person has shared any history at all: with
none it is needs_setup, and with some it is idle and ready to be asked.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import AgentFact, AgentStatus, AgentSummary, count_rows
from backend.models.agent_memory import KnowledgeDocument


# Report the trading analyst's live state for one user: how much history it
# has to read, read from the same table an autopsy searches.
async def describe(session: AsyncSession, user_id: str) -> AgentSummary:
    documents = await count_rows(session, KnowledgeDocument, user_id)

    if documents == 0:
        status: AgentStatus = "needs_setup"
        detail = "Share a statement or a trade journal and it can read your history."
    else:
        status = "idle"
        detail = "Ready. Ask it to analyze your trading."
    # The chunk count is only meaningful when there are documents; without any,
    # showing zero reads as "there is nothing here" rather than as a count.
    facts = (
        (AgentFact("Documents", str(documents)),)
        if documents
        else ()
    )

    return AgentSummary(
        id="trading",
        name="Trading",
        role=(
            "A personal trading analyst. It reads your own history — uploaded "
            "statements, journals, notes about why you entered, held, or "
            "exited positions — and names the behaviours that repeat, what "
            "they have cost, and what to stop, start, and keep. It decides "
            "nothing for you and trades nothing; it tells you what your own "
            "record keeps doing."
        ),
        status=status,
        detail=detail,
        trigger="On request",
        setup_needs=(
            "a statement or trade journal shared with it, so it has a record "
            "to read"
        ),
        facts=facts,
    )
