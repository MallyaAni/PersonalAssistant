"""The listing's link offer is kept: "send me the links for the salsa night" works.

The listing used to print a row of links under every event; it now ends by
offering them, so the follow-up that delivers them is the whole feature - an
offer nobody can take up is the failure this project keeps circling. This runs
the real router against the real model, exactly as the reminder follow-up
does, and then exercises the real picker plus the code-built link renderer, so
it measures that "the second one" resolves to the event it points at and the
links are grounded, not invented.
"""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_routing_llm_client,
)
from backend.core.event_extraction import Extraction, ListedEvent
from backend.core.events_listing import render_listing
from backend.services.main_action_selector import MainActionSelector
from backend.tasks.picker import pick_many
from backend.tools.actions import SendEventLinksAction

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

NOW = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)

LISTED = (
    ListedEvent(
        name="Sunday Sessions", venue="The Lawn", area="Batu Bolong", artist="DJ Dea",
        what="Deep house on the grass.", when_text="every Sunday from 4pm",
        recurring=True,
        starts_at=datetime(2026, 8, 30, 16, 0, tzinfo=UTC), start_time=time(16, 0),
        price_text="free before 6pm", source_url="https://www.thelawncanggu.com/whats-on",
        source_title="The Lawn",
    ),
    ListedEvent(
        name="Sunset Session", venue="Potato Head", area="Seminyak", artist="",
        what="Sunset by the pool.", when_text="Saturday 5 September 2026",
        recurring=False,
        starts_at=datetime(2026, 9, 5, 18, 0, tzinfo=UTC), start_time=time(18, 0),
        price_text="entry IDR 250k", source_url="https://potatohead.co/events",
        source_title="Potato Head",
    ),
)
LISTING = render_listing(Extraction(LISTED), NOW)


def _history() -> list[dict]:
    return [
        {
            "query": "what's on in Canggu this weekend?",
            "response": LISTING,
            "created_at": "2026-08-29T18:00:00+00:00",
        }
    ]


@pytest.fixture
def selector(llm):
    from backend.config.settings import settings

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")
    return MainActionSelector(
        llm, invocation, settings.SEARCH_MCP_SERVER_ID, settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None, diagram_enabled=True, presentation_enabled=True,
    )


async def test_links_for_a_listed_event_route_to_send_event_links(selector):
    # The follow-up the new tool exists for. It must name the event that was
    # asked about, not answer about the first in the list.
    action = await selector.select(
        "events_user",
        "send me the links for the sunset session",
        _history(),
        None,
        local_now="Saturday 2026-08-29 14:00 - they are in Canggu (Asia/Makassar)",
        zone="Asia/Makassar",
    )
    print(f"\naction: {action!r}")
    assert isinstance(action, SendEventLinksAction), action
    said = f"{action!r}".casefold()
    assert "sunset" in said or "potato" in said, action


async def test_the_picker_targets_the_named_event_and_the_links_are_grounded():
    # The other half: given the typed records, the picker resolves which event
    # "the sunset session at potato head" means, and the code-built message
    # carries grounded links for that event - not the first in the list.
    from backend.core.event_links import render_links_for
    from backend.core.links import URL_IN_TEXT, template_is_grounded

    items = [
        {"id": str(i), "name": e.name, "venue": e.venue, "area": e.area}
        for i, e in enumerate(LISTED)
    ]

    def _describe(item: dict) -> str:
        where = ", ".join(
            part for part in (item.get("venue") or "", item.get("area") or "") if part
        )
        return f"{item.get('name')} at {where}"

    picked = await pick_many(
        get_routing_llm_client(),
        "the sunset session at potato head",
        items,
        _describe,
        hint=LISTING,
    )
    assert picked, picked
    chosen = [LISTED[int(i)] for i in picked]
    message = render_links_for(chosen)
    assert "Sunset Session" in message, message
    assert "Potato Head" in message, message
    assert "Sunday Sessions" not in message, message
    sources = {e.source_url for e in chosen}
    for url in URL_IN_TEXT.findall(message):
        cleaned = url.rstrip(".,;:!?)]}\"'")
        assert cleaned in sources or template_is_grounded(
            cleaned, LISTING
        ), cleaned
