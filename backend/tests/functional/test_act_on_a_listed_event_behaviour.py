"""After a listing, can it actually do something about one of them?

The operator's standard for this project: it exists to take a task off a
person, not to produce a nicely-formatted page. An events listing that ends
"tell me which one and I'll set a reminder" is a promise, and this is the test
that the promise is kept.

The listing is now written by code from typed records
(`backend/core/events_listing.py`), so the day, the time, the venue and the
price are all in the conversation history, dated
(`backend/services/transcript.py`). That should be everything the router needs
to turn "remind me about the second one" into a real reminder without any new
machinery. This measures whether it is.
"""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from backend.core.dependencies import get_routing_llm_client
from backend.core.event_extraction import Extraction, ListedEvent
from backend.core.events_listing import render_listing
from backend.services.main_action_selector import ScheduleTaskAction
from backend.tasks.picker import pick_task

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)

LISTED = (
    ListedEvent(
        name="Sunday Sessions", venue="The Lawn", area="Batu Bolong", artist="DJ Dea",
        what="Deep house on the grass.", when_text="every Sunday from 4pm", recurring=True,
        starts_at=datetime(2026, 8, 30, 16, 0, tzinfo=UTC), start_time=time(16, 0),
        price_text="free before 6pm", source_url="https://www.thelawncanggu.com/whats-on",
        source_title="The Lawn",
    ),
    ListedEvent(
        name="Sunset Session", venue="Potato Head", area="Seminyak", artist="",
        what="Sunset by the pool.", when_text="Saturday 5 September 2026", recurring=False,
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


async def test_the_listing_puts_the_day_time_and_place_where_a_follow_up_can_use_them():
    # The precondition. If these are not in the reply, nothing downstream can
    # act on them and the tests below would be measuring the wrong thing.
    assert "Sunset Session" in LISTING and "Potato Head" in LISTING
    assert "6pm" in LISTING and "Sat 5 Sep" in LISTING


@pytest.fixture
def selector(llm):
    from backend.config.settings import settings
    from backend.core.dependencies import get_mcp_invocation_service
    from backend.services.main_action_selector import MainActionSelector

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(settings.SEARCH_MCP_SERVER_ID):
        pytest.skip("internet MCP server is not configured as auto-invocable")
    return MainActionSelector(
        llm, invocation, settings.SEARCH_MCP_SERVER_ID, settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration=None, diagram_enabled=True, presentation_enabled=True,
    )


async def test_remind_me_about_the_second_one_becomes_a_real_reminder(selector):
    action = await selector.select(
        "events_user",
        "remind me about the second one",
        _history(),
        None,
        local_now="Saturday 2026-08-29 14:00 - they are in Canggu (Asia/Makassar)",
        zone="Asia/Makassar",
    )
    print(f"\naction: {action!r}")
    assert isinstance(action, ScheduleTaskAction), action
    said = f"{action!r}".casefold()
    # It must be about the one they pointed at, not the first in the list.
    assert "potato" in said or "sunset" in said, action


async def test_the_picker_resolves_which_listed_event_a_follow_up_names():
    # The other half: once reminders exist for both, "move the Potato Head one"
    # has to find the right task rather than the only one with a time.
    tasks = [
        {"id": "t-lawn", "instruction": "Sunday Sessions at The Lawn", "cadence": "once",
         "hour": 16, "minute": 0, "timezone": "Asia/Makassar"},
        {"id": "t-ph", "instruction": "Sunset Session at Potato Head", "cadence": "once",
         "hour": 18, "minute": 0, "timezone": "Asia/Makassar"},
    ]
    chosen = await pick_task(
        get_routing_llm_client(), "the Potato Head one", tasks, hint=LISTING[-400:]
    )
    assert chosen == "t-ph", chosen
