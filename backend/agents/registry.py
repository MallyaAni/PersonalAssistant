"""What specialized agents exist, and what each one is currently doing.

This is a description of the system rather than a second source of truth. Every
field is read from the tables the agent itself writes, so the tab cannot drift
from reality by being updated in the wrong place — an agent that stops working
shows as broken here rather than showing whatever it last claimed.

**Adding an agent means adding a folder**, and one line below. Nothing else in
this module knows anything about any particular agent: the shapes live in
`cards.py`, and each agent's own reading of itself lives in `agents/<name>/`.
It used to all share one module, so every new agent meant editing the file every
other agent lived in.

The dependency runs one way and has to keep doing so. This layer imports domain
packages — `discovery`, `presentations` — and none of them import back. An
agent's *decisions* belong in its folder here; the machinery it drives belongs
in its domain package.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import (
    AgentDescriber,
    AgentFact,
    AgentStatus,
    AgentSummary,
)
from backend.agents.deck import card as deck_card
from backend.agents.scout import card as scout_card

# Every agent the workspace shows, in the order it shows them. This tuple is the
# whole registration mechanism, deliberately: a list that can be read in one
# glance beats discovery-by-import-scanning, which fails silently when a module
# is renamed.
DESCRIBERS: tuple[AgentDescriber, ...] = (
    scout_card.describe,
    deck_card.describe,
)

# Re-exported so callers depend on `backend.agents` for agent shapes rather than
# reaching into `cards` directly.
__all__ = [
    "DESCRIBERS",
    "AgentFact",
    "AgentRegistry",
    "AgentStatus",
    "AgentSummary",
]


class AgentRegistry:
    """Read the live state of every specialized agent for one user."""

    def __init__(
        self,
        session: AsyncSession,
        describers: tuple[AgentDescriber, ...] | None = None,
    ) -> None:
        self.session = session
        # Injectable so a test can describe one agent without standing up the
        # tables every other agent reads.
        self.describers = DESCRIBERS if describers is None else describers

    async def describe_all(self, user_id: str) -> tuple[AgentSummary, ...]:
        return tuple(
            [await describe(self.session, user_id) for describe in self.describers]
        )
