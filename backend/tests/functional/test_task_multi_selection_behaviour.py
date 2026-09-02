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
