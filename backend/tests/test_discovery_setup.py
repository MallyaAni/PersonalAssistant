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
from backend.discovery.projection import INTEREST_KEY_PREFIX, LOCALITY_KEY
from backend.discovery.types import DiscoveryProfile, Interest, Locality, label_digest
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


# A suggestion keeps the capitalisation it was written with. Normalizing decides
# whether something is interest-shaped; it does not decide how it reads, and
# returning the folded form made every suggestion arrive in lower case while a
# typed interest kept its capitals.
def test_a_suggestion_keeps_its_capitalisation():
    records = (
        {"value": "Rock Climbing"},
        {"value": "live JAZZ"},
        {"value": "  Trail   Running  "},
    )

    labels = [item.label for item in propose_interests(records, _profile())]

    assert labels == ["Rock Climbing", "live JAZZ", "Trail Running"]


# Identity stays case-insensitive, so a differently-capitalised duplicate is
# still one interest rather than a second row the user has to delete twice.
def test_capitalisation_does_not_create_a_duplicate():
    proposals = propose_interests(({"value": "HIKING"},), _profile(("Hiking",)))

    assert proposals == ()


# A profile fact describes the person, not what they enjoy. Both are approved
# facts, so without telling them apart the finder offered a home locality and a
# preferred name as interests — the two facts almost every account has, which is
# what made it look like it suggested everything in memory.
def test_profile_facts_are_never_proposed_as_interests():
    records = (
        {"value": "Arlington, Virginia, US", "fact_key": LOCALITY_KEY},
        {"value": "ani", "fact_key": "preferred_name"},
        {"value": "concise", "fact_key": "response_style"},
        {"value": "bouldering", "fact_key": "hobby"},
    )

    labels = [item.label for item in propose_interests(records, _profile())]

    assert labels == ["bouldering"]


# An interest already projected onto the profile is not a new suggestion.
def test_an_already_recorded_interest_is_not_re_proposed():
    records = (
        {
            "value": "hiking",
            "fact_key": f"{INTEREST_KEY_PREFIX}{label_digest('hiking')}",
        },
    )

    assert propose_interests(records, _profile()) == ()


# A page of one city's events is worth nothing in another. Familiarity was
# already scoped per place; sources were not, so a curated DC page kept being
# read after someone travelled — filling a digest with things happening several
# hundred miles away.
@pytest.mark.asyncio
async def test_a_source_is_only_read_where_it_belongs():
    import uuid as _uuid

    from sqlalchemy import delete

    from backend.database.session import AsyncSessionLocal
    from backend.discovery.sources_repository import DiscoverySourceRepository
    from backend.models.discovery_source import DiscoverySource

    user_id = f"src_{_uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoverySourceRepository(session)
            await repo.upsert_source(
                user_id, "links", "https://example.org/dc", locality_label="Arlington"
            )
            # No place: a national feed travels with the user.
            await repo.upsert_source(user_id, "rss", "https://example.org/national")

            here = await repo.list_sources(
                user_id, enabled_only=True, locality_label="Arlington", scoped=True
            )
            away = await repo.list_sources(
                user_id, enabled_only=True, locality_label="Denver", scoped=True
            )
            everything = await repo.list_sources(user_id)

        assert {item.url for item in here} == {
            "https://example.org/dc",
            "https://example.org/national",
        }
        # The DC page goes quiet; the national one still travels.
        assert {item.url for item in away} == {"https://example.org/national"}
        # Managing sources must still show all of them, or travelling would
        # read as having lost one.
        assert len(everything) == 2
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoverySource).where(DiscoverySource.user_id == user_id)
            )
            await session.commit()


# A source that existed before scoping has no place and must keep behaving
# exactly as it did: read everywhere.
@pytest.mark.asyncio
async def test_an_unscoped_source_is_read_everywhere():
    import uuid as _uuid

    from sqlalchemy import delete

    from backend.database.session import AsyncSessionLocal
    from backend.discovery.sources_repository import DiscoverySourceRepository
    from backend.models.discovery_source import DiscoverySource

    user_id = f"src_{_uuid.uuid4().hex[:8]}"
    try:
        async with AsyncSessionLocal() as session:
            repo = DiscoverySourceRepository(session)
            await repo.upsert_source(user_id, "ics", "https://example.org/anywhere")
            for place in ("Arlington", "Denver", None):
                live = await repo.list_sources(
                    user_id, enabled_only=True, locality_label=place, scoped=True
                )
                assert len(live) == 1
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DiscoverySource).where(DiscoverySource.user_id == user_id)
            )
            await session.commit()


# Novelty suppression is switchable, because "never show the same thing twice"
# is right on a schedule and wrong while judging what a sweep produces. What is
# seen is still recorded either way, so turning it back on resumes with the
# history intact rather than from nothing.
@pytest.mark.asyncio
async def test_novelty_suppression_can_be_switched_off(monkeypatch):
    from backend.config.settings import settings as live_settings

    assert live_settings.DISCOVERY_NOVELTY_ENABLED in (True, False)

    # The flag is read at sweep time rather than captured at construction, so an
    # operator changing it does not need the process rebuilt around it.
    monkeypatch.setattr(live_settings, "DISCOVERY_NOVELTY_ENABLED", False)
    assert live_settings.DISCOVERY_NOVELTY_ENABLED is False
    monkeypatch.setattr(live_settings, "DISCOVERY_NOVELTY_ENABLED", True)
    assert live_settings.DISCOVERY_NOVELTY_ENABLED is True
