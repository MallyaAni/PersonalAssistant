"""Search as a second enumerator, without inventing dates.

Feeds cover institutions; a trail association's group hike exists only as a page
someone wrote. These tests cover the two properties that let search widen
coverage without damaging the rest of the loop: a date is read and never
inferred, and the metered cost of a sweep is bounded before it runs.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.digest import render_message
from backend.discovery.fetching import RequestBudget
from backend.discovery.novelty import ScoredCandidate
from backend.discovery.relevance import MAX_UNDATED, RankedCandidate, RelevanceRanker
from backend.core.dates import extract_explicit_date
from backend.discovery.sources.web import WebEventSource
from backend.search.types import SearchResult, SearchResults

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class _StubSearch:
    def __init__(
        self, results: list[tuple[str, str, str]], enabled: bool = True
    ) -> None:
        self.results = results
        self.enabled = enabled
        self.queries: list[str] = []

    def is_enabled(self) -> bool:
        return self.enabled

    async def search(self, query: str, max_results: int | None = None) -> SearchResults:
        self.queries.append(query)
        return SearchResults(
            query=query,
            provider="stub",
            results=tuple(
                SearchResult(title=title, url=url, content=content, score=1.0)
                for title, url, content in self.results
            ),
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Group hike on 2026-09-12, meet at the trailhead", (2026, 9, 12)),
        ("Trail cleanup September 12, 2026", (2026, 9, 12)),
        ("Ridge walk 12 September 2026", (2026, 9, 12)),
        ("Sunrise hike Sept 3rd, 2026", (2026, 9, 3)),
    ],
)
def test_an_explicit_date_is_read(text: str, expected: tuple[int, int, int]):
    parsed = extract_explicit_date(text, now=_NOW)
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day) == expected
    # Always zone-aware, or stage 5 could not emit a DTSTART.
    assert parsed.tzinfo is not None


@pytest.mark.parametrize(
    "text",
    [
        "Group hike this weekend",
        "Join us next Saturday for a walk",
        "Summer hiking series",
        "Hiking club meets weekly",
        "",
    ],
)
def test_a_relative_date_is_never_guessed(text: str):
    # Resolving "this weekend" needs a reference point the snippet does not
    # carry. Guessing produces an appointment at a confidently wrong time.
    assert extract_explicit_date(text, now=_NOW) is None


def test_a_past_date_is_not_an_upcoming_event():
    assert extract_explicit_date("Trail cleanup March 3, 2026", now=_NOW) is None


# Verify an explicitly old result is rejected instead of being relabeled undated.
@pytest.mark.asyncio
async def test_a_result_with_an_explicit_past_date_is_not_returned():
    search = _StubSearch(
        [
            (
                "Museum afterhours",
                "https://museum.example/afterhours",
                "This event took place on July 21, 2020.",
            ),
            (
                "Museum late night September 12, 2099",
                "https://museum.example/late-night",
                "An evening programme at the museum.",
            ),
        ]
    )
    source = WebEventSource("web-search", search, "Arlington", ("museums",))

    events = await source.fetch()

    assert [event.title for event in events] == ["Museum late night September 12, 2099"]


@pytest.mark.asyncio
async def test_results_become_events_and_undated_ones_stay_unschedulable():
    search = _StubSearch(
        [
            (
                "Ridge hike September 12, 2026",
                "https://trails.example/ridge",
                "Meet at 9",
            ),
            ("Weekly group walks", "https://trails.example/weekly", "Every weekend"),
        ]
    )
    source = WebEventSource("web-search", search, "Arlington", ("hiking",))

    events = await source.fetch()

    assert len(events) == 2
    dated = next(item for item in events if item.is_schedulable)
    undated = next(item for item in events if not item.is_schedulable)
    assert dated.starts_at is not None
    assert undated.starts_at is None
    # The URL is the only stable identity a search result has.
    assert undated.external_id == "https://trails.example/weekly"


@pytest.mark.asyncio
async def test_the_query_budget_bounds_the_metered_cost():
    search = _StubSearch([])
    budget = RequestBudget(limit=2)
    source = WebEventSource(
        "web-search",
        search,
        "Arlington",
        ("hiking", "pottery", "jazz", "cycling"),
        budget=budget,
        max_queries=4,
    )

    await source.fetch()

    # Four interests, but the budget allowed two queries.
    assert len(search.queries) == 2
    assert budget.remaining == 0


@pytest.mark.asyncio
async def test_a_disabled_provider_yields_nothing():
    source = WebEventSource(
        "web-search", _StubSearch([], enabled=False), "Arlington", ()
    )
    assert await source.fetch() == ()


@pytest.mark.asyncio
async def test_one_query_per_interest_rather_than_a_combined_one():
    search = _StubSearch([])
    source = WebEventSource(
        "web-search",
        search,
        "Arlington",
        ("hiking", "pottery"),
        include_general=False,
    )

    await source.fetch()

    assert len(search.queries) == 2
    assert any("hiking" in query for query in search.queries)
    assert any("pottery" in query for query in search.queries)


# One query names no interest, so a sweep can surface something the user never
# thought to ask for. Every other query is interest-shaped by construction,
# which means the loop could otherwise only return more of what it knew about.
@pytest.mark.asyncio
async def test_a_general_query_asks_what_is_on_without_naming_an_interest():
    search = _StubSearch([])
    source = WebEventSource("web-search", search, "Arlington", ("hiking", "pottery"))

    await source.fetch()

    general = [
        query
        for query in search.queries
        if "hiking" not in query and "pottery" not in query
    ]
    assert len(general) == 1
    assert "Arlington" in general[0]


# It goes first, so a tight budget spends its one request on the query that can
# return something new rather than on a fourth variation of one interest.
@pytest.mark.asyncio
async def test_the_general_query_is_spent_first_under_a_tight_budget():
    search = _StubSearch([])
    source = WebEventSource(
        "web-search", search, "Arlington", ("hiking",), max_queries=1
    )

    await source.fetch()

    assert len(search.queries) == 1
    assert "hiking" not in search.queries[0]


def _candidate(title: str, starts_at: datetime | None) -> ScoredCandidate:
    from backend.discovery.events import DiscoveredEvent

    vector = [1.0] + [0.0] * 767
    return ScoredCandidate(
        DiscoveredEvent(
            source_id="web-search",
            external_id=f"https://example.org/{title}",
            title=title,
            starts_at=starts_at,
            ends_at=None,
            place=None,
            url=f"https://example.org/{title}",
            summary=None,
        ),
        vector,
    )


def test_undated_finds_are_ranked_but_capped_below_dated_ones():
    ranker = RelevanceRanker({"hiking": [1.0] + [0.0] * 767}, {"hiking": 2})
    candidates = tuple(
        _candidate(f"walk-{index}", None) for index in range(MAX_UNDATED + 3)
    ) + (_candidate("dated", _NOW + timedelta(days=10)),)

    ranked = ranker.rank(candidates, now=_NOW)

    dated = [item for item in ranked if item.event.starts_at is not None]
    undated = [item for item in ranked if item.event.starts_at is None]
    assert len(dated) == 1
    # A weaker offer must not crowd out a schedulable one.
    assert len(undated) == MAX_UNDATED
    # Dated entries come first.
    assert ranked[0].event.starts_at is not None


def test_the_digest_separates_datable_events_from_mentions():
    dated = RankedCandidate(
        _candidate("Ridge hike", _NOW + timedelta(days=9)), 0.9, "hiking"
    )
    mention = RankedCandidate(_candidate("Weekly group walks", None), 0.8, "hiking")

    # `now` is passed because the renderer drops events that have already
    # started. Without it this read the real clock, so the test passed until
    # wall time moved past its fixed date and then failed for reasons that had
    # nothing to do with what it checks.
    message = render_message((dated, mention), "https://example.org/cal", now=_NOW)

    assert message is not None
    assert "Coming up near you:" in message
    assert "I found this, but couldn't confirm the date:" in message
    # A mention carries a link, never a calendar entry: nobody said when it is.
    added = message.split("couldn't confirm the date:")[1]
    assert "Add:" not in added
    assert "https://example.org/Weekly group walks" in added


def test_a_digest_of_only_mentions_is_still_worth_sending():
    mention = RankedCandidate(_candidate("Weekly group walks", None), 0.8, "hiking")
    message = render_message((mention,), "https://example.org/cal")

    assert message is not None
    assert "Coming up near you:" not in message
    assert "I found this, but couldn't confirm the date:" in message
