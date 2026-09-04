""""Cancel this and set that" is two actions, and both have to happen.

One tool decision per turn was never a design; it was a ceiling on what a
request could express. `manage_tasks` used to say, in its own description, that
changing a reminder's time meant cancelling it and scheduling a new one - two
calls, where the selector makes one. Handed a request it had no way to carry
out, the model answered as though it had, and the row was untouched.

`reschedule` closed that one sentence. It did not close the class: "cancel the
tesla reminder and remind me to take the bins out at 7pm" is still two
different tools, and no single decision expresses it.

These run the real routing model and read the real rows back. The assertion
that matters is the datastore - no tesla row, exactly one bins row at 19:00 -
not that two actions were selected, and not that the reply mentioned both. The
reply claiming a change is precisely what was true while nothing had happened.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.config.settings import settings
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.database.session import AsyncSessionLocal
from backend.discovery.schedule import Cadence
from backend.services.main_action_selector import MainActionSelector
from backend.tasks.repository import ScheduledTaskRepository
from backend.services.turn_steps import run_steps
from backend.tools import AUTOMATION_TOOLS, describe_action
from backend.tools.actions import ManageTasksAction, ScheduleTaskAction

ZONE = "America/New_York"
USER = "functional-tests-turn-steps"

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


def _selector() -> MainActionSelector:
    return MainActionSelector(
        get_routing_llm_client(),
        get_mcp_invocation_service(),
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None,
        diagram_enabled=True,
        presentation_enabled=True,
    )


# Apply one routed action to the store, exactly as _apply_step does, and say
# what happened in the words the loop feeds back to the next decision.
async def _apply(tasks: ScheduledTaskRepository, action, now: datetime) -> str:
    if isinstance(action, ScheduleTaskAction):
        await tasks.create(
            USER,
            action.instruction,
            Cadence(
                cadence=action.cadence,
                hour=action.hour,
                minute=action.minute,
                weekday=action.weekday,
                timezone=ZONE,
                on_date=now.date(),
            ),
            channel="web",
        )
        return describe_action(action) or "scheduled something"
    assert isinstance(action, ManageTasksAction), action
    existing = await tasks.list_for_user(USER, enabled_only=False)
    if action.operation == "cancel":
        for row in existing:
            if "tesla" in row["instruction"].lower():
                await tasks.delete_owned(USER, row["id"])
                break
    return describe_action(action) or f"{action.operation} a task"


async def _clean(tasks: ScheduledTaskRepository) -> None:
    for row in await tasks.list_for_user(USER, enabled_only=False):
        await tasks.delete_owned(USER, row["id"])


# The real one. A copy of it here is how the line the model reads in a test
# stops being the line it reads in production.
from backend.services.conversation_service import _step_line as _describe


# Drive the real loop with the real router and the real store.
async def _run(tasks: ScheduledTaskRepository, request: str, now: datetime, steps_max: int):
    selector = _selector()
    clock = now.strftime("%Y-%m-%d %H:%M ") + ZONE

    async def apply(action):
        return "task", {"line": await _apply(tasks, action, now)}

    async def decide(lines: list[str]):
        return await selector.select(
            USER, request, [], None, local_now=clock,
            only=AUTOMATION_TOOLS, steps_taken=lines,
        )

    first = await selector.select(USER, request, [], None, local_now=clock)
    return await run_steps(
        first,
        apply=apply,
        decide=decide,
        describe=_describe,
        creates=lambda item: isinstance(item, ScheduleTaskAction),
        max_steps=steps_max,
        budget_seconds=60.0,
    )


async def test_a_two_step_request_cancels_one_task_and_creates_another() -> None:
    """The required assertion: both steps happened, and the rows prove it."""
    local_now = datetime.now(ZoneInfo(ZONE))
    clock = local_now.strftime("%Y-%m-%d %H:%M ") + ZONE
    request = "cancel the tesla reminder and remind me to take the bins out at 7pm"

    async with AsyncSessionLocal() as session:
        tasks = ScheduledTaskRepository(session)
        await _clean(tasks)
        await tasks.create(
            USER,
            "remind me to do my tesla software update",
            Cadence(
                cadence="once",
                hour=12,
                minute=0,
                weekday=0,
                timezone=ZONE,
                on_date=local_now.date() + timedelta(days=1),
            ),
            channel="imessage",
        )

        steps = await _run(tasks, request, local_now, steps_max=3)

        remaining = await tasks.list_for_user(USER, enabled_only=False)
        tesla = [t for t in remaining if "tesla" in t["instruction"].lower()]
        bins = [t for t in remaining if "bin" in t["instruction"].lower()]

        try:
            assert not tesla, f"the tesla reminder was still there: {tesla}"
            assert len(bins) == 1, f"expected exactly one bins task, got {bins}"
            assert bins[0]["hour"] == 19, f"armed for {bins[0]['hour']}:00"
            # The stop is the router declining, not the ceiling.
            assert len(steps) == 2, f"took {len(steps)} steps: {steps}"
        finally:
            await _clean(tasks)


async def test_a_one_action_request_takes_exactly_one_step() -> None:
    """The duplicate-task regression, asserted directly.

    `create` has no dedupe key, and a loop that keeps deciding is exactly how a
    single reminder becomes two. The stop has to come from the router having
    nothing left to do.
    """
    local_now = datetime.now(ZoneInfo(ZONE))
    request = "remind me to stretch at 6pm"

    async with AsyncSessionLocal() as session:
        tasks = ScheduledTaskRepository(session)
        await _clean(tasks)
        steps = await _run(tasks, request, local_now, steps_max=3)

        rows = await tasks.list_for_user(USER, enabled_only=False)
        try:
            assert len(steps) == 1, f"took {len(steps)} steps: {steps}"
            assert len(rows) == 1, f"expected one task, got {rows}"
        finally:
            await _clean(tasks)


async def test_a_later_step_cannot_reach_outside_the_bookkeeping_tools() -> None:
    """The guard that bounds the blast radius, pinned so it cannot be relaxed.

    Structural rather than behavioural on purpose: `only` is enforced in code
    because a prompt instruction not to reach for search is the kind of thing a
    model ignores under pressure.
    """
    captured: list[list[str]] = []
    selector = _selector()
    original = selector.llm.chat_with_tools

    def spy(messages, tools, max_tokens):
        captured.append([tool["function"]["name"] for tool in tools])
        return original(messages, tools, max_tokens)

    selector.llm.chat_with_tools = spy  # type: ignore[method-assign]
    try:
        await selector.select(
            USER,
            "remind me to take the bins out at 7pm",
            [],
            None,
            local_now="2026-08-23 10:38 " + ZONE,
            only=AUTOMATION_TOOLS,
            steps_taken=["scheduled something"],
        )
    finally:
        selector.llm.chat_with_tools = original  # type: ignore[method-assign]

    assert captured, "the router was never called"
    offered = set(captured[0])
    assert offered <= set(AUTOMATION_TOOLS), f"a later step was offered {offered}"
    assert "search_web" not in offered
    assert "generate_image" not in offered
