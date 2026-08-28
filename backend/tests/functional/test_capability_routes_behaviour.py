"""Three capabilities that had no live test naming them: showing a picture
again, building a deck, and managing skills. Routed on the real router from
the phrasings people used (backend.cli.real_utterances, 2026-08-27).
"""

from __future__ import annotations

import pytest

from backend.tools import DelegateAction, ManageSkillsAction, ShowImageAction

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


_PICTURE = [{"query": "make a picture of a brown horse wearing a pink hat", "response": "Here's the image you asked for."}]


async def test_show_me_that_image_shows_it_again(selector) -> None:
    for said in ("can you show me that image?", "yes, show me the mockup image"):
        action = await selector.select("functional_test_user", said, _PICTURE, None)
        assert isinstance(action, ShowImageAction), (said, action)


async def test_make_me_a_deck_goes_to_the_presentation_agent(selector) -> None:
    action = await selector.select("functional_test_user", "make me a deck about the DGX Spark, two slides", [], None)
    assert isinstance(action, DelegateAction), action


async def test_what_skills_do_i_have_lists_them(selector) -> None:
    for said in ("what skills do i have?", "forget the weekend brief skill"):
        action = await selector.select("functional_test_user", said, [], None, skills=[{"id": "s1", "name": "Weekend brief", "slug": "weekend-brief", "instruction": "list three things to do this weekend"}])
        assert isinstance(action, ManageSkillsAction), (said, action)
