"""A continuation's steps are applied as the turn that handed them over.

The run worker is another process. The turn's ContextVars - the channel, the
speaker, the zone, the conversation, the replied-to message - do not exist
there, so the run carries them and the API sets them for the duration of one
step. Without this a reminder created by a group continuation was saved on
"web" and never sent, a room check-in skipped the room's sensitive-subject
refusal, and the change log wrote a null conversation so "undo that" inside
the run was unscoped. The decision reads the conversation's history too; an
empty one re-composed "try again" against nothing.
"""

from __future__ import annotations

import pytest

from backend.services import conversation_service as cs
from backend.services.chat_steps import call_of
from backend.services.turn_steps import Done
from backend.tools.actions import ScheduleTaskAction


def _service() -> cs.ConversationService:
    service = cs.ConversationService.__new__(cs.ConversationService)
    service.repository = None
    service.history_turn_limit = 20
    service.discovery_profile = None
    return service


@pytest.mark.asyncio
async def test_apply_step_sets_the_turns_context_for_the_step_and_restores_it():
    service = _service()
    seen: dict[str, object] = {}

    async def execute(user_id, action, metadata, frame):
        seen["vars"] = {
            "channel": cs._turn_channel.get(),
            "speaker": cs._turn_speaker.get(),
            "zone": cs._turn_zone.get(),
            "conversation": cs._turn_conversation.get(),
            "query": cs._turn_query.get(),
            "replying_to": cs._replying_to.get(),
        }
        seen["metadata"] = metadata
        seen["frame_conversation"] = frame.conversation_id
        return "task", {"kind": "scheduled"}

    service._execute_step = execute  # type: ignore[method-assign]
    outer = cs._turn_channel.get()
    out = await service.apply_step(
        "ani",
        "remind me at nine",
        "conv-1",
        call_of(ScheduleTaskAction("call the bank", "once", 9)),
        context={
            "channel": "imessage_group",
            "speaker_user_id": "member-a",
            "timezone": "America/New_York",
            "replying_to": "guid-1",
        },
    )
    assert out["kind"] == "task"
    assert out["outcome"] == {"kind": "scheduled"}
    assert seen["vars"] == {
        "channel": "imessage_group",
        "speaker": "member-a",
        "zone": "America/New_York",
        "conversation": "conv-1",
        "query": "remind me at nine",
        "replying_to": "guid-1",
    }
    # The executor is told the channel, so `_apply_check_ins` sees the room
    # and refuses a sensitive subject there.
    assert seen["metadata"] == {"channel": "imessage_group"}
    assert seen["frame_conversation"] == "conv-1"
    # The turn's own context is untouched once the step is done.
    assert cs._turn_channel.get() == outer
    assert cs._turn_speaker.get() is None
    assert cs._turn_conversation.get() is None


@pytest.mark.asyncio
async def test_apply_step_restores_the_context_when_the_step_raises():
    service = _service()

    async def broken(user_id, action, metadata, frame):
        raise RuntimeError("the tool is down")

    service._execute_step = broken  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await service.apply_step(
            "ani",
            "remind me",
            "conv-1",
            call_of(ScheduleTaskAction("call the bank", "once", 9)),
            context={"channel": "imessage_group", "speaker_user_id": "member-a"},
        )
    assert cs._turn_channel.get() == "web"
    assert cs._turn_speaker.get() is None


@pytest.mark.asyncio
async def test_decide_step_reads_the_conversation_and_merges_the_room_turns():
    service = _service()
    seen: dict[str, object] = {}
    room_turn = {
        "query": "draw me a chess picture",
        "response": "Here is the picture.",
        "created_at": "2026-09-04T18:00:00",
        "metadata": {},
    }

    class _Repository:
        async def get_history(self, conversation_id, user_id, limit):
            seen["conversation"] = (conversation_id, user_id, limit)
            return [
                {
                    "query": "try again",
                    "response": "",
                    "created_at": "2026-09-04T18:05:00",
                    "metadata": {},
                }
            ]

    class _Selector:
        async def decide(self, user_id, query, history, active_image, **kwargs):
            seen["history"] = [turn["query"] for turn in history]
            seen["replying_to"] = kwargs.get("replying_to")
            return Done("nothing further")

    async def room_turns(user_id):
        return [room_turn]

    service.repository = _Repository()
    service.main_action_selector = _Selector()
    service.room_turns_reader = room_turns

    async def zone(user_id):
        return "America/New_York"

    service._primary_timezone = zone

    view = await service.decide_step(
        "ani",
        "try again",
        [],
        30.0,
        conversation_id="conv-1",
        context={"channel": "imessage", "replying_to": "guid-1"},
    )
    assert view["kind"] == "done"
    assert seen["conversation"] == ("conv-1", "ani", 20)
    # The room's request is beside the direct message, oldest first.
    assert seen["history"] == ["draw me a chess picture", "try again"]
    assert seen["replying_to"] == "guid-1"


@pytest.mark.asyncio
async def test_a_group_continuation_decides_on_its_own_room_alone():
    service = _service()
    seen: dict[str, object] = {}

    class _Selector:
        async def decide(self, user_id, query, history, active_image, **kwargs):
            seen["history"] = list(history)
            return Done("nothing further")

    async def room_turns(user_id):
        raise AssertionError("a room turn must not read the other rooms")

    service.main_action_selector = _Selector()
    service.room_turns_reader = room_turns

    async def zone(user_id):
        return "America/New_York"

    service._primary_timezone = zone
    await service.decide_step(
        "group-1", "what did we decide", [], 30.0,
        conversation_id=None, context={"channel": "imessage_group"},
    )
    assert seen["history"] == []
