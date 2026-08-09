"""What every agent card is made of.

The shapes here are the contract between the agent layer and the workspace tab:
an agent describes itself as a status, a line of detail, and some labelled
readings. Nothing in this module knows which agents exist — that is each agent's
own business, in its own folder.

Splitting this out is what lets adding an agent be adding a folder. Before, the
types, the registry, and every agent's describer shared one 262-line module, so
a new agent meant editing the file that all the others live in.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

AgentStatus = Literal["idle", "working", "scheduled", "needs_setup", "disabled"]


@dataclass(frozen=True, slots=True)
class AgentFact:
    """One labelled reading about an agent, shown as-is."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class AgentSummary:
    """One specialized agent as the workspace presents it."""

    id: str
    name: str
    role: str
    status: AgentStatus
    # What it is waiting on or doing, in one line the user can act on.
    detail: str
    trigger: str
    last_active_at: datetime | None = None
    facts: tuple[AgentFact, ...] = field(default=())
    # Which workspace view holds this agent's output, when it has one elsewhere.
    opens_view: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "status": self.status,
            "detail": self.detail,
            "trigger": self.trigger,
            "last_active_at": (
                self.last_active_at.isoformat() if self.last_active_at else None
            ),
            "facts": [{"label": f.label, "value": f.value} for f in self.facts],
            "opens_view": self.opens_view,
        }


class AgentDescriber(Protocol):
    """How an agent reports itself.

    Every field an agent returns is read from the tables it actually writes, so
    a card cannot drift from reality by being updated in the wrong place. An
    agent that has stopped working shows as broken rather than showing whatever
    it last claimed.
    """

    async def __call__(self, session: AsyncSession, user_id: str) -> AgentSummary: ...


# Count one user's rows in a table an agent owns.
async def count_rows(session: AsyncSession, model: Any, user_id: str) -> int:
    value = await session.scalar(
        select(func.count(model.id)).where(model.user_id == user_id)
    )
    return int(value or 0)


# A short relative phrase. Absolute timestamps are the wrong unit for "when will
# this happen next" and force the reader to do arithmetic.
def relative_when(moment: datetime | None) -> str:
    if moment is None:
        return "not scheduled"
    now = datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    seconds = (moment - now).total_seconds()
    if seconds <= 0:
        return "due now"
    if seconds < 3_600:
        return f"in {max(int(seconds // 60), 1)} min"
    if seconds < 86_400:
        return f"in {int(seconds // 3_600)} h"
    return f"in {int(seconds // 86_400)} d"
