"""An opinion about the picture in view is a conversation, not an edit or a
re-show - and a request to change it is still an edit.

Measured 0/9 as no-tool on 2026-08-26 (edit) and 2026-08-27 (show) before
discuss_image gave the router a third thing to choose.
"""

from __future__ import annotations

import pytest

from backend.tools import DiscussImageAction, EditImageAction

pytestmark = pytest.mark.asyncio


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


_PICTURE = [{"query": "make a picture of me in a linen outfit with a straw hat",
             "response": "Here's the image you asked for."}]


@pytest.mark.parametrize(
    "said",
    [
        "which hat do you like better for this outfit?",
        "would the cowboy hat have suited me better?",
        "do you think the colours work together?",
    ],
)
async def test_an_opinion_about_the_picture_is_discussed_not_edited(selector, said: str) -> None:
    action = await selector.select("functional_test_user", said, _PICTURE, "active-image-id")
    assert isinstance(action, DiscussImageAction), action


async def test_a_change_is_still_an_edit(selector) -> None:
    action = await selector.select("functional_test_user", "swap the straw hat for a cowboy hat", _PICTURE, "active-image-id")
    assert isinstance(action, EditImageAction), action
