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


WORLDS: dict[str, WorldFactory] = {"code_review": _code_review}


class RunWorker:
    """Work the oldest claimable run to its next stop."""

    def __init__(
        self,
        worlds: Mapping[str, WorldFactory] | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.worlds = dict(worlds) if worlds is not None else WORLDS
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
                self.worker_id, settings.AGENT_RUN_LEASE_SECONDS
            )
        if run is None:
            return False
        factory = self.worlds.get(str(run["kind"]))
        if factory is None:
            async with AsyncSessionLocal() as db:
                await AgentRunRepository(db).finish(
                    run["id"], "failed", error_code="no_world", worker_id=self.worker_id
                )
            logger.warning("run_kind_unknown", extra={"run_id": run["id"], "kind": run["kind"]})
            return True
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(self._renew(run["id"], stop))
        try:
            outcome = await self.controller.execute(run, factory(run))
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
        return True

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
