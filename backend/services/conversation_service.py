import asyncio
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from anyio import CancelScope

from backend.agents.graph import build_assistant_graph
from backend.agents.state import AgentState
from backend.artifacts.diagram import is_diagram_request
from backend.artifacts.image_retrieval import ImageRetrievalPolicy
from backend.artifacts.image_routing import ImageRecallPolicy
from backend.core.egress import OutboundPrivacyPolicy
from backend.core.interfaces import (
    ArtifactEmbeddingStore,
    ConversationRepository,
    ConversationTracer,
    MemoryService,
    SearchProvider,
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
from backend.search.cascade import CascadingSearchRouter
from backend.services.diagram_artifact_service import DiagramArtifactService

logger = logging.getLogger(__name__)

# Snippet length shown beneath each cited source in the interface.
_SNIPPET_CHARS = 240

# Extracted page text arrives with Markdown headings, emphasis and list markers.
# A citation is displayed as plain prose, so the syntax is stripped rather than
# rendered: these snippets are untrusted third-party text and must never be
# interpreted as formatting.
_MARKDOWN_NOISE = re.compile(r"[#*_`>\[\]]+")


# Flatten extracted page text into one readable line for display.
def _plain_snippet(content: str) -> str:
    cleaned = _MARKDOWN_NOISE.sub(" ", content)
    return " ".join(cleaned.split())[:_SNIPPET_CHARS]


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
        search: SearchProvider | None = None,
        search_routing: CascadingSearchRouter | None = None,
        image_recall: ImageRecallPolicy | None = None,
        image_search: ArtifactEmbeddingStore | None = None,
        image_search_limit: int = 5,
        image_retrieval: ImageRetrievalPolicy | None = None,
        search_privacy: OutboundPrivacyPolicy | None = None,
    ):
        self.memory = memory
        self.assistant_graph = build_assistant_graph(llm)
        self.repository = repository
        self.tracer = tracer
        self.history_turn_limit = history_turn_limit
        self.memory_coordinator = memory_coordinator
        self.diagram_artifacts = diagram_artifacts
        self.search = search
        self.search_routing = search_routing
        self.image_recall = image_recall
        self.image_search = image_search
        self.image_search_limit = image_search_limit
        # Screening is not optional: a missing policy would mean raw queries
        # leaving the machine, so one is always constructed.
        self.search_privacy = search_privacy or OutboundPrivacyPolicy()
        self.image_retrieval = image_retrieval or ImageRetrievalPolicy(
            max_distance=0.96,
            min_margin=0.015,
        )

    # Find stored images whose pixels match the request, when the deterministic
    # policy says this turn is a recall. Image vectors share the text latent
    # space, so the query is embedded once by the ordinary text embedder.
    async def _load_image_matches(
        self,
        user_id: str,
        query: str,
        trace_id: str,
        query_embedding: list[float] | None,
    ) -> list[dict[str, Any]]:
        if self.image_recall is None or self.image_search is None:
            return []
        decision = self.image_recall.decide(query)
        if not decision.should_search:
            return []

        logger.info(
            "Trace %s routing to image search (reason=%s)", trace_id, decision.reason
        )
        try:
            vector = query_embedding or await self.memory.embed_query(query)
            # Over-fetch so the policy can inspect the runner up before filtering.
            ranked = await self.image_search.search_by_embedding(
                user_id,
                vector,
                max(self.image_search_limit, 2),
                ImageRetrievalPolicy.CANDIDATE_CEILING,
            )
            return self.image_retrieval.select(ranked)[: self.image_search_limit]
        except Exception:
            # A retrieval failure degrades the answer; it must not fail the turn.
            logger.warning("Trace %s image search failed", trace_id, exc_info=True)
            return []

    # Attach optional retrieved context in place, streaming progress so the
    # interface can show a search happening and cite what it used. Search runs
    # against a remote provider and is the slowest step, so it is announced
    # before it starts rather than reported only once it returns.
    async def _stream_retrieved_context(
        self,
        context: dict[str, Any],
        user_id: str,
        query: str,
        trace_id: str,
        query_embedding: list[float] | None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if await self._should_search(query, trace_id):
            screened = self.search_privacy.sanitize(query)
            if not screened.allowed:
                # Categories are logged, never the text that triggered them.
                logger.info(
                    "Trace %s blocked an outbound search (categories=%s)",
                    trace_id,
                    ",".join(screened.categories),
                )
                yield {
                    "event": "search_blocked",
                    "data": {"categories": list(screened.categories)},
                }
                search_results = []
            else:
                if screened.was_rewritten:
                    logger.info(
                        "Trace %s minimized an outbound search (categories=%s)",
                        trace_id,
                        ",".join(screened.categories),
                    )
                yield {
                    "event": "search_started",
                    "data": {
                        "query": screened.query,
                        "minimized": screened.was_rewritten,
                    },
                }
                search_results = await self._load_search_context(
                    screened.query, trace_id
                )
            if search_results:
                context["search"] = search_results
            # Sources are always reported, including an empty list, so the
            # interface can retract the indicator instead of leaving it running.
            yield {
                "event": "search_results",
                "data": {
                    "sources": [
                        {
                            "title": item["title"],
                            "url": item["url"],
                            # A short snippet lets the reader judge a source
                            # without opening it; the full text stays in the
                            # prompt rather than being shipped to the browser.
                            "snippet": _plain_snippet(item["content"]),
                        }
                        for item in search_results
                    ]
                },
            }

        image_matches = await self._load_image_matches(
            user_id,
            query,
            trace_id,
            query_embedding,
        )
        if image_matches:
            # Tell the model the images exist and are already shown, so it
            # describes them rather than claiming it cannot display images.
            context["images"] = [
                {
                    "kind": match.get("kind"),
                    "title": match.get("title"),
                    "created_at": match.get("created_at"),
                    "description": (match.get("metadata") or {}).get("analysis"),
                }
                for match in image_matches
            ]
            yield {"event": "image_matches", "data": {"artifacts": image_matches}}

    # Report whether this turn will search, without issuing the query. The
    # decision may consult a bounded classifier, so it is awaited once and the
    # result reused rather than recomputed for the provider call.
    async def _should_search(self, query: str, trace_id: str) -> bool:
        if self.search is None or self.search_routing is None:
            return False
        if not self.search.is_enabled():
            return False
        decision = await self.search_routing.decide(query)
        if decision.should_search:
            logger.info(
                "Trace %s routing to web search (reason=%s)",
                trace_id,
                decision.reason,
            )
        return decision.should_search

    # Fetch live results only when the deterministic policy asks for them.
    async def _load_search_context(
        self,
        query: str,
        trace_id: str,
    ) -> list[dict[str, Any]]:
        if self.search is None:
            return []
        try:
            found = await self.search.search(query)
        except Exception:
            # A search outage degrades the answer; it must not fail the turn.
            logger.warning("Trace %s web search failed", trace_id, exc_info=True)
            return []
        return [
            {"title": item.title, "url": item.url, "content": item.content}
            for item in found.results
        ]

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

        # Embed the query once and reuse the vector across every vector store.
        need_personal_semantic = plan is None or plan.use_semantic
        need_agent_vector = self.memory_coordinator is not None and (
            plan is None or plan.needs_vector()
        )
        query_embedding = None
        if need_personal_semantic or need_agent_vector:
            query_embedding = await self.memory.embed_query(query)

        profile = await self.memory.get_user_profile(user_id)
        episodic = (
            await self.memory.get_episodic_memory(user_id, query)
            if plan is None or plan.use_episodic
            else []
        )
        semantic = (
            await self.memory.get_semantic_memory(
                user_id, query, query_embedding=query_embedding
            )
            if need_personal_semantic
            else []
        )
        history = await self.repository.get_history(
            resolved_conversation_id,
            user_id,
            self.history_turn_limit,
        )

        # 2. Build Context and State
        context: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "profile": profile,
            "episodic": episodic,
            "semantic": semantic,
        }
        # The turn is announced before retrieval so the interface can show a
        # search running rather than sitting silent through the slowest step.
        yield {
            "event": "start",
            "data": {
                "trace_id": trace_id,
                "conversation_id": resolved_conversation_id,
            },
        }
        async for retrieval_event in self._stream_retrieved_context(
            context,
            user_id,
            query,
            trace_id,
            query_embedding,
        ):
            yield retrieval_event

        if self.memory_coordinator is not None:
            context = await self.memory_coordinator.prepare_context(
                user_id,
                resolved_conversation_id,
                query,
                trace_id,
                context,
                plan_result,
                query_embedding=query_embedding,
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
