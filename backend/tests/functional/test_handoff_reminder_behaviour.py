"""A reminder made by a continuation is saved on the channel it came from.

A turn that runs out its clock hands the rest to a durable run. Before the
run carried the turn's channel, `apply_step` executed with empty metadata, so
`schedule_task` saved the reminder on "web" - the reply confirmed it and the
task runner, which delivers by channel, never sent it. The same missing
context left the change log's conversation null, so "undo that" inside the
run was unscoped.

This drives the production hand-off (`_hand_off` creating the run, the run
claimed the way the worker claims it) and the real `ChatContinuationWorld`
into the real `apply_step`, against the real schema. Only the router's choice
is scripted: the defect was in what the boundary carried, not in what the
model decided.

pinned prompt: none - this is the step boundary, not a prompt.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.agents.chat.world import KIND, ChatContinuationWorld
from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.runs.repository import AgentRunRepository
from backend.services.chat_steps import decision_view
from backend.services.conversation_service import ConversationService, _turn_speaker
from backend.services.turn_steps import BUDGET, Act
from backend.tasks.repository import ScheduledTaskRepository
from backend.tools.actions import ScheduleTaskAction

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

ZONE = "America/New_York"


# The one dependency `_schedule_task` needs beyond the repository: the zone
# the reminder is armed in. The channel assertion below does not depend on it.
class _Profile:
    async def get_profile(self, _owner: str):
        locality = SimpleNamespace(is_primary=True, timezone=ZONE)
        return SimpleNamespace(localities=(locality,))


class _ScriptedSteps:
    """The two API routes, answered from a script and applied for real."""

    def __init__(self, service: ConversationService) -> None:
        self.service = service
        self.contexts: list[dict | None] = []

    async def decide(self, user_id, query, lines, remaining_seconds, context=None):
        self.contexts.append(context)
        return decision_view(
            Act(
                ScheduleTaskAction(
                    instruction="call the bank",
                    cadence="once",
                    hour=9,
                    minute=0,
                )
            )
        )

    async def apply(self, user_id, query, conversation_id, call, context=None):
        self.contexts.append(context)
        return await self.service.apply_step(
            user_id, query, conversation_id, call, context=context
        )


async def _hand_off_and_claim(service: ConversationService, user: str) -> dict:
    """Hand a budget-stopped turn to a run, then claim it before the live worker does."""
    for _attempt in range(5):
        handed = await service._hand_off(
            user,
            "remind me tomorrow at 9am to call the bank",
            {
                "channel": "imessage",
                "timezone": ZONE,
                "replying_to": "guid-1",
            },
            str(uuid.uuid4()),
            ["web search: bank hours (2 results)"],
            BUDGET,
        )
        assert handed is not None, "the hand-off created no run"
        async with AsyncSessionLocal() as db:
            claimed = await AgentRunRepository(db).claim_next(
                "handoff-test", 60.0, kinds=(KIND,), user_id=user
            )
        if claimed is not None:
            return claimed
    raise AssertionError("a live worker claimed every run this test created")


async def _clean(user: str) -> None:
    from backend.api.v1.admin import purge_owned_rows

    async with AsyncSessionLocal() as db:
        await AgentRunRepository(db).delete_for_user(user)
        await purge_owned_rows(db, user)
        await db.commit()


async def test_a_continuations_reminder_is_saved_on_the_channel_it_came_from(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_RUNS_ENABLED", True)
    user = f"functional-handoff-{uuid.uuid4().hex[:10]}"

    service = ConversationService.__new__(ConversationService)
    service.discovery_profile = _Profile()  # type: ignore[attr-defined]
    service.repository = None  # type: ignore[attr-defined]

    try:
        # The repository's session must outlive the step: `apply_step` saves
        # the task through it, so it is opened around the whole continuation.
        async with AsyncSessionLocal() as db:
            service.scheduled_tasks = ScheduledTaskRepository(db)  # type: ignore[attr-defined]
            token = _turn_speaker.set("ani")
            try:
                claimed = await _hand_off_and_claim(service, user)
                assert claimed["channel"] == "imessage", claimed
                assert claimed["timezone"] == ZONE, claimed
                assert claimed["replying_to"] == "guid-1", claimed

                client = _ScriptedSteps(service)
                world = ChatContinuationWorld(claimed, client)
                decision = await world.decide([])
                assert isinstance(decision, Act), decision
                applied = await world.apply(decision.action)
                assert applied is not None, "the continuation's step was dropped"
                kind, outcome = applied
                assert kind == "task", applied
                assert outcome["kind"] == "scheduled", outcome

                tasks = await ScheduledTaskRepository(db).list_for_user(
                    user, enabled_only=False
                )
                assert len(tasks) == 1, tasks
                assert tasks[0]["channel"] == "imessage", (
                    "a reminder from a continuation was saved on the wrong channel "
                    f"({tasks[0]['channel']!r}) and would never be delivered"
                )
                # The change is scoped to the conversation the run continues, so
                # "undo that" inside the run acts on this reminder and not on the
                # newest change anywhere else in the account.
                change = await ScheduledTaskRepository(db).latest_undoable(
                    user, claimed["conversation_id"]
                )
                assert change is not None, "the continuation's change was logged unscoped"
                assert change["kind"] == "scheduled"

                expected = {
                    "channel": "imessage",
                    "speaker_user_id": "ani",
                    "timezone": ZONE,
                    "replying_to": "guid-1",
                }
                assert client.contexts == [expected, expected], client.contexts
            finally:
                _turn_speaker.reset(token)
    finally:
        await _clean(user)
