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

That claim-first rule cost a real digest, which is why the retry below exists.
A sweep finished at 5:30pm while the Mac that sends was asleep; the send failed,
the claim stood, and the run recorded a clean success with the failure visible
only as `last_error` on the subscriber row. Nobody was told, and nothing tried
again.

The retry does not weaken the rule. It rests on a distinction the channel now
draws: a connection that was never *established* proves the message never left,
while anything after the request is on the wire proves nothing at all. Only the
first releases the claim. An ambiguous failure still loses the digest on
purpose, because the alternative is sending it twice.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.discovery.channels import DeliveryResult, NotificationChannel
from backend.discovery.digest import render_message
from backend.discovery.relevance import RankedCandidate
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.subscribers import Subscriber, SubscriberRepository

# Permitting one address on the machine that sends, returning what happened.
# A plain callable so this module depends on the capability rather than on the
# MCP layer that provides it.
type RecipientGranter = Callable[[str, str], Awaitable[str]]

# How long to keep trying an unreachable bridge, and how fast to back off.
#
# The deadline is what keeps a digest from becoming a nuisance. Today's events
# are worth reading a few hours late; they are not worth a phone buzzing at 3am
# about a concert that finished. Six hours covers a laptop shut for the evening
# and stops well short of the next morning.
DELIVERY_DEADLINE = timedelta(hours=6)
DELIVERY_RETRY_BASE = timedelta(minutes=5)
DELIVERY_RETRY_MAX = timedelta(hours=1)

# Enough doublings to pass the cap above (5min << 4 = 80min > 1h), and few
# enough that the arithmetic stays small whatever the stored counter says.
_MAX_DOUBLINGS = 8


# When the next attempt should happen, or None once it is no longer worth one.
def next_delivery_attempt(
    scheduled_for: datetime,
    attempts: int,
    now: datetime,
) -> datetime | None:
    # Exponential, so a machine that is off for the evening is not polled every
    # five minutes for six hours.
    #
    # The exponent is bounded rather than the product: capping afterwards means
    # computing the huge value first, and `2 ** 99` overflows the multiplication
    # before any cap can apply. The attempt counter is durable, so a run that
    # somehow accumulates them would have crashed the worker here.
    doublings = min(max(0, attempts), _MAX_DOUBLINGS)
    step = min(DELIVERY_RETRY_BASE * (2**doublings), DELIVERY_RETRY_MAX)
    when = now + step
    return None if when > scheduled_for + DELIVERY_DEADLINE else when


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    attempted: int
    delivered: int
    skipped: int
    failures: tuple[str, ...]
    # Set when the digest provably never left and is waiting for another try.
    retry_at: datetime | None = None


class DigestDelivery:
    """Send one digest to the people permitted to receive it."""

    def __init__(
        self,
        subscribers: SubscriberRepository,
        channels: dict[str, NotificationChannel],
        runs: DiscoveryRunRepository | None = None,
        granter: "RecipientGranter | None" = None,
    ) -> None:
        self.subscribers = subscribers
        self.channels = channels
        self.runs = runs
        self.granter = granter

    # Tell the sending machine about a recipient it does not know, then let the
    # digest be tried again.
    #
    # Granting happens when an operator approves, which does nothing for anyone
    # approved before that existed — and there is no moment left at which to fix
    # them, because approval has already passed. This is that moment: the first
    # send that gets refused. It also covers the operator enabling grants on the
    # bridge later, which is otherwise a change with no event attached to it.
    #
    # Only ever a re-statement of a decision already made. A subscriber reaching
    # here is approved and unrevoked; nothing is being permitted that an operator
    # did not already permit.
    async def _grant_and_reconsider(
        self,
        subscriber: Subscriber,
        result: DeliveryResult,
    ) -> DeliveryResult:
        if self.granter is None or not subscriber.approved:
            return result
        if await self.granter(subscriber.channel, subscriber.address) != "granted":
            # Grants are switched off on the bridge, or it cannot be reached.
            # Either is for a person to resolve, so the refusal stands as it was.
            return result
        # The bridge refused before sending, so nothing went out, and it will
        # accept this address now. That makes the digest safe to send again —
        # which is the whole point of noticing.
        return DeliveryResult(
            delivered=False, error_code="recipient_not_allowed", unsent=True
        )

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
        # The slot this digest belongs to, which is what the retry deadline is
        # measured from. A sweep that started late does not get extra hours.
        scheduled_for: datetime | None = None,
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

        return await self._send_to_all(
            user_id,
            message,
            run_id=run_id,
            scheduled_for=scheduled_for or now or datetime.now(UTC),
            attempts=0,
            now=now,
        )

    # Send a digest that was rendered earlier and never made it out.
    #
    # The stored text is resent verbatim rather than rebuilt, because rendering
    # is time-dependent: it drops events that have already started, so a rebuilt
    # digest would quietly shrink between the slot and the retry.
    async def redeliver(
        self,
        user_id: str,
        message: str,
        run_id: str,
        scheduled_for: datetime,
        attempts: int,
        now: datetime | None = None,
    ) -> DeliveryReport:
        return await self._send_to_all(
            user_id,
            message,
            run_id=run_id,
            scheduled_for=scheduled_for,
            attempts=attempts,
            now=now,
        )

    async def _send_to_all(
        self,
        user_id: str,
        message: str,
        run_id: str | None,
        scheduled_for: datetime | None,
        attempts: int,
        now: datetime | None = None,
    ) -> DeliveryReport:
        recipients = await self.subscribers.list_subscribers(
            user_id, deliverable_only=True
        )
        delivered = 0
        skipped = 0
        failures: list[str] = []
        # A retry is only safe when *every* failure proved nothing was sent. One
        # ambiguous result among them and the whole digest stays put, because
        # there is no per-recipient record of who already received it.
        unsent = True
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
            if result.error_code == "recipient_not_allowed":
                result = await self._grant_and_reconsider(subscriber, result)
            await self.subscribers.record_delivery(subscriber.id, result.error_code)
            if result.delivered:
                delivered += 1
            elif result.error_code == "pull_channel":
                # Not a failure: this subscriber fetches for themselves.
                skipped += 1
            else:
                failures.append(subscriber.id)
                unsent = unsent and result.unsent

        retry_at = await self._schedule_retry(
            run_id=run_id,
            message=message,
            scheduled_for=scheduled_for,
            attempts=attempts,
            delivered=delivered,
            failures=failures,
            unsent=unsent,
            now=now,
        )
        return DeliveryReport(
            attempted=len(recipients),
            delivered=delivered,
            skipped=skipped,
            failures=tuple(failures),
            retry_at=retry_at,
        )

    # Hand the digest back for a later attempt, or close it out for good.
    async def _schedule_retry(
        self,
        run_id: str | None,
        message: str,
        scheduled_for: datetime | None,
        attempts: int,
        delivered: int,
        failures: list[str],
        unsent: bool,
        now: datetime | None,
    ) -> datetime | None:
        if self.runs is None or run_id is None or scheduled_for is None:
            return None
        moment = now or datetime.now(UTC)
        if not failures:
            # Either it went, or there was nobody to send to. Both are settled.
            await self.runs.settle_delivery(run_id, None, delivered=delivered > 0)
            return None
        if delivered or not unsent:
            # Something arrived, or something might have. Retrying would risk a
            # second copy, so this digest ends here whatever happened to it.
            await self.runs.settle_delivery(
                run_id, "delivery_failed", delivered=delivered > 0
            )
            return None
        retry_at = next_delivery_attempt(scheduled_for, attempts, moment)
        if retry_at is None:
            # Out of time. A digest this old is no longer worth arriving.
            await self.runs.settle_delivery(run_id, "delivery_expired")
            return None
        await self.runs.defer_delivery(run_id, message, retry_at)
        return retry_at

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
