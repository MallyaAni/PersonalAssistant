"""Scout searching and ranking for a person rather than for a topic.

Before this, the only things about a person that reached a sweep were a two-word
interest label and a city: the query was `{label} {place} {month year}` and the
vector a candidate was scored against was the embedding of `label`. That is how a
man was sent a women-only running event — nothing in the query was about him.

These tests cover the three properties that make the change safe rather than
merely better: what may be read out of memory at all, that the query skeleton and
budget are unchanged, and that every failure lands exactly on the old behaviour.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")
os.environ["POSTGRES_HOST"] = "localhost"

from backend.database.session import AsyncSessionLocal
from backend.discovery.aiming import AimPlanner
from backend.discovery.events import DiscoveredEvent
from backend.discovery.novelty import ScoredCandidate, SeenItemRepository
from backend.discovery.personal_context import PersonalContext, PersonalContextReader
from backend.discovery.projection import interest_fact, locality_fact
from backend.discovery.relevance import RankedCandidate
from backend.discovery.reranking import MemoryReranker
from backend.discovery.runner import DiscoveryRunner
from backend.discovery.sources.web import WebEventSource
from backend.discovery.sources_repository import DiscoverySourceRepository
from backend.discovery.types import DiscoveryProfile, Interest, Locality
from backend.models.discovery_source import DiscoverySeenItem, DiscoverySource
from backend.models.memory import MemoryFact, SemanticMemory
from backend.search.types import SearchResult, SearchResults

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


# The stored column is fixed at 768 dimensions, so test vectors are the real
# width with the signal in the leading components.
def _vec(*values: float) -> list[float]:
    vector = [0.0] * 768
    for index, value in enumerate(values):
        vector[index] = value
    return vector


# A model that answers with whatever the test decided, and records what it was
# asked. Every prompt in this subsystem is grammar-constrained and greedy, so a
# canned reply is a faithful stand-in for the runtime.
class _StubWriter:
    def __init__(self, *replies: str, fail: bool = False) -> None:
        self.replies = list(replies)
        self.fail = fail
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any] | None] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        self.prompts.append(
            "\n".join(message.get("content", "") for message in messages)
        )
        self.schemas.append(response_schema)
        if self.fail:
            raise RuntimeError("inference runtime unavailable")
        reply = self.replies.pop(0) if self.replies else "{}"
        return {"content": reply}


class _StubSearch:
    def __init__(self, results: list[tuple[str, str, str]] | None = None) -> None:
        self.results = results or []
        self.queries: list[str] = []

    def is_enabled(self) -> bool:
        return True

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


def _event(
    external_id: str,
    title: str,
    days_ahead: int | None = 10,
    summary: str | None = None,
) -> DiscoveredEvent:
    return DiscoveredEvent(
        source_id="src-1",
        external_id=external_id,
        title=title,
        starts_at=_NOW + timedelta(days=days_ahead) if days_ahead is not None else None,
        ends_at=None,
        place="Arlington, Virginia",
        url=f"https://example.org/{external_id}",
        summary=summary,
    )


def _ranked(*events: DiscoveredEvent) -> tuple[RankedCandidate, ...]:
    return tuple(
        RankedCandidate(
            candidate=ScoredCandidate(event=event, embedding=_vec(1.0)),
            score=0.9 - index * 0.01,
            matched_interest=None,
        )
        for index, event in enumerate(events)
    )


async def _cleanup(user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        for statement in (
            delete(MemoryFact).where(MemoryFact.user_id == user_id),
            delete(SemanticMemory).where(SemanticMemory.user_id == user_id),
            delete(DiscoverySeenItem).where(DiscoverySeenItem.user_id == user_id),
            delete(DiscoverySource).where(DiscoverySource.user_id == user_id),
        ):
            await session.execute(statement)
        await session.commit()


# Insert one fact directly. The approval path is exercised by the memory suite;
# what matters here is which stored rows a sweep is allowed to read.
def _fact(
    user_id: str,
    fact_key: str,
    value: str,
    approval_state: str = "approved",
    expires_at: datetime | None = None,
    version: int = 1,
) -> MemoryFact:
    return MemoryFact(
        user_id=user_id,
        fact_type="profile",
        fact_key=fact_key,
        value=value,
        normalized_value=value.casefold(),
        approval_state=approval_state,
        confidence=1.0,
        purpose="personalization",
        source_conversation_id=None,
        source_trace_id=uuid.uuid4(),
        version=version,
        expires_at=expires_at,
        extra_data={},
    )


# --- what may be read out of memory at all ---------------------------------


@pytest.mark.asyncio
async def test_only_approved_unexpired_facts_reach_a_sweep():
    user_id = f"pc_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                (
                    _fact(user_id, "running_style", "runs casually at weekends"),
                    _fact(user_id, "pending_thing", "not approved", "pending"),
                    _fact(user_id, "old_thing", "superseded", "superseded"),
                    _fact(
                        user_id,
                        "lapsed_thing",
                        "expired",
                        expires_at=_NOW - timedelta(days=1),
                    ),
                )
            )
            await session.commit()

            context = await PersonalContextReader(session).read(user_id, now=_NOW)

        joined = " ".join(context.statements)
        assert "runs casually at weekends" in joined
        # A pending proposal is not what the user agreed to be known by, and a
        # superseded or expired fact is what they used to be.
        assert "not approved" not in joined
        assert "superseded" not in joined
        assert "expired" not in joined
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_projections_and_identifiers_never_reach_a_sweep():
    user_id = f"pc_{uuid.uuid4().hex[:12]}"
    interest = interest_fact("Run Clubs")
    locality = locality_fact("Arlington", "Virginia")
    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                (
                    _fact(user_id, interest.fact_key, interest.value),
                    _fact(user_id, locality.fact_key, locality.value),
                    _fact(user_id, "preferred_name", "Ani"),
                    _fact(user_id, "response_style", "concise"),
                    _fact(user_id, "contact", "reach me at ani@example.com"),
                    _fact(user_id, "running_style", "runs casually at weekends"),
                )
            )
            await session.commit()

            context = await PersonalContextReader(session).read(user_id, now=_NOW)

        joined = " ".join(context.statements).casefold()
        # Interests and the locality already reach a sweep as typed rows.
        assert "run clubs" not in joined
        assert "arlington" not in joined
        # A name identifies the searcher and helps no search for a happening.
        assert "ani" not in joined.split()
        assert "concise" not in joined
        # The egress screen blocks an account identifier outright, so the whole
        # statement is dropped rather than trimmed.
        assert "example.com" not in joined
        assert "runs casually at weekends" in joined
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_remembered_sentences_join_the_context_and_it_stays_bounded():
    user_id = f"pc_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            session.add_all(
                _fact(user_id, f"fact_{index}", f"statement number {index}")
                for index in range(20)
            )
            session.add(
                SemanticMemory(
                    user_id=user_id,
                    content="They prefer beginner-friendly group activities.",
                    embedding=_vec(1.0),
                    purpose="user_explicit",
                    embedding_model="stub",
                    embedding_version="1",
                    embedding_dimension=768,
                    expires_at=None,
                    extra_data={},
                )
            )
            await session.commit()

            reader = PersonalContextReader(session)
            bounded = await reader.read(user_id, now=_NOW)
            small = await PersonalContextReader(session, max_statements=1).read(
                user_id, now=_NOW
            )

        # A long memory must not grow an unattended weekly prompt without limit.
        assert len(bounded.statements) == 12
        assert len(small.statements) == 1
        assert not bounded.is_empty
        assert PersonalContext().is_empty
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_remembered_sentence_reaches_the_context():
    user_id = f"pc_{uuid.uuid4().hex[:12]}"
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                SemanticMemory(
                    user_id=user_id,
                    content="They prefer beginner-friendly group activities.",
                    embedding=_vec(1.0),
                    purpose="user_explicit",
                    embedding_model="stub",
                    embedding_version="1",
                    embedding_dimension=768,
                    expires_at=None,
                    extra_data={},
                )
            )
            await session.commit()

            context = await PersonalContextReader(session).read(user_id, now=_NOW)

        assert context.statements == (
            "They prefer beginner-friendly group activities.",
        )
    finally:
        await _cleanup(user_id)


# --- aiming the queries -----------------------------------------------------


_CONTEXT = PersonalContext(
    (
        "running style: runs casually at weekends",
        "They prefer beginner-friendly group activities.",
    )
)


@pytest.mark.asyncio
async def test_an_aimed_subject_replaces_the_bare_label():
    writer = _StubWriter(
        '{"aims": [{"interest": "Run Clubs", '
        '"subject": "casual weekend group runs", '
        '"profile": "relaxed weekend group runs for beginners"}]}'
    )

    aim = await AimPlanner(writer).plan(("Run Clubs",), _CONTEXT, "Arlington, Virginia")

    assert aim.subjects() == ("casual weekend group runs",)
    # The key stays the user's own label, so a digest still names the interest
    # they stated rather than a phrasing of ours.
    assert aim.vector_texts() == {
        "Run Clubs": "relaxed weekend group runs for beginners"
    }


@pytest.mark.asyncio
async def test_the_skeleton_and_the_budget_are_unchanged():
    search = _StubSearch()
    source = WebEventSource(
        "web-search",
        search,
        "Arlington",
        ("casual weekend group runs", "beginner pottery classes"),
        region="Virginia",
        include_general=False,
        max_queries=2,
    )

    await source.fetch()

    # `{subject} {place} {month year}` — the phrasing that was measured. Naming
    # the month kept 6 of 9 results where "events near X upcoming" kept 0 of 5.
    assert search.queries == [
        "casual weekend group runs Arlington, Virginia August 2026",
        "beginner pottery classes Arlington, Virginia August 2026",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject",
    [
        # The skeleton appends the month and year; a subject naming one would
        # produce a query that says it twice.
        "group runs in September",
        "group runs 2026",
        # And the place, for the same reason.
        "group runs in Arlington",
        "group runs around Virginia",
        # Longer than a kind of happening.
        "a really quite extraordinarily long description of the kind of running "
        "this person enjoys doing",
        # Personal framing the egress screen would have to minimize.
        "my diagnosis and running",
    ],
)
async def test_an_unusable_subject_falls_back_to_the_interest_label(subject: str):
    writer = _StubWriter(
        json.dumps(
            {
                "aims": [
                    {
                        "interest": "Run Clubs",
                        "subject": subject,
                        "profile": "weekend runs",
                    }
                ]
            }
        )
    )

    aim = await AimPlanner(writer).plan(("Run Clubs",), _CONTEXT, "Arlington, Virginia")

    # Rejection is not a failure: the label is what a query carried before any
    # of this existed.
    assert aim.subjects() == ("Run Clubs",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "planner",
    [
        AimPlanner(None),
        AimPlanner(_StubWriter(fail=True)),
        AimPlanner(_StubWriter("not json at all")),
        AimPlanner(
            _StubWriter(
                '{"aims": [{"interest": "Something Else", '
                '"subject": "x", "profile": "y"}]}'
            )
        ),
    ],
)
async def test_every_failure_lands_on_the_old_behaviour(planner: AimPlanner):
    aim = await planner.plan(("Run Clubs", "Pottery"), _CONTEXT, "Arlington")

    assert aim.subjects() == ("Run Clubs", "Pottery")
    assert aim.vector_texts() == {"Run Clubs": "Run Clubs", "Pottery": "Pottery"}


@pytest.mark.asyncio
async def test_an_empty_memory_still_describes_each_interest():
    writer = _StubWriter(
        '{"aims": [{"interest": "Horses", "subject": "Horses", '
        '"profile": "horse riding, equestrian shows and stables"}]}'
    )

    aim = await AimPlanner(writer).plan(("Horses",), PersonalContext(), "Alexandria")

    # Most of the measured benefit is here rather than in personalization. A
    # real digest attributed "COLLECTIVE at The Light Horse" to "Horses" — a
    # concert matched to an equestrian interest by the name of the pub. Two
    # words cannot be matched against an event description at all.
    assert writer.prompts, "the model is asked even with nothing known"
    assert "no facts about themselves yet" in writer.prompts[0]
    assert aim.vector_texts() == {
        "Horses": "horse riding, equestrian shows and stables"
    }
    # The query is untouched, so no metered search behaviour changes with it.
    assert aim.subjects() == ("Horses",)


# --- ordering the shortlist -------------------------------------------------


@pytest.mark.asyncio
async def test_the_model_reorders_what_deterministic_ranking_admitted():
    shortlist = _ranked(
        _event("a", "Advanced trail race"),
        _event("b", "Beginner group run"),
        _event("c", "Track night"),
    )
    writer = _StubWriter('{"order": [2, 3], "excluded": []}')

    ordered = await MemoryReranker(writer).order(shortlist, _CONTEXT, now=_NOW)

    titles = [item.event.title for item in ordered]
    # Two were ranked; the third keeps its deterministic place behind them.
    assert titles == ["Beginner group run", "Track night", "Advanced trail race"]


@pytest.mark.asyncio
async def test_an_explicitly_stated_restriction_can_drop_a_find():
    shortlist = _ranked(
        _event("a", "Women's 5K", summary="This run is open to women only."),
        _event("b", "Beginner group run"),
    )
    writer = _StubWriter('{"order": [2], "excluded": [1]}')

    ordered = await MemoryReranker(writer).order(shortlist, _CONTEXT, now=_NOW)

    assert [item.event.title for item in ordered] == ["Beginner group run"]


@pytest.mark.asyncio
async def test_excluding_everything_falls_back_rather_than_shipping_empty():
    shortlist = _ranked(_event("a", "One"), _event("b", "Two"))
    writer = _StubWriter('{"order": [], "excluded": [1, 2]}')

    ordered = await MemoryReranker(writer).order(shortlist, _CONTEXT, now=_NOW)

    # Far likelier a model failure than a person for whom nothing is eligible.
    assert len(ordered) == 2


@pytest.mark.asyncio
async def test_an_undated_mention_never_displaces_a_dated_find():
    shortlist = _ranked(
        _event("a", "Dated one"),
        _event("b", "Undated one", days_ahead=None),
        _event("c", "Dated two"),
    )
    # The model asks for the undated mention first; the cap still holds.
    writer = _StubWriter('{"order": [2, 1, 3], "excluded": []}')

    ordered = await MemoryReranker(writer).order(
        shortlist, _CONTEXT, now=_NOW, limit=1, undated_limit=1
    )

    # A find with no start cannot become a calendar entry, so it is capped
    # separately and always follows the dated ones.
    assert [item.event.title for item in ordered] == ["Dated one", "Undated one"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reranker",
    [
        MemoryReranker(None),
        MemoryReranker(_StubWriter(fail=True)),
        MemoryReranker(_StubWriter("{not json}")),
    ],
)
async def test_a_failed_ordering_keeps_the_deterministic_one(
    reranker: MemoryReranker,
):
    shortlist = _ranked(_event("a", "First"), _event("b", "Second"))

    ordered = await reranker.order(shortlist, _CONTEXT, now=_NOW)

    assert [item.event.title for item in ordered] == ["First", "Second"]


@pytest.mark.asyncio
async def test_the_model_is_made_to_answer_the_exclusion_question():
    shortlist = _ranked(_event("a", "First"), _event("b", "Second"))
    writer = _StubWriter('{"order": [1, 2], "excluded": []}')

    await MemoryReranker(writer).order(shortlist, _CONTEXT, now=_NOW)

    # Left optional in the grammar, the live model never emitted the field at
    # all — three greedy runs returned only an order, so the question was
    # skipped rather than answered.
    schema = writer.schemas[0]
    assert schema is not None
    assert sorted(schema["required"]) == ["excluded", "order"]


@pytest.mark.asyncio
async def test_an_empty_memory_leaves_the_order_alone():
    shortlist = _ranked(_event("a", "First"), _event("b", "Second"))
    writer = _StubWriter('{"order": [2, 1], "excluded": []}')

    ordered = await MemoryReranker(writer).order(shortlist, PersonalContext(), now=_NOW)

    assert writer.prompts == []
    assert [item.event.title for item in ordered] == ["First", "Second"]


# --- one whole sweep --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sweep_searches_and_ranks_with_what_memory_knows(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "DISCOVERY_PERSONAL_QUERIES_ENABLED", True)
    monkeypatch.setattr(settings, "DISCOVERY_MEMORY_RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "DISCOVERY_WEB_SEARCH_ENABLED", True)

    user_id = f"pc_{uuid.uuid4().hex[:12]}"
    search = _StubSearch(
        [
            (
                "Beginner group run September 12, 2026",
                "https://runs.example/beginner",
                "An easy weekend run for anyone starting out.",
            ),
        ]
    )
    # One call aims the sweep, one orders the shortlist, and the rest describe
    # the finds that were selected.
    writer = _StubWriter(
        '{"aims": [{"interest": "Run Clubs", '
        '"subject": "casual weekend group runs", '
        '"profile": "relaxed weekend group runs for beginners"}]}',
        '{"order": [1], "excluded": []}',
    )

    class _Embeddings:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            self.texts.extend(texts)
            return [_vec(1.0) for _ in texts]

    embeddings = _Embeddings()
    try:
        async with AsyncSessionLocal() as session:
            session.add(_fact(user_id, "running_style", "runs casually at weekends"))
            await session.commit()

            runner = DiscoveryRunner(
                sources=DiscoverySourceRepository(session),
                seen=SeenItemRepository(session),
                embeddings=embeddings,
                search=search,
                writer=writer,
            )
            profile = DiscoveryProfile(
                interests=(
                    Interest(
                        id="i1",
                        label="Run Clubs",
                        strength=3,
                        provenance="user_explicit",
                    ),
                ),
                localities=(
                    Locality(
                        id="l1",
                        label="Arlington",
                        region="Virginia",
                        radius_km=25,
                        timezone="America/New_York",
                        is_primary=True,
                    ),
                ),
            )

            result = await runner.sweep(user_id, profile, now=_NOW, persist=False)

        # The query is about this person, in the skeleton that was measured.
        assert (
            "casual weekend group runs Arlington, Virginia August 2026"
            in search.queries
        )
        # And the vector a candidate was scored against is no longer two words.
        assert "relaxed weekend group runs for beginners" in embeddings.texts
        assert "Run Clubs" not in embeddings.texts
        # The approved fact reached the prompts; the search provider never saw it.
        assert any("runs casually at weekends" in prompt for prompt in writer.prompts)
        assert not any("casually" in query for query in search.queries)
        assert len(result.selected) == 1
    finally:
        await _cleanup(user_id)


@pytest.mark.asyncio
async def test_a_sweep_with_the_flags_off_searches_the_bare_label(monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "DISCOVERY_PERSONAL_QUERIES_ENABLED", False)
    monkeypatch.setattr(settings, "DISCOVERY_MEMORY_RERANK_ENABLED", False)
    monkeypatch.setattr(settings, "DISCOVERY_WEB_SEARCH_ENABLED", True)

    user_id = f"pc_{uuid.uuid4().hex[:12]}"
    search = _StubSearch()
    writer = _StubWriter()
    try:
        async with AsyncSessionLocal() as session:
            session.add(_fact(user_id, "running_style", "runs casually at weekends"))
            await session.commit()

            runner = DiscoveryRunner(
                sources=DiscoverySourceRepository(session),
                seen=SeenItemRepository(session),
                embeddings=type(
                    "_E",
                    (),
                    {"embed_texts": lambda self, texts: [_vec(1.0) for _ in texts]},
                )(),
                search=search,
                writer=writer,
            )
            profile = DiscoveryProfile(
                interests=(
                    Interest(
                        id="i1",
                        label="Run Clubs",
                        strength=3,
                        provenance="user_explicit",
                    ),
                ),
                localities=(
                    Locality(
                        id="l1",
                        label="Arlington",
                        region="Virginia",
                        radius_km=25,
                        timezone="America/New_York",
                        is_primary=True,
                    ),
                ),
            )

            await runner.sweep(user_id, profile, now=_NOW, persist=False)

        assert "Run Clubs Arlington, Virginia August 2026" in search.queries
        # Nothing was read out of memory and nothing was asked of the model.
        assert writer.prompts == []
    finally:
        await _cleanup(user_id)
