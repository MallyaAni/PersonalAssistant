"""A hard constraint removes the result that violates it, and two people with
different constraints get different appropriate answers to the same question
while a factual question is answered the same for both.

The ranker is handed the person's constraints beside the results. This sends
the real results shape to the real ranking model: for someone allergic to
shellfish the oyster bar is named under violates and the others are not; for
someone with no constraint nothing is; and for a factual question with the
same two profiles, the order is identical, because a constraint decides what
is an answer for them, not what is true. The classifier that files a
constraint at capture is exercised beside it.

pinned prompt: search/rank (the constraints paragraph), and
semantic_fact_is_constraint in backend/memory/proposal_agent.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.dependencies import get_llm_client, get_routing_llm_client
from backend.core.result_ranking import judge_results
from backend.memory.proposal_agent import MemoryProposalAgent

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_DINNER = [
    {
        "title": "Island Creek Oyster Bar - Kenmore Square",
        "url": "https://islandcreekoysterbar.example/",
        "content": "Raw bar with a dozen oyster varieties, lobster rolls, clam chowder and a whole fried fish. Open till 11.",
    },
    {
        "title": "Yume Wo Katare - Davis Square",
        "url": "https://yumewokatare.example/",
        "content": "Jiro-style pork ramen, one bowl, expect a line. Cash only. Somerville, MA.",
    },
    {
        "title": "Life Alive Organic Cafe - Central Square",
        "url": "https://lifealive.example/",
        "content": "Vegetarian and vegan bowls, wraps and smoothies. Cambridge, MA.",
    },
    {
        "title": "Sarma - Somerville",
        "url": "https://sarma.example/",
        "content": "Eastern Mediterranean small plates: lamb, halloumi, fried chicken, vegetable mezze. Somerville, MA.",
    },
]
_DINNER_QUESTION = "where should I have dinner near Somerville tonight?"

_FACT = [
    {"title": "Somerville, Massachusetts - Wikipedia", "url": "https://en.wikipedia.example/Somerville", "content": "Somerville was first settled in 1630 as part of Charlestown and incorporated as a town in 1842."},
    {"title": "History of Somerville | City of Somerville", "url": "https://somervillema.example/history", "content": "Somerville separated from Charlestown and was incorporated in 1842; it became a city in 1872."},
    {"title": "Best brunch in Somerville 2026", "url": "https://eater.example/somerville-brunch", "content": "Our picks for weekend brunch across Somerville."},
]
_FACT_QUESTION = "when was Somerville incorporated as a town?"
_NOW = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)


async def _verdicts(constraints: tuple[str, ...], results, question):
    llm = get_routing_llm_client()
    ranking = await judge_results(llm, question, "Somerville, MA", [dict(r) for r in results], now=_NOW, constraints=constraints)
    return ranking


async def test_the_oyster_bar_violates_a_shellfish_allergy_and_nothing_else_does():
    hits = 0
    seen = []
    for _ in range(3):
        ranking = await _verdicts(("allergic to shellfish",), _DINNER, _DINNER_QUESTION)
        seen.append(ranking.violates)
        if ranking.violates == (1,):
            hits += 1
    assert hits >= 2, seen


async def test_with_no_constraint_nothing_is_a_violation():
    misses = 0
    seen = []
    for _ in range(3):
        ranking = await _verdicts((), _DINNER, _DINNER_QUESTION)
        seen.append(ranking.violates)
        if ranking.violates:
            misses += 1
    assert misses <= 1, seen


async def test_a_vegetarian_and_an_unconstrained_person_get_different_dinners_but_the_same_history():
    vegetarian = await _verdicts(("vegetarian - eats no meat or fish",), _DINNER, _DINNER_QUESTION)
    anyone = await _verdicts((), _DINNER, _DINNER_QUESTION)
    # The constraint removes what it must and keeps the vegetarian cafe.
    assert 3 not in vegetarian.violates, vegetarian
    assert 1 in vegetarian.violates and 2 in vegetarian.violates, vegetarian
    assert anyone.violates == (), anyone
    # A factual question is not personal: same verdicts, nothing violated.
    fact_vegetarian = await _verdicts(("vegetarian - eats no meat or fish",), _FACT, _FACT_QUESTION)
    fact_anyone = await _verdicts((), _FACT, _FACT_QUESTION)
    assert fact_vegetarian.violates == () and fact_anyone.violates == (), (fact_vegetarian, fact_anyone)
    assert fact_vegetarian.scores is not None and fact_anyone.scores is not None
    top_vegetarian = max(range(3), key=lambda i: fact_vegetarian.scores[i])
    top_anyone = max(range(3), key=lambda i: fact_anyone.scores[i])
    assert top_vegetarian == top_anyone and top_anyone in (0, 1), (fact_vegetarian, fact_anyone)


# The label, judged on what the classifier captured: every fact it wrote for
# the sentence carries the right flag, and it captured at least once. Whether
# it captures at all is the memory-capture discipline suite's property, not
# this one's - "I use a wheelchair, so I need step-free access" was captured
# in one run of three on 2026-09-05, and labelled a constraint that once.
@pytest.mark.parametrize(
    ("said", "constraint"),
    [
        ("I'm allergic to shellfish, so never suggest oyster places.", True),
        ("I'm vegetarian - I don't eat meat or fish.", True),
        ("I use a wheelchair, so I need step-free access.", True),
        ("I prefer quiet restaurants over loud ones.", False),
    ],
)
async def test_the_classifier_files_a_limit_as_a_constraint_and_a_taste_as_a_preference(llm, said, constraint):
    captured = []
    for _ in range(3):
        result = await MemoryProposalAgent(get_llm_client()).propose(said)
        captured.extend(p for p in result.proposals if p.get("kind") == "semantic_fact")
    assert captured, f"never captured as a fact in three runs: {said!r}"
    wrong = [
        fact for fact in captured
        if bool(fact.get("is_constraint")) is not constraint or not fact.get("is_preference")
    ]
    assert len(wrong) <= len(captured) // 3, captured
