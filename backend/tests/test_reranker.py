"""The reranker stage's contract: a second opinion that can never hurt.

The client and the ordering logic are pure enough to test without a model.
Whether the real reranker orders well is functional
(functional/test_reranker_behaviour.py); what these prove is the fail-soft
contract - reranking improves an ordering that already exists, so every
failure path must keep the cosine order rather than cost the turn.
"""

import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.services.conversation_service import _reranked


def _candidates():
    return [
        {"you_said": "first by cosine", "retrieval": {"cosine_distance": 0.1}},
        {"you_said": "second by cosine", "retrieval": {"cosine_distance": 0.2}},
        {"you_said": "third by cosine", "retrieval": {"cosine_distance": 0.3}},
    ]


@pytest.mark.asyncio
async def test_the_reranker_reorders_when_it_answers():
    async def scores(query, documents):
        # The cross-encoder disagrees with cosine: last is most relevant.
        return [0.1, 0.5, 0.9]

    ordered = await _reranked(scores, "q", _candidates())
    assert [item["you_said"] for item in ordered] == [
        "third by cosine",
        "second by cosine",
        "first by cosine",
    ]
    # The score rides along, so telemetry can compare the two orderings.
    assert ordered[0]["retrieval"]["rerank_score"] == 0.9


@pytest.mark.asyncio
async def test_no_answer_keeps_the_cosine_order():
    async def unavailable(query, documents):
        return None

    ordered = await _reranked(unavailable, "q", _candidates())
    assert [item["you_said"] for item in ordered] == [
        "first by cosine",
        "second by cosine",
        "third by cosine",
    ]


@pytest.mark.asyncio
async def test_a_raising_reranker_keeps_the_cosine_order():
    async def broken(query, documents):
        raise RuntimeError("hung endpoint")

    ordered = await _reranked(broken, "q", _candidates())
    assert [item["you_said"] for item in ordered] == [
        "first by cosine",
        "second by cosine",
        "third by cosine",
    ]


@pytest.mark.asyncio
async def test_a_single_candidate_is_never_sent_for_ranking():
    calls = []

    async def spy(query, documents):
        calls.append(documents)
        return [1.0]

    only = [{"you_said": "alone"}]
    assert await _reranked(spy, "q", only) == only
    assert calls == []


def test_an_empty_base_url_disables_the_stage():
    from backend.core.reranker import reranker_enabled

    # The default is off; a host that never configures a reranker keeps its
    # first-pass ordering everywhere, with no request ever attempted.
    assert reranker_enabled() is False or bool(
        os.environ.get("RERANKER_BASE_URL")
    )
