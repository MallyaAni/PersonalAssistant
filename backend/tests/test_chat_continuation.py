"""A chat turn's unfinished work becomes a run, and the run finishes it.

Pinned here without a model: the call that carries an action across the
boundary and back unchanged; the decision as the boundary shows it; the
world that continues a turn against a scripted assistant, driven by the
real controller on the real schema; the grant that lets it read and not
send; and the hand-off itself - a turn stopped by its budget or ceiling
creates the run and tells the reply, a turn the router ended does not.
"""

from __future__ import annotations

import dataclasses
import typing
import uuid
from typing import Any

import pytest

from backend.agents.chat.world import KIND, ChatContinuationWorld, StepCall, lines_of
from backend.agents.graph import _build_system_prompt, _render_handed_off, turn_context_messages
from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.runs.controller import RunController
from backend.runs.grants import grant_of
from backend.runs.repository import AgentRunRepository
from backend.services.chat_steps import action_of, call_of, decision_view
from backend.services.mcp_tool_orchestration_service import MCPToolPlan
from backend.services.turn_steps import (
    BUDGET,
    CEILING,
    DECLINED,
    Act,
    Done,
    NeedsInput,
    Unavailable,
)
from backend.tools import actions as A
from backend.tools.actions import MainAction, SearchAction, ToolboxAction

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------------- the call


def _sample(cls: type) -> Any:
    values: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        origin = typing.get_origin(field.type) or field.type
        text = str(field.type)
        if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            continue
        if "MCPToolPlan" in text:
            values[field.name] = MCPToolPlan("srv", "tool", {"q": 1}, "fp")
        elif "int" in text and "str" not in text:
            values[field.name] = 3
        elif "bool" in text:
            values[field.name] = True
        elif "list" in text or "tuple" in text or origin in (list, tuple):
            values[field.name] = []
        elif "dict" in text or origin is dict:
            values[field.name] = {}
        else:
            values[field.name] = "x"
    return cls(**values)


@pytest.mark.parametrize("cls", [*(c for c in typing.get_args(MainAction) if c is not type(None)), A.ManageCheckInsAction])
def test_every_action_survives_the_trip_across_the_boundary(cls):
    action = _sample(cls)
    call = call_of(action)
    assert call["type"] == cls.__name__
    rebuilt = action_of(call)
    assert rebuilt == action
    assert type(rebuilt) is cls


def test_a_call_naming_nothing_this_system_has_is_no_action():
    assert action_of({"type": "DropTables", "fields": {}}) is None
    assert action_of({"type": "SearchAction", "fields": {"nonsense": 1}}) is None
    assert action_of(None) is None


def test_the_decision_view_carries_the_contract_beside_the_call():
    view = decision_view(Act(SearchAction(query="best ramen", max_results=None)))
    assert view["kind"] == "act"
    assert view["tool"] == "search_web"
    assert view["effect"] == "read"
    assert view["creates"] is False
    assert action_of(view["call"]) == SearchAction(query="best ramen", max_results=None)
    assert decision_view(Done("nothing further")) == {"kind": "done", "reason": "nothing further"}
    assert decision_view(NeedsInput("schedule_task", "time"))["kind"] == "needs_input"
    assert decision_view(Unavailable("down"))["kind"] == "unavailable"


# ------------------------------------------------------------ the world


class ScriptedAssistant:
    """The API's two routes, answered from a script.

    `plan` is the sequence of decision views; `applied` records every call
    the world carried out.
    """

    def __init__(self, plan: list[dict[str, Any]], outcome: dict[str, Any] | None = None) -> None:
        self.plan = list(plan)
        self.applied: list[dict[str, Any]] = []
        self.shown: list[list[str]] = []
        self.outcome = outcome or {"kind": "found", "count": 3}

    async def decide(self, user_id: str, query: str, lines: list[str], remaining_seconds: float) -> dict[str, Any]:
        self.shown.append(list(lines))
        index = len(self.applied)
        return self.plan[index] if index < len(self.plan) else {"kind": "done", "reason": "nothing further"}

    async def apply(self, user_id: str, query: str, conversation_id: str | None, call: dict[str, Any]) -> dict[str, Any]:
        self.applied.append(call)
        return {"kind": "search", "outcome": dict(self.outcome), "line": "web search"}


def _step(action: MainAction, **overrides) -> dict[str, Any]:
    view = decision_view(Act(action))
    view.update(overrides)
    return view


def _user() -> str:
    return f"chatrun_{uuid.uuid4().hex[:10]}"


async def _make_run(user: str, lines: list[str]) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await AgentRunRepository(db).create(
            user, "channel:chat", KIND, "find ramen near me and the weather", lines,
            budget_seconds=30.0, max_steps=6, max_creates=1, conversation_id=None, channel="web",
        )


async def _claim(user: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        claimed = await AgentRunRepository(db).claim_next("chat-w", 60.0, kinds=(KIND,), user_id=user)
    assert claimed is not None
    return claimed


async def _clean(user: str) -> None:
    async with AsyncSessionLocal() as db:
        await AgentRunRepository(db).delete_for_user(user)


def test_the_turns_lines_come_from_the_runs_acceptance():
    assert lines_of({"acceptance": ["web search: ramen (3 results)", " ", "recall: none"]}) == [
        "web search: ramen (3 results)", "recall: none",
    ]


async def test_a_continuation_carries_out_the_routers_steps_and_completes_when_it_declines():
    user = _user()
    before = ["web search: ramen near me (3 results)"]
    try:
        await _make_run(user, before)
        claimed = await _claim(user)
        assistant = ScriptedAssistant([
            _step(SearchAction(query="weather tonight", max_results=None)),
        ])
        world = ChatContinuationWorld(claimed, assistant)
        grant = grant_of("search_web", "mcp:read")
        outcome = await RunController(AsyncSessionLocal, "chat-w").execute(claimed, world, grant)
        assert outcome.status == "completed", outcome
        # The router saw the turn's steps and then the run's own.
        assert assistant.shown[0] == before
        assert assistant.shown[1][0] == before[0] and "weather tonight" in assistant.shown[1][1]
        assert [action_of(call) for call in assistant.applied] == [SearchAction(query="weather tonight", max_results=None)]
        async with AsyncSessionLocal() as db:
            found = await AgentRunRepository(db).get_owned(user, claimed["id"])
        assert found["status"] == "completed"
        assert [row["tool"] for row in found["actions"]] == ["search_web"]
        assert found["result"]["evidence"]["steps_before"] == before
        assert "weather tonight" in found["result"]["summary"]
    finally:
        await _clean(user)


async def test_a_step_that_would_send_needs_the_persons_yes():
    world = ChatContinuationWorld({"id": "r", "user_id": "u", "objective": "q", "acceptance": [], "budget_seconds": 30}, ScriptedAssistant([]))
    read = StepCall("search_web", "{}", "web search", "x", None, False, "read", "never")
    send = StepCall("mcp_send", '{"type": "ToolboxAction"}', "send", "x", None, False, "send", "consequential")
    write = StepCall("schedule_task", "{}", "schedule", "x", "k", True, "write", "never")
    assert world.needs_approval(read) is False
    assert world.needs_approval(write) is False
    assert world.needs_approval(send) is True
    # A toolbox step is named at the grant by its effect, never by the server's tool.
    assert world.tool_name(send) == "mcp:send"
    assert world.tool_name(read) == "search_web"


async def test_a_toolbox_read_is_within_the_chat_grant_and_a_toolbox_write_is_not():
    user = _user()
    try:
        await _make_run(user, [])
        claimed = await _claim(user)
        writing = ToolboxAction(plan=MCPToolPlan("notes", "append_note", {"text": "x"}, "fp"))
        assistant = ScriptedAssistant([
            _step(ToolboxAction(plan=MCPToolPlan("weather", "forecast", {"city": "Boston"}, "fp")), effect="read"),
            _step(writing, effect="write", tool="append_note"),
        ])
        world = ChatContinuationWorld(claimed, assistant)
        from backend.workers.run_worker import GRANTS

        outcome = await RunController(AsyncSessionLocal, "chat-w").execute(claimed, world, GRANTS[KIND])
        assert outcome.status == "failed"
        assert outcome.error_code == "unauthorized_tool"
        # The read ran; the write was refused before it was applied.
        assert len(assistant.applied) == 1
        async with AsyncSessionLocal() as db:
            found = await AgentRunRepository(db).get_owned(user, claimed["id"])
        assert [(row["tool"], row["status"]) for row in found["actions"]] == [("mcp:read", "succeeded"), ("mcp:write", "refused")]
    finally:
        await _clean(user)


async def test_a_router_that_needs_input_ends_the_run_for_the_person_to_answer():
    user = _user()
    try:
        await _make_run(user, [])
        claimed = await _claim(user)
        world = ChatContinuationWorld(claimed, ScriptedAssistant([{"kind": "needs_input", "tool": "schedule_task", "missing": "a time"}]))
        outcome = await RunController(AsyncSessionLocal, "chat-w").execute(claimed, world, grant_of("search_web"))
        assert outcome.status == "failed"
        assert outcome.error_code == "needs_input"
        async with AsyncSessionLocal() as db:
            found = await AgentRunRepository(db).get_owned(user, claimed["id"])
        assert "needs something you did not say" in found["result"]["summary"]
    finally:
        await _clean(user)


# ---------------------------------------------------------- the hand-off


class _Turn:
    """The pieces of `_task_turn_context` the hand-off reads."""


def _service(monkeypatch, created: list[dict[str, Any]]):
    from backend.services.conversation_service import ConversationService

    service = ConversationService.__new__(ConversationService)

    async def creator(user_id, query, lines, conversation_id, channel):
        run = {"id": "run-1", "user_id": user_id, "query": query, "lines": list(lines), "conversation_id": conversation_id, "channel": channel}
        created.append(run)
        return run

    service.run_creator = creator  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "AGENT_RUNS_ENABLED", True)
    return service


async def test_a_turn_cut_short_hands_the_rest_to_a_run_and_tells_the_reply(monkeypatch):
    created: list[dict[str, Any]] = []
    service = _service(monkeypatch, created)
    handed = await service._hand_off("ani", "ramen and weather", {"channel": "imessage"}, "conv-1", ["web search: ramen (3 results)"], BUDGET)
    assert handed == {"run_id": "run-1", "steps_done": ["web search: ramen (3 results)"], "stopped": BUDGET}
    assert created[0]["channel"] == "imessage" and created[0]["conversation_id"] == "conv-1"
    assert created[0]["lines"] == ["web search: ramen (3 results)"]


async def test_no_run_is_created_when_runs_are_not_hosted(monkeypatch):
    created: list[dict[str, Any]] = []
    service = _service(monkeypatch, created)
    monkeypatch.setattr(settings, "AGENT_RUNS_ENABLED", False)
    assert await service._hand_off("ani", "q", {}, "", ["x"], CEILING) is None
    assert created == []


async def test_a_failed_hand_off_ends_the_turn_quietly(monkeypatch):
    service = _service(monkeypatch, [])

    async def broken(*args):
        raise RuntimeError("database away")

    service.run_creator = broken  # type: ignore[attr-defined]
    assert await service._hand_off("ani", "q", {}, "", ["x"], BUDGET) is None


def test_the_loop_hands_off_only_when_the_clock_ran_out_after_a_clean_step():
    # The condition the loop applies, read from the source: the clock, never
    # the ceiling (a ceiling stop is an answered turn; continuing it re-ran
    # the same search and texted a failure, live, 2026-09-06), and never
    # after a failed, refused or unknown last step.
    import inspect

    from backend.services import conversation_service as module

    source = inspect.getsource(module.ConversationService._task_turn_context)
    assert "turn.stopped == BUDGET" in source
    assert "turn.stopped in (BUDGET, CEILING)" not in source
    assert module._NOT_WORTH_CONTINUING == {"failed", "refused", "unknown"}
    assert BUDGET != DECLINED and CEILING != DECLINED


async def test_a_router_that_names_a_step_the_turn_already_took_ends_the_run_as_done():
    user = _user()
    before = ["Web search: anything fun this weekend (8 results)"]
    try:
        await _make_run(user, before)
        claimed = await _claim(user)
        # The router asks for the very search the turn already ran.
        assistant = ScriptedAssistant([_step(SearchAction(query="anything fun this weekend", max_results=None), label="Web search", detail="anything fun this weekend")])
        world = ChatContinuationWorld(claimed, assistant)
        outcome = await RunController(AsyncSessionLocal, "chat-w").execute(claimed, world, grant_of("search_web"))
        assert outcome.status == "completed", outcome
        assert assistant.applied == []
        async with AsyncSessionLocal() as db:
            found = await AgentRunRepository(db).get_owned(user, claimed["id"])
        assert found["actions"] == []
        assert "Nothing further" in found["result"]["summary"]
    finally:
        await _clean(user)


def test_the_reply_is_shown_the_hand_off_as_a_record_and_a_rule():
    context = {
        "query": "ramen and weather",
        "handed_off": {"run_id": "run-1", "steps_done": ["web search: ramen near me (3 results)"], "stopped": BUDGET},
    }
    rendered = _render_handed_off(context["handed_off"])
    assert "Handed off" in rendered and "web search: ramen near me (3 results)" in rendered
    system = _build_system_prompt(context)
    assert "handed the rest to a background run" in system
    shown = "\n".join(message["content"] for message in turn_context_messages(context))
    assert "Handed off" in shown or "Handed off" in system
    assert _render_handed_off({}) == ""


# ------------------------------------------------------------- the routes


# The two step routes reach the service under the person's own authority and
# the chat scope, and carry the call through unchanged.
def test_the_step_routes_reach_the_service_with_the_call_intact(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services.conversation_service import ConversationService

    seen: dict[str, Any] = {}

    async def decide_step(self, user_id, query, lines, remaining_seconds):
        seen["decide"] = (user_id, query, list(lines), remaining_seconds)
        return decision_view(Act(SearchAction(query="weather tonight", max_results=None)))

    async def apply_step(self, user_id, query, conversation_id, call):
        seen["apply"] = (user_id, query, conversation_id, call)
        return {"kind": "search", "outcome": {"kind": "found", "count": 2}, "line": "web search: weather tonight (2 results)"}

    monkeypatch.setattr(ConversationService, "decide_step", decide_step)
    monkeypatch.setattr(ConversationService, "apply_step", apply_step)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    with TestClient(app) as client:
        decided = client.post(
            "/api/v1/chat/ani/steps/decide",
            json={"query": "ramen and weather", "lines": ["web search: ramen (3 results)"], "remaining_seconds": 40},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["kind"] == "act"
        assert seen["decide"] == ("ani", "ramen and weather", ["web search: ramen (3 results)"], 40.0)
        applied = client.post(
            "/api/v1/chat/ani/steps/apply",
            json={"query": "ramen and weather", "conversation_id": "c1", "call": decided.json()["call"]},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["outcome"] == {"kind": "found", "count": 2}
        assert action_of(seen["apply"][3]) == SearchAction(query="weather tonight", max_results=None)
