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


# The sweep's shape: "delete the paused ones" arrives after forty other
# journeys have left the harness user with more reminders, some active, some
# paused, with similar words. The journey gapped on its first run in three
# consecutive sweeps and passed alone on retry (2026-09-02), so the picker is
# measured over the longer list, three reps.
_CROWDED_TASKS = [
    {"id": "6604c6dc-5886-4f56-93b6-61c0164bb244", "instruction": "call the bank", "cadence": "once", "hour": 9, "minute": 0, "timezone": "America/New_York", "on_date": "2026-09-03", "enabled": False},
    {"id": "35fa6698-d06b-4884-96b6-72df2e2ff671", "instruction": "water the plants", "cadence": "once", "hour": 10, "minute": 0, "timezone": "America/New_York", "on_date": "2026-09-03", "enabled": False},
    {"id": "9b1e4d2a-0c7f-4a53-8e1d-2f6b7c8d9e0f", "instruction": "call the dentist", "cadence": "once", "hour": 10, "minute": 0, "timezone": "America/New_York", "on_date": "2026-09-03", "enabled": True},
    {"id": "c2d4e6f8-1a3b-4c5d-8e7f-9a0b1c2d3e4f", "instruction": "Remind me to stretch", "cadence": "daily", "hour": 18, "minute": 0, "timezone": "America/New_York", "enabled": True},
    {"id": "d3e5f7a9-2b4c-4d6e-9f8a-0b1c2d3e4f5a", "instruction": "Weather text for Arlington", "cadence": "daily", "hour": 8, "minute": 0, "timezone": "America/New_York", "enabled": True},
    {"id": "e4f6a8b0-3c5d-4e7f-8a9b-1c2d3e4f5a6b", "instruction": "renew the car registration", "cadence": "once", "hour": 9, "minute": 0, "timezone": "America/New_York", "on_date": "2026-09-03", "enabled": True},
]


async def test_the_paused_ones_among_many_tasks_are_exactly_the_paused_ones() -> None:
    llm = get_routing_llm_client()
    misses = []
    for _ in range(3):
        chosen = await pick_many_tasks(llm, "the paused ones", _CROWDED_TASKS, hint=_LIVE_HINT)
        if set(chosen) != {_CROWDED_TASKS[0]["id"], _CROWDED_TASKS[1]["id"]}:
            misses.append(chosen)
    assert not misses, f"{len(misses)}/3 picked the wrong set: {misses}"


# The pauses that precede it: in the sweep's first run the reply listed the
# bank and plants reminders as still active, so "pause the bank reminder"
# had not found its task among the crowd. pick_one over the same list, the
# words the sweep uses, three reps each.
async def test_one_reminder_named_among_many_is_found() -> None:
    from backend.tasks.picker import pick_task

    llm = get_routing_llm_client()
    active = [dict(task, enabled=True) for task in _CROWDED_TASKS]
    misses = []
    for which, expected in (("the bank reminder", _CROWDED_TASKS[0]["id"]), ("the plants reminder", _CROWDED_TASKS[1]["id"])):
        for _ in range(3):
            chosen = await pick_task(llm, which, active, hint="Got it - I'll remind you tomorrow at 10:00 AM to water the plants.")
            if chosen != expected:
                misses.append((which, chosen))
    assert not misses, f"{len(misses)}/6 picked the wrong reminder: {misses}"
