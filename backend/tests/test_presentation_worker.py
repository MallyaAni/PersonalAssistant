"""A finished deck tells the conversation that asked for it, exactly once.

The terminal notification is the only place a background deck becomes visible
to the person, so these tests pin the two ways it can go wrong: the notice is
sent twice after a retry, and the notice is written as a turn with an empty
user bubble in front of it. The channel is exercised with stubs because the
consent rules are covered by `test_discovery_subscriber_ownership.py`.
"""
import os
from typing import Any

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import pytest

import backend.workers.presentation_worker as presentation_worker

pytestmark = pytest.mark.asyncio


class _Session:
    """Stand in for one async database session."""

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def rollback(self) -> None:
        return None


class _Delivery:
    """Report one successful channel send."""

    delivered = True
    error_code = None


class _Channel:
    """Record what the worker asked to be sent."""

    def __init__(self, sent: list[tuple[str, str]]) -> None:
        self.sent = sent

    async def send(self, address: str, message: str) -> _Delivery:
        self.sent.append((address, message))
        return _Delivery()


@pytest.fixture
def worker_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install stubs and return the record of what the worker did."""
    state: dict[str, Any] = {
        "claim": True,
        "turns": [],
        "sent": [],
        "channel": "imessage",
        "address": "ani@example.com",
    }

    class Jobs:
        def __init__(self, session: Any) -> None:
            self.session = session

        async def claim_notification(self, job_id: str) -> bool:
            took = state["claim"]
            state["claim"] = False
            return took

        async def claim_next(self, worker_id: str, lease: int) -> dict[str, Any] | None:
            return state.get("next_job")

    class Presentations:
        def __init__(self, session: Any) -> None:
            self.session = session

        async def get_owned(self, user_id: str, presentation_id: str) -> dict[str, Any]:
            return {
                "id": presentation_id,
                "user_id": user_id,
                "title": "Quarterly deck",
                "conversation_id": "conversation-1",
            }

    class Conversations:
        def __init__(self, session: Any) -> None:
            self.session = session

        async def save_turn(self, conversation_id: str, payload: dict[str, Any]) -> None:
            state["turns"].append((conversation_id, payload))

    async def enrolled_address(user_id: str, channel: str) -> str | None:
        return state["address"]

    monkeypatch.setattr(presentation_worker, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(presentation_worker, "SQLAlchemyPresentationJobRepository", Jobs)
    monkeypatch.setattr(presentation_worker, "SQLAlchemyPresentationRepository", Presentations)
    monkeypatch.setattr(presentation_worker, "SQLAlchemyConversationRepository", Conversations)
    monkeypatch.setattr(presentation_worker, "enrolled_address", enrolled_address)
    monkeypatch.setattr(
        presentation_worker,
        "get_discovery_channels",
        lambda: {state["channel"]: _Channel(state["sent"])},
    )
    return state


def _job(channel: str = "imessage") -> dict[str, Any]:
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "user_id": "ani.mallya",
        "presentation_id": "22222222-2222-4222-8222-222222222222",
        "channel": channel,
    }


async def test_a_ready_deck_leaves_one_assistant_only_turn_and_one_message(
    worker_state: dict[str, Any],
) -> None:
    await presentation_worker.PresentationJobWorker("test")._write_and_send_result(
        _job(), "ready"
    )

    assert len(worker_state["turns"]) == 1
    conversation_id, payload = worker_state["turns"][0]
    assert conversation_id == "conversation-1"
    # An empty query with assistant_only is what keeps the notice from being
    # restored as a user bubble followed by an answer.
    assert payload["query"] == ""
    assert payload["response"] == 'Your presentation "Quarterly deck" is ready.'
    assert payload["metadata"] == {
        "kind": "presentation_result",
        "assistant_only": True,
        "presentation_id": "22222222-2222-4222-8222-222222222222",
        "status": "ready",
    }
    assert worker_state["sent"] == [
        ("ani@example.com", 'Your presentation "Quarterly deck" is ready.')
    ]


async def test_a_second_notification_attempt_does_nothing(
    worker_state: dict[str, Any],
) -> None:
    worker = presentation_worker.PresentationJobWorker("test")
    await worker._write_and_send_result(_job(), "ready")
    await worker._write_and_send_result(_job(), "ready")

    assert len(worker_state["turns"]) == 1
    assert len(worker_state["sent"]) == 1


async def test_a_web_deck_writes_the_turn_without_messaging(
    worker_state: dict[str, Any],
) -> None:
    await presentation_worker.PresentationJobWorker("test")._write_and_send_result(
        _job(channel="web"), "ready"
    )

    assert len(worker_state["turns"]) == 1
    assert worker_state["sent"] == []


async def test_a_failed_deck_says_it_could_not_finish(
    worker_state: dict[str, Any],
) -> None:
    await presentation_worker.PresentationJobWorker("test")._write_and_send_result(
        _job(), "failed"
    )

    assert worker_state["turns"][0][1]["response"] == (
        'I couldn\'t finish the presentation "Quarterly deck".'
    )


async def test_a_notification_failure_never_fails_the_job(
    worker_state: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(job: dict[str, Any], status: str) -> None:
        raise RuntimeError("conversation store is down")

    monkeypatch.setattr(
        presentation_worker.PresentationJobWorker,
        "_write_and_send_result",
        broken,
    )

    # The deck is already ready; a courtesy notice that cannot be written must
    # not surface as a generation failure.
    await presentation_worker.PresentationJobWorker("test")._notify_terminal(
        _job(), "ready"
    )


async def test_a_job_finalized_by_a_dead_worker_is_announced_by_the_next_claim(
    worker_state: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    announced: list[str] = []
    executed: list[dict[str, Any]] = []
    worker_state["next_job"] = {**_job(), "status": "ready"}

    async def notify(self: Any, job: dict[str, Any], status: str) -> None:
        announced.append(status)

    async def execute(self: Any, job: dict[str, Any]) -> None:
        executed.append(job)

    monkeypatch.setattr(presentation_worker.PresentationJobWorker, "_notify_terminal", notify)
    monkeypatch.setattr(presentation_worker.PresentationJobWorker, "_execute", execute)

    handled = await presentation_worker.PresentationJobWorker("test").run_once()

    assert handled is True
    assert announced == ["ready"]
    assert executed == []
