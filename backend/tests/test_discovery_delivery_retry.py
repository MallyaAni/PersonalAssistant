"""A digest must survive a bridge that was asleep, without ever arriving twice.

These two requirements pull against each other, and the tests here are mostly
about the tension. Retrying is what saves the 5:30pm digest that was lost when
the Mac was shut; retrying the wrong failure is how someone gets the same
message twice, which is the one outcome this subsystem treats as unrecoverable.

The whole design rests on a single distinction, so it is tested from both
sides: a connection that was never established proves nothing was sent, and
anything else proves nothing at all.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend.discovery.channels import DeliveryResult, NotificationChannel
from backend.discovery.delivery import (
    DELIVERY_DEADLINE,
    DigestDelivery,
    next_delivery_attempt,
)
from backend.discovery.subscribers import Subscriber

_SLOT = datetime(2026, 8, 8, 21, 30, tzinfo=UTC)

_SUBSCRIBER = Subscriber(
    id="sub-1",
    channel="imessage",
    address="2025550143",
    label=None,
    token="t",
    active=True,
    deliverable=True,
    approved=True,
    delivery_count=0,
    last_error=None,
)


class _Channel(NotificationChannel):
    """A bridge that fails however the test needs it to."""

    def __init__(self, result: DeliveryResult) -> None:
        self.result = result
        self.sent: list[tuple[str, str]] = []

    @property
    def channel_id(self) -> str:
        return "imessage"

    async def send(self, address, message, attachment=None) -> DeliveryResult:
        self.sent.append((address, message))
        return self.result


class _Subscribers:
    def __init__(self, subscribers=(_SUBSCRIBER,)) -> None:
        self._subscribers = tuple(subscribers)
        self.recorded: list[str | None] = []

    async def list_subscribers(self, user_id, deliverable_only=False):
        return self._subscribers

    async def record_delivery(self, subscriber_id, error_code=None):
        self.recorded.append(error_code)


class _Runs:
    """Records what the delivery decided to do with the run."""

    def __init__(self) -> None:
        self.deferred: list[tuple[str, str, datetime]] = []
        self.settled: list[str | None] = []
        self.marked_delivered: list[bool] = []

    async def defer_delivery(self, run_id, message, retry_at) -> bool:
        self.deferred.append((run_id, message, retry_at))
        return True

    async def settle_delivery(self, run_id, error_code, delivered=False) -> bool:
        self.settled.append(error_code)
        self.marked_delivered.append(delivered)
        return True


def _delivery(result: DeliveryResult) -> tuple[DigestDelivery, _Runs, _Channel]:
    runs = _Runs()
    channel = _Channel(result)
    delivery = DigestDelivery(_Subscribers(), {"imessage": channel}, runs)
    return delivery, runs, channel


_UNREACHABLE = DeliveryResult(
    delivered=False, error_code="channel_unreachable", unsent=True
)
_AMBIGUOUS = DeliveryResult(delivered=False, error_code="channel_failed")


@pytest.mark.asyncio
async def test_a_sleeping_bridge_leaves_the_digest_waiting():
    # The failure that started all this: the Mac was shut at 5:30pm.
    delivery, runs, _ = _delivery(_UNREACHABLE)

    report = await delivery.redeliver(
        "ani.mallya", "tonight in DC", "run-1", _SLOT, attempts=0, now=_SLOT
    )

    assert report.delivered == 0
    assert report.retry_at is not None
    assert len(runs.deferred) == 1
    assert runs.deferred[0][1] == "tonight in DC"
    # Not settled: settling is what threw the digest away.
    assert runs.settled == []


@pytest.mark.asyncio
async def test_an_ambiguous_failure_is_never_retried():
    # The message may already have gone. Losing it beats sending it twice.
    delivery, runs, _ = _delivery(_AMBIGUOUS)

    report = await delivery.redeliver(
        "ani.mallya", "tonight in DC", "run-1", _SLOT, attempts=0, now=_SLOT
    )

    assert report.retry_at is None
    assert runs.deferred == []
    assert runs.settled == ["delivery_failed"]
    # Nothing arrived, so nothing claims it did.
    assert runs.marked_delivered == [False]


@pytest.mark.asyncio
async def test_a_digest_is_given_up_on_once_it_is_too_late():
    delivery, runs, _ = _delivery(_UNREACHABLE)

    report = await delivery.redeliver(
        "ani.mallya",
        "tonight in DC",
        "run-1",
        _SLOT,
        attempts=0,
        # Six hours on, the evening it announced is over.
        now=_SLOT + DELIVERY_DEADLINE,
    )

    assert report.retry_at is None
    assert runs.deferred == []
    assert runs.settled == ["delivery_expired"]


@pytest.mark.asyncio
async def test_a_successful_send_settles_and_never_defers():
    delivery, runs, channel = _delivery(DeliveryResult(delivered=True))

    report = await delivery.redeliver(
        "ani.mallya", "tonight in DC", "run-1", _SLOT, attempts=0, now=_SLOT
    )

    assert report.delivered == 1
    assert runs.deferred == []
    assert runs.settled == [None]
    # The deferral released the write-once claim, so a retry that works has to
    # re-take it. Without this the run reads as never delivered forever, and a
    # digest sitting on the user's phone is reported as unsent.
    assert runs.marked_delivered == [True]
    # Sent verbatim. Re-rendering would drop events that have since started,
    # so a retried digest would quietly be a different, smaller message.
    assert channel.sent == [("2025550143", "tonight in DC")]


@pytest.mark.asyncio
async def test_one_ambiguous_recipient_holds_back_the_whole_digest():
    # There is no per-recipient record of who already received it, so a retry
    # would resend to everyone. One uncertain result taints the batch.
    runs = _Runs()
    channels = {"imessage": _Channel(_UNREACHABLE), "other": _Channel(_AMBIGUOUS)}
    subscribers = _Subscribers(
        (_SUBSCRIBER, replace(_SUBSCRIBER, id="sub-2", channel="other"))
    )
    delivery = DigestDelivery(subscribers, channels, runs)

    await delivery.redeliver(
        "ani.mallya", "tonight", "run-1", _SLOT, attempts=0, now=_SLOT
    )

    assert runs.deferred == []
    assert runs.settled == ["delivery_failed"]


def test_the_backoff_grows_so_a_dark_machine_is_not_polled_all_evening():
    first = next_delivery_attempt(_SLOT, 0, _SLOT)
    second = next_delivery_attempt(_SLOT, 1, _SLOT)
    third = next_delivery_attempt(_SLOT, 2, _SLOT)

    assert first == _SLOT + timedelta(minutes=5)
    assert second == _SLOT + timedelta(minutes=10)
    assert third == _SLOT + timedelta(minutes=20)


def test_the_backoff_is_capped_and_then_stops_entirely():
    # However many attempts have failed, the wait stays bounded...
    capped = next_delivery_attempt(_SLOT, 99, _SLOT)
    assert capped == _SLOT + timedelta(hours=1)

    # ...until the deadline, after which there is nothing worth sending.
    assert next_delivery_attempt(_SLOT, 0, _SLOT + DELIVERY_DEADLINE) is None


# --- a recipient the sending machine does not know yet ------------------------


_NOT_ALLOWED = DeliveryResult(delivered=False, error_code="recipient_not_allowed")


def _delivery_with_granter(outcome: str):
    runs = _Runs()
    channel = _Channel(_NOT_ALLOWED)
    granted: list[tuple[str, str]] = []

    async def _grant(channel_id: str, address: str) -> str:
        granted.append((channel_id, address))
        return outcome

    delivery = DigestDelivery(_Subscribers(), {"imessage": channel}, runs, _grant)
    return delivery, runs, granted


@pytest.mark.asyncio
async def test_a_refused_recipient_is_granted_and_the_digest_retried():
    # Granting happens when an operator approves, which does nothing for anyone
    # approved before that existed. The first refused send is the only moment
    # left to fix them.
    delivery, runs, granted = _delivery_with_granter("granted")

    report = await delivery.redeliver(
        "jenos1", "tonight in DC", "run-1", _SLOT, attempts=0, now=_SLOT
    )

    assert granted == [("imessage", "2025550143")]
    # The bridge refused before sending, so nothing went out and it will accept
    # the address now: safe to try again.
    assert report.retry_at is not None
    assert len(runs.deferred) == 1
    assert runs.settled == []


@pytest.mark.asyncio
async def test_a_bridge_that_will_not_grant_leaves_the_refusal_standing():
    # Grants switched off, or a bridge that cannot be reached. Both need a
    # person, so the digest is not retried against an unchanged refusal.
    delivery, runs, granted = _delivery_with_granter("refused")

    report = await delivery.redeliver(
        "jenos1", "tonight in DC", "run-1", _SLOT, attempts=0, now=_SLOT
    )

    assert granted  # it was attempted
    assert report.retry_at is None
    assert runs.deferred == []
    assert runs.settled == ["delivery_failed"]


@pytest.mark.asyncio
async def test_an_unapproved_recipient_is_never_granted():
    # Granting only ever restates a decision an operator already made. It must
    # not become a way for a pending request to permit itself.
    runs = _Runs()
    granted: list[str] = []

    async def _grant(channel_id: str, address: str) -> str:
        granted.append(address)
        return "granted"

    pending = replace(_SUBSCRIBER, approved=False)
    delivery = DigestDelivery(
        _Subscribers((pending,)), {"imessage": _Channel(_NOT_ALLOWED)}, runs, _grant
    )

    await delivery.redeliver("jenos1", "hi", "run-1", _SLOT, attempts=0, now=_SLOT)

    assert granted == []
    assert runs.settled == ["delivery_failed"]


@pytest.mark.asyncio
async def test_without_a_granter_the_refusal_is_simply_reported():
    delivery, runs, _ = _delivery(_NOT_ALLOWED)

    report = await delivery.redeliver(
        "jenos1", "hi", "run-1", _SLOT, attempts=0, now=_SLOT
    )

    assert report.retry_at is None
    assert runs.settled == ["delivery_failed"]
