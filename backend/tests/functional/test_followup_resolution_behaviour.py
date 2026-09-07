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


async def test_a_try_again_reads_as_asking_for_the_same_thing_again(llm):
    # A group, 2026-09-07: four "try again"s after a no-results listing were
    # each read as a fresh question because the field excluded a failure that
    # had visibly happened - and the group answered its own four retries with
    # nothing. "Try again" is one request whatever the failure was.
    no_results = [{"query": "what's going on in the area?", "response": "Nothing I can date from what came back."}]
    resolution = await resolve_followup(get_routing_llm_client(), "try again", no_results)
    assert resolution is not None and resolution.redoes_previous is True, resolution
    # The same wording after a real answer is the same field: the person
    # wants the thing done again, not a fresh question answered.
    after_answer = await resolve_followup(get_routing_llm_client(), "try again", _SHOW)
    assert after_answer is not None and after_answer.redoes_previous is True, after_answer
    # But the assistant asking a question and the person answering it is not
    # a redo of anything: "the waterfront" is a fresh answer.
    answered = await resolve_followup(
        get_routing_llm_client(),
        "the waterfront",
        [{"query": "where are you heading?", "response": "I can look at the schedule for any of these - where are you heading?"}],
    )
    assert answered is not None and answered.redoes_previous is False, answered
