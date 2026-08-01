"""Stage 6: the outbound boundary.

Delivery is the only irreversible step in the loop, so these tests are about
what must never happen: sending without consent, sending after revocation,
sending twice, or reporting a success that did not occur.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.channels import (
    DeliveryResult,
    MessagesAppChannel,
    NotificationChannel,
    NullChannel,
    PullOnlyChannel,
)
from backend.discovery.delivery import DigestDelivery
from backend.discovery.digest import render_message
from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.relevance import RankedCandidate
from backend.discovery.subscribers import SubscriberRepository
from backend.models.discovery_subscriber import DiscoverySubscriber

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
_BASE = "https://example.org/api/v1/discovery/u/calendar"


class _RecordingChannel(NotificationChannel):
    def __init__(self, channel_id: str = "imessage") -> None:
        self._channel_id = channel_id
        self.sent: list[tuple[str, str]] = []

    @property
    def channel_id(self) -> str:
        return self._channel_id

    async def send(self, address: str, message: str) -> DeliveryResult:
        self.sent.append((address, message))
        return DeliveryResult(delivered=True)


def _ranked(title: str, days_ahead: int = 10) -> RankedCandidate:
    event = DiscoveredEvent(
        source_id="src-1",
        external_id=f"evt-{title}",
        title=title,
        starts_at=_NOW + timedelta(days=days_ahead),
        ends_at=None,
        place="New Haven, CT",
        url="https://example.org/e",
        summary=None,
    )
    return RankedCandidate(ScoredCandidate(event, None), 0.9, "jazz")


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DiscoverySubscriber).where(DiscoverySubscriber.user_id == user_id)
        )
        await session.commit()


def test_an_empty_selection_produces_no_message():
    # Sending "nothing this week" every week is how a proactive assistant
    # trains people to ignore it.
    assert render_message((), _BASE) is None


def test_the_message_carries_a_local_time_and_a_calendar_link():
    message = render_message(
        (_ranked("Jazz at the Green"),), _BASE, timezone="America/New_York"
    )

    assert message is not None
    assert "Jazz at the Green" in message
    # 2026-08-11T12:00Z is 08:00 in New York, not 12:00.
    assert "8:00am" in message
    assert f"{_BASE}/" in message
    assert ".ics" in message


def test_an_unknown_timezone_falls_back_rather_than_failing():
    message = render_message((_ranked("Jazz"),), _BASE, timezone="Mars/Olympus")
    assert message is not None


def test_long_titles_are_bounded():
    message = render_message((_ranked("x" * 400),), _BASE)
    assert message is not None
    assert "…" in message
    assert len(message) < 1_000


@pytest.mark.asyncio
async def test_the_default_channel_refuses_to_send():
    # Egress ships disabled: an operator turns it on deliberately rather than
    # discovering it was on because a default said so.
    result = await NullChannel().send("+15550100", "hello")
    assert result.delivered is False
    assert result.error_code == "egress_disabled"


@pytest.mark.asyncio
async def test_a_pull_channel_never_sends():
    result = await PullOnlyChannel().send("device", "hello")
    assert result.delivered is False
    assert result.error_code == "pull_channel"


@pytest.mark.asyncio
async def test_a_channel_failure_is_never_reported_as_success():
    async def _explode(tool_name: str, arguments: dict[str, str]) -> object:
        raise RuntimeError("bridge offline")

    channel = MessagesAppChannel(_explode, "send_message")
    result = await channel.send("+15550100", "hello")

    assert result.delivered is False
    assert result.error_code == "channel_unreachable"


@pytest.mark.asyncio
async def test_the_channel_receives_only_the_address_and_the_message():
    captured: dict[str, object] = {}

    async def _capture(tool_name: str, arguments: dict[str, str]) -> object:
        captured["tool"] = tool_name
        captured["arguments"] = dict(arguments)
        return None

    await MessagesAppChannel(_capture, "send_message").send("+15550100", "hi")

    assert captured["tool"] == "send_message"
    assert captured["arguments"] == {"to": "+15550100", "body": "hi"}


@pytest.mark.asyncio
async def test_enrolling_without_consent_stores_an_undeliverable_permission():
    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SubscriberRepository(session)
            person = await repo.enroll(user_id, "imessage", "+15550100")

            assert person.deliverable is False
            assert person.active is False
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_delivery_reaches_only_consented_subscribers():
    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SubscriberRepository(session)
            await repo.enroll(user_id, "imessage", "+15550100", consented=True)
            await repo.enroll(user_id, "imessage", "+15550199", consented=False)
            channel = _RecordingChannel()

            report = await DigestDelivery(repo, {"imessage": channel}).deliver(
                user_id, (_ranked("Jazz"),), _BASE
            )

            assert report.delivered == 1
            assert len(channel.sent) == 1
            assert channel.sent[0][0] == "+15550100"
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_revocation_stops_delivery_and_invalidates_the_shared_link():
    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SubscriberRepository(session)
            person = await repo.enroll(user_id, "imessage", "+15550100", consented=True)
            original_token = person.token
            channel = _RecordingChannel()

            assert await repo.revoke(user_id, uuid.UUID(person.id)) is True

            report = await DigestDelivery(repo, {"imessage": channel}).deliver(
                user_id, (_ranked("Jazz"),), _BASE
            )

            assert report.delivered == 0
            assert channel.sent == []
            # The calendar link already handed out must stop resolving too.
            assert await repo.by_token(original_token) is None
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_an_unconfigured_channel_skips_rather_than_sending_elsewhere():
    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SubscriberRepository(session)
            await repo.enroll(user_id, "imessage", "+15550100", consented=True)
            other = _RecordingChannel("shortcuts_pull")

            report = await DigestDelivery(repo, {"shortcuts_pull": other}).deliver(
                user_id, (_ranked("Jazz"),), _BASE
            )

            assert report.delivered == 0
            assert other.sent == []
            assert report.skipped == 1
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_token_resolves_to_its_owner():
    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SubscriberRepository(session)
            person = await repo.enroll(user_id, "imessage", "+15550100", consented=True)

            resolved = await repo.by_token(person.token)

            assert resolved is not None
            assert resolved[0] == user_id
            assert await repo.by_token("not-a-real-token") is None
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_re_enrolling_the_same_address_updates_one_permission():
    # Otherwise revoking would leave a forgotten duplicate still receiving.
    user_id = f"sub_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = SubscriberRepository(session)
            await repo.enroll(user_id, "imessage", "+15550100", consented=True)
            await repo.enroll(
                user_id, "imessage", "+15550100", label="Sam", consented=True
            )

            assert len(await repo.list_subscribers(user_id)) == 1
    finally:
        await _cleanup(user_id)
