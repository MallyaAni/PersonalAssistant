from dataclasses import dataclass

import pytest

from backend.search.routing_cases import ROUTING_CASES, RoutingCase
from backend.services.search_routing_evaluator import SearchRoutingEvaluator


@dataclass(frozen=True, slots=True)
class _Verdict:
    """The one field the evaluator reads, so it needs no router type."""

    should_search: bool


class FixedRouter:
    """Decide by a lookup table so scoring can be asserted exactly."""

    def __init__(self, decisions: dict[str, bool]) -> None:
        self.decisions = decisions

    async def decide(self, query: str) -> _Verdict:
        return _Verdict(should_search=self.decisions.get(query, False))


CASES = (
    RoutingCase("volatile hit", True, "implicit_volatile"),
    RoutingCase("volatile miss", True, "implicit_volatile"),
    RoutingCase("stable kept", False, "skill"),
    RoutingCase("stable over-searched", False, "skill"),
)


@pytest.mark.asyncio
async def test_scoring_separates_misses_from_unnecessary_searches():
    router = FixedRouter(
        {
            "volatile hit": True,
            "volatile miss": False,
            "stable kept": False,
            "stable over-searched": True,
        }
    )

    report = await SearchRoutingEvaluator(router, CASES).evaluate()  # type: ignore[arg-type]

    assert report.overall.recall == 0.5
    assert report.overall.specificity == 0.5
    # A regression must name the query that broke, not only move a percentage.
    assert report.misses == ["volatile miss"]
    assert report.false_alarms == ["stable over-searched"]


@pytest.mark.asyncio
async def test_categories_localise_a_regression():
    router = FixedRouter({"volatile hit": True, "stable kept": False})

    report = await SearchRoutingEvaluator(router, CASES).evaluate()  # type: ignore[arg-type]
    data = report.to_dict()

    # Recall collapsed in one shape of question while the other held.
    assert data["by_category"]["implicit_volatile"]["recall"] == 0.5
    assert data["by_category"]["skill"]["specificity"] == 1.0


@pytest.mark.asyncio
async def test_a_perfect_router_scores_perfectly():
    router = FixedRouter({case.query: case.needs_search for case in CASES})

    report = await SearchRoutingEvaluator(router, CASES).evaluate()  # type: ignore[arg-type]

    assert report.overall.recall == 1.0
    assert report.overall.specificity == 1.0
    assert report.misses == []


def test_the_labelled_set_is_balanced_enough_to_measure_both_directions():
    needs = [c for c in ROUTING_CASES if c.needs_search]
    stable = [c for c in ROUTING_CASES if not c.needs_search]

    # Specificity is meaningless without stable cases, and recall without
    # volatile ones, so neither side may quietly disappear.
    assert len(needs) >= 15
    assert len(stable) >= 10
    # Volatile questions with no temporal marker are the hard case that
    # patterns alone cannot catch; they must stay well represented.
    implicit = [c for c in needs if c.category == "implicit_volatile"]
    assert len(implicit) >= 10
