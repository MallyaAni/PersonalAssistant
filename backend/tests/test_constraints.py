"""A hard constraint is a limit, not a taste: filed as its own purpose,
carried by the person context without ever leaving, handed to the ranker as
something a result must not cross, and the result that crosses it dropped.

Pinned without a model: the purpose a constraint proposal is stored under,
the person context's view of it, the ranker's parsing of `violates`, and the
filter that removes violators from an ordered list by identity.
"""

from __future__ import annotations

import json

import pytest

from backend.core.result_ranking import Ranking, _parse_violates, judge_results
from backend.memory.person_context import Known, PersonContext, PersonSources, build_person_context
from backend.memory.purposes import CONSTRAINT_PURPOSE, PREFERENCE_PURPOSE, PREFERENCE_PURPOSES
from backend.services.conversation_service import _without_violators

pytestmark = pytest.mark.asyncio


class _Memory:
    def __init__(self, records):
        self.records = records

    async def get_preferences(self, user_id, limit=5):
        return self.records[:limit]


class _LLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple] = []

    def chat(self, messages, max_tokens=1024, response_schema=None, temperature=None):
        self.calls.append((messages, max_tokens, response_schema, temperature))
        return {"content": self.content}


_RESULTS = [
    {"title": "Island Creek Oyster Bar", "url": "https://a.example", "content": "Raw bar, oysters, lobster rolls."},
    {"title": "Yume Wo Katare", "url": "https://b.example", "content": "Pork ramen, Davis Square."},
    {"title": "Life Alive", "url": "https://c.example", "content": "Vegetarian bowls and smoothies."},
]


def test_a_constraint_is_a_preference_purpose_of_its_own():
    assert CONSTRAINT_PURPOSE in PREFERENCE_PURPOSES and PREFERENCE_PURPOSE in PREFERENCE_PURPOSES
    assert CONSTRAINT_PURPOSE != PREFERENCE_PURPOSE


async def test_the_person_context_tells_a_limit_from_a_taste_and_neither_leaves():
    person = await build_person_context(
        "u",
        PersonSources(memory=_Memory([
            {"id": "m1", "content": "allergic to shellfish", "purpose": CONSTRAINT_PURPOSE},
            {"id": "m2", "content": "likes spicy food", "purpose": PREFERENCE_PURPOSE},
        ])),
    )
    assert [item.kind for item in person.preferences] == ["constraint", "preference"]
    assert person.constraint_lines() == ("allergic to shellfish",)
    assert person.search_terms() == ()
    assert "must: allergic to shellfish" in person.ranking_lines()
    assert "likes spicy food" in person.ranking_lines()
    assert person.as_trace()["constraints"] == 1
    # The view with a disposition keeps the limit.
    assert person.with_dispositions(("likes new things",)).constraints == person.constraints


def test_violates_is_read_only_as_in_range_numbers_each_once():
    assert _parse_violates({"content": json.dumps({"violates": [1, 1, 3, 9, "2"]})}, 3) == (1, 3)
    assert _parse_violates({"content": "not json"}, 3) == ()
    assert _parse_violates({"content": json.dumps({"violates": "1"})}, 3) == ()


async def test_the_ranker_is_handed_the_constraints_and_its_verdict_rides_with_the_order():
    llm = _LLM(json.dumps({"order": [2, 3, 1], "events": False, "travel": False, "on_subject": True, "violates": [1]}))
    ranking = await judge_results(llm, "dinner near Davis Square", "Somerville", _RESULTS, constraints=("allergic to shellfish",))
    assert isinstance(ranking, Ranking)
    assert ranking.violates == (1,)
    assert ranking.scores == [1.0, 3.0, 2.0]
    messages, _, schema, _ = llm.calls[0]
    assert "Hard constraints" in messages[1]["content"] and "allergic to shellfish" in messages[1]["content"]
    assert "violates" in schema["required"]


async def test_without_constraints_a_named_violation_is_ignored():
    llm = _LLM(json.dumps({"order": [1, 2, 3], "events": False, "travel": False, "on_subject": True, "violates": [1]}))
    ranking = await judge_results(llm, "dinner", "", _RESULTS)
    assert ranking.violates == ()
    assert "Hard constraints" not in llm.calls[0][0][1]["content"]


def test_violators_are_removed_from_the_ordered_list_by_identity_not_position():
    candidates = [dict(item) for item in _RESULTS]
    ordered = [candidates[1], candidates[2], candidates[0]]
    kept, dropped = _without_violators(ordered, candidates, [1])
    assert dropped == 1
    assert [item["title"] for item in kept] == ["Yume Wo Katare", "Life Alive"]
    assert _without_violators(ordered, candidates, []) == (ordered, 0)
    assert _without_violators(ordered, candidates, [9]) == (ordered, 0)


def test_a_known_without_a_kind_of_constraint_is_not_one():
    person = PersonContext(user_id="u", preferences=(Known("likes jazz", "preference"),))
    assert person.constraints == () and person.constraint_lines() == ()


def test_the_classifier_schema_requires_the_fact_flags():
    from backend.memory.proposal_agent import FACT_FLAGS, GroupMemoryProposalDecision, MemoryProposalDecision, decision_schema

    for model in (MemoryProposalDecision, GroupMemoryProposalDecision):
        schema = decision_schema(model)
        assert set(FACT_FLAGS) <= set(schema["required"])
        assert "semantic_fact_is_constraint" in schema["properties"]


def test_the_backfill_files_a_constraint_above_a_preference_above_a_fact():
    from backend.cli.classify_preferences import PLAIN_FACT_PURPOSE, target_purpose

    assert target_purpose(True, True) == CONSTRAINT_PURPOSE
    assert target_purpose(False, True) == CONSTRAINT_PURPOSE
    assert target_purpose(True, False) == PREFERENCE_PURPOSE
    assert target_purpose(False, False) == PLAIN_FACT_PURPOSE
