"""How Scout reports itself to the workspace.

Scout's status is genuinely three-valued — unconfigured, scheduled, or running —
and conflating them would hide the most common failure, which is having no
sources.

Only the *card* lives here. Scout's sweep is a domain process run by a worker
rather than by the chat graph, so it stays in `backend/discovery/`: this package
depends on that one, and reversing any part of it would make the two import each
other.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.cards import AgentFact, AgentStatus, AgentSummary, count_rows
from backend.agents.cards import relative_when as _when
from backend.config.settings import settings
from backend.discovery.reachability import (
    calendar_base_url,
    is_reachable_from_other_devices,
)
from backend.models.discovery import DiscoveryInterest
from backend.models.discovery_run import DiscoveryRun, DiscoverySchedule
from backend.models.discovery_source import DiscoverySource
from backend.models.discovery_subscriber import DiscoverySubscriber

# How many interest labels the agent's line will name before summarising.
_NAMED_INTERESTS = 12


# Name the interests in the agent's own line, bounded.
#
# Asked "what are my interests?" the assistant answered "I don't actually have
# a list of your interests" and in the same reply reported that Scout tracks
# ten - it had the count and no way to read the labels. Bounded because this
# reaches every reply's prompt: enough to answer with, not the whole table.
def _following(labels: list[str]) -> str:
    if not labels:
        return ""
    shown = ", ".join(labels[:_NAMED_INTERESTS])
    if len(labels) > _NAMED_INTERESTS:
        shown += f", and {len(labels) - _NAMED_INTERESTS} more"
    return f" Following: {shown}."


# Report Scout's live state for one user, read from the tables it writes.
async def describe(session: AsyncSession, user_id: str) -> AgentSummary:
    sources = await count_rows(session, DiscoverySource, user_id)
    # The labels, not only how many. Asked "what are my interests?", the
    # assistant answered "I don't actually have a list of your interests" and
    # then, in the same reply, reported that Scout tracks ten of them - it had
    # the count and no way to read the names. The agent that owns them is the
    # one place they can come from.
    followed = (
        (
            await session.execute(
                select(DiscoveryInterest.label)
                .where(DiscoveryInterest.user_id == user_id)
                .order_by(DiscoveryInterest.created_at)
            )
        )
        .scalars()
        .all()
    )
    labels = [str(label).strip() for label in followed if str(label or "").strip()]
    interests = len(labels)
    subscribers = await count_rows(session, DiscoverySubscriber, user_id)
    schedule = await session.scalar(
        select(DiscoverySchedule).where(DiscoverySchedule.user_id == user_id)
    )
    latest = await session.scalar(
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

    detail += _following(labels)

    if not settings.DISCOVERY_EGRESS_ENABLED and subscribers:
        detail += " Delivery is off, so nothing is sent."
    # A calendar link that only resolves on this machine is dead on the phone it
    # was sent to, and nothing about the send would reveal that.
    base = calendar_base_url(settings.DISCOVERY_CALENDAR_BASE_URL)
    reachable = is_reachable_from_other_devices(base)
    if not reachable:
        detail += (
            " Calendar links will not open on a phone —"
            " set DISCOVERY_CALENDAR_BASE_URL to this machine's address."
        )
    facts.append(
        AgentFact("Calendar links", _link_host(base) if reachable else "unreachable")
    )

    return AgentSummary(
        id="discovery",
        name="Scout",
        role=(
            "Scout is the standing-work agent: anything that should happen on "
            "a schedule rather than right now. That covers a recurring sweep "
            "for things happening near you that match your interests, each "
            "turned into a calendar entry, and equally a recurring search, "
            "lookup, or report on any subject at all. Interests are what the "
            "events sweep needs; they are not a requirement for scheduling "
            "something, and no subject is out of scope."
        ),
        status=status,
        detail=detail,
        trigger="Weekly schedule" if schedule else "On request",
        setup_needs=(
            "for the events sweep: interests to follow, a home locality, a "
            "cadence with an hour and timezone, and somewhere to deliver to. "
            "Scheduling anything else needs none of those - only a time and "
            "what to do"
        ),
        last_active_at=latest.completed_at if latest else None,
        facts=tuple(facts),
    )


# Whether a sweep could find anything without a configured feed.
def _can_search() -> bool:
    return settings.DISCOVERY_WEB_SEARCH_ENABLED


# Just the host, so the card shows where links point without a URL in it.
def _link_host(base_url: str) -> str:
    without_scheme = base_url.split("://", 1)[-1]
    return without_scheme.split("/", 1)[0] or base_url
