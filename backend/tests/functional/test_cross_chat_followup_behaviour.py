"""A direct "try again" after a picture asked for in the group is read as
that retry, when the router is shown the room's turn beside the direct ones.

Live, 2026-09-04 and 2026-09-05: "try again" in the one-to-one chat, minutes
after a chess picture was asked for in the group, was routed to an events
search both times - the direct chat's own history said nothing about a
picture. The router now sees the person's recent room turns marked as the
room's. This sends the merged history to the real resolver and router and
asks that "try again" be read as a picture retry, not a search.

pinned prompt: referent/followup (with a room turn labelled in the transcript).
"""

from __future__ import annotations

import pytest

from backend.core.dependencies import get_routing_llm_client
from backend.services.cross_chat import merged_for_routing
from backend.services.followup import resolve_followup
from backend.services.main_action_selector import MainActionSelector
from backend.tools.actions import GenerateImageAction, SearchAction

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_DIRECT = [
    {"query": "what are the most fun events happening in the area this week?", "response": "Sat 5 Sep - Africa Fest, White Bank Park...", "metadata": {"channel": "imessage"}, "created_at": "2026-09-04T12:01:00+00:00"},
]
_ROOM = [
    {"query": "Can you please generate a picture that shows a “castle” in chess?", "response": "Here's the image you asked for.",
     "metadata": {"channel": "imessage_group", "group": {"speaker_name": "Jenos"}, "cross_chat": {"chat_name": "Groupie"}, "artifact_ids": ["e4fad6e3"], "trace": {"route": {"label": "New images", "detail": "A chessboard close-up showing the castle move"}}},
     "created_at": "2026-09-04T21:10:00+00:00"},
]
_MERGED = merged_for_routing(_DIRECT, _ROOM)


@pytest.fixture(scope="session")
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")
    return MainActionSelector(
        llm, invocation, settings.SEARCH_MCP_SERVER_ID, settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None, diagram_enabled=True, presentation_enabled=True,
    )


async def test_the_resolver_reads_the_retry_against_the_rooms_picture():
    held = 0
    seen = []
    for _ in range(3):
        resolution = await resolve_followup(get_routing_llm_client(), "try again", _MERGED)
        seen.append(resolution)
        if resolution is not None and resolution.refers_to == "picture" and "chess" in f"{resolution.self_contained} {resolution.subject}".casefold():
            held += 1
    assert held >= 2, seen


async def test_the_router_retries_the_picture_rather_than_searching(selector):
    pictures = searches = 0
    seen = []
    for _ in range(3):
        action = await selector.select("cross_chat_eval", "try again", _MERGED, None)
        seen.append(action)
        if isinstance(action, GenerateImageAction):
            pictures += 1
        if isinstance(action, SearchAction):
            searches += 1
    assert pictures >= 2, seen
    assert searches == 0, seen


async def test_without_the_room_turn_the_same_words_are_not_a_picture(selector):
    # The control: the direct history alone gives "try again" no picture to
    # retry, so a picture route here would mean the words, not the merge.
    pictures = 0
    seen = []
    for _ in range(3):
        action = await selector.select("cross_chat_eval", "try again", _DIRECT, None)
        seen.append(action)
        if isinstance(action, GenerateImageAction):
            pictures += 1
    assert pictures <= 1, seen
