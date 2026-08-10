"""Completing a place name with the local model.

The properties that matter are not "does it know geography" — that was measured
against the live model and recorded in the module — but the ones that keep a
wrong or missing answer harmless: a suggestion is never required, a duplicate is
never offered as a choice, and nothing here can fail a form.
"""

import json
import os
from typing import Any

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.scout.place_suggest import (
    MAX_SUGGESTIONS,
    PlaceSuggester,
    PlaceSuggestion,
)


class _StubWriter:
    def __init__(self, reply: str = "{}", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls = 0
        self.prompts: list[str] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        self.prompts.append(messages[-1].get("content", ""))
        if self.fail:
            raise RuntimeError("inference runtime unavailable")
        return {"content": self.reply}


def _reply(*places: tuple[str, str]) -> str:
    return json.dumps({"places": [{"town": t, "region": r} for t, r in places]})


@pytest.mark.asyncio
async def test_it_offers_each_place_that_a_name_could_mean():
    writer = _StubWriter(_reply(("Arlington", "Texas"), ("Arlington", "Virginia")))

    suggestions = await PlaceSuggester(writer).suggest("Arlingt")

    # Telling namesakes apart is the whole reason the list exists.
    assert suggestions == (
        PlaceSuggestion(town="Arlington", region="Texas"),
        PlaceSuggestion(town="Arlington", region="Virginia"),
    )


@pytest.mark.asyncio
async def test_the_same_place_twice_is_offered_once():
    writer = _StubWriter(_reply(("Arlington", "Virginia"), ("arlington", "virginia")))

    suggestions = await PlaceSuggester(writer).suggest("Arlingt")

    # Identity is the pair and is case-folded, so a repeat is dropped while two
    # genuinely different Arlingtons both survive.
    assert suggestions == (PlaceSuggestion(town="Arlington", region="Virginia"),)


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", ["", " ", "A", "  x "])
async def test_too_little_typed_asks_the_model_nothing(typed: str):
    writer = _StubWriter(_reply(("Anywhere", "Somewhere")))

    assert await PlaceSuggester(writer).suggest(typed) == ()
    # Below two characters every name in the world matches, so the call is not
    # worth making.
    assert writer.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suggester",
    [
        PlaceSuggester(None),
        PlaceSuggester(_StubWriter(fail=True)),
        PlaceSuggester(_StubWriter("not json")),
        PlaceSuggester(_StubWriter('{"places": [{"town": "Nowhere"}]}')),
    ],
)
async def test_anything_unusable_is_simply_no_suggestions(suggester: PlaceSuggester):
    # Never an error: the fields are free text and the form has to keep working
    # exactly as it does without a model.
    assert await suggester.suggest("Arlingt") == ()


@pytest.mark.asyncio
async def test_a_place_missing_either_half_is_not_offered():
    writer = _StubWriter(
        _reply(("Arlington", ""), ("", "Virginia"), ("Boston", "Massachusetts"))
    )

    suggestions = await PlaceSuggester(writer).suggest("Arlingt")

    # A suggestion exists to supply both halves at once; one half is no use.
    assert suggestions == (PlaceSuggestion(town="Boston", region="Massachusetts"),)


@pytest.mark.asyncio
async def test_the_offered_list_stays_bounded():
    writer = _StubWriter(
        _reply(*[(f"Springfield{index}", "Illinois") for index in range(12)])
    )

    suggestions = await PlaceSuggester(writer).suggest("Springfie")

    assert len(suggestions) <= MAX_SUGGESTIONS


@pytest.mark.asyncio
async def test_the_query_is_bounded_before_it_reaches_a_prompt():
    writer = _StubWriter(_reply(("Somewhere", "Someplace")))

    await PlaceSuggester(writer).suggest("A" * 500)

    assert len(writer.prompts[0]) < 200
