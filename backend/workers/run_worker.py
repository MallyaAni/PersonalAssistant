"""Host durable runs: claim the oldest, hold the lease, drive it, close it.

Runs live in the discovery worker's process, on their own loop, like the
scheduled tasks and the iMessage conversation do: each wants its own poll
rhythm and none should starve another. Which agent runs a run is decided by
its `kind`, looked up in the registry of worlds; a kind nobody registered
fails the run rather than guessing.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from backend.config.settings import settings
from backend.core.logging_config import get_logger
from backend.database.session import AsyncSessionLocal
from backend.runs.controller import RunController
from backend.runs.delivery import RunDelivery
from backend.runs.grants import Grant, grant_of
from backend.runs.repository import AgentRunRepository
from backend.runs.worlds import RunWorld, WorldFactory

logger = get_logger(__name__)

# Every kind of run this process can host, in one place, so the roster is
# readable in a glance. Each factory builds the agent's world for one run
# from the shared collaborators - the invocation boundary and the structured
# model - which is all a world may reach.
def _code_review(run: dict) -> RunWorld:
    from backend.agents.review.prompts import ReviewPrompts
    from backend.agents.review.world import ReviewWorld
    from backend.core.dependencies import (
        get_mcp_invocation_service,
        get_structured_llm_client,
    )

    return ReviewWorld(
        run, get_mcp_invocation_service(), ReviewPrompts(get_structured_llm_client())
    )


def _security_review(run: dict) -> RunWorld:
    from backend.agents.review.prompts import ReviewPrompts
    from backend.agents.security.world import SecurityWorld
    from backend.core.dependencies import (
        get_mcp_invocation_service,
        get_structured_llm_client,
    )

    return SecurityWorld(
        run,
        get_mcp_invocation_service(),
        ReviewPrompts(get_structured_llm_client(), findings_prompt="security/findings"),
    )


def _chat_continuation(run: dict) -> RunWorld:
    from backend.agents.chat.client import HttpStepClient
    from backend.agents.chat.world import ChatContinuationWorld

    return ChatContinuationWorld(run, HttpStepClient())


def _experience_review(run: dict) -> RunWorld:
    from backend.agents.experience.prompts import ExperiencePrompts
    from backend.agents.experience.world import ExperienceWorld
    from backend.core.dependencies import get_structured_llm_client

    return ExperienceWorld(run, AsyncSessionLocal, ExperiencePrompts(get_structured_llm_client()))


WORLDS: dict[str, WorldFactory] = {
    "code_review": _code_review,
    "security_review": _security_review,
    "chat_continuation": _chat_continuation,
    "experience_review": _experience_review,
}


# What a continuation of a chat turn may call: the built-in tools whose
# contracts allow a later step with the run's whole budget in hand, and reads
# through any MCP server (the world names a toolbox step by its effect).
def _chat_grant() -> Grant:
    from backend.tools import discuss_image as discuss_image_tool
    from backend.tools import show_image as show_image_tool
    from backend.tools.registry import later_step_tools

    # The two picture tools the loop's executor does not carry out are not
    # granted either, so the wall matches what the turn itself may do.
    names = later_step_tools(float(settings.AGENT_RUN_DEFAULT_BUDGET_SECONDS)) - {
        show_image_tool.NAME, discuss_image_tool.NAME,
    }
    return grant_of(*names, "mcp:read")

# What each kind may call, fixed here and enforced by the controller: the
# read tools of the repo server and the kind's own analysis steps, nothing
# else. A world that asks for anything outside its grant ends its run with
# `unauthorized_tool`, whatever talked it into asking.
GRANTS: dict[str, Grant] = {
    "code_review": grant_of(
        "repo_show_commit", "repo_diff", "repo_read_file", "review_findings"
    ),
    "security_review": grant_of(
        "repo_show_commit", "repo_diff", "repo_read_file", "repo_grep",
        "security_findings", "security_judge_hits",
    ),
    "chat_continuation": _chat_grant(),
    "experience_review": grant_of("turns_read", "experience_judge", "memory_forget", "experience_report"),
}


# ------------------------------------------------------- the daily review
#
# One experience review per person per day, for everyone who spoke to the
# assistant in the last day. Created, not run, here: the run loop claims it
# like any other. Idempotent on (person, day), so a restart never doubles it.
async def schedule_experience_reviews(now: datetime | None = None) -> int:
    from sqlalchemy import func, select

    from backend.models.agent_run import AgentRun
    from backend.models.conversation import Conversation

    moment = now or datetime.now(UTC)
    if moment.hour != int(settings.AGENT_EXPERIENCE_REVIEW_HOUR_UTC):
        return 0
    since = moment - timedelta(hours=24)
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    created = 0
    async with AsyncSessionLocal() as db:
        spoke = (
            await db.execute(
                select(Conversation.user_id, func.max(Conversation.created_at))
                .where(Conversation.created_at >= since.replace(tzinfo=None))
                .group_by(Conversation.user_id)
            )
        ).all()
        people = [str(user) for user, _ in spoke if not str(user).startswith("group:")]
        repo = AgentRunRepository(db)
        for person in people:
            already = await db.scalar(
                select(func.count(AgentRun.id)).where(
                    AgentRun.user_id == person,
                    AgentRun.kind == "experience_review",
                    AgentRun.created_at >= day_start,
                )
            )
            if already:
                continue
            latest = await db.scalar(
                select(Conversation.extra_data)
                .where(Conversation.user_id == person)
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
            channel = str((latest or {}).get("channel") or "web") if isinstance(latest, dict) else "web"
            await repo.create(
                person,
                "agent:experience",
                "experience_review",
                f"review experience for {person} since {since.isoformat()}",
                ["read", "judged", "reported"],
                budget_seconds=float(settings.AGENT_RUN_DEFAULT_BUDGET_SECONDS),
                max_steps=40,
                max_creates=1,
                channel=channel if channel in ("web", "imessage", "imessage_group") else "web",
            )
            created += 1
    if created:
        logger.info("experience_reviews_scheduled", extra={"count": created})
    return created


# Check once an hour whether today's reviews are due; the loop the worker
# process starts beside the run loop.
async def review_schedule_loop() -> None:
    while True:
        try:
            if settings.AGENT_EXPERIENCE_REVIEW_ENABLED:
                await schedule_experience_reviews()
        except Exception:
            logger.warning("experience_review_schedule_error", exc_info=True)
        await asyncio.sleep(3600)


# The address a person enrolled for a channel, from the discovery
# subscribers - the one place this system keeps who may be messaged where.
async def _enrolled_address(user_id: str, channel: str) -> str | None:
    from backend.discovery.subscribers import SubscriberRepository

    async with AsyncSessionLocal() as db:
        for subscriber in await SubscriberRepository(db).list_subscribers(user_id):
            if subscriber.channel == channel and subscriber.active and subscriber.approved:
                return subscriber.address
    return None


# The delivery the worker uses, on the discovery channels.
def _delivery() -> RunDelivery:
    from backend.core.dependencies import get_discovery_channels

    return RunDelivery(get_discovery_channels(), _enrolled_address)


class RunWorker:
    """Work the oldest claimable run to its next stop."""

    def __init__(
        self,
        worlds: Mapping[str, WorldFactory] | None = None,
        worker_id: str | None = None,
        grants: Mapping[str, Grant] | None = None,
        delivery: RunDelivery | None = None,
    ) -> None:
        self.worlds = dict(worlds) if worlds is not None else WORLDS
        self.grants = dict(grants) if grants is not None else GRANTS
        self.delivery = delivery
        self.worker_id = worker_id or f"runs-{uuid.uuid4().hex[:8]}"
        self.controller = RunController(
            AsyncSessionLocal,
            self.worker_id,
            approval_ttl_seconds=settings.AGENT_RUN_APPROVAL_TTL_SECONDS,
        )

    # One run, or False when nothing is claimable.
    async def run_once(self) -> bool:
        async with AsyncSessionLocal() as db:
            run = await AgentRunRepository(db).claim_next(
                self.worker_id, settings.AGENT_RUN_LEASE_SECONDS, kinds=self.worlds.keys()
            )
        if run is None:
            return False
        factory = self.worlds.get(str(run["kind"]))
        if factory is None:
            # Unreachable while the claim is filtered by kind; kept as the
            # second wall so a run of a kind this process cannot host is
            # closed rather than left running.
            async with AsyncSessionLocal() as db:
                await AgentRunRepository(db).finish(
                    run["id"], "failed", error_code="no_world", worker_id=self.worker_id
                )
            logger.warning("run_kind_unknown", extra={"run_id": run["id"], "kind": run["kind"]})
            return True
        grant = self.grants.get(str(run["kind"]))
        if grant is None:
            # A kind with a world but no grant would run unwalled; it does
            # not run at all.
            async with AsyncSessionLocal() as db:
                await AgentRunRepository(db).finish(
                    run["id"], "failed", error_code="no_grant", worker_id=self.worker_id
                )
            logger.warning("run_kind_ungranted", extra={"run_id": run["id"], "kind": run["kind"]})
            return True
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._renew(run["id"], stop))
        try:
            outcome = await self.controller.execute(run, factory(run), grant)
        except Exception:
            logger.warning("run_attempt_crashed", extra={"run_id": run["id"]}, exc_info=True)
            async with AsyncSessionLocal() as db:
                await AgentRunRepository(db).finish(
                    run["id"],
                    "failed",
                    error_code="attempt_crashed",
                    worker_id=self.worker_id,
                    retryable=True,
                    max_attempts=settings.AGENT_RUN_MAX_ATTEMPTS,
                )
            return True
        finally:
            stop.set()
            await asyncio.gather(heartbeat, return_exceptions=True)
        logger.info(
            "run_attempt_finished",
            extra={"run_id": run["id"], "status": outcome.status, "stopped": outcome.stopped},
        )
        await self._tell(run, outcome)
        return True

    # The person hears how it ended, on the channel the run came from; a
    # delivery that fails is an event on the run, never a failed run.
    async def _tell(self, run: dict, outcome) -> None:
        delivery = self.delivery
        if delivery is None:
            delivery = self.delivery = _delivery()
        try:
            async with AsyncSessionLocal() as db:
                repo = AgentRunRepository(db)
                current = await repo.get(run["id"])
                summary = ((current or {}).get("result") or {}).get("summary") or outcome.stopped
                await delivery.deliver(repo, current or run, outcome.status, str(summary))
        except Exception:
            logger.warning("run_delivery_error", extra={"run_id": run["id"]}, exc_info=True)

    # Hold the claim while the run works.
    async def _renew(self, run_id: str, stop: asyncio.Event) -> None:
        interval = max(10.0, settings.AGENT_RUN_LEASE_SECONDS / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            async with AsyncSessionLocal() as db:
                await AgentRunRepository(db).renew_lease(
                    run_id, self.worker_id, settings.AGENT_RUN_LEASE_SECONDS
                )


# Poll for runs forever; the loop the worker process starts.
async def run_loop() -> None:
    worker = RunWorker()
    logger.info("run_worker_started", extra={"worker_id": worker.worker_id})
    asyncio.create_task(review_schedule_loop())
    while True:
        try:
            handled = await worker.run_once()
        except Exception:
            logger.warning("run_worker_loop_error", exc_info=True)
            handled = False
        if not handled:
            await asyncio.sleep(settings.AGENT_RUN_POLL_SECONDS)
