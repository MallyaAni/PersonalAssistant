"""A place from a previous answer cannot redirect a follow-up's search.

Compose is handed the conversation, and a previous answer full of one town can
put that town into a follow-up's query even when the person's own place is on
record: "try again" after a listing of Colonial Heights events searched
"Colonial Heights ... Courthouse Virginia" for a person in Courthouse
(2026-09-04), and a query with two towns comes back from the wrong one. The
model names the foreign places; these tests prove the code drops them and
re-holds the person's own. The functional suite measures the model judgement
itself; this measures the wiring around it.
"""
import pytest

from backend.services.conversation_service import _drop_foreign_places
from backend.services.search_planner import SearchPlanner, strip_phrases


class StubLLM:
    """Answer a schema'd place judgement with a fixed payload, or fail."""

    def __init__(self, places=(), fail=False) -> None:
        self.places = places
        self.fail = fail
        self.calls: list[dict] = []

    def chat(self, messages, max_tokens=200, response_schema=None, temperature=None):
        self.calls.append(
            {
                "prompt": messages[0]["content"],
                "user": messages[1]["content"],
                "schema": response_schema,
                "temperature": temperature,
            }
        )
        if self.fail:
            raise RuntimeError("inference runtime unreachable")
        return {
            "content": __import__("json").dumps(
                {"place_bound": True, "places": list(self.places)}
            )
        }


class StubPlanner:
    """The planner as the search path sees it: one place judgement - whether
    the question is about here, and which names in the query are elsewhere."""

    def __init__(self, foreign=("Colonial Heights",), fail=False, bound=True) -> None:
        self.foreign = foreign
        self.fail = fail
        self.bound = bound

    def place_judgement(self, question, query, place):
        from backend.services.search_planner import PlaceJudgement

        if self.fail:
            raise RuntimeError("inference runtime unreachable")
        return PlaceJudgement(self.bound, self.foreign)


def test_strip_phrases_removes_the_named_phrases_and_tidies_the_gap():
    out = strip_phrases(
        "fun things to do Colonial Heights this weekend Courthouse Virginia",
        ("Colonial Heights",),
    )
    assert out == "fun things to do this weekend Courthouse Virginia"


def test_strip_phrases_with_nothing_returns_the_query():
    query = "events in Arlington this week"
    assert strip_phrases(query, ()) == query


def test_foreign_places_keeps_the_persons_own_words():
    planner = SearchPlanner(
        StubLLM(["Colonial Heights", "Courthouse", "Virginia", "Washington DC"])
    )
    assert planner.foreign_places("a query", "Courthouse, Virginia") == (
        "Colonial Heights",
        "Washington DC",
    )


def test_foreign_places_deduplicates_and_bounds():
    planner = SearchPlanner(
        StubLLM(
            ["DC", "DC", "New York", "Boston", "Chicago", "Miami", "Denver"]
        )
    )
    foreign = planner.foreign_places("a query", "Courthouse, Virginia")
    assert foreign == ("DC", "New York", "Boston", "Chicago", "Miami", "Denver")


def test_foreign_places_fails_quietly():
    planner = SearchPlanner(StubLLM(fail=True))
    assert planner.foreign_places("a query", "Courthouse, Virginia") == ()


@pytest.mark.asyncio
async def test_the_search_path_drops_a_foreign_place_and_holds_the_own():
    query = "fun things to do Colonial Heights this week Courthouse Virginia"
    out = await _drop_foreign_places(
        StubPlanner(),
        query,
        "what's are some fun things to do in the area this week?",
        "Courthouse, Virginia",
    )
    assert "colonial heights" not in out.casefold()
    assert "courthouse" in out.casefold()


@pytest.mark.asyncio
async def test_a_non_place_bound_question_is_left_alone():
    # The judgement, not a word list, says the question is not about here.
    query = "how much does a PS5 cost now"
    out = await _drop_foreign_places(
        StubPlanner(bound=False), query, "how much does a PS5 cost now", "Courthouse, Virginia"
    )
    assert out == query


@pytest.mark.asyncio
async def test_no_known_place_means_no_judgement():
    query = "fun things to do Colonial Heights this week"
    out = await _drop_foreign_places(StubPlanner(), query, "what's on in the area?", "")
    assert out == query


@pytest.mark.asyncio
async def test_a_failed_place_judgement_leaves_the_query_as_composed():
    query = "fun things to do Colonial Heights this week"
    out = await _drop_foreign_places(
        StubPlanner(fail=True),
        query,
        "what's on in the area this week?",
        "Courthouse, Virginia",
    )
    assert out == query
