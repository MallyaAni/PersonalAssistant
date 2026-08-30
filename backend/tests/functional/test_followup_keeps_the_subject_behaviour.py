"""A follow-up's search names what the conversation is about - and results
about something else are not the answer.

2026-08-26, over iMessage: in a conversation about Netflix's "Surviving
Paradise", "does only one person win at the end?" was searched as "Squid
Game The Challenge ... winner" and "you mentioned there was only one
season" as "Love Island USA seasons"; the reply then described Love Island
winners as the answer. The router must copy the subject, never substitute
one; the reply must notice results about the wrong thing.
"""

from __future__ import annotations

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.tests.functional.semantic import states
from backend.tools import SearchAction

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


_SHOW = [
    {"query": "Please describe the premise of Netflix's Surviving Paradise",
     "response": "Twelve contestants think they are headed to a luxury villa in Greece; instead most are banished to the wilderness and must earn their way in, competing for $100,000. Season 1 dropped October 20, 2023."},
]
_PRODUCT = [
    {"query": "tell me about the Framework Laptop 13",
     "response": "The Framework Laptop 13 is a modular, repairable 13-inch laptop with swappable ports and mainboards; the current generation uses AMD Ryzen AI 300 chips."},
]

_OTHER_SHOWS = ("love island", "squid game", "the circle", "too hot to handle", "survivor")


@pytest.mark.parametrize(
    "followup",
    ["does only one person win at the end?", "how do they make it into the villa?", "you mentioned there was only one season"],
)
async def test_a_followup_about_a_show_searches_that_show(selector, followup: str) -> None:
    action = await selector.select("functional_test_user", followup, _SHOW, None)
    assert isinstance(action, SearchAction), action
    query = action.query.casefold()
    assert "surviving paradise" in query, action.query
    assert not any(other in query for other in _OTHER_SHOWS), action.query


async def test_a_followup_about_a_product_searches_that_product(selector) -> None:
    action = await selector.select("functional_test_user", "does it have a touchscreen option?", _PRODUCT, None)
    assert isinstance(action, SearchAction), action
    assert "framework" in action.query.casefold(), action.query


_LOVE_ISLAND = [
    {"title": "Love Island USA winners by season", "url": "https://example.com/li",
     "content": "Season 6 winners Serena Page and Kordell Beckham split the $100,000; season 7 Amaya Espinal and Bryan Arenales; the final couple chooses to split or keep."},
    {"title": "Love Island USA season 8 finale", "url": "https://example.com/li8",
     "content": "Bryce Dettloff and Trinity Tatum won season 8 and split the prize."},
]
_SURVIVING = [
    {"title": "Surviving Paradise finale explained", "url": "https://example.com/sp",
     "content": "In the Surviving Paradise finale the remaining villa contestants vote; Joel Fugler was named the season 1 winner and took the $100,000."},
    {"title": "Surviving Paradise season 1 recap", "url": "https://example.com/sp1",
     "content": "Netflix's Surviving Paradise season 1: how the outsiders earned their way into the villa and who won."},
]


async def test_the_ranker_flags_results_about_a_different_show(llm) -> None:
    from backend.core.result_ranking import judge_results

    question = "does only one person win at the end? (searched as: Surviving Paradise Netflix winner how many win)"
    off = await judge_results(llm, question, "Arlington, Virginia", _LOVE_ISLAND)
    assert off.on_subject is False, off
    on = await judge_results(llm, question, "Arlington, Virginia", _SURVIVING)
    assert on.on_subject is True, on


async def test_results_about_a_different_show_are_not_the_answer(llm) -> None:
    context = {
        "channel": "imessage",
        "search_state": {"ran": True, "off_subject": True},
        "search": [
            {"title": "Love Island USA winners by season", "url": "https://example.com/li",
             "content": "Season 6 winners Serena Page and Kordell Beckham split the $100,000; season 7 Amaya Espinal and Bryan Arenales; the final couple chooses to split or keep."},
            {"title": "Love Island USA season 8 finale", "url": "https://example.com/li8",
             "content": "Bryce Dettloff and Trinity Tatum won season 8 and split the prize."},
        ],
    }
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.extend([
        {"role": "user", "content": _SHOW[0]["query"]},
        {"role": "assistant", "content": _SHOW[0]["response"]},
        {"role": "user", "content": "does only one person win at the end?"},
    ])
    text = str(llm.chat(messages, 400, None, 0.0)["content"])
    assert not states(text, "The reply presents Love Island winners or a couple splitting the prize as the answer about Surviving Paradise."), text
    # The disclosure itself is no longer the model's to write. Asked for it,
    # it arrived once in six (measured 2026-08-29) - five times out of six the
    # assistant answered from memory as though it had checked. Code now sends
    # that sentence before the model's first token
    # (conversation_service, beside the events listing), so what is asked of
    # the model here is the other half: having been told the disclosure is
    # already made, it must not undo it by claiming to have looked something up.
    assert not states(text, "The reply claims to have looked this up, searched, or checked it just now."), text
