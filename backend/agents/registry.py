"""What specialized agents exist, and what each one is currently doing.

This is a description of the system rather than a second source of truth. Every
field is read from the tables the agent itself writes, so the tab cannot drift
from reality by being updated in the wrong place — an agent that stops working
shows as broken here rather than showing whatever it last claimed.

Adding an agent means adding a describer, not a database row.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.discovery.reachability import (
    calendar_base_url,
    is_reachable_from_other_devices,
)
from backend.models.discovery import DiscoveryInterest
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule
from backend.models.discovery_source import DiscoverySource
from backend.models.discovery_subscriber import DiscoverySubscriber
from backend.models.presentation import PresentationJob

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
        }


class AgentRegistry:
    """Read the live state of every specialized agent for one user."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def describe_all(self, user_id: str) -> tuple[AgentSummary, ...]:
        return (
            await self._describe_discovery(user_id),
            await self._describe_presentation(user_id),
        )

    # Scout: the ambient discovery loop. Its status is genuinely three-valued —
    # unconfigured, scheduled, or running — and conflating them would hide the
    # most common failure, which is having no sources.
    async def _describe_discovery(self, user_id: str) -> AgentSummary:
        sources = await self._count(DiscoverySource, user_id)
        interests = await self._count(DiscoveryInterest, user_id)
        subscribers = await self._count(DiscoverySubscriber, user_id)
        schedule = await self.session.scalar(
            select(DiscoverySchedule).where(DiscoverySchedule.user_id == user_id)
        )
        latest = await self.session.scalar(
            select(DiscoveryRun)
            .where(DiscoveryRun.user_id == user_id)
            .order_by(DiscoveryRun.scheduled_for.desc())
            .limit(1)
        )

        facts = [
            AgentFact("Feeds", str(sources)),
            AgentFact("Interests", str(interests)),
            AgentFact("Subscribers", str(subscribers)),
        ]
        if latest is not None:
            facts.append(AgentFact("Last run", latest.status))
            facts.append(AgentFact("Found", str(latest.candidate_count)))

        if latest is not None and latest.status == "running":
            status: AgentStatus = "working"
            detail = "Sweeping feeds now."
        elif interests == 0 or (sources == 0 and not _can_search()):
            status = "needs_setup"
            missing = []
            if interests == 0:
                missing.append("an interest")
            # A feed is only required when search cannot enumerate. With search
            # available, interests and a place are enough — demanding a feed here
            # would send the user hunting for .ics URLs they do not need.
            if sources == 0 and not _can_search():
                missing.append("a feed")
            detail = f"Add {' and '.join(missing)} before it can find anything."
        elif schedule is None or not schedule.enabled:
            status = "idle"
            detail = "No schedule set, so it only runs when asked."
        else:
            status = "scheduled"
            detail = f"Next sweep {_when(schedule.next_run_at)}."

        if not settings.DISCOVERY_EGRESS_ENABLED and subscribers:
            detail += " Delivery is off, so nothing is sent."
        # A calendar link that only resolves on this machine is dead on the
        # phone it was sent to, and nothing about the send would reveal that.
        base = calendar_base_url(settings.DISCOVERY_CALENDAR_BASE_URL)
        reachable = is_reachable_from_other_devices(base)
        if not reachable:
            detail += (
                " Calendar links will not open on a phone —"
                " set DISCOVERY_CALENDAR_BASE_URL to this machine's address."
            )
        facts.append(
            AgentFact(
                "Calendar links", _link_host(base) if reachable else "unreachable"
            )
        )

        return AgentSummary(
            id="discovery",
            name="Scout",
            role=(
                "Finds things happening near you that match what you like, "
                "and turns each one into a calendar entry."
            ),
            status=status,
            detail=detail,
            trigger="Weekly schedule" if schedule else "On request",
            last_active_at=latest.completed_at if latest else None,
            facts=tuple(facts),
        )

    # Deck: the presentation specialist. It is request-driven, so "scheduled" is
    # never one of its states.
    async def _describe_presentation(self, user_id: str) -> AgentSummary:
        active = await self.session.scalar(
            select(func.count(PresentationJob.id)).where(
                PresentationJob.user_id == user_id,
                PresentationJob.status.in_(("queued", "running")),
            )
        )
        latest = await self.session.scalar(
            select(PresentationJob)
            .where(PresentationJob.user_id == user_id)
            .order_by(PresentationJob.created_at.desc())
            .limit(1)
        )
        completed = await self.session.scalar(
            select(func.count(PresentationJob.id)).where(
                PresentationJob.user_id == user_id,
                PresentationJob.status == "ready",
            )
        )

        facts = [AgentFact("Decks built", str(completed or 0))]
        if latest is not None:
            facts.append(AgentFact("Last job", latest.status))

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
        )

    async def _count(self, model: Any, user_id: str) -> int:
        value = await self.session.scalar(
            select(func.count(model.id)).where(model.user_id == user_id)
        )
        return int(value or 0)


# Whether a sweep could find anything without a configured feed.
def _can_search() -> bool:
    return settings.DISCOVERY_WEB_SEARCH_ENABLED


# Just the host, so the card shows where links point without a URL in it.
def _link_host(base_url: str) -> str:
    without_scheme = base_url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0] or base_url


# A short relative phrase. Absolute timestamps are the wrong unit for "when will
# this happen next" and force the reader to do arithmetic.
def _when(moment: datetime | None) -> str:
    if moment is None:
        return "not scheduled"
    now = datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    delta = moment - now
    seconds = delta.total_seconds()
    if seconds <= 0:
        return "due now"
    if seconds < 3_600:
        return f"in {max(int(seconds // 60), 1)} min"
    if seconds < 86_400:
        return f"in {int(seconds // 3_600)} h"
    return f"in {int(seconds // 86_400)} d"
