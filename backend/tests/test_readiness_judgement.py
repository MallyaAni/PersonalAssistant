"""The burst judgement: what is asked, and how failure reads."""

import json

import pytest

from backend.services.readiness import FAIL_OPEN, Readiness, judge_readiness, parse_readiness


class _Llm:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def chat(self, messages, max_tokens, schema, temperature):
        self.calls.append((messages, max_tokens, schema, temperature))
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"content": json.dumps(self.answer)}


@pytest.mark.asyncio
async def test_the_fragments_are_numbered_under_the_previous_reply():
    llm = _Llm(
        {
            "complete": True,
            "needs_reply": True,
            "accepts_offer": False,
            "reason": "a question",
        }
    )
    verdict = await judge_readiness(llm, "Thai or pizza on Friday?", ["ok so", "thai then?"])
    assert verdict == Readiness(True, True, "a question")
    ((messages, _tokens, schema, temperature),) = llm.calls
    assert temperature == 0.0
    assert schema["required"] == [
        "complete",
        "needs_reply",
        "accepts_offer",
        "reason",
    ]
    assert messages[0]["role"] == "system" and "complete" in messages[0]["content"]
    user = messages[1]["content"]
    assert "Setting: a one-to-one text conversation." in user
    assert "The assistant's previous message: Thai or pizza on Friday?" in user
    assert "1. ok so\n2. thai then?" in user


@pytest.mark.asyncio
async def test_a_group_setting_is_named():
    llm = _Llm(
        {
            "complete": True,
            "needs_reply": False,
            "accepts_offer": False,
            "reason": "chatter",
        }
    )
    await judge_readiness(llm, "", ["sounds good"], in_group=True)
    assert "Setting: a group chat with several people." in llm.calls[0][0][1]["content"]
    assert "previous message: (none)" in llm.calls[0][0][1]["content"]


@pytest.mark.asyncio
async def test_nothing_said_needs_no_model_and_no_reply():
    llm = _Llm(
        {
            "complete": True,
            "needs_reply": True,
            "accepts_offer": False,
            "reason": "",
        }
    )
    verdict = await judge_readiness(llm, "x", ["", "   "])
    assert verdict.needs_reply is False and verdict.complete is True
    assert llm.calls == []


@pytest.mark.asyncio
async def test_a_failed_call_fails_open_to_answering():
    verdict = await judge_readiness(_Llm(RuntimeError("down")), "x", ["hi"])
    assert verdict == FAIL_OPEN
    assert verdict.complete and verdict.needs_reply


def test_unreadable_answers_fail_open():
    assert parse_readiness("not json") == FAIL_OPEN
    assert parse_readiness({"content": "{}"}) == FAIL_OPEN
    assert parse_readiness(None) == FAIL_OPEN
    assert parse_readiness(
        {
            "content": json.dumps(
                {
                    "complete": False,
                    "needs_reply": True,
                    "accepts_offer": False,
                    "reason": "x" * 300,
                }
            )
        }
    ) == Readiness(False, True, "x" * 160)


# A tapback is complete whatever the model says about it: one reaction on
# one bubble, nothing more coming. The model still decides whether it
# accepts an offer.
@pytest.mark.asyncio
async def test_a_tapback_is_complete_even_when_the_model_calls_it_ambiguous():
    import json

    from backend.services.readiness import judge_readiness

    class Ambiguous:
        def chat(self, messages, max_tokens=256, schema=None, temperature=None):
            return {"content": json.dumps({"complete": False, "needs_reply": False, "accepts_offer": False, "reason": "ambiguous"})}

    verdict = await judge_readiness(Ambiguous(), "Which sounds better to you, Thai or pizza?", ["❤️"], addressed_by="tapback")
    assert verdict.complete is True and verdict.accepts_offer is False

    class Accepts:
        def chat(self, messages, max_tokens=256, schema=None, temperature=None):
            return {"content": json.dumps({"complete": False, "needs_reply": False, "accepts_offer": True, "reason": "yes"})}

    verdict = await judge_readiness(Accepts(), "Want me to find a few good Thai places?", ["👍"], addressed_by="tapback")
    assert verdict.complete is True and verdict.accepts_offer is True and verdict.needs_reply is True
