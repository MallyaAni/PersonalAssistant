"""A run's stop reaches its person, and what happened to the message is on
the run's record.

Pinned without a database: a recording repository and a scripted channel,
because what is under test is the decision - which stops are told, on which
channel, to which address - and the words, which must carry no evidence.
"""

from __future__ import annotations

import pytest

from backend.discovery.channels import DeliveryResult, NotificationChannel
from backend.runs.delivery import MAX_MESSAGE_CHARS, RunDelivery, compose

pytestmark = pytest.mark.asyncio


class _Repo:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    async def record_event(self, run_id: str, kind: str, detail: dict | None) -> None:
        self.events.append((run_id, kind, dict(detail or {})))


class _Channel(NotificationChannel):
    def __init__(self, result: DeliveryResult) -> None:
        self.result = result
        self.sent: list[tuple[str, str]] = []

    @property
    def channel_id(self) -> str:
        return "imessage"

    async def send(self, address: str, message: str, attachment=None) -> DeliveryResult:
        self.sent.append((address, message))
        return self.result


def _run(**overrides) -> dict:
    base = {"id": "r1", "user_id": "ani", "kind": "security_review", "channel": "imessage", "error_code": None}
    base.update(overrides)
    return base


async def _address(user_id: str, channel: str) -> str | None:
    return "+15550100" if user_id == "ani" and channel == "imessage" else None


async def test_a_completed_run_is_told_on_its_channel_and_recorded():
    channel = _Channel(DeliveryResult(delivered=True))
    repo = _Repo()
    went = await RunDelivery({"imessage": channel}, _address).deliver(repo, _run(), "completed", "two findings, one dismissed")
    assert went == "delivered"
    assert channel.sent == [("+15550100", "Your security review finished. two findings, one dismissed")]
    assert repo.events == [("r1", "delivered", {"channel": "imessage", "chars": len(channel.sent[0][1])})]


async def test_a_web_run_is_not_pushed_and_the_record_says_why():
    channel = _Channel(DeliveryResult(delivered=True))
    repo = _Repo()
    went = await RunDelivery({"imessage": channel}, _address).deliver(repo, _run(channel="web"), "completed", "s")
    assert went == "web" and channel.sent == []
    assert repo.events[0][1] == "delivery_skipped"


async def test_a_stop_nobody_needs_to_hear_about_is_not_sent():
    channel = _Channel(DeliveryResult(delivered=True))
    repo = _Repo()
    assert await RunDelivery({"imessage": channel}, _address).deliver(repo, _run(), "running", "s") == "not_a_stop"
    assert channel.sent == [] and repo.events == []


async def test_no_address_and_no_channel_are_skips_on_the_record():
    channel = _Channel(DeliveryResult(delivered=True))
    repo = _Repo()
    delivery = RunDelivery({"imessage": channel}, _address)
    assert await delivery.deliver(repo, _run(user_id="someone_else"), "failed", "s") == "no_address"
    assert await delivery.deliver(repo, _run(channel="pager"), "failed", "s") == "no_channel"
    assert [kind for _, kind, _ in repo.events] == ["delivery_skipped", "delivery_skipped"]
    assert channel.sent == []


async def test_a_refusing_channel_is_a_failed_delivery_not_a_failed_run():
    channel = _Channel(DeliveryResult(delivered=False, error_code="bridge_unreachable"))
    repo = _Repo()
    went = await RunDelivery({"imessage": channel}, _address).deliver(repo, _run(), "waiting_approval", "needs a yes")
    assert went == "failed"
    assert repo.events == [("r1", "delivery_failed", {"channel": "imessage", "error": "bridge_unreachable"})]


def test_the_words_name_the_stop_and_stay_bounded():
    assert compose(_run(kind="code_review"), "completed", "one finding") == "Your code review finished. one finding"
    assert compose(_run(error_code="unauthorized_tool"), "failed", "") == "Your security review stopped without finishing (unauthorized_tool)."
    assert compose(_run(), "waiting_approval", "") == "Your security review is waiting for your approval before it goes on."
    long = compose(_run(), "completed", "x" * 2000)
    assert len(long) <= MAX_MESSAGE_CHARS and long.endswith("…")
