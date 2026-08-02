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

from backend.discovery.calendar import build_calendar
from backend.discovery.channels import Attachment, NotificationChannel
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
        calendar_base_url: str | None,
        timezone: str = "America/New_York",
        run_id: str | None = None,
        worker_id: str | None = None,
        now: datetime | None = None,
    ) -> DeliveryReport:
        # One calendar file carrying every dated find. Attaching it is what makes
        # a digest work away from home: a link has to reach the machine that
        # served it, a file that arrives with the message does not.
        attachment = build_calendar_attachment(selected)
        # With the file attached, links would only be the ones that fail off the
        # sender's network, so the message drops them.
        message = render_message(
            selected,
            None if attachment is not None else calendar_base_url,
            timezone=timezone,
        )
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
            result = await channel.send(subscriber.address, message, attachment)
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


# Render every dated selection as one attachable calendar, or None when nothing
# in the digest can be scheduled. A single file lets a phone offer "add all"
# rather than making the recipient tap once per event.
def build_calendar_attachment(
    selected: tuple[RankedCandidate, ...],
) -> Attachment | None:
    events = tuple(item.event for item in selected if item.event.starts_at is not None)
    if not events:
        return None
    try:
        document = build_calendar(events, calendar_name="AniOS Discoveries")
    except ValueError:
        return None
    return Attachment(
        filename="discoveries.ics",
        media_type="text/calendar",
        content=document.encode("utf-8"),
    )


# Which subscribers would receive a digest right now, without sending one.
# Exists so the operator can answer "who is this going to?" before it goes.
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
