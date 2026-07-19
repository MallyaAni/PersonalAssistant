import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from anyio import CancelScope

from backend.agents.graph import build_assistant_graph
from backend.agents.state import AgentState
from backend.artifacts.diagram import is_diagram_request
from backend.core.interfaces import (
    ConversationRepository,
    ConversationTracer,
    MemoryService,
)
from backend.core.llm import LLMClient
from backend.memory.coordinator import MemoryCoordinatorAgent
from backend.memory.proposals import (
    propose_entity,
    propose_knowledge,
    propose_preferred_name,
    propose_procedure,
    propose_response_style,
)
from backend.models.schemas import ChatStreamEvent
from backend.services.diagram_artifact_service import DiagramArtifactService

logger = logging.getLogger(__name__)


# Build at most one explicit, non-persisted memory proposal for a chat request.
def _memory_proposal(
    query: str,
    conversation_id: str,
    trace_id: str,
) -> dict[str, Any] | None:
    preferred_name = propose_preferred_name(query)
    if preferred_name:
        return {
            "kind": "preferred_name",
            "value": preferred_name,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
        }
    response_style = propose_response_style(query)
    if response_style:
        return {
            "kind": "response_style",
            "value": response_style,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
        }
    structured_proposals = (
        ("entity", propose_entity(query)),
        ("procedure", propose_procedure(query)),
        ("knowledge", propose_knowledge(query)),
    )
    for kind, value in structured_proposals:
        if value is not None:
            return {
                "kind": kind,
                **value,
                "conversation_id": conversation_id,
                "trace_id": trace_id,
            }
    return None


class ConversationService:
    # Assemble the conversation workflow from replaceable application boundaries.
    def __init__(
        self,
        memory: MemoryService,
        llm: LLMClient,
        repository: ConversationRepository,
        tracer: ConversationTracer,
        history_turn_limit: int = 10,
        memory_coordinator: MemoryCoordinatorAgent | None = None,
        diagram_artifacts: DiagramArtifactService | None = None,
    ):
        self.memory = memory
        self.assistant_graph = build_assistant_graph(llm)
        self.repository = repository
        self.tracer = tracer
        self.history_turn_limit = history_turn_limit
        self.memory_coordinator = memory_coordinator
        self.diagram_artifacts = diagram_artifacts

    # Stream either ordinary assistant text or an explicit diagram artifact request.
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

        if self.diagram_artifacts is not None and is_diagram_request(query):
            async for event in self._process_diagram_request(
                user_id,
                query,
                resolved_conversation_id,
                trace_id,
                metadata or {},
            ):
                yield event
            return

        # 1. Plan and load only the context components needed for this request.
        plan_result = None
        if self.memory_coordinator is not None:
            plan_result = await self.memory_coordinator.plan(user_id, query)
        plan = plan_result[0] if plan_result is not None else None
        profile = await self.memory.get_user_profile(user_id)
        episodic = (
            await self.memory.get_episodic_memory(user_id, query)
            if plan is None or plan.use_episodic
            else []
        )
        semantic = (
            await self.memory.get_semantic_memory(user_id, query)
            if plan is None or plan.use_semantic
            else []
        )
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
        if self.memory_coordinator is not None:
            context = await self.memory_coordinator.prepare_context(
                user_id,
                resolved_conversation_id,
                query,
                trace_id,
                context,
                plan_result,
            )

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
        await self._persist_completed_turn(
            user_id,
            initial_state.conversation_id,
            query,
            response_text,
            trace_id,
            history,
            metadata or {},
        )
        proposal = _memory_proposal(
            query,
            initial_state.conversation_id,
            trace_id,
        )
        if proposal is not None:
            yield {
                "event": "memory_proposal",
                "data": proposal,
            }
        yield {"event": "done", "data": {}}

    # Generate, persist, and stream one explicit diagram artifact lifecycle.
    async def _process_diagram_request(
        self,
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if self.diagram_artifacts is None:
            raise RuntimeError("Diagram artifact service is not configured")
        history = await self.repository.get_history(
            conversation_id,
            user_id,
            self.history_turn_limit,
        )
        yield {
            "event": "start",
            "data": {
                "trace_id": trace_id,
                "conversation_id": conversation_id,
            },
        }
        pending = await self.diagram_artifacts.begin(
            user_id,
            conversation_id,
            trace_id,
        )
        artifact_id = str(pending["id"])
        yield {
            "event": "artifact_started",
            "data": {
                "id": artifact_id,
                "kind": "diagram",
                "status": "pending",
            },
        }
        self.tracer.log_step(trace_id, "diagram_generation", {"status": "started"})

        try:
            artifact = await self.diagram_artifacts.complete(
                artifact_id,
                user_id,
                query,
            )
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await self.diagram_artifacts.fail(
                    artifact_id,
                    user_id,
                    error_code="cancelled",
                )
                self.tracer.log_step(
                    trace_id,
                    "diagram_generation",
                    {"status": "cancelled", "artifact_id": artifact_id},
                )
            raise
        except Exception:
            logger.exception("Diagram generation failed for trace %s", trace_id)
            await self.diagram_artifacts.fail(artifact_id, user_id)
            response_text = (
                "I couldn't create that diagram. Please revise the request "
                "and try again."
            )
            await self._persist_completed_turn(
                user_id,
                conversation_id,
                query,
                response_text,
                trace_id,
                history,
                {
                    **metadata,
                    "artifact_ids": [artifact_id],
                    "artifact_status": "failed",
                },
            )
            self.tracer.log_step(
                trace_id,
                "diagram_generation",
                {"status": "failed", "artifact_id": artifact_id},
            )
            yield {"event": "delta", "data": {"content": response_text}}
            yield {
                "event": "artifact_error",
                "data": {
                    "id": artifact_id,
                    "message": "Unable to create the diagram.",
                },
            }
            yield {"event": "done", "data": {}}
            return

        response_text = f"Created an editable diagram: {artifact['title']}."
        await self._persist_completed_turn(
            user_id,
            conversation_id,
            query,
            response_text,
            trace_id,
            history,
            {
                **metadata,
                "artifact_ids": [artifact_id],
                "artifact_status": "ready",
            },
        )
        self.tracer.log_step(
            trace_id,
            "diagram_generation",
            {"status": "completed", "artifact_id": artifact_id},
        )
        yield {"event": "delta", "data": {"content": response_text}}
        yield {"event": "artifact_ready", "data": artifact}
        yield {"event": "done", "data": {}}

    # Persist a completed turn and update automatic memory lifecycle state.
    async def _persist_completed_turn(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        response_text: str,
        trace_id: str,
        history: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        await self.repository.save_turn(
            conversation_id,
            {
                "user_id": user_id,
                "query": query,
                "response": response_text,
                "metadata": metadata,
            },
        )
        if self.memory_coordinator is None:
            return
        try:
            turn_count = await self.repository.count_turns(
                conversation_id,
                user_id,
            )
            await self.memory_coordinator.record_completed_turn(
                user_id,
                conversation_id,
                query,
                response_text,
                trace_id,
                history,
                turn_count,
            )
        except Exception:
            logger.exception(
                "Memory lifecycle update failed for trace %s",
                trace_id,
            )
