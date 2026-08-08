"""Deliver one sweep's digest to consented subscribers, exactly once.

Delivery is the only irreversible step in the whole loop. Everything before it
can be recomputed; a message that arrived cannot be recalled. That asymmetry
sets the rules here:

- the run is marked delivered *before* any channel is called, because a crash
  after sending must not cause a resend. Losing a delivery is recoverable by a
  human asking; duplicating one is not;
- consent and revocation are checked at send time against the current row, not
  against whatever the sweep saw when it started;
- one subscriber failing does not stop the others, and does not fail the run.
"""

from dataclasses import dataclass
from datetime import datetime

from backend.discovery.channels import NotificationChannel
from backend.discovery.digest import render_message
from backend.discovery.relevance import RankedCandidate
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.subscribers import Subscriber, SubscriberRepository


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    attempted: int
    delivered: int
    skipped: int
    failures: tuple[str, ...]

    @property
    def sent_anything(self) -> bool:
        return self.delivered > 0


class DigestDelivery:
    """Send one digest to the people permitted to receive it."""

    def __init__(
        self,
        subscribers: SubscriberRepository,
        channels: dict[str, NotificationChannel],
        runs: DiscoveryRunRepository | None = None,
    ) -> None:
        self.subscribers = subscribers
        self.channels = channels
        self.runs = runs

    async def deliver(
        self,
        user_id: str,
        selected: tuple[RankedCandidate, ...],
        # Unused: a digest no longer carries a calendar file or link. Kept so
        # existing callers keep working until they are updated.
        calendar_base_url: str | None = None,
        timezone: str = "America/New_York",
        run_id: str | None = None,
        worker_id: str | None = None,
        now: datetime | None = None,
    ) -> DeliveryReport:
        # No attachment. A calendar file arriving unasked is friction on a
        # phone, and the message is read in a few seconds either way — so a
        # digest is now text plus the source's own link, which works from
        # anywhere without this machine being reachable at all.
        message = render_message(selected, timezone=timezone, now=now)
        if message is None:
            # Nothing worth sending. Recording the run as delivered still
            # matters: it stops a resumed attempt from re-deciding and sending
            # a digest the first attempt deliberately withheld.
            await self._claim(run_id, worker_id)
            return DeliveryReport(attempted=0, delivered=0, skipped=0, failures=())

        # Claim before sending. A crash between the claim and the send loses a
        # digest; a claim after sending would resend one.
        if not await self._claim(run_id, worker_id):
            return DeliveryReport(attempted=0, delivered=0, skipped=0, failures=())

        recipients = await self.subscribers.list_subscribers(
            user_id, deliverable_only=True
        )
        delivered = 0
        skipped = 0
        failures: list[str] = []
        for subscriber in recipients:
            if not subscriber.deliverable:
                skipped += 1
                continue
            channel = self.channels.get(subscriber.channel)
            if channel is None:
                skipped += 1
                await self.subscribers.record_delivery(
                    subscriber.id, "channel_unconfigured"
                )
                continue
            result = await channel.send(subscriber.address, message)
            await self.subscribers.record_delivery(subscriber.id, result.error_code)
            if result.delivered:
                delivered += 1
            elif result.error_code == "pull_channel":
                # Not a failure: this subscriber fetches for themselves.
                skipped += 1
            else:
                failures.append(subscriber.id)

        return DeliveryReport(
            attempted=len(recipients),
            delivered=delivered,
            skipped=skipped,
            failures=tuple(failures),
        )

    # Write-once delivery. Returns False when this run already delivered, which
    # is what makes a resumed run safe to re-enter.
    async def _claim(self, run_id: str | None, worker_id: str | None) -> bool:
        if self.runs is None or run_id is None or worker_id is None:
            return True
        return await self.runs.mark_delivered(run_id, worker_id)


def describe_recipients(subscribers: tuple[Subscriber, ...]) -> list[dict[str, object]]:
    return [
        {
            "id": subscriber.id,
            "channel": subscriber.channel,
            "label": subscriber.label,
            "deliverable": subscriber.deliverable,
        }
        for subscriber in subscribers
    ]
