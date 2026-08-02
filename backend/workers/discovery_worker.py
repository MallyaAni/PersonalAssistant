"""Run scheduled ambient discovery sweeps.

Two responsibilities, deliberately in one process so there is exactly one thing
to run and exactly one thing to stop:

1. produce — queue a run for every schedule whose slot has arrived. Safe to call
   from any number of processes: the slot uniqueness constraint turns a
   duplicate attempt into a no-op rather than a second sweep;
2. consume — claim one queued or lease-expired run, execute the sweep, persist
   its digest, then deliver it.

The digest is saved before delivery is attempted, so a crash between the two
leaves work to resume rather than work to redo. Delivery itself is write-once,
so the resumed attempt declines rather than sending twice.
"""

import asyncio
import socket
import uuid
from contextlib import suppress
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import (
    get_discovery_channels,
    get_discovery_runner_for_session,
)
from backend.core.logging_config import get_logger
from backend.database.session import AsyncSessionLocal
from backend.discovery.delivery import DigestDelivery
from backend.discovery.reachability import (
    calendar_base_url,
    is_reachable_from_other_devices,
)
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.subscribers import SubscriberRepository

logger = get_logger(__name__)


class DiscoveryRunCancelledError(RuntimeError):
    """Signals cooperative cancellation at a safe checkpoint."""


class DiscoveryWorker:
    """Queue due sweeps and execute the claimed ones."""

    def __init__(self, worker_id: str | None = None) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"

    # Queue whatever is due. Separate from claiming so a failure to produce
    # cannot consume the lease of something already running.
    async def enqueue_due(self) -> int:
        async with AsyncSessionLocal() as session:
            created = await DiscoveryRunRepository(session).enqueue_due_runs()
        if created:
            logger.info(
                "discovery_runs_enqueued",
                extra={"count": len(created)},
            )
        return len(created)

    # Claim and execute at most one run, so the loop stays testable.
    async def run_once(self) -> bool:
        async with AsyncSessionLocal() as session:
            run = await DiscoveryRunRepository(session).claim_next(
                self.worker_id,
                settings.DISCOVERY_RUN_LEASE_SECONDS,
            )
        if run is None:
            return False
        await self._execute(run)
        return True

    async def _execute(self, run: dict[str, Any]) -> None:
        run_id = str(run["id"])
        user_id = str(run["user_id"])
        stop_heartbeat = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(run_id, stop_heartbeat))
        try:
            async with AsyncSessionLocal() as session:
                runs = DiscoveryRunRepository(session)
                if await runs.cancellation_requested(run_id):
                    raise DiscoveryRunCancelledError()

                profile = await DiscoveryProfileRepository(session).get_profile(user_id)
                runner = get_discovery_runner_for_session(session)
                result = await runner.sweep(user_id, profile, run_id=run_id)

                # Persist before delivering. A crash after this point resumes
                # with the selection intact instead of re-reading every feed.
                await runs.save_digest(
                    run_id,
                    self.worker_id,
                    result.to_digest_json(),
                    len(result.selected),
                    result.requests_spent,
                )

                report = await DigestDelivery(
                    SubscriberRepository(session),
                    get_discovery_channels(),
                    runs,
                ).deliver(
                    user_id,
                    result.selected,
                    _calendar_base(user_id),
                    timezone=_timezone_for(profile),
                    run_id=run_id,
                    worker_id=self.worker_id,
                )
                await runs.mark_ready(run_id, self.worker_id)

            logger.info(
                "discovery_run_ready",
                extra={
                    "run_id": run_id,
                    "selected": len(result.selected),
                    "candidates": result.candidate_count,
                    "requests_spent": result.requests_spent,
                    "delivered": report.delivered,
                },
            )
        except DiscoveryRunCancelledError:
            async with AsyncSessionLocal() as session:
                await DiscoveryRunRepository(session).mark_cancelled(
                    run_id, self.worker_id
                )
            logger.info("discovery_run_cancelled", extra={"run_id": run_id})
        except Exception:
            async with AsyncSessionLocal() as session:
                await DiscoveryRunRepository(session).mark_failed(
                    run_id, self.worker_id, "sweep_failed"
                )
            logger.exception("discovery_run_failed", extra={"run_id": run_id})
        finally:
            stop_heartbeat.set()
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    # Renew the lease until the run reaches a terminal state. A sweep reads
    # several feeds over the network, so it can legitimately outlive one lease.
    async def _heartbeat(self, run_id: str, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=settings.DISCOVERY_RUN_HEARTBEAT_SECONDS,
                )
            except TimeoutError:
                async with AsyncSessionLocal() as session:
                    renewed = await DiscoveryRunRepository(session).renew_lease(
                        run_id,
                        self.worker_id,
                        settings.DISCOVERY_RUN_LEASE_SECONDS,
                    )
                if not renewed:
                    return


# A digest's value is the "Add" link, and a link to localhost is dead on the
# recipient's phone — where localhost is the phone. The configured value wins
# when it is routable; otherwise the host's LAN address replaces loopback.
def _calendar_base(user_id: str) -> str:
    base = calendar_base_url(settings.DISCOVERY_CALENDAR_BASE_URL)
    if not is_reachable_from_other_devices(base):
        logger.warning(
            "discovery_calendar_links_unreachable",
            extra={"base_url": base},
        )
    return f"{base.rstrip('/')}/{user_id}/calendar"


# A digest is read in the recipient's local time, and the user's primary place
# is where that comes from.
def _timezone_for(profile: Any) -> str:
    primary = getattr(profile, "primary_locality", None)
    if primary is not None and getattr(primary, "timezone", None):
        return str(primary.timezone)
    return "America/New_York"


# Poll without holding a transaction open while idle. Producing and consuming
# share one cadence: a sweep is weekly, so nothing here needs to be prompt.
async def run() -> None:
    worker = DiscoveryWorker()
    logger.info("discovery_worker_started", extra={"worker_id": worker.worker_id})
    while True:
        await worker.enqueue_due()
        handled = await worker.run_once()
        if not handled:
            await asyncio.sleep(settings.DISCOVERY_POLL_SECONDS)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
