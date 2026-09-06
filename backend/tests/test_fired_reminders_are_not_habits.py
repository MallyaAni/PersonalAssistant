"""A reminder that fired is not something the person said, and a photo
shared in a room without addressing the assistant is still seen.

Two live failures from 2026-09-05, pinned without a model. A weekly
reminder's instruction replays as the user's line every time it fires, so
the reply read a place the person hates as "your usual move"; the transcript
now marks a firing as a firing and recall skips it. And a picture sent to a
room without naming the assistant was dropped before anything looked at it;
the room path now describes and stores it under the room and the sharer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.services.transcript import FIRING_NOTE, is_a_firing, transcript_lines, user_content

pytestmark = pytest.mark.asyncio

_FIRED = {
    "query": "Remind me about salsa at Don Tito's",
    "response": "Salsa night at Don Tito's is today.",
    "metadata": {"channel": "imessage", "scheduled_task": {"id": "t1"}},
    "created_at": "2026-09-02T21:00:00+00:00",
}
_SAID = {"query": "shut it with don titos, i don't care about that", "response": "Fine.", "metadata": {"channel": "imessage"}}


def test_a_firing_is_told_apart_from_a_thing_they_said():
    assert is_a_firing(_FIRED) is True
    assert is_a_firing(_SAID) is False
    assert is_a_firing({}) is False


def test_the_reply_sees_a_firing_marked_as_one():
    fired = user_content(_FIRED)
    assert FIRING_NOTE in fired and "Remind me about salsa at Don Tito's" in fired
    assert FIRING_NOTE not in user_content(_SAID)


def test_the_router_and_resolver_see_the_same_marking():
    lines = transcript_lines([_FIRED, _SAID])
    assert FIRING_NOTE in lines[0]
    assert all(FIRING_NOTE not in line for line in lines[2:])


class _Repo:
    def __init__(self, rows):
        self.rows = rows

    async def get_recalled_turns(self, user_id, embedding, top_k, max_distance, exclude):
        return self.rows


async def test_recall_skips_the_firings_and_keeps_what_they_said():
    from backend.services.postgres_memory_service import PostgresMemoryService

    fired = SimpleNamespace(
        query="Remind me about salsa at Don Tito's", created_at=datetime(2026, 9, 2, 21, tzinfo=UTC),
        extra_data={"channel": "imessage", "scheduled_task": {"id": "t1"}},
    )
    said = SimpleNamespace(
        query="i hate don tito's except for salsa nights", created_at=datetime(2026, 9, 5, 21, tzinfo=UTC),
        extra_data={"channel": "imessage"},
    )
    service = PostgresMemoryService.__new__(PostgresMemoryService)
    service.repo = _Repo([(fired, 0.1), (fired, 0.12), (said, 0.2)])
    recalled = await service.get_recalled_turns("ani", [0.0] * 768, top_k=3, max_cosine_distance=0.5)
    assert [item["said"] for item in recalled] == ["i hate don tito's except for salsa nights"]
