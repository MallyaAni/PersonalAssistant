"""The task runner's contract, with the repository, chat, and bridge stubbed.

What a fired run must do: converse on the task's own conversation marked as
a scheduled-task turn, deliver to the person's iMessage address when that is
the task's channel, keep web output on the run, and close the run with the
right status whichever way it went.
"""

import os
from typing import Any

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.workers.imessage_chat import TurnImage, TurnResult
from backend.workers.task_runner import TaskRunner


def _task(channel: str = "imessage") -> dict[str, Any]:
    return {
        "id": "task-1",
        "user_id": "user-1",
        "instruction": "text me the weather",
        "channel": channel,
        "conversation_id": "conv-1",
    }


class _Harness:
    def __init__(self, monkeypatch, turn: TurnResult | None, address: str | None):
        self.runner = TaskRunner(self._invoke, base_url="http://backend:8000")
        self.sent: list[dict] = []
        self.finished: list[tuple] = []
        self.turn_bodies: list[dict] = []

        async def fake_turn(task):
            self.turn_bodies.append(task)
            return turn

        async def fake_finish(run_id, status, task=None, output=None, error_code=None):
            self.finished.append((run_id, status, output, error_code))

        async def fake_address(user_id):
            return address

        monkeypatch.setattr(self.runner, "_turn", fake_turn)
        monkeypatch.setattr(self.runner, "_finish", fake_finish)
        monkeypatch.setattr(self.runner, "_address_for", fake_address)

    async def _invoke(self, tool, arguments):
        self.sent.append(arguments)
        return {"status": "sent", "guid": "g1"}


@pytest.mark.asyncio
async def test_imessage_task_is_delivered_and_closed_as_delivered(monkeypatch):
    harness = _Harness(monkeypatch, TurnResult("72F and sunny", ()), "+15550001111")
    await harness.runner._deliver("run-1", _task(), TurnResult("72F and sunny", ()))
    assert harness.sent == [{"to": "+15550001111", "body": "72F and sunny"}]
    assert harness.finished == [("run-1", "delivered", "72F and sunny", None)]


@pytest.mark.asyncio
async def test_web_task_keeps_its_output_on_the_run(monkeypatch):
    harness = _Harness(monkeypatch, None, None)
    await harness.runner._deliver("run-2", _task("web"), TurnResult("done", ()))
    assert harness.sent == []
    assert harness.finished == [("run-2", "completed", "done", None)]


@pytest.mark.asyncio
async def test_missing_subscriber_is_undeliverable_not_failed(monkeypatch):
    harness = _Harness(monkeypatch, None, None)
    await harness.runner._deliver("run-3", _task(), TurnResult("hi", ()))
    assert harness.finished == [("run-3", "undeliverable", "hi", "no_subscriber")]


@pytest.mark.asyncio
async def test_images_ride_along_as_attachments(monkeypatch):
    harness = _Harness(monkeypatch, None, "+15550001111")
    turn = TurnResult(
        "here you go", (TurnImage("art-1", "image/png", data_base64="QUJD"),)
    )
    await harness.runner._deliver("run-4", _task(), turn)
    assert harness.sent[0]["body"] == "here you go"
    assert harness.sent[1]["attachment_base64"] == "QUJD"
    assert harness.finished[0][1] == "delivered"


# The turn itself: the body posted to /chat carries the task's conversation
# and the scheduled-task mark, and the stream's deltas become the reply.
@pytest.mark.asyncio
async def test_turn_posts_on_the_task_conversation_marked_as_scheduled(monkeypatch):
    import httpx

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization", "")
        stream = (
            'event: start\ndata: {"conversation_id": "conv-1"}\n\n'
            'event: delta\ndata: {"content": "72F "}\n\n'
            'event: delta\ndata: {"content": "and sunny"}\n\n'
            "event: done\ndata: {}\n\n"
        )
        return httpx.Response(200, text=stream)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched_client)
    runner = TaskRunner(lambda *_: None, base_url="http://backend:8000")
    turn = await runner._turn(_task())
    assert turn is not None
    assert turn.reply == "72F and sunny"
    assert seen["body"]["conversation_id"] == "conv-1"
    assert seen["body"]["metadata"] == {"channel": "imessage", "scheduled_task": True}
    assert seen["body"]["query"] == "text me the weather"
    assert seen["auth"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_run_once_closes_a_run_whose_turn_failed(monkeypatch):
    harness = _Harness(monkeypatch, None, "+15550001111")

    class _Repo:
        def __init__(self, _db):
            pass

        async def claim_next(self, worker_id, lease):
            return {"id": "run-5", "user_id": "user-1", "task": _task()}

        async def renew_lease(self, run_id, worker_id, lease):
            return True

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    import backend.workers.task_runner as module

    monkeypatch.setattr(module, "ScheduledTaskRepository", _Repo)
    monkeypatch.setattr(module, "AsyncSessionLocal", lambda: _Session())
    assert await harness.runner.run_once() is True
    assert harness.finished == [("run-5", "failed", None, "turn_failed")]
    assert harness.sent == []


@pytest.mark.asyncio
async def test_a_group_task_is_delivered_into_the_chat(monkeypatch):
    room = "iMessage;+;chat778899001122"
    harness = _Harness(monkeypatch, TurnResult("Digest for the crew", ()), room)
    await harness.runner._deliver("run-1", _task("imessage_group"), TurnResult("Digest for the crew", ()))
    assert harness.sent == [{"to": room, "body": "Digest for the crew"}]
    assert harness.finished == [("run-1", "delivered", "Digest for the crew", None)]
