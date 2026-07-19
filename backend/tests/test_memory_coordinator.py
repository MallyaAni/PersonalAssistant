import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.core.llm import LLMClient
from backend.memory.coordinator import (
    MemoryCoordinatorAgent,
    MemoryQueryPlan,
    build_memory_query_plan,
)
from backend.services.conversation_service import ConversationService
from backend.tests.doubles import (
    StubConversationRepository,
    StubMemoryService,
    StubTracer,
)


class FakeSemanticCache:
    # Create an in-memory semantic cache for coordinator tests.
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str, str], dict[str, Any]] = {}

    # Return a cached planning response when one exists.
    async def get(
        self,
        user_id: str,
        query: str,
        model: str,
        *,
        semantic_fallback: bool = True,
    ) -> dict[str, Any] | None:
        assert semantic_fallback is False
        return self.entries.get((user_id, query, model))

    # Save a planning response in the fake cache.
    async def put(
        self,
        user_id: str,
        query: str,
        response: str,
        model: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        entry = {"response": response, "expires_at": expires_at}
        self.entries[(user_id, query, model)] = entry
        return entry


class FakeWorkingStore:
    # Create an in-memory working store for coordinator tests.
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    # Replace the current fake working-memory item.
    async def upsert(
        self,
        user_id: str,
        conversation_id: str,
        memory_key: str,
        value: str,
        purpose: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        item = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "memory_key": memory_key,
            "value": value,
            "purpose": purpose,
            "expires_at": expires_at,
        }
        self.items = [item]
        return item

    # List working items that match a user and conversation.
    async def list_active(
        self, user_id: str, conversation_id: str
    ) -> list[dict[str, Any]]:
        return [
            item
            for item in self.items
            if item["user_id"] == user_id and item["conversation_id"] == conversation_id
        ]


class FakeVectorStore:
    # Create a searchable fake store with a result label.
    def __init__(self, label: str) -> None:
        self.label = label
        self.queries: list[tuple[str, str, int]] = []

    # Record a query and return one labeled result.
    async def search(
        self, user_id: str, query: str, top_k: int
    ) -> list[dict[str, str]]:
        self.queries.append((user_id, query, top_k))
        return [{"content": self.label}]


class FakeSummaryStore(FakeVectorStore):
    # Create a fake summary store that records saved summaries.
    def __init__(self) -> None:
        super().__init__("summary")
        self.saved: list[dict[str, Any]] = []

    # Return the latest matching saved summary.
    async def latest(self, user_id: str, conversation_id: str) -> dict[str, Any] | None:
        matches = [
            item
            for item in self.saved
            if item["user_id"] == user_id and item["conversation_id"] == conversation_id
        ]
        return matches[-1] if matches else None

    # Record a summary query and return one result.
    async def search(
        self, user_id: str, query: str, top_k: int
    ) -> list[dict[str, str]]:
        self.queries.append((user_id, query, top_k))
        return [{"id": "search", "content": self.label}]

    # Save a summary in the fake store.
    async def save(
        self,
        user_id: str,
        conversation_id: str,
        content: str,
        through_turn_count: int,
        source_trace_id: str,
    ) -> dict[str, Any]:
        item = {
            "id": str(len(self.saved) + 1),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "content": content,
            "through_turn_count": through_turn_count,
            "source_trace_id": source_trace_id,
        }
        self.saved.append(item)
        return item


class FakeStores:
    # Assemble all fake stores used by the coordinator.
    def __init__(self) -> None:
        self.semantic_cache = FakeSemanticCache()
        self.working = FakeWorkingStore()
        self.entities = FakeVectorStore("entity")
        self.knowledge = FakeVectorStore("knowledge")
        self.summaries = FakeSummaryStore()
        self.procedures = FakeVectorStore("procedure")


class FakeToolbox:
    # Create a fake tool-descriptor search store.
    def __init__(self) -> None:
        self.queries: list[tuple[str, str, str | None, int]] = []

    # Record a tool search and return one descriptor.
    async def search_descriptors(
        self,
        user_id: str,
        query: str,
        server_id: str | None,
        top_k: int,
    ) -> list[dict[str, str]]:
        self.queries.append((user_id, query, server_id, top_k))
        return [{"tool_name": "calendar"}]


# Verify explicit query terms enable the intended memory store.
@pytest.mark.parametrize(
    ("query", "enabled"),
    [
        ("Do you remember what happened last time?", "use_episodic"),
        ("Who is the person on that project?", "use_entities"),
        ("What does my reference document say?", "use_knowledge"),
        ("Recap our earlier conversation", "use_summaries"),
        ("What workflow steps should I use?", "use_procedures"),
        ("Which calendar tool should I use?", "use_toolbox"),
    ],
)
def test_query_plan_routes_explicit_intent(query: str, enabled: str) -> None:
    plan = build_memory_query_plan(query)

    assert getattr(plan, enabled) is True
    assert plan.use_working is True
    assert plan.use_semantic is True


# Verify query plans are cached and only selected stores are searched.
@pytest.mark.asyncio
async def test_coordinator_caches_plan_and_queries_only_selected_stores() -> None:
    stores = FakeStores()
    toolbox = FakeToolbox()
    coordinator = MemoryCoordinatorAgent(
        cast(Any, stores),
        cast(Any, toolbox),
        cache_ttl=timedelta(minutes=5),
    )
    query = (
        "Remember and recap who is on the project, what the reference document "
        "says, which workflow steps and calendar tool to use."
    )

    first_plan = await coordinator.plan("ani.mallya", query)
    context = await coordinator.prepare_context(
        "ani.mallya",
        "11111111-1111-4111-8111-111111111111",
        query,
        "22222222-2222-4222-8222-222222222222",
        {"profile": {"name": "Ani"}},
        first_plan,
    )
    second_plan, cache_hit = await coordinator.plan("ani.mallya", query)

    assert first_plan[1] is False
    assert second_plan == first_plan[0]
    assert cache_hit is True
    assert context["memory_plan"]["semantic_cache_hit"] is False
    assert context["profile"] == {"name": "Ani"}
    assert context["working"][0]["memory_key"] == "memory_query_plan"
    assert context["entities"] == [{"content": "entity"}]
    assert context["knowledge"] == [{"content": "knowledge"}]
    assert context["summaries"] == [{"id": "search", "content": "summary"}]
    assert context["procedures"] == [{"content": "procedure"}]
    assert context["toolbox"] == [{"tool_name": "calendar"}]
    assert all(
        store.queries
        for store in (
            stores.entities,
            stores.knowledge,
            stores.summaries,
            stores.procedures,
        )
    )
    assert toolbox.queries
    assert stores.working.items[0]["expires_at"] > datetime.now(UTC)


# Verify completed turns update working memory and periodic summaries.
@pytest.mark.asyncio
async def test_completed_turn_updates_session_state_and_periodic_summary() -> None:
    stores = FakeStores()
    coordinator = MemoryCoordinatorAgent(
        cast(Any, stores),
        cast(Any, FakeToolbox()),
        summary_interval=2,
    )
    conversation_id = "44444444-4444-4444-8444-444444444444"

    await coordinator.record_completed_turn(
        "ani.mallya",
        conversation_id,
        "First question",
        "First answer",
        "55555555-5555-4555-8555-555555555555",
        [],
        1,
    )
    await coordinator.record_completed_turn(
        "ani.mallya",
        conversation_id,
        "Second question",
        "Second answer",
        "66666666-6666-4666-8666-666666666666",
        [{"query": "First question", "response": "First answer"}],
        2,
    )
    plan_result = await coordinator.plan("ani.mallya", "Hello")
    context = await coordinator.prepare_context(
        "ani.mallya",
        conversation_id,
        "Hello",
        "77777777-7777-4777-8777-777777777777",
        {},
        plan_result,
    )

    assert len(stores.summaries.saved) == 1
    assert stores.summaries.saved[0]["through_turn_count"] == 2
    assert "First question" in stores.summaries.saved[0]["content"]
    assert "Second answer" in stores.summaries.saved[0]["content"]
    assert context["summaries"][0]["through_turn_count"] == 2
    assert stores.working.items[0]["memory_key"] == "memory_query_plan"


class RecordingMemory(StubMemoryService):
    # Initialize retrieval call counters for the service test.
    def __init__(self) -> None:
        self.episodic_calls = 0
        self.semantic_calls = 0

    # Record an episodic retrieval and return a fixed result.
    async def get_episodic_memory(
        self, user_id: str, query: str
    ) -> list[dict[str, str]]:
        self.episodic_calls += 1
        return [{"content": "episodic result"}]

    # Record a semantic retrieval and return a fixed result.
    async def get_semantic_memory(
        self, user_id: str, query: str, top_k: int = 5
    ) -> list[dict[str, str]]:
        self.semantic_calls += 1
        return [{"content": "semantic result"}]


class SelectiveCoordinator:
    # Return a plan that enables only episodic retrieval.
    async def plan(self, user_id: str, query: str) -> tuple[MemoryQueryPlan, bool]:
        return (
            MemoryQueryPlan(use_episodic=True, use_semantic=False),
            False,
        )

    # Return the base context unchanged for this focused test.
    async def prepare_context(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        trace_id: str,
        base_context: dict[str, Any],
        plan_result: tuple[MemoryQueryPlan, bool] | None = None,
    ) -> dict[str, Any]:
        return base_context

    # Accept completed turns without adding test side effects.
    async def record_completed_turn(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        response: str,
        trace_id: str,
        prior_history: list[dict[str, Any]],
        turn_count: int,
    ) -> None:
        return None


class CapturingLLM(LLMClient):
    # Initialize captured prompt messages.
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    # Return a fixed non-streaming completion.
    def generate_text(self, prompt: str, max_tokens: int = 512) -> str:
        return "ok"

    # Return a fixed chat response.
    def chat(
        self, messages: list[dict[str, str]], max_tokens: int = 512
    ) -> dict[str, str]:
        return {"content": "ok"}

    # Capture streamed prompt messages and yield one response chunk.
    def stream_chat(
        self, messages: list[dict[str, str]], max_tokens: int = 512
    ) -> Iterator[str]:
        self.messages = messages
        yield "ok"


# Verify conversation retrieval follows the coordinator's selected stores.
@pytest.mark.asyncio
async def test_conversation_service_obeys_coordinator_retrieval_plan() -> None:
    memory = RecordingMemory()
    llm = CapturingLLM()
    service = ConversationService(
        memory=memory,
        llm=llm,
        repository=StubConversationRepository(),
        tracer=StubTracer(),
        memory_coordinator=cast(Any, SelectiveCoordinator()),
    )

    events = [
        event
        async for event in service.process_request(
            "ani.mallya",
            "Do you remember last time?",
            "33333333-3333-4333-8333-333333333333",
        )
    ]

    assert memory.episodic_calls == 1
    assert memory.semantic_calls == 0
    assert "episodic result" in llm.messages[0]["content"]
    assert [event["event"] for event in events] == ["start", "delta", "done"]
