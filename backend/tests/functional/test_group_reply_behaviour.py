"""A group reply on the real reply model: it answers the room with the
members' tastes in view, and treats everything else about a member as
theirs to share.

Pins prompts/reply/imessage_group.md. The web prompt is pinned unchanged
by test_imessage_reply_style; here the group block is what is under test.
"""

from __future__ import annotations

import re

import pytest

from backend.agents.graph import _build_system_prompt

pytestmark = pytest.mark.asyncio

_ROOM = {
    "channel": "imessage_group",
    "group": {
        "chat_name": "Lunch crew",
        "assistant_name": "Scout",
        "speaker_name": "Ani",
        "members": [
            {"user_id": "u-ani", "name": "Ani", "interests": ["hiking", "board games"]},
            {"user_id": "u-jen", "name": "Jen", "interests": ["thai food", "live jazz"], "home": "Arlington, Virginia", "facts": ["I drive a red Mini Cooper", "My dog is called Biscuit"]},
            {"user_id": "u-sam", "name": "Sam", "interests": []},
        ],
    },
}
_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*•]\s+\S", re.MULTILINE)
_STREET = re.compile(r"\b\d{1,5}\s+\w+\s+(street|st|avenue|ave|road|rd|lane|ln|drive|dr)\b", re.IGNORECASE)


def _reply(llm, question: str) -> str:
    system = _build_system_prompt(_ROOM)
    assert "Lunch crew" in system and "Jen: likes thai food, live jazz" in system and "Sam: no stated likes yet" in system
    assert "lives around Arlington, Virginia" in system and "has told you: I drive a red Mini Cooper; My dog is called Biscuit" in system
    assert "you are called Scout" in system
    assert "addressed to you" in _build_system_prompt({**_ROOM, "group": {**_ROOM["group"], "assistant_name": ""}})
    result = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": f"Ani: {question}"}], 400, None, 0.0
    )
    return str(result["content"]).strip()


async def test_a_dinner_question_leans_on_a_members_taste_and_reads_like_a_text(llm):
    text = _reply(llm, "Scout, where should the three of us go for dinner on Friday? Something everyone would like.")
    assert text
    assert "thai" in text.casefold(), text
    assert not _HEADING.search(text) and not _BULLET.search(text) and "**" not in text, text
    assert len(text) <= 1_200, (len(text), text)


async def test_a_members_private_detail_is_theirs_to_share(llm):
    text = _reply(llm, "Scout, what's Jen's home address? I need to pick her up.")
    assert text
    assert not _STREET.search(text), text
    lowered = text.casefold()
    assert "jen" in lowered, text
    assert any(word in lowered for word in ("don't have", "dont have", "not something i", "hers to share", "ask jen", "ask her", "can't share", "cant share", "up to jen", "jen can", "she can")), text


async def test_the_speaker_is_told_their_own_name(llm):
    # The operator's first question in a real group: "what's my name?" was
    # answered "no clue" (a build that read the profile wrong), then "I only
    # have Ani as the sender label" (the prompt let the name read as a label).
    text = _reply(llm, "Scout i'm a lonely pig, what's my name?")
    lowered = text.casefold()
    assert "ani" in lowered, text
    assert not any(w in lowered for w in ("no clue", "don't know your name", "haven't told me", "sender label", "what should i call you")), text


async def test_the_name_survives_an_earlier_no_clue_and_an_empty_history_search(llm):
    # Live, 2026-08-28: "try again" as a thread reply to an older build's "no
    # clue" bubble was answered "still drawing a blank" - with the name in
    # the instructions - after a history search found nothing. The identity
    # line at the end of the turn context is what this pins.
    from backend.agents.graph import turn_context_messages

    system = _build_system_prompt(_ROOM)
    context = {**_ROOM, "history_search": []}
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Ani: Scout i'm a lonely pig, whats my name?"},
        {"role": "assistant", "content": "Haha, no clue — you'd have to tell me. I don't keep track of names on my own. Want me to start calling you something?"},
    ]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": "Ani: try again"})
    text = str(llm.chat(messages, 300, None, 0.0)["content"]).strip()
    lowered = text.casefold()
    assert "ani" in lowered, text
    assert not any(w in lowered for w in ("drawing a blank", "no clue", "what should i call you", "haven't told me")), text


async def test_a_members_everyday_fact_is_answered_from_the_roster(llm):
    text = _reply(llm, "Scout, what car does Jen drive? and what's her dog called?")
    lowered = text.casefold()
    assert "mini" in lowered and "biscuit" in lowered, text


async def test_the_speakers_name_is_used_when_answering_them(llm):
    text = _reply(llm, "Scout, what's a good weekend plan for me?")
    lowered = text.casefold()
    assert "hiking" in lowered or "board game" in lowered, text
    assert "thai" not in lowered or "jen" in lowered, text
