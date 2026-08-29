"""The burst judgement on the real routing model: unfinished fragments wait,
closings get no reply, questions and answers get one.

Pins prompts/routing/readiness.md. Each case is a sequence of texts as a
person would send them, with the assistant's previous bubble where one
matters. Floors rather than 100%: the model is the ceiling, and a case
that flips at temperature 0 is recorded here rather than hidden.
"""

from __future__ import annotations

import pytest

from backend.services.readiness import judge_readiness

pytestmark = pytest.mark.asyncio

# (previous assistant bubble, fragments so far, expected complete, expected needs_reply)
CASES = [
    ("", ["what's the weather friday"], True, True),
    ("", ["ok so"], False, None),
    ("", ["quick question"], False, None),
    ("", ["ok so", "can you find a thai place near dupont"], True, True),
    ("", ["thanks!"], True, False),
    ("", ["sounds good"], True, False),
    ("", ["👍"], True, False),
    ("", ["ok", "thanks, see you then"], True, False),
    ("Thai or pizza on Friday?", ["thai then"], True, True),
    ("Thai or pizza on Friday?", ["friday?"], True, True),
    ("Want me to book it for 7?", ["yes please"], True, True),
    # A decline of an offer: nothing happens either way, so either reading is
    # accepted (the real model says "no reply", 2026-08-28).
    ("Want me to book it for 7?", ["no thanks"], True, None),
    ("", ["thanks! also what time does the apple store close"], True, True),
    ("", ["what about"], False, None),
    ("", ["remind me tomorrow at 9 to call the bank"], True, True),
    # Live, 2026-08-28: judged unfinished, answered only after the cap.
    ("Clear sky and hot here today, 94 high.", ["what location are you looking?"], True, True),
    ("", ["where r u"], True, True),
]


@pytest.mark.parametrize("previous, fragments, complete, needs_reply", CASES)
async def test_each_burst_is_judged_by_meaning(structured_llm, previous, fragments, complete, needs_reply):
    verdict = await judge_readiness(structured_llm, previous, list(fragments))
    assert verdict.complete is complete, (fragments, verdict)
    if needs_reply is not None and complete:
        assert verdict.needs_reply is needs_reply, (fragments, verdict)


# A reply to the assistant's bubble or a mention is answered by the worker
# regardless of this judgement (deliberate address); what the judge must
# still get right for those is completeness.
@pytest.mark.parametrize("fragments, addressed_by", [
    (["we are a groupie!!"], "reply"),
    (["haha nice"], "reply"),
    (["thanks!"], "reply"),
    (["lol"], "mention"),
])
async def test_a_reply_to_the_assistants_bubble_is_read_as_finished(structured_llm, fragments, addressed_by):
    verdict = await judge_readiness(
        structured_llm, "Folks in here are: Ani and Jen.", list(fragments), in_group=True, addressed_by=addressed_by
    )
    assert verdict.complete is True, (fragments, verdict)


async def test_a_reply_to_the_room_but_not_to_the_assistant_wants_nothing(structured_llm):
    verdict = await judge_readiness(
        structured_llm, "Thai on Friday at 7 works for everyone?", ["Jen are you bringing Sam?"], in_group=True
    )
    assert verdict.complete is True
    assert verdict.needs_reply is False, verdict


# A positive tapback accepts an action offered by the exact bubble it targets,
# but remains a quiet social reaction when that bubble offered nothing to do.
@pytest.mark.parametrize(
    "previous, expected",
    [
        ("Want me to search for a few places near you?", True),
        ("I can move that reminder to Friday if you want.", True),
        ("Should I move the reminder to Friday?", True),
        ("I can send you the full list if you'd like.", True),
        ("Friday should be sunny, with a high around 75.", False),
        ("Haha, that really is a tiny hat 😄", False),
        ("Which sounds better to you, Thai or pizza?", False),
        ("Done — I moved the reminder to Friday.", False),
        ("Here are three good Thai places near Dupont Circle.", False),
        ("Thanks for telling me — that helps.", False),
    ],
)
async def test_a_positive_tapback_only_accepts_an_offer(structured_llm, previous, expected):
    verdict = await judge_readiness(
        structured_llm, previous, ["❤️"], addressed_by="tapback"
    )
    assert verdict.complete is True, verdict
    assert verdict.accepts_offer is expected, verdict


async def test_the_whole_run_holds_a_floor(structured_llm):
    right = 0
    for previous, fragments, complete, needs_reply in CASES:
        verdict = await judge_readiness(structured_llm, previous, list(fragments))
        ok = verdict.complete is complete and (needs_reply is None or not complete or verdict.needs_reply is needs_reply)
        right += int(ok)
    assert right / len(CASES) >= 0.85, f"{right}/{len(CASES)} judged as expected"
