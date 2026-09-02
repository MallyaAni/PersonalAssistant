"""Does "the paused ones" pick every paused task, and nothing else?

2026-09-02: "delete the paused ones" (a real utterance) reached a picker
that returned exactly one id, so of a set of paused tasks only one could
ever be cancelled - the rest stayed scheduled no matter what the reply
claimed. A set is a valid selection: the words name several tasks, and the
picker must return all of them.
"""

from __future__ import annotations

import pytest

from backend.core.dependencies import get_routing_llm_client
from backend.tasks.picker import pick_many_tasks

pytestmark = pytest.mark.asyncio

_TASKS = [
    {"id": "t-stretch", "instruction": "Remind me to stretch", "cadence": "daily", "hour": 18, "minute": 0, "timezone": "America/New_York", "enabled": False},
    {"id": "t-weather", "instruction": "Weather text at 7am", "cadence": "daily", "hour": 7, "minute": 0, "timezone": "America/New_York", "enabled": False},
    {"id": "t-tito", "instruction": "Don Tito reminder tonight", "cadence": "once", "hour": 19, "minute": 0, "timezone": "America/New_York", "enabled": True},
]


async def test_the_paused_ones_names_every_paused_task() -> None:
    llm = get_routing_llm_client()
    for _ in range(3):
        chosen = await pick_many_tasks(llm, "the paused ones", _TASKS)
        assert set(chosen) == {"t-stretch", "t-weather"}, chosen


async def test_a_single_task_is_still_one_id() -> None:
    llm = get_routing_llm_client()
    chosen = await pick_many_tasks(llm, "the stretch reminder", _TASKS)
    assert chosen == ["t-stretch"], chosen


async def test_nothing_matching_is_an_empty_list() -> None:
    llm = get_routing_llm_client()
    chosen = await pick_many_tasks(llm, "the scout sweep", _TASKS)
    assert chosen == [], chosen


# The live shape: real UUIDs, the schedule phrase with a date, and the
# assistant's previous sentence as the hint. Two reminders of 36-character
# ids did not fit the picker's fixed 64-token answer and came back as an
# empty list (the deploy sweep, 2026-09-02); the ids above are short enough
# to have hidden it.
_LIVE_TASKS = [
    {"id": "6604c6dc-5886-4f56-93b6-61c0164bb244", "instruction": "call the bank", "cadence": "once", "hour": 9, "minute": 0, "timezone": "America/New_York", "on_date": "2026-09-03", "enabled": False},
    {"id": "35fa6698-d06b-4884-96b6-72df2e2ff671", "instruction": "water the plants", "cadence": "once", "hour": 10, "minute": 0, "timezone": "America/New_York", "on_date": "2026-09-03", "enabled": False},
    {"id": "9b1e4d2a-0c7f-4a53-8e1d-2f6b7c8d9e0f", "instruction": "call the dentist", "cadence": "once", "hour": 10, "minute": 0, "timezone": "America/New_York", "on_date": "2026-09-03", "enabled": True},
]
_LIVE_HINT = (
    "Done — I've paused the reminder to water the plants that was set for tomorrow at 10:00 AM. "
    "It won't fire on Thursday, and it's now on hold. Just let me know if you'd like me to resume or reschedule it."
)


async def test_the_paused_ones_with_real_ids_and_the_live_hint() -> None:
    llm = get_routing_llm_client()
    for _ in range(3):
        chosen = await pick_many_tasks(llm, "the paused ones", _LIVE_TASKS, hint=_LIVE_HINT)
        assert set(chosen) == {_LIVE_TASKS[0]["id"], _LIVE_TASKS[1]["id"]}, chosen
