import uuid
from typing import Any

from backend.core.interfaces import (
    ConversationRepository,
    ConversationTracer,
    MemoryService,
)


class StubMemoryService(MemoryService):
    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "preferences": {}}

    async def get_episodic_memory(
        self,
        user_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        return []

    async def get_semantic_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def embed_query(self, query: str) -> list[float]:
        return [0.0, 0.0, 0.0]

    # Below: the concrete auto-save methods a real memory service exposes but
    # the abstract interface above does not declare, needed so a
    # ConversationService under test can persist a classified proposal
    # immediately instead of raising AttributeError on this double.

    # Record a preferred-name save without a database.
    async def approve_preferred_name(
        self,
        user_id: str,
        name: str,
        source_conversation_id: str,
        source_trace_id: str,
        expires_at: Any = None,
    ) -> dict[str, Any]:
        return {"profile": {"user_id": user_id, "name": name}, "deduplicated": False}

    # Record a generic typed fact save without a database.
    async def approve_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        fact_key: str,
        value: str,
        purpose: str,
        source_conversation_id: str | None,
        source_trace_id: str,
        expires_at: Any,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "fact": {"fact_type": fact_type, "fact_key": fact_key, "value": value},
            "deduplicated": False,
        }

    # Record a batch discovery-interest save without a database.
    async def approve_discovery_interests(
        self,
        *,
        user_id: str,
        labels: list[str],
        source_conversation_id: str,
        source_trace_id: str,
    ) -> dict[str, Any]:
        return {"interests": list(labels)}

    # Record an episodic memory save without a database.
    async def save_episodic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: Any = None,
    ) -> dict[str, Any]:
        return {"content": content}

    # Record a semantic memory save without a database.
    async def save_semantic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: Any = None,
    ) -> dict[str, Any]:
        return {"content": content}


class StubConversationRepository(ConversationRepository):
    async def get_history(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return []

    async def save_turn(
        self,
        conversation_id: str,
        turn: dict[str, Any],
    ) -> None:
        return None

    # Report no persisted turns for tests that use this repository double.
    async def count_turns(self, conversation_id: str, user_id: str) -> int:
        return 0


class StubTracer(ConversationTracer):
    def start_trace(self, user_id: str) -> str:
        return str(uuid.uuid4())

    def log_step(
        self,
        trace_id: str,
        step_name: str,
        metadata: dict[str, Any],
    ) -> None:
        return None


class StubMainActionSelector:
    """Return one fixed action without a native tool-calling round trip.

    Routing itself - whether the main model decides to search - is the model's
    own native tool-call decision, tested in test_main_action_selector.py
    against a controlled LLM double and again in the functional suite against
    the real runtime. The tests that use this one are downstream of that
    decision: they exercise what the application does once told to search, or
    to show a picture, or to draw a diagram, so each states its action
    explicitly rather than relying on wording a pattern would happen to match.

    One copy, here. There were four identical ones - in test_chat_api.py,
    test_search_wiring.py, test_show_image.py and test_diagram_artifacts.py -
    and on 2026-08-29 adding a keyword argument to the real selector turned
    twenty tests red in four files at once, each needing the same edit. The
    signature below mirrors MainActionSelector.select; when that gains an
    argument, this is the one place that has to learn about it.
    """

    def __init__(self, action: Any) -> None:
        self.action = action
        # What it was last asked, so a test can assert on what the service
        # passed down without a second double.
        self.calls: list[dict[str, Any]] = []

    async def select(
        self,
        user_id: str,
        query: str,
        history: list[dict[str, Any]],
        active_image_artifact_id: str | None,
        query_embedding: list[float] | None = None,
        local_now: str | None = None,
        skills: list[dict[str, Any]] | None = None,
        unattended: bool = False,
        only: frozenset[str] | None = None,
        steps_taken: list[str] | None = None,
        zone: str = "",
    ) -> Any:
        self.calls.append({"user_id": user_id, "query": query, "zone": zone})
        return self.action
