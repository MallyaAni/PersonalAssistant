"""Web results are reranked against the question, and the providers' order
survives every failure."""

from __future__ import annotations

import pytest

from backend.services.conversation_service import _rerank_question, _rerank_web_results

_RESULTS = [
    {"title": "Ballhooter Festival 2026", "url": "https://www.bandsintown.com/c/arlington-va", "content": "Snowshoe Mountain, WV"},
    {"title": "Arlington Farmers Market", "url": "https://arlingtonva.us/market", "content": "Courthouse Plaza, Saturday 8 AM"},
    {"title": "Jazz on the lawn", "url": "https://arlingtonva.us/jazz", "content": "Lubber Run Amphitheater, Sunday 7 PM"},
]


@pytest.mark.asyncio
async def test_results_take_the_rerankers_order_and_carry_their_scores() -> None:
    async def scores(question, documents):
        assert "Arlington" in question
        return [0.1, 0.9, 0.8]

    ordered = await _rerank_web_results(scores, "events in Arlington this weekend", [dict(r) for r in _RESULTS], keep=8)
    assert [r["title"] for r in ordered] == ["Arlington Farmers Market", "Jazz on the lawn", "Ballhooter Festival 2026"]
    assert ordered[0]["rerank_score"] == 0.9


@pytest.mark.asyncio
async def test_only_the_top_are_kept() -> None:
    async def scores(question, documents):
        return [0.1, 0.9, 0.8]

    ordered = await _rerank_web_results(scores, "q", [dict(r) for r in _RESULTS], keep=2)
    assert [r["title"] for r in ordered] == ["Arlington Farmers Market", "Jazz on the lawn"]


@pytest.mark.asyncio
async def test_a_failing_or_silent_reranker_keeps_the_providers_order() -> None:
    async def boom(question, documents):
        raise RuntimeError("reranker down")

    async def silent(question, documents):
        return None

    async def short(question, documents):
        return [0.5]

    for call in (boom, silent, short):
        ordered = await _rerank_web_results(call, "q", [dict(r) for r in _RESULTS], keep=8)
        assert [r["title"] for r in ordered] == [r["title"] for r in _RESULTS]
        assert "rerank_score" not in ordered[0]


@pytest.mark.asyncio
async def test_one_result_is_not_reranked() -> None:
    async def never(question, documents):
        raise AssertionError("should not be called")

    assert await _rerank_web_results(never, "q", [dict(_RESULTS[0])], keep=8) == [_RESULTS[0]]


def test_the_place_is_a_hint_in_the_question_not_a_filter() -> None:
    assert _rerank_question("what's on this weekend?", "Arlington, Virginia") == "what's on this weekend? (asked from Arlington, Virginia)"
    assert _rerank_question("what's on this weekend?", "") == "what's on this weekend?"
