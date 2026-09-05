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


WORLDS: dict[str, WorldFactory] = {
    "code_review": _code_review,
    "security_review": _security_review,
}

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
}


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
    while True:
        try:
            handled = await worker.run_once()
        except Exception:
            logger.warning("run_worker_loop_error", exc_info=True)
            handled = False
        if not handled:
            await asyncio.sleep(settings.AGENT_RUN_POLL_SECONDS)
