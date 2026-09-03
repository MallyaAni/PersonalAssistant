"""A group's scheduled firing runs on the zone the task was set in. A room
has no home and a firing no speaker, so the chess tip ran on UTC and wished
the group fun at trivia "later" the morning after (2026-09-03)."""
from types import SimpleNamespace

import pytest

from backend.services.conversation_service import ConversationService, _turn_zone


class _NoPlace:
    async def get_profile(self, user_id: str):
        return SimpleNamespace(localities=())


@pytest.mark.asyncio
async def test_a_group_without_a_place_runs_on_the_firings_zone():
    service = ConversationService.__new__(ConversationService)
    service.discovery_profile = _NoPlace()
    token = _turn_zone.set("America/New_York")
    try:
        assert await service._primary_timezone("group:abc") == "America/New_York"
        assert await service._primary_place("group:abc") == ("", "America/New_York")
    finally:
        _turn_zone.reset(token)
    token = _turn_zone.set("")
    try:
        assert await service._primary_timezone("group:abc") is None
        assert await service._primary_place("group:abc") is None
    finally:
        _turn_zone.reset(token)
