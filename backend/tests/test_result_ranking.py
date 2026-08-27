"""The main model's order is applied only when it is a real permutation."""

from __future__ import annotations

import json

import pytest

from backend.core.result_ranking import _parse_order, order_by_usefulness

_RESULTS = [
    {"title": "Ballhooter Festival 2026", "url": "https://bandsintown.example/wv", "content": "Snowshoe, WV"},
    {"title": "Arlington Farmers Market", "url": "https://arlingtonva.example/market", "content": "Saturday 8 AM"},
    {"title": "Jazz on the Lawn", "url": "https://arlingtonva.example/jazz", "content": "Sunday 7 PM"},
]


class _LLM:
    def __init__(self, content: str, raises: bool = False) -> None:
        self.content, self.raises = content, raises
        self.calls: list[tuple] = []

    def chat(self, messages, max_tokens=1024, response_schema=None, temperature=None):
        self.calls.append((messages, max_tokens, response_schema, temperature))
        if self.raises:
            raise RuntimeError("model down")
        return {"content": self.content}


@pytest.mark.asyncio
async def test_the_order_becomes_scores_highest_first() -> None:
    llm = _LLM(json.dumps({"order": [2, 3, 1]}))
    scores = await order_by_usefulness(llm, "events in Arlington this weekend", "Arlington, Virginia", _RESULTS)
    assert scores == [1.0, 3.0, 2.0]
    messages, max_tokens, schema, temperature = llm.calls[0]
    assert temperature == 0.0 and schema["required"] == ["order", "events", "travel", "on_subject"]
    assert "Asked from: Arlington, Virginia" in messages[1]["content"]
    assert "[1] Ballhooter Festival 2026" in messages[1]["content"]


@pytest.mark.asyncio
async def test_a_bad_order_or_a_failed_call_yields_nothing() -> None:
    assert await order_by_usefulness(_LLM(json.dumps({"order": [1, 1, 2]})), "q", "", _RESULTS) is None
    assert await order_by_usefulness(_LLM(json.dumps({"order": [1, 2]})), "q", "", _RESULTS) is None
    assert await order_by_usefulness(_LLM("not json"), "q", "", _RESULTS) is None
    assert await order_by_usefulness(_LLM("{}", raises=True), "q", "", _RESULTS) is None
    assert await order_by_usefulness(_LLM(json.dumps({"order": [1]})), "q", "", _RESULTS[:1]) is None


def test_parse_order_accepts_only_a_permutation() -> None:
    assert _parse_order({"content": '{"order": [3, 1, 2]}'}, 3) == [3, 1, 2]
    assert _parse_order({"content": '{"order": [3, 1]}'}, 3) is None
    assert _parse_order({"content": '{"order": ["a"]}'}, 1) is None
    assert _parse_order({"content": "nope"}, 2) is None


@pytest.mark.asyncio
async def test_what_is_known_is_handed_over_as_a_tie_breaker_only() -> None:
    llm = _LLM(json.dumps({"order": [2, 3, 1]}))
    await order_by_usefulness(llm, "q", "Canggu", _RESULTS, known=("interests: salsa dance, bachata dance", "lives in Canggu"))
    content = llm.calls[0][0][1]["content"]
    assert "use only to break ties" in content and "- interests: salsa dance, bachata dance" in content
    llm = _LLM(json.dumps({"order": [1, 2, 3]}))
    await order_by_usefulness(llm, "q", "", _RESULTS, known=())
    assert "What is known about the person" not in llm.calls[0][0][1]["content"]


def test_memory_items_become_lines_whatever_field_holds_them() -> None:
    from backend.services.conversation_service import _memory_text

    assert _memory_text({"content": "likes salsa"}) == "likes salsa"
    assert _memory_text({"value": "Canggu, Bali"}) == "Canggu, Bali"
    assert _memory_text("plain") == "plain"
    assert _memory_text({"id": 3}) == ""


@pytest.mark.asyncio
async def test_the_events_verdict_rides_with_the_order() -> None:
    from backend.core.result_ranking import judge_results

    ranking = await judge_results(_LLM(json.dumps({"order": [2, 3, 1], "events": True})), "q", "", _RESULTS)
    assert ranking.scores == [1.0, 3.0, 2.0] and ranking.events is True
    ranking = await judge_results(_LLM(json.dumps({"order": [1, 1, 2], "events": True})), "q", "", _RESULTS)
    assert ranking.scores is None and ranking.events is True, "a bad order still carries the verdict"
    ranking = await judge_results(_LLM(json.dumps({"order": [1, 2, 3]})), "q", "", _RESULTS)
    assert ranking.events is False


@pytest.mark.asyncio
async def test_the_travel_verdict_rides_with_the_order() -> None:
    from backend.core.result_ranking import judge_results

    ranking = await judge_results(_LLM(json.dumps({"order": [1, 2, 3], "events": False, "travel": True})), "q", "", _RESULTS)
    assert ranking.travel is True and ranking.events is False
    ranking = await judge_results(_LLM(json.dumps({"order": [1, 2, 3]})), "q", "", _RESULTS)
    assert ranking.travel is False
