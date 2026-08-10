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
from datetime import UTC, datetime
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import (
    get_digest_writer,
    get_discovery_channels,
    get_discovery_runner_for_session,
    grant_recipient_on_bridge,
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
    # How long to wait before the next slot is due, so the producer wakes for
    # the schedule rather than on a fixed drumbeat.
    async def seconds_until_due(self) -> float:
        async with AsyncSessionLocal() as session:
            due = await DiscoveryRunRepository(session).next_due_at()
        if due is None:
            # Nothing scheduled: fall back to the ordinary idle cadence, which
            # is also how a schedule created while sleeping gets noticed.
            return float(settings.DISCOVERY_POLL_SECONDS)
        remaining = (due - datetime.now(UTC)).total_seconds()
        # Never longer than the idle cadence, or a schedule added or moved while
        # asleep would not be seen until the old slot came round.
        return max(0.0, min(remaining, float(settings.DISCOVERY_POLL_SECONDS)))

    async def enqueue_due(self) -> int:
        async with AsyncSessionLocal() as session:
            created = await DiscoveryRunRepository(session).enqueue_due_runs()
        if created:
            logger.info(
                "discovery_runs_enqueued",
                extra={"count": len(created)},
            )
        return len(created)

    # Send at most one digest that was rendered earlier and never got out.
    #
    # Separate from the sweep path because there is no sweep to do: the digest
    # already exists, and re-running the search to rebuild it would spend
    # metered calls to reproduce something already on disk.
    async def deliver_pending(self) -> bool:
        async with AsyncSessionLocal() as session:
            runs = DiscoveryRunRepository(session)
            pending = await runs.claim_pending_delivery(self.worker_id)
            if pending is None:
                return False
            message = pending.get("delivery_message")
            run_id = str(pending["id"])
            if not message:
                # Nothing to send. Recorded rather than retried forever, since
                # a pending delivery with no text cannot become one.
                await runs.settle_delivery(run_id, "delivery_lost")
                return True
            report = await DigestDelivery(
                SubscriberRepository(session),
                get_discovery_channels(),
                runs,
                grant_recipient_on_bridge,
            ).redeliver(
                str(pending["user_id"]),
                str(message),
                run_id=run_id,
                scheduled_for=pending["scheduled_for"],
                attempts=int(pending["delivery_attempts"]),
            )
        logger.info(
            "discovery_digest_redelivered",
            extra={
                "run_id": run_id,
                "delivered": report.delivered,
                "attempt": pending["delivery_attempts"],
                "retry_at": report.retry_at.isoformat() if report.retry_at else None,
            },
        )
        return True

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
                    grant_recipient_on_bridge,
                    get_digest_writer(),
                ).deliver(
                    user_id,
                    result.selected,
                    _calendar_base(user_id),
                    timezone=_timezone_for(profile),
                    run_id=run_id,
                    worker_id=self.worker_id,
                    scheduled_for=run.get("scheduled_for"),
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
# A due slot that cannot be claimed would otherwise spin this loop as fast as
# the database can answer.
_MIN_IDLE_SECONDS = 0.5


def _timezone_for(profile: Any) -> str:
    primary = getattr(profile, "active_locality", None)
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
        if handled:
            continue
        # Only when no sweep is waiting. A digest whose retry is due is less
        # urgent than a slot that is due now, and the retry has hours of budget.
        if await worker.deliver_pending():
            continue
        # Sleep until the next slot rather than for a fixed interval, so a
        # sweep asked for at 17:10:00 starts then instead of somewhere in the
        # following minute. The floor keeps a due-but-unclaimable slot from
        # spinning the loop.
        delay = await worker.seconds_until_due()
        await asyncio.sleep(max(delay, _MIN_IDLE_SECONDS))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
