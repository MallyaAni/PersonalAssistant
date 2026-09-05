"""One view of the person, with provenance, and an egress rule it enforces.

The search path assembled three views of the person in three places. This
is the one they read now, and the property that matters most is the one no
consumer can get wrong by accident: a preference - a fact about the person -
never comes back from `search_terms()`, whatever a caller asks for.
"""

from types import SimpleNamespace

import pytest

from backend.memory.person_context import (
    COMPOSER_INTERESTS,
    Known,
    PersonContext,
    PersonSources,
    build_person_context,
)

pytestmark = pytest.mark.asyncio


class _Profile:
    def __init__(self, labels):
        self.labels = labels

    async def get_profile(self, user_id):
        return SimpleNamespace(interests=[SimpleNamespace(label=label) for label in self.labels])


class _Memory:
    def __init__(self, records):
        self.records = records

    async def get_preferences(self, user_id, limit=5):
        return self.records[:limit]


class _Broken:
    async def get_profile(self, user_id):
        raise RuntimeError("store down")

    async def get_preferences(self, user_id, limit=5):
        raise RuntimeError("store down")


async def test_interests_may_leave_and_preferences_may_not():
    person = await build_person_context(
        "u",
        PersonSources(
            discovery_profile=_Profile(["salsa", "board games"]),
            memory=_Memory([{"id": "m1", "content": "allergic to shellfish"}]),
        ),
    )
    assert person.search_terms() == ("salsa", "board games")
    assert all(item.may_leave for item in person.interests)
    assert all(not item.may_leave for item in person.preferences)
    assert person.preferences[0].memory_id == "m1"
    assert person.preferences[0].store == "memory_facts"
    lines = person.ranking_lines("something to do tonight")
    assert "allergic to shellfish" in lines
    assert any(line.startswith("interests:") for line in lines)


async def test_a_preference_never_comes_back_as_a_search_term_even_if_asked_wide():
    person = PersonContext(
        "u",
        interests=(),
        preferences=(Known("has a wheelchair", "preference", may_leave=False),),
    )
    assert person.search_terms(limit=100) == ()
    assert "has a wheelchair" in person.ranking_lines()


async def test_a_broken_store_costs_its_part_not_the_turn():
    person = await build_person_context("u", PersonSources(discovery_profile=_Broken(), memory=_Broken()))
    assert person.interests == ()
    assert person.preferences == ()
    assert person.ranking_lines() == ()


async def test_ranking_lines_put_the_question_bearing_interests_first_and_stay_bounded():
    labels = [f"interest {index}" for index in range(30)] + ["salsa dancing"]
    person = await build_person_context("u", PersonSources(discovery_profile=_Profile(labels)))
    line = next(line for line in person.ranking_lines("where to go salsa dancing") if line.startswith("interests:"))
    listed = line.removeprefix("interests: ").split(", ")
    assert listed[0] == "salsa dancing"
    assert len(listed) == COMPOSER_INTERESTS
    assert len(person.ranking_lines()) <= 8


async def test_dispositions_ride_with_the_same_object():
    person = PersonContext("u", interests=(Known("hiking", "interest", may_leave=True),))
    steered = person.with_dispositions(("likes new things",))
    assert steered.dispositions == ("likes new things",)
    assert steered.search_terms() == ("hiking",)
    assert steered.as_trace()["dispositions"] == ["likes new things"]
    assert steered.as_trace()["may_leave"] == ["hiking"]


async def test_a_preference_noted_as_an_iso_string_keeps_its_provenance():
    person = await build_person_context(
        "u",
        PersonSources(memory=_Memory([{"id": "m1", "content": "vegetarian", "created_at": "2026-09-01T10:00:00+00:00"}])),
    )
    assert person.preferences[0].noted_at is not None
    assert person.preferences[0].noted_at.year == 2026
