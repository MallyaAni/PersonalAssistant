"""The share screen: verdicts by meaning, cached, failing closed."""

import json

import pytest

from backend.memory import share_screen
from backend.memory.share_screen import forget_verdicts, parse_private, shareable


class _Llm:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def chat(self, messages, max_tokens, schema, temperature):
        self.calls.append((messages, schema, temperature))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"content": json.dumps(answer)}


@pytest.fixture(autouse=True)
def _fresh():
    forget_verdicts()
    yield
    forget_verdicts()


@pytest.mark.asyncio
async def test_private_statements_are_dropped_and_the_rest_kept_in_order():
    llm = _Llm([{"private": [2]}])
    kept = await shareable(llm, ("I drive a red Mini", "I'm seeing a therapist on Tuesdays", "My dog is Biscuit"))
    assert kept == ("I drive a red Mini", "My dog is Biscuit")
    ((messages, schema, temperature),) = llm.calls
    assert temperature == 0.0 and schema["required"] == ["private"]
    assert "1. I drive a red Mini\n2. I'm seeing a therapist on Tuesdays\n3. My dog is Biscuit" in messages[1]["content"]


@pytest.mark.asyncio
async def test_verdicts_are_remembered_so_a_room_asking_often_costs_one_judgement():
    llm = _Llm([{"private": []}, {"private": [1]}])
    assert await shareable(llm, ("I drive a red Mini",)) == ("I drive a red Mini",)
    assert await shareable(llm, ("I drive a red Mini",)) == ("I drive a red Mini",)
    assert len(llm.calls) == 1
    # A new statement is judged; the known one is not re-asked.
    assert await shareable(llm, ("I drive a red Mini", "I owe the bank 40k")) == ("I drive a red Mini",)
    assert len(llm.calls) == 2
    assert "I owe the bank 40k" in llm.calls[1][0][1]["content"] and "red Mini" not in llm.calls[1][0][1]["content"]


@pytest.mark.asyncio
async def test_a_failed_judgement_shares_nothing_unjudged():
    llm = _Llm([RuntimeError("down")])
    assert await shareable(llm, ("I drive a red Mini",)) == ()
    llm = _Llm([{"private": []}, RuntimeError("down")])
    assert await shareable(llm, ("I drive a red Mini",)) == ("I drive a red Mini",)
    # Known verdicts still apply when the model is away; the new one waits.
    assert await shareable(llm, ("I drive a red Mini", "new thing")) == ("I drive a red Mini",)


def test_unreadable_answers_are_no_verdict():
    assert parse_private("nope") is None
    assert parse_private({"content": json.dumps({"private": "x"})}) is None
    assert parse_private({"content": json.dumps({"private": [1, "2"]})}) == {1, 2}
    assert parse_private({"content": json.dumps({"private": []})}) == set()


@pytest.mark.asyncio
async def test_the_statement_count_is_bounded():
    llm = _Llm([{"private": []}])
    many = tuple(f"fact {i}" for i in range(20))
    kept = await shareable(llm, many)
    assert len(kept) == share_screen._MAX_STATEMENTS
