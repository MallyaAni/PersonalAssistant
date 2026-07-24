"""Measure whether web-search routing sends the right turns to the internet."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from backend.search.cascade import CascadingSearchRouter
from backend.search.routing_cases import ROUTING_CASES, RoutingCase


@dataclass(frozen=True, slots=True)
class RoutingOutcome:
    """Counts for one group of labelled queries."""

    routed_when_needed: int = 0
    missed: int = 0
    skipped_when_stable: int = 0
    searched_unnecessarily: int = 0

    # Share of changing answers that reached the internet. This is the metric
    # that matters most: a miss is a confident answer from stale training data,
    # while an unnecessary search only costs a second.
    @property
    def recall(self) -> float:
        needed = self.routed_when_needed + self.missed
        return self.routed_when_needed / needed if needed else 1.0

    # Share of settled questions that were correctly answered locally.
    @property
    def specificity(self) -> float:
        stable = self.skipped_when_stable + self.searched_unnecessarily
        return self.skipped_when_stable / stable if stable else 1.0


@dataclass
class RoutingReport:
    """Aggregate and per-category routing quality over the labelled set."""

    overall: RoutingOutcome
    by_category: dict[str, RoutingOutcome]
    misses: list[str] = field(default_factory=list)
    false_alarms: list[str] = field(default_factory=list)

    # Render the report as JSON-friendly data for a CLI or a build gate.
    def to_dict(self) -> dict[str, Any]:
        return {
            "recall": round(self.overall.recall, 4),
            "specificity": round(self.overall.specificity, 4),
            "cases": (
                self.overall.routed_when_needed
                + self.overall.missed
                + self.overall.skipped_when_stable
                + self.overall.searched_unnecessarily
            ),
            "by_category": {
                name: {
                    "recall": round(outcome.recall, 4),
                    "specificity": round(outcome.specificity, 4),
                }
                for name, outcome in sorted(self.by_category.items())
            },
            # Named so a regression points at the query that broke, not just a
            # percentage that moved.
            "missed": self.misses,
            "searched_unnecessarily": self.false_alarms,
        }


class SearchRoutingEvaluator:
    """Run the routing cascade over labelled queries and score its decisions."""

    # Evaluate whichever router the caller assembled, so pattern-only and
    # pattern-plus-classifier configurations are measured the same way.
    def __init__(
        self,
        router: CascadingSearchRouter,
        cases: tuple[RoutingCase, ...] = ROUTING_CASES,
    ) -> None:
        self.router = router
        self.cases = cases

    # Score every labelled query and report aggregate and per-category quality.
    async def evaluate(self) -> RoutingReport:
        tallies: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "routed_when_needed": 0,
                "missed": 0,
                "skipped_when_stable": 0,
                "searched_unnecessarily": 0,
            }
        )
        misses: list[str] = []
        false_alarms: list[str] = []

        for case in self.cases:
            decided = (await self.router.decide(case.query)).should_search
            if case.needs_search and decided:
                key = "routed_when_needed"
            elif case.needs_search:
                key = "missed"
                misses.append(case.query)
            elif decided:
                key = "searched_unnecessarily"
                false_alarms.append(case.query)
            else:
                key = "skipped_when_stable"
            tallies[case.category][key] += 1

        by_category = {
            name: RoutingOutcome(**counts) for name, counts in tallies.items()
        }
        overall = RoutingOutcome(
            routed_when_needed=sum(o.routed_when_needed for o in by_category.values()),
            missed=sum(o.missed for o in by_category.values()),
            skipped_when_stable=sum(
                o.skipped_when_stable for o in by_category.values()
            ),
            searched_unnecessarily=sum(
                o.searched_unnecessarily for o in by_category.values()
            ),
        )
        return RoutingReport(
            overall=overall,
            by_category=by_category,
            misses=misses,
            false_alarms=false_alarms,
        )
