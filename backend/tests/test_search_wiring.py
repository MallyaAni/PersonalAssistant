from collections.abc import Iterator

import pytest

from backend.core.llm import LLMClient
from backend.search.types import SearchResult, SearchResults
from backend.services.conversation_service import ConversationService
from backend.services.main_action_selector import MainAction, SearchAction
from backend.tests.doubles import (
    StubConversationRepository,
    StubMemoryService,
    StubTracer,
)


class RecordingLLM(LLMClient):
    """Capture the assembled messages so prompt wiring can be asserted."""

    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def generate_text(self, prompt, max_tokens=512):
        return "deterministic response"

    def chat(self, messages, max_tokens=512):
        return {"content": "deterministic response"}

    def stream_chat(self, messages, max_tokens=512) -> Iterator[str]:
        self.messages = messages
        yield "ok"


class RecordingSearch:
    """Search double recording calls and optionally failing."""

    def __init__(self, enabled: bool = True, fail: bool = False) -> None:
        self.enabled = enabled
        self.fail = fail
        self.queries: list[str] = []

    def is_enabled(self) -> bool:
        return self.enabled

    async def search(self, query: str, max_results: int | None = None) -> SearchResults:
        self.queries.append(query)
        if self.fail:
            raise RuntimeError("provider outage")
        return SearchResults(
            query=query,
            results=(
                SearchResult(
                    title="Result",
                    url="https://example.test/a",
                    content="fresh fact",
                    score=0.9,
                ),
            ),
            provider="stub",
        )


class RecordingMCPSearch(RecordingSearch):
    """Expose the fixed MCP identity used by the web-search adapter."""

    # Return the server and tool shown in the chat lifecycle.
    @property
    def tool_identity(self) -> tuple[str, str]:
        return "internet", "search_web"


class RecordingImageSearch:
    """Return one strong image match with generation provenance."""

    def __init__(self, generation_prompt: str) -> None:
        self.generation_prompt = generation_prompt
        self.calls: list[dict[str, object]] = []

    # Record the semantic lookup and return a discriminating best match.
    async def search_by_embedding(
        self,
        user_id: str,
        embedding: list[float],
        limit: int,
        max_distance: float,
    ) -> list[dict]:
        self.calls.append(
            {
                "user_id": user_id,
                "embedding": embedding,
                "limit": limit,
                "max_distance": max_distance,
            }
        )
        return [
            {
                "id": "88888888-8888-4888-8888-888888888888",
                "kind": "generated_image",
                "title": "Generated image",
                "created_at": "2026-07-23T12:00:00Z",
                "metadata": {"generation_prompt": self.generation_prompt},
                "distance": 0.90,
            },
            {
                "id": "99999999-9999-4999-8999-999999999999",
                "kind": "generated_image",
                "title": "Generated image",
                "metadata": {},
                "distance": 0.94,
            },
        ]


class AlwaysImageContextRouter:
    """Approve image recall for tests exercising referenced-image search."""

    # Return the one modality whose downstream behavior this fixture proves.
    async def required_modalities(self, query: str) -> tuple[str, ...]:
        return ("image",)


async def _events(service: ConversationService, query: str) -> list[dict]:
    return [
        event
        async for event in service.process_request(
            "search_user",
            query,
            "33333333-3333-4333-8333-333333333333",
            {"source": "test"},
        )
    ]


async def _run(service: ConversationService, query: str) -> None:
    async for _ in service.process_request(
        "search_user",
        query,
        "33333333-3333-4333-8333-333333333333",
        {"source": "test"},
    ):
        pass


class StubMainActionSelector:
    """Return one fixed action without a native tool-calling round trip.

    Routing itself -- whether the main model decides to search -- is the
    model's own native tool-call decision, tested in
    test_main_action_selector.py against a controlled LLM double and again in
    the functional suite against the real runtime. This file is downstream of
    that decision: it exercises what the application does once told to
    search -- egress screening, budget handling, event ordering, and image
    context -- so each test states its action explicitly rather than relying
    on wording a pattern would happen to match.
    """

    def __init__(self, action: MainAction) -> None:
        self.action = action

    async def select(
        self,
        user_id: str,
        query: str,
        history: list[dict],
        active_image_artifact_id: str | None,
        query_embedding: list[float] | None = None,
    ) -> MainAction:
        return self.action


def _service(
    search: RecordingSearch,
    llm: RecordingLLM,
    image_search: RecordingImageSearch | None = None,
    action: MainAction = None,
) -> ConversationService:
    return ConversationService(
        memory=StubMemoryService(),
        llm=llm,
        repository=StubConversationRepository(),
        tracer=StubTracer(),
        search=search,  # type: ignore[arg-type]
        main_action_selector=StubMainActionSelector(action),  # type: ignore[arg-type]
        artifact_context_router=(AlwaysImageContextRouter() if image_search else None),
        image_search=image_search,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_recency_query_searches_and_reaches_the_system_prompt():
    search = RecordingSearch()
    llm = RecordingLLM()
    action = SearchAction(query="what is the latest python release")

    await _run(
        _service(search, llm, action=action), "what is the latest python release"
    )

    assert search.queries == ["what is the latest python release"]
    # Everything the model was sent. This turn's search results and image
    # context ride in their own message after the history now, so reading
    # messages[0] alone would test position rather than delivery.
    system = "".join(message["content"] for message in llm.messages)
    assert "fresh fact" in system
    assert "https://example.test/a" in system
    assert "untrusted" in system


@pytest.mark.asyncio
async def test_no_action_never_calls_the_search_provider():
    search = RecordingSearch()
    llm = RecordingLLM()

    await _run(_service(search, llm, action=None), "explain how a b-tree works")

    assert search.queries == []
    assert "Search results:" not in llm.messages[0]["content"]


@pytest.mark.asyncio
async def test_disabled_provider_is_never_called_even_when_the_model_chose_to_search():
    search = RecordingSearch(enabled=False)
    llm = RecordingLLM()
    action = SearchAction(query="what is the latest python release")

    await _run(
        _service(search, llm, action=action), "what is the latest python release"
    )

    assert search.queries == []


@pytest.mark.asyncio
async def test_search_failure_degrades_the_answer_without_failing_the_turn():
    search = RecordingSearch(fail=True)
    llm = RecordingLLM()
    action = SearchAction(query="what is the latest python release")

    await _run(
        _service(search, llm, action=action), "what is the latest python release"
    )

    # The turn still completes; the prompt simply carries no search block.
    assert search.queries == ["what is the latest python release"]
    assert "Search results:" not in llm.messages[0]["content"]


@pytest.mark.asyncio
async def test_service_without_search_configured_still_answers():
    llm = RecordingLLM()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=llm,
        repository=StubConversationRepository(),
        tracer=StubTracer(),
    )

    await _run(service, "what is the latest python release")

    assert "Search results:" not in llm.messages[0]["content"]


@pytest.mark.asyncio
async def test_search_is_announced_before_it_runs_and_sources_are_streamed():
    search = RecordingSearch()
    llm = RecordingLLM()
    action = SearchAction(query="what is the latest python release")

    events = await _events(
        _service(search, llm, action=action), "what is the latest python release"
    )
    names = [event["event"] for event in events]

    # The interface must be able to show the search running, so the
    # announcement precedes the provider call and the first answer token.
    assert names.index("search_started") < names.index("search_results")
    assert names.index("search_results") < names.index("delta")
    sources = [event for event in events if event["event"] == "search_results"][0][
        "data"
    ]["sources"]
    assert sources == [
        {
            "title": "Result",
            "url": "https://example.test/a",
            "snippet": "fresh fact",
        }
    ]


@pytest.mark.asyncio
async def test_no_search_events_are_emitted_when_no_action_was_chosen():
    search = RecordingSearch()
    llm = RecordingLLM()

    events = await _events(
        _service(search, llm, action=None), "explain how a b-tree works"
    )
    names = [event["event"] for event in events]

    assert "search_started" not in names
    assert "search_results" not in names


@pytest.mark.asyncio
async def test_sources_are_reported_empty_so_the_indicator_can_be_retracted():
    search = RecordingSearch(fail=True)
    llm = RecordingLLM()
    action = SearchAction(query="what is the latest python release")

    events = await _events(
        _service(search, llm, action=action), "what is the latest python release"
    )
    reported = [e for e in events if e["event"] == "search_results"]

    # A failed search still reports, otherwise the indicator would spin forever.
    assert len(reported) == 1
    assert reported[0]["data"]["sources"] == []


@pytest.mark.asyncio
async def test_a_credential_bearing_query_never_reaches_the_provider():
    search = RecordingSearch()
    llm = RecordingLLM()
    query = "is my latest api key sk-abcdef0123456789abcdef valid"

    # The model chose to search with this exact text -- which is exactly the
    # scenario the egress screen exists to catch regardless of how routing
    # got there.
    events = await _events(
        _service(search, llm, action=SearchAction(query=query)),
        query,
    )
    names = [event["event"] for event in events]

    # No network call is made at all, and the turn still answers.
    assert search.queries == []
    assert "search_started" not in names
    blocked = [e for e in events if e["event"] == "search_blocked"][0]
    assert "credential" in blocked["data"]["categories"]


@pytest.mark.asyncio
async def test_personal_framing_is_stripped_before_the_provider_sees_it():
    search = RecordingSearch()
    llm = RecordingLLM()
    query = "what is the latest treatment for my psoriasis"

    # Egress strips the personal framing before the provider sees it,
    # regardless of how the turn was routed to search.
    events = await _events(
        _service(search, llm, action=SearchAction(query=query)),
        query,
    )

    # The provider receives the public topic, never the user's framing. The
    # exact wording is not the contract; the absence of the possessive is.
    sent = search.queries[0]
    assert "psoriasis" in sent
    assert "my" not in sent.split()
    started = [e for e in events if e["event"] == "search_started"][0]
    assert started["data"]["minimized"] is True
    assert "my" not in started["data"]["query"].split()


# Verify MCP-backed internet search emits both search and tool transparency events.
@pytest.mark.asyncio
async def test_mcp_search_provider_streams_tool_lifecycle():
    search = RecordingMCPSearch()
    llm = RecordingLLM()
    action = SearchAction(query="what is the latest python release")

    events = await _events(
        _service(search, llm, action=action), "what is the latest python release"
    )
    names = [event["event"] for event in events]

    assert names.index("search_started") < names.index("tool_started")
    assert names.index("tool_started") < names.index("tool_finished")
    assert names.index("tool_finished") < names.index("search_results")
    assert [e for e in events if e["event"] == "tool_finished"][0]["data"] == {
        "server_id": "internet",
        "tool_name": "search_web",
        "status": "succeeded",
        "message": "Tool completed.",
    }


# Verify search-control wording is not sent as part of the factual query.
@pytest.mark.asyncio
async def test_search_control_words_are_removed_before_provider_call():
    search = RecordingSearch()
    llm = RecordingLLM()
    query = "Search online for the latest stable Python release and cite the source."

    await _run(_service(search, llm, action=SearchAction(query=query)), query)

    assert search.queries == ["the latest stable Python release"]


# Verify referenced-image search includes safe prompt provenance.
@pytest.mark.asyncio
async def test_referenced_image_context_enriches_explicit_search():
    search = RecordingSearch()
    llm = RecordingLLM()
    image_search = RecordingImageSearch("A sleek cobalt sports car at sunset")
    query = "can you search the internet for that car to get its model?"

    events = await _events(
        _service(search, llm, image_search, action=SearchAction(query=query)),
        query,
    )

    names = [event["event"] for event in events]
    assert names.index("image_matches") < names.index("search_started")
    assert search.queries == [
        "that car to get its model. "
        "Referenced image description: A sleek cobalt sports car at sunset"
    ]
    # Everything the model was sent. This turn's search results and image
    # context ride in their own message after the history now, so reading
    # messages[0] alone would test position rather than delivery.
    system = "".join(message["content"] for message in llm.messages)
    assert "A sleek cobalt sports car at sunset" in system
    assert "https://example.test/a" in system


# Verify sensitive image provenance is blocked before any provider call.
@pytest.mark.asyncio
async def test_sensitive_referenced_image_context_never_leaves_the_machine():
    search = RecordingSearch()
    llm = RecordingLLM()
    image_search = RecordingImageSearch(
        "A car with api key sk-abcdef0123456789abcdef on the dashboard"
    )
    query = "search the internet for that car"

    events = await _events(
        _service(search, llm, image_search, action=SearchAction(query=query)),
        query,
    )

    assert search.queries == []
    blocked = [event for event in events if event["event"] == "search_blocked"]
    assert blocked[0]["data"]["categories"] == ["credential"]
