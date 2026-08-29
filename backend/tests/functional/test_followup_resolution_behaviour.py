"""One reading of a follow-up, before anything acts on it.

Every incident of 2026-08-26/27 was a second turn about something the first
turn mentioned, resolved separately - and differently - by the router, the
search composer, the task picker and the memory agent. This pins the single
resolver on the real routing model: the restatement carries the exact thing
the conversation names, and says what kind of thing it is.
"""

from __future__ import annotations

import pytest

from backend.core.dependencies import get_routing_llm_client
from backend.services.followup import resolve_followup

pytestmark = pytest.mark.asyncio

_SHOW = [{"query": "Please describe the premise of Netflix's Surviving Paradise",
          "response": "Twelve contestants think they are headed to a luxury villa in Greece; most are banished to the wilderness and must earn their way in, competing for $100,000."}]
_PICTURE = [{"query": "make a picture of me in a straw hat with a linen outfit",
             "response": "Here's the image you asked for."}]
_DRAFT = [{"query": "draft an email to my retail team asking for shift coverage this Saturday",
           "response": "Subject: Shift coverage this Saturday\n\nHi team, I need cover for Saturday 8am-7pm. Please reply by Thursday if you can take it. Thanks, Ani"}]
_TASK = [{"query": "remind me tomorrow at 9am to call the dentist",
          "response": "Done - I've set a reminder to call the dentist tomorrow at 9:00 AM."}]
_SCOUT = [{"query": "run scout every day at 3pm",
           "response": "Done - Scout's sweep is now scheduled for daily at 3:00 PM."}]
_ICE_CREAM = [{"query": "what's your favorite ice cream?",
               "response": "Ha, I don't have taste buds, but for your 9pm run tonight I'd go classic salted caramel. What's yours two?"}]


@pytest.mark.parametrize(
    ("history", "message", "kind", "must_contain"),
    [
        (_SHOW, "does only one person win at the end?", "subject", "surviving paradise"),
        (_SHOW, "you mentioned there was only one season", "subject", "surviving paradise"),
        (_PICTURE, "which hat do you like better for this outfit?", "picture", "hat"),
        (_PICTURE, "can you regenerate it?", "picture", ""),
        (_DRAFT, "More casual", "draft", ""),
        (_TASK, "move it to 10am", "task", "dentist"),
        (_SCOUT, "make it weekly instead", "scout", "scout"),
        # Live in a group, 2026-08-28: no pronoun, but only about ice cream.
        (_ICE_CREAM, "based on what you know about us what do you think we will like", "subject", "ice cream"),
    ],
)
async def test_the_reading_names_the_thing_and_its_kind(llm, history, message, kind, must_contain):
    resolution = await resolve_followup(get_routing_llm_client(), message, history)
    assert resolution is not None
    assert resolution.refers_to == kind, resolution
    restated = resolution.self_contained.casefold()
    # The thing may be named in the restatement or in `subject`: the reply
    # and the search rounds read both (an implicit subject - "what do you
    # think we will like" after ice cream - tends to land in `subject`).
    assert must_contain in restated or must_contain in resolution.subject.casefold(), resolution
    for other in ("love island", "squid game"):
        assert other not in restated, resolution


async def test_a_standalone_message_is_left_alone(llm):
    resolution = await resolve_followup(get_routing_llm_client(), "what is the capital of Peru?", _SHOW)
    assert resolution is not None and resolution.refers_to == "none", resolution
    assert "peru" in resolution.self_contained.casefold() and "paradise" not in resolution.self_contained.casefold(), resolution


async def test_the_reading_never_answers_or_adds_facts(llm):
    resolution = await resolve_followup(get_routing_llm_client(), "does only one person win at the end?", _SHOW)
    restated = resolution.self_contained.casefold()
    assert "?" in resolution.self_contained, resolution
    assert not any(word in restated for word in ("yes", "no,", "winner is", "joel")), resolution
