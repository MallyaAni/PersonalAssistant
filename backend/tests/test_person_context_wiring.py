"""The search stage and the ranker read one PersonContext per turn.

Pins the wiring rather than the object: that `_known_for_ranking` is the
object's lines plus the recalled memory, that the same object is reused
within a turn, and that a stated preference reaches the ranker but never the
outbound search terms.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from backend.services import conversation_service as module
from backend.services.conversation_service import ConversationService, _turn_person

pytestmark = pytest.mark.asyncio


class _Profile:
    async def get_profile(self, user_id):
        return SimpleNamespace(interests=[SimpleNamespace(label="salsa"), SimpleNamespace(label="hiking")])


class _Memory:
    def __init__(self) -> None:
        self.calls = 0

    async def get_preferences(self, user_id, limit=5):
        self.calls += 1
        return [{"id": "p1", "content": "uses a wheelchair"}]


def _service() -> ConversationService:
    service = ConversationService.__new__(ConversationService)
    service.discovery_profile = _Profile()
    service.memory = _Memory()
    service.llm = None
    return service


async def test_the_ranker_reads_the_person_and_the_recalled_memory():
    _turn_person.set(None)
    service = _service()
    context = {"user_id": "u", "query": "somewhere to go salsa dancing", "semantic": [{"content": "loves live bands"}]}
    lines = await service._known_for_ranking(context)
    assert any(line.startswith("interests: salsa") for line in lines)
    assert "uses a wheelchair" in lines
    assert "loves live bands" in lines


async def test_one_object_per_turn():
    _turn_person.set(None)
    service = _service()
    context = {"user_id": "u", "query": "x"}
    first = await service._person_context(context)
    second = await service._person_context(context)
    assert first is second
    assert service.memory.calls == 1


async def test_a_preference_never_becomes_a_search_term():
    _turn_person.set(None)
    service = _service()
    person = await service._person_context({"user_id": "u", "query": "x"})
    assert person.search_terms() == ("salsa", "hiking")
    assert "uses a wheelchair" not in person.search_terms(100)


def test_the_search_stage_takes_its_interests_from_the_person():
    source = inspect.getsource(module.ConversationService._stream_web_search)
    assert "self._person_context(context)" in source
    assert "person.search_terms(" in source
    assert "_known_interests(" not in source, "the search stage must not fetch its own view"
