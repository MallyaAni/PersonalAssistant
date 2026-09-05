"""A person's answer to a waiting run, from chat, binds the same approval the
API would.

Driven against the real schema: a run parked on a pending approval, then the
answer carried the way a chat turn carries it. One waiting run is the one; a
number picks among several; several and no number is a question back;
nothing waiting is said plainly; status lists what there is. The reply
rendering is pinned beside it, and the tool row parses what the router
would send.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend.agents.graph import _build_system_prompt, _render_run_context
from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.runs.repository import AgentRunRepository
from backend.services.run_answers import answer, waiting_for
from backend.tools import manage_runs
from backend.tools.actions import ManageRunsAction

pytestmark = pytest.mark.asyncio


def _user() -> str:
    return f"answers_{uuid.uuid4().hex[:10]}"


# A run parked on one pending approval for `summary`.
async def _parked(user: str, summary: str) -> tuple[dict[str, Any], dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        repo = AgentRunRepository(db)
        run = await repo.create(
            user, "channel:chat", "chat_continuation", f"objective for {summary}", [],
            budget_seconds=30.0, max_steps=3, max_creates=1,
        )
        claimed = await repo.claim_next("w", 60.0, kinds=("chat_continuation",), user_id=user)
        assert claimed and claimed["id"] == run["id"]
        approval = await repo.request_approval(run["id"], user, "send_message", "hash-" + summary, "mum", summary, 3600.0)
        assert await repo.park_for_approval(run["id"], "w")
    return run, approval


async def _clean(user: str) -> None:
    async with AsyncSessionLocal() as db:
        await AgentRunRepository(db).delete_for_user(user)


async def _state(user: str, run_id: str) -> tuple[str, list[str]]:
    async with AsyncSessionLocal() as db:
        found = await AgentRunRepository(db).get_owned(user, run_id)
    return found["status"], [a["status"] for a in found["approvals"]]


def test_the_row_parses_what_the_router_sends():
    assert manage_runs.parse({"mode": "approve", "which": " 2 "}) == ManageRunsAction("approve", "2")
    assert manage_runs.parse({"mode": "status"}) == ManageRunsAction("status", "")
    assert manage_runs.parse({"mode": "delete"}) is None
    assert manage_runs.TOOL.contract.effect == "write"
    assert manage_runs.TOOL.contract.is_creation(ManageRunsAction("approve")) is False


async def test_one_waiting_run_is_the_one_and_a_yes_wakes_it():
    user = _user()
    try:
        run, _ = await _parked(user, "send the summary to mum")
        outcome = await answer(AsyncSessionLocal, user, ManageRunsAction("approve"))
        assert outcome["kind"] == "run_approved"
        assert outcome["chosen"]["summary"] == "send the summary to mum"
        status, approvals = await _state(user, run["id"])
        assert status == "queued" and approvals == ["granted"]
        # Answered once: nothing waits any more.
        again = await answer(AsyncSessionLocal, user, ManageRunsAction("approve"))
        assert again["kind"] == "runs_nothing_pending"
    finally:
        await _clean(user)


async def test_a_no_denies_and_wakes_the_run_to_record_it():
    user = _user()
    try:
        run, _ = await _parked(user, "book the table")
        outcome = await answer(AsyncSessionLocal, user, ManageRunsAction("deny"))
        assert outcome["kind"] == "run_denied"
        status, approvals = await _state(user, run["id"])
        assert status == "queued" and approvals == ["denied"]
    finally:
        await _clean(user)


async def test_several_waiting_need_a_number_and_a_number_picks_that_one():
    user = _user()
    try:
        first, _ = await _parked(user, "send the summary to mum")
        second, _ = await _parked(user, "book the table")
        unsettled = await answer(AsyncSessionLocal, user, ManageRunsAction("approve", "the one about dinner"))
        assert unsettled["kind"] == "runs_which"
        assert [view["number"] for view in unsettled["waiting"]] == [1, 2]
        picked = await answer(AsyncSessionLocal, user, ManageRunsAction("approve", "2"))
        assert picked["kind"] == "run_approved" and picked["chosen"]["summary"] == "book the table"
        assert (await _state(user, second["id"]))[1] == ["granted"]
        assert (await _state(user, first["id"]))[1] == ["pending"]
        # One left: it is the one, without a number.
        last = await answer(AsyncSessionLocal, user, ManageRunsAction("deny"))
        assert last["kind"] == "run_denied" and last["chosen"]["summary"] == "send the summary to mum"
    finally:
        await _clean(user)


async def test_status_lists_the_runs_and_what_waits():
    user = _user()
    try:
        await _parked(user, "send the summary to mum")
        outcome = await answer(AsyncSessionLocal, user, ManageRunsAction("status"))
        assert outcome["kind"] == "runs_status"
        assert outcome["waiting"][0]["summary"] == "send the summary to mum"
        assert outcome["runs"][0]["status"] == "waiting_approval"
        async with AsyncSessionLocal() as db:
            listed = await waiting_for(AgentRunRepository(db), user)
        assert [view["number"] for view in listed] == [1]
    finally:
        await _clean(user)


async def test_the_service_answers_only_while_runs_are_hosted(monkeypatch):
    from backend.services.conversation_service import ConversationService

    service = ConversationService.__new__(ConversationService)
    monkeypatch.setattr(settings, "AGENT_RUNS_ENABLED", False)
    assert await service._apply_runs_action("ani", ManageRunsAction("approve")) == {"kind": "unavailable"}
    assert await service._runs_waiting("ani") == []


def test_the_reply_is_shown_the_answer_and_the_waiting_runs():
    approved = {
        "run_outcomes": [{"kind": "run_approved", "chosen": {"approval_id": "a1", "kind": "chat continuation", "summary": "send the summary to mum"}}],
        "runs_waiting": [
            {"number": 1, "approval_id": "a1", "kind": "chat continuation", "summary": "send the summary to mum", "objective": "o"},
            {"number": 2, "approval_id": "a2", "kind": "security review", "summary": "open a ticket", "objective": "p"},
        ],
    }
    rendered = _render_run_context(approved)
    assert "approved" in rendered and "Nothing has happened yet" in rendered
    # The answered one is not listed as still waiting; the other is.
    assert "2. security review wants to: open a ticket" in rendered
    assert "1. chat continuation" not in rendered
    assert "Background runs" in _build_system_prompt(approved)
    which = _render_run_context({"run_outcomes": [{"kind": "runs_which", "waiting": []}], "runs_waiting": approved["runs_waiting"]})
    assert "ask which" in which.lower() and "1. chat continuation" in which
    assert _render_run_context({}) == ""
    assert "run_outcome" not in _build_system_prompt({"query": "hi"})
