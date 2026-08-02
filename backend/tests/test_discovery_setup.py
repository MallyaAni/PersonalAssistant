"""Setup assist: proposing feeds and interests without guessing.

The property under test is that a proposal is earned. A feed is offered only
after it has been fetched and parsed, and an interest only from memory the user
already approved.
"""

import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.discovery.feed_finder import FeedFinder
from backend.discovery.interest_finder import propose_interests
from backend.discovery.types import DiscoveryProfile, Interest, Locality
from backend.search.types import SearchResult, SearchResults


class _StubSearch:
    def __init__(self, urls: list[str], enabled: bool = True) -> None:
        self.urls = urls
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
                SearchResult(title=url, url=url, content="", score=1.0)
                for url in self.urls
            ),
        )


_CALENDAR = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:a@v\r\nDTSTART:20260910T230000Z\r\n"
    "SUMMARY:Jazz night\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:b@v\r\nDTSTART:20260917T230000Z\r\n"
    "SUMMARY:Blues night\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def _profile(interests: tuple[str, ...] = ()) -> DiscoveryProfile:
    return DiscoveryProfile(
        interests=tuple(
            Interest(id=str(index), label=label, strength=2, provenance="user_explicit")
            for index, label in enumerate(interests)
        ),
        localities=(
            Locality(
                id="l1",
                label="New Haven",
                region="CT",
                radius_km=25,
                timezone="America/New_York",
                is_primary=True,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_no_search_provider_yields_no_suggestions():
    # Setup must degrade to manual entry rather than erroring when search is
    # unconfigured, which is the default state of this project.
    finder = FeedFinder(_StubSearch([], enabled=False))
    assert await finder.suggest("New Haven", ("jazz",)) == ()


@pytest.mark.asyncio
async def test_only_feed_shaped_urls_are_probed(monkeypatch):
    fetched: list[str] = []

    async def _fetch(url: str, **kwargs: object) -> str:
        fetched.append(url)
        return _CALENDAR

    import backend.discovery.feed_finder as module

    monkeypatch.setattr(module, "fetch_feed", _fetch)
    search = _StubSearch(
        [
            "https://venue.example/about",  # ordinary page: never fetched
            "https://venue.example/events.ics",
            "https://blog.example/feed/",
        ]
    )

    candidates = await FeedFinder(search).suggest("New Haven", ("jazz",))

    assert "https://venue.example/about" not in fetched
    assert "https://venue.example/events.ics" in fetched
    assert any(item.url.endswith("events.ics") for item in candidates)


@pytest.mark.asyncio
async def test_a_candidate_is_offered_only_after_it_parses(monkeypatch):
    async def _fetch(url: str, **kwargs: object) -> str:
        # Looks like a feed, is not one.
        return "<html><body>not a feed</body></html>"

    import backend.discovery.feed_finder as module

    monkeypatch.setattr(module, "fetch_feed", _fetch)
    search = _StubSearch(["https://venue.example/events.ics"])

    assert await FeedFinder(search).suggest("New Haven", ()) == ()


@pytest.mark.asyncio
async def test_a_candidate_carries_a_recognizable_sample(monkeypatch):
    async def _fetch(url: str, **kwargs: object) -> str:
        return _CALENDAR

    import backend.discovery.feed_finder as module

    monkeypatch.setattr(module, "fetch_feed", _fetch)
    search = _StubSearch(["https://venue.example/events.ics"])

    candidates = await FeedFinder(search).suggest("New Haven", ())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.kind == "ics"
    assert candidate.event_count == 2
    # The user should recognize what they are adding rather than trust a URL.
    assert "Jazz night" in candidate.sample_titles
    assert candidate.title == "venue.example"


@pytest.mark.asyncio
async def test_queries_carry_only_the_stated_place_and_interests():
    search = _StubSearch([])
    await FeedFinder(search).suggest("New Haven", ("jazz", "pottery"))

    joined = " ".join(search.queries).lower()
    assert "new haven" in joined
    assert "jazz" in joined
    # No memory, conversation, or identifying detail beyond the stated place.
    assert "ani" not in joined


def test_prose_is_never_turned_into_an_interest():
    records = (
        {"value": "jazz", "content": "jazz"},
        {"value": "the user asked me to remember their dentist appointment"},
        {"value": "x"},
    )

    proposals = propose_interests(records, _profile())

    labels = [item.label for item in proposals]
    assert "jazz" in labels
    # A sentence is not an interest, and a two-character token is too generic
    # to rank an event against.
    assert len(labels) == 1


def test_a_records_internal_key_never_becomes_an_interest():
    # Found live: a note filed under the key `dentist` whose value is prose was
    # rejected as prose and then proposed from its key instead, offering
    # "dentist" as something the user likes. The record must say what they like,
    # not what it is filed as.
    records = (
        {
            "value": "the user asked me to remember their dentist appointment",
            "topic": "dentist",
            "content": "the user asked me to remember their dentist appointment",
        },
    )

    assert propose_interests(records, _profile()) == ()


def test_an_interest_already_on_the_profile_is_not_proposed_again():
    records = ({"value": "Jazz"},)
    proposals = propose_interests(records, _profile(("jazz",)))
    # Case and spacing resolve to one interest, so this is a duplicate.
    assert proposals == ()


def test_a_proposal_carries_its_evidence():
    records = ({"value": "ceramics", "content": "I have been taking a ceramics class"},)
    proposals = propose_interests(records, _profile())

    assert proposals[0].label == "ceramics"
    assert "ceramics class" in proposals[0].evidence
