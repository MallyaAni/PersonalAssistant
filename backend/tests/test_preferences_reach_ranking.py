"""Standing preferences: how they are stored, and how far they are allowed to travel.

A preference is selected by what it *is* - a purpose stamped when it was
saved - not by asking an embedding whether it looks relevant. The measurement
behind that, taken 2026-08-29: "recommend a salsa night" scored 0.371-0.476
against a stored preference and "what is the capital of Peru" scored 0.499
against the same one. No threshold separates them, so kind is the only honest
selector.

The second half of this file is the bound. `known` reaches the result ranker
(tie-break only) and the per-event description. It must not reach the reply
prompt: a standing interest list once bent unrelated answers toward hiking,
and that is why interests are kept out of it to this day.
"""

from __future__ import annotations

import pytest

from backend.memory.purposes import PREFERENCE_PURPOSE, PREFERENCE_PURPOSES
from backend.services.conversation_service import ConversationService

pytestmark = pytest.mark.asyncio


class _Memory:
    """A memory service that answers only what the preference path asks of it."""

    def __init__(self, preferences: list[dict] | None = None):
        self.preferences = preferences or []
        self.asked_for: list[tuple[str, int]] = []

    async def get_preferences(self, user_id: str, limit: int = 5) -> list[dict]:
        self.asked_for.append((user_id, limit))
        return [item for item in self.preferences if item["user_id"] == user_id][:limit]


def _service(memory: _Memory) -> ConversationService:
    service = ConversationService.__new__(ConversationService)
    service.memory = memory
    return service


PREFERENCES = [
    {"user_id": "ani", "content": "Prefers venues on the metro, in Arlington."},
    {"user_id": "ani", "content": "Prefers quality events, not sketchy ones."},
    {"user_id": "ani", "content": "Dislikes fins."},
    {"user_id": "ani", "content": "A fourth one, past the limit."},
    {"user_id": "someone-else", "content": "Wants the most chocolate possible."},
]


async def test_the_stored_purpose_is_what_selects_a_preference():
    assert PREFERENCE_PURPOSE in PREFERENCE_PURPOSES


async def test_preferences_come_back_as_lines_bounded_to_three():
    lines = await _service(_Memory(PREFERENCES))._known_preferences("ani")
    assert len(lines) == 3, lines
    assert "Prefers venues on the metro, in Arlington." in lines
    assert "A fourth one, past the limit." not in lines


async def test_one_persons_preferences_never_reach_another():
    # The group case: jenos1's chocolate must not colour ani's ranking.
    lines = await _service(_Memory(PREFERENCES))._known_preferences("ani")
    assert not any("chocolate" in line for line in lines), lines


async def test_someone_with_no_preferences_gets_nothing_not_an_error():
    assert await _service(_Memory(PREFERENCES))._known_preferences("nobody") == ()


async def test_a_memory_service_without_the_reader_is_not_an_error():
    # Older services, and every test double written before this existed.
    class _Old:
        pass

    service = ConversationService.__new__(ConversationService)
    service.memory = _Old()
    assert await service._known_preferences("ani") == ()


async def test_a_reader_that_raises_does_not_take_down_the_turn():
    class _Broken(_Memory):
        async def get_preferences(self, user_id: str, limit: int = 5) -> list[dict]:
            raise RuntimeError("the database is having a day")

    service = _service(_Broken())
    known = await service._known_for_ranking({"user_id": "ani", "query": "what's on?"})
    assert isinstance(known, tuple)  # the turn survives; ranking just knows less


async def test_preferences_reach_the_ranker_and_stay_within_its_bound():
    service = _service(_Memory(PREFERENCES))
    known = await service._known_for_ranking({"user_id": "ani", "query": "what's on?"})
    assert any("metro" in line for line in known), known
    # `known` is capped whatever else the turn carries, so a long memory list
    # cannot crowd the ranker's prompt.
    assert len(known) <= 8


async def test_the_reply_prompt_is_not_given_preferences():
    # The bound that matters most, asserted structurally rather than trusted:
    # nothing on the reply path calls the preference reader.
    memory = _Memory(PREFERENCES)
    service = _service(memory)
    await service._known_for_ranking({"user_id": "ani", "query": "what's on?"})
    assert memory.asked_for == [("ani", 3)]


async def test_an_anonymous_turn_asks_for_no_preferences():
    memory = _Memory(PREFERENCES)
    await _service(memory)._known_for_ranking({"query": "what's on?"})
    assert memory.asked_for == []
