import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from backend.agents.graph import build_assistant_graph
from backend.agents.state import AgentState
from backend.core.interfaces import (
    ConversationRepository,
    ConversationTracer,
    MemoryService,
)
from backend.core.llm import LLMClient
from backend.memory.proposals import propose_preferred_name
from backend.models.schemas import ChatStreamEvent

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        memory: MemoryService,
        llm: LLMClient,
        repository: ConversationRepository,
        tracer: ConversationTracer,
        history_turn_limit: int = 10,
    ):
        self.memory = memory
        self.assistant_graph = build_assistant_graph(llm)
        self.repository = repository
        self.tracer = tracer
        self.history_turn_limit = history_turn_limit

    async def process_request(
        self,
        user_id: str,
        query: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        trace_id = self.tracer.start_trace(user_id)
        resolved_conversation_id = conversation_id or str(uuid.uuid4())
        logger.info("Started conversation trace %s", trace_id)

        # 1. Load context components
        profile = await self.memory.get_user_profile(user_id)
        episodic = await self.memory.get_episodic_memory(user_id, query)
        semantic = await self.memory.get_semantic_memory(user_id, query)
        history = await self.repository.get_history(
            resolved_conversation_id,
            user_id,
            self.history_turn_limit,
        )

        # 2. Build Context and State
        context = {
            "user_id": user_id,
            "query": query,
            "profile": profile,
            "episodic": episodic,
            "semantic": semantic,
        }

        initial_state = AgentState(
            conversation_id=resolved_conversation_id,
            user_id=user_id,
            current_query=query,
            history=history,
            context_data=context,
            trace_id=trace_id,
        )

        # 3. Execute AssistantGraph
        self.tracer.log_step(trace_id, "graph_execution", {"status": "started"})
        response_chunks = []
        yield {
            "event": "start",
            "data": {
                "trace_id": trace_id,
                "conversation_id": initial_state.conversation_id,
            },
        }
        async for event in self.assistant_graph.astream(
            initial_state.model_dump(),
            stream_mode="custom",
        ):
            if event.get("type") == "message.delta":
                chunk = event["content"]
                response_chunks.append(chunk)
                yield {"event": "delta", "data": {"content": chunk}}
        self.tracer.log_step(trace_id, "graph_execution", {"status": "completed"})

        response_text = "".join(response_chunks)

        # 4. Persist conversation
        await self.repository.save_turn(
            initial_state.conversation_id,
            {
                "user_id": user_id,
                "query": query,
                "response": response_text,
                "metadata": metadata or {},
            },
        )
        preferred_name = propose_preferred_name(query)
        if preferred_name:
            yield {
                "event": "memory_proposal",
                "data": {
                    "kind": "preferred_name",
                    "value": preferred_name,
                    "conversation_id": initial_state.conversation_id,
                    "trace_id": trace_id,
                },
            }
        yield {"event": "done", "data": {}}
