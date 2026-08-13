import asyncio
import logging
import re
import secrets
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import httpx
from anyio import CancelScope

from backend.agents.graph import build_assistant_graph
from backend.agents.state import AgentState
from backend.agents.vision.memory import VisualMemorySelector
from backend.artifacts.image_lineage import (
    collapse_duplicate_content,
    collapse_revision_chains,
)
from backend.artifacts.image_prompt_match import prefer_prompt_matches
from backend.artifacts.image_recall_router import CascadingImageRecallRouter
from backend.artifacts.image_retrieval import ImageRetrievalPolicy
from backend.artifacts.lineage import Lineage
from backend.artifacts.types import ImageGenerationRequest
from backend.core.egress import OutboundPrivacyPolicy
from backend.core.interfaces import (
    ArtifactEmbeddingStore,
    ArtifactLineageStore,
    BinaryArtifactRepository,
    ConversationRepository,
    ConversationTracer,
    MemoryService,
    SearchProvider,
)
from backend.core.llm import LLMClient
from backend.discovery.projection import locality_fact
from backend.discovery.service import DiscoveryProfileService
from backend.mcp.invocation import MCPInvocationError
from backend.memory.coordinator import MemoryCoordinatorAgent
from backend.memory.proposal_agent import MemoryProposalAgent
from backend.models.schemas import ChatStreamEvent
from backend.search.budgeted import SearchBudgetExceededError
from backend.search.query import normalize_search_query
from backend.services.agent_memory_manager import AgentMemoryManager
from backend.services.diagram_artifact_service import DiagramArtifactService
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.image_refinement_service import (
    ImageRefinementService,
    RefinementError,
)
from backend.services.image_style_service import ImageStyleService
from backend.services.main_action_selector import (
    CreateDiagramAction,
    DelegateAction,
    EditImageAction,
    GenerateImageAction,
    MainAction,
    MainActionSelector,
    SearchAction,
    ToolboxAction,
)
from backend.services.mcp_tool_orchestration_service import MCPToolOrchestrationService
from backend.services.presentation_job_service import PresentationJobService

logger = logging.getLogger(__name__)

# Snippet length shown beneath each cited source in the interface.
_SNIPPET_CHARS = 240
_IMAGE_DESCRIPTION_CHARS = 500

# Extracted page text arrives with Markdown headings, emphasis and list markers.
# A citation is displayed as plain prose, so the syntax is stripped rather than
# rendered: these snippets are untrusted third-party text and must never be
# interpreted as formatting.
_MARKDOWN_NOISE = re.compile(r"[#*_`>\[\]]+")


# Flatten extracted page text into one readable line for display.
def _plain_snippet(content: str) -> str:
    cleaned = _MARKDOWN_NOISE.sub(" ", content)
    return " ".join(cleaned.split())[:_SNIPPET_CHARS]


# Return the best bounded text provenance available for one stored image.
def _image_description(match: dict[str, Any]) -> str:
    metadata = match.get("metadata") or {}
    description = ""
    thread = metadata.get("analysis_thread")
    if isinstance(thread, list) and thread:
        first = thread[0]
        if (
            isinstance(first, dict)
            and str(first.get("prompt", "")).strip().casefold()
            == "describe this image."
        ):
            description = str(first.get("answer") or "")
    description = (
        description
        or metadata.get("analysis")
        or metadata.get("generation_prompt")
        or ""
    )
    return " ".join(str(description).split())[:_IMAGE_DESCRIPTION_CHARS]


# Describe the picture an edited one was made from, when recall collapsed it.
#
# Absent for an image that is nobody's revision, so an ordinary match is
# described exactly as it was before. `edited_from` is stated in the terms that
# matter to a reader — an uploaded original is the user's own picture, and the
# edits are listed oldest first so "the hat was replaced" is legible as history
# rather than as what the picture always showed.
def _image_lineage(lineage: Lineage | None) -> dict[str, Any]:
    if lineage is None:
        return {}
    described = str(lineage.origin.get("description") or "")
    rendered: dict[str, Any] = {
        "edited_from": {
            "supplied_by_user": lineage.supplied_by_user,
            "title": lineage.origin.get("title"),
            "description": described[:_IMAGE_DESCRIPTION_CHARS],
        }
    }
    if lineage.edits:
        rendered["edits_applied"] = list(lineage.edits)
    return rendered


# Describe an unobserved revision from its source plus explicit edit history.
def _effective_image_description(
    match: dict[str, Any],
    lineage: Lineage | None,
) -> str:
    description = _image_description(match)
    if description or lineage is None or not lineage.edits:
        return description
    edits = "; ".join(lineage.edits)
    return (
        f"The current image shows these completed edits: {edits}. All "
        "unmentioned visible details remain as recorded in edited_from.description."
    )[:_IMAGE_DESCRIPTION_CHARS]


# Name an unreachable provider specifically -- the same distinction the
# direct REST endpoints these actions replace already made. Read as an
# ordinary refusal instead, a downed ComfyUI process looked like a declined
# request rather than an outage nobody had started.
def _image_provider_failure_message(exc: BaseException, action: str) -> str:
    if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout):
        return (
            "The image generation backend (ComfyUI) isn't running. "
            "Start it and try again."
        )
    return f"I couldn't {action} that image. Please try again."


# Add matched-image context only after the user explicitly asks for web search.
def _image_aware_search_query(
    query: str,
    image_matches: list[dict[str, Any]],
) -> str:
    normalized = normalize_search_query(query)
    if not image_matches:
        return normalized
    description = _image_description(image_matches[0])
    if not description:
        return normalized
    subject = normalized.rstrip(" .?!")
    return f"{subject}. Referenced image description: {description}"



# Describe the pending save in one short line for the prompt. Only the value the
# user themselves stated is echoed, so nothing new is disclosed to the model.
def _proposal_summary(proposal: dict[str, Any]) -> str:
    labels = proposal.get("labels")
    if isinstance(labels, list):
        return ", ".join(str(label) for label in labels)[:200]
    for field in ("content", "value", "canonical_name", "name", "title", "label"):
        value = proposal.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


# Describe all pending profile saves so the assistant accurately explains consent.
def _proposal_summaries(proposals: tuple[dict[str, Any], ...]) -> str:
    summaries = filter(None, (_proposal_summary(item) for item in proposals))
    return "; ".join(summaries)[:400]


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
        image_recall: CascadingImageRecallRouter | None = None,
        image_search: ArtifactEmbeddingStore | None = None,
        image_artifacts: BinaryArtifactRepository | None = None,
        lineage: ArtifactLineageStore | None = None,
        image_search_limit: int = 5,
        image_retrieval: ImageRetrievalPolicy | None = None,
        search_privacy: OutboundPrivacyPolicy | None = None,
        tool_orchestration: MCPToolOrchestrationService | None = None,
        main_action_selector: MainActionSelector | None = None,
        image_generation: ImageArtifactService | None = None,
        image_style: ImageStyleService | None = None,
        image_refinement: ImageRefinementService | None = None,
        presentation_jobs: PresentationJobService | None = None,
        presentation_model: str | None = None,
        discovery_profile: DiscoveryProfileService | None = None,
        memory_proposals: MemoryProposalAgent | None = None,
        visual_memory: VisualMemorySelector | None = None,
        agent_memory: AgentMemoryManager | None = None,
    ):
        self.memory = memory
        self.assistant_graph = build_assistant_graph(llm)
        self.repository = repository
        self.tracer = tracer
        self.history_turn_limit = history_turn_limit
        self.memory_coordinator = memory_coordinator
        self.diagram_artifacts = diagram_artifacts
        self.search = search
        self.image_recall = image_recall
        self.image_search = image_search
        self.image_artifacts = image_artifacts
        self.lineage = lineage
        self.image_search_limit = image_search_limit
        # Screening is not optional: a missing policy would mean raw queries
        # leaving the machine, so one is always constructed.
        self.search_privacy = search_privacy or OutboundPrivacyPolicy()
        self.image_retrieval = image_retrieval or ImageRetrievalPolicy(
            # Deliberately loose, and not comparable to discovery's 0.08
            # novelty or 0.16 familiarity: those measure text embeddings,
            # these measure image embeddings, where genuine matches
            # observed in this space sit around 0.90-0.94. Tightening this
            # on the strength of the text numbers disables recall
            # outright, so any change needs the real distance
            # distribution measured first.
            max_distance=0.96,
            cluster_delta=0.006,
        )
        self.tool_orchestration = tool_orchestration
        self.main_action_selector = main_action_selector
        self.image_generation = image_generation
        self.image_style = image_style
        self.image_refinement = image_refinement
        self.presentation_jobs = presentation_jobs
        self.presentation_model = presentation_model
        self.discovery_profile = discovery_profile
        self.memory_proposals = memory_proposals
        self.visual_memory = visual_memory
        self.agent_memory = agent_memory
        # One saver per proposal kind, so persisting a batch is a lookup and a
        # call rather than a branch per kind - see `_persist_memory_proposals`.
        self._memory_proposal_savers: dict[
            str,
            Callable[[str, str, str, dict[str, Any]], Awaitable[bool]],
        ] = {
            "preferred_name": self._save_preferred_name_proposal,
            "response_style": self._save_response_style_proposal,
            "discovery_locality": self._save_discovery_locality_proposal,
            "discovery_interests": self._save_discovery_interests_proposal,
            "entity": self._save_entity_proposal,
            "procedure": self._save_procedure_proposal,
            "knowledge": self._save_knowledge_proposal,
            "semantic_fact": self._save_semantic_fact_proposal,
            "episodic": self._save_episodic_proposal,
        }

    # Ask the model that is about to answer this turn what it actually needs,
    # in one native tool call. Every candidate -- live search, a new or edited
    # picture, a diagram, or a specialist handoff -- is offered together, so
    # the choice (including choosing none of them) reflects the request as a
    # whole rather than several independent guesses that never saw each other.
    async def _select_main_action(
        self,
        user_id: str,
        query: str,
        history: list[dict[str, Any]],
        active_image_artifact_id: str | None,
    ) -> MainAction:
        if self.main_action_selector is None:
            return None
        try:
            return await self.main_action_selector.select(
                user_id,
                query,
                history,
                active_image_artifact_id,
            )
        except Exception:
            logger.warning("Main action selection failed", exc_info=True)
            return None

    # Queue a specialist presentation job and persist the delegated chat turn.
    async def _process_presentation_delegation(
        self,
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if self.presentation_jobs is None:
            raise RuntimeError("Presentation jobs are not configured")
        yield {
            "event": "agent_started",
            "data": {
                "agent_id": "presentation_agent",
                "agent_name": "PresentationAgent",
                "model": self.presentation_model,
            },
        }
        history = await self.repository.get_history(
            conversation_id,
            user_id,
            self.history_turn_limit,
        )
        try:
            job = await self.presentation_jobs.enqueue(
                user_id,
                conversation_id,
                trace_id,
                query,
            )
        except Exception:
            logger.exception(
                "Presentation delegation failed for trace %s",
                trace_id,
            )
            response_text = (
                "I couldn't queue the presentation. No background job was started."
            )
            await self._persist_completed_turn(
                user_id,
                conversation_id,
                query,
                response_text,
                trace_id,
                history,
                {**metadata, "delegated_agent": "presentation_agent"},
            )
            yield {
                "event": "agent_finished",
                "data": {
                    "agent_id": "presentation_agent",
                    "agent_name": "PresentationAgent",
                    "model": self.presentation_model,
                    "status": "failed",
                    "message": "The presentation job could not be queued.",
                },
            }
            yield {"event": "delta", "data": {"content": response_text}}
            yield {"event": "done", "data": {}}
            return
        job_id = str(job["id"])
        yield {
            "event": "agent_finished",
            "data": {
                "agent_id": "presentation_agent",
                "agent_name": "PresentationAgent",
                "model": self.presentation_model,
                "job_id": job_id,
                "status": "queued",
                "message": "Presentation job queued in the background.",
            },
        }
        response_text = (
            "PresentationAgent is creating your editable deck in the background. "
            f"You can follow job `{job_id}` in Presentations while we keep chatting."
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
                "delegated_agent": "presentation_agent",
                "presentation_job_id": job_id,
            },
        )
        yield {"event": "delta", "data": {"content": response_text}}
        yield {"event": "done", "data": {}}

    # Yield `artifact_started` the moment a slow operation's pending row exists,
    # rather than only once the whole thing finishes, so the interface shows the
    # same live "generating" state a diagram gets. At most one event is yielded;
    # the caller still awaits `operation` itself for the final result or error.
    async def _stream_pending_started(
        self,
        operation: "asyncio.Task[dict[str, Any]]",
        pending: dict[str, Any],
        ready: asyncio.Event,
        kind: str,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        ready_wait = asyncio.ensure_future(ready.wait())
        done, _pending_futures = await asyncio.wait(
            {operation, ready_wait}, return_when=asyncio.FIRST_COMPLETED
        )
        if ready_wait in done:
            yield {
                "event": "artifact_started",
                "data": {"id": pending["id"], "kind": kind, "status": "pending"},
            }
        else:
            ready_wait.cancel()

    # Generate one image the main model chose to create, streaming the same
    # artifact lifecycle a diagram uses, and persist the turn so this exchange
    # remains visible to memory and future context -- unlike the direct REST
    # path this replaces for chat, which never touched conversation history.
    async def _process_image_generation(
        self,
        user_id: str,
        query: str,
        prompt: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if self.image_generation is None:
            raise RuntimeError("Image generation is not configured")
        learned_style = (
            await self.image_style.get_style(user_id)
            if self.image_style is not None
            else ""
        )
        pending: dict[str, Any] = {}
        ready = asyncio.Event()

        async def _on_pending(artifact: dict[str, Any]) -> None:
            pending["id"] = str(artifact["id"])
            ready.set()

        task: asyncio.Task[dict[str, Any]] = asyncio.create_task(
            self.image_generation.generate(
                user_id=user_id,
                conversation_id=conversation_id,
                trace_id=trace_id,
                request=ImageGenerationRequest(
                    prompt=prompt,
                    width=2048,
                    height=2048,
                    seed=secrets.randbelow(2**63),
                ),
                extra_style=learned_style,
                on_pending=_on_pending,
            )
        )
        async for event in self._stream_pending_started(
            task, pending, ready, "generated_image"
        ):
            yield event

        try:
            artifact = await task
        except Exception as exc:
            logger.exception(
                "Chat-initiated image generation failed for trace %s", trace_id
            )
            response_text = _image_provider_failure_message(exc, "generate")
            await self._persist_completed_turn(
                user_id,
                conversation_id,
                query,
                response_text,
                trace_id,
                history,
                {
                    **metadata,
                    "artifact_ids": [pending["id"]] if pending else [],
                    "artifact_status": "failed",
                },
            )
            yield {"event": "delta", "data": {"content": response_text}}
            if pending.get("id"):
                yield {
                    "event": "artifact_error",
                    "data": {"id": pending["id"], "message": response_text},
                }
            yield {"event": "done", "data": {}}
            return

        response_text = "Here's the image you asked for."
        await self._persist_completed_turn(
            user_id,
            conversation_id,
            query,
            response_text,
            trace_id,
            history,
            {**metadata, "artifact_ids": [str(artifact["id"])]},
        )
        yield {"event": "delta", "data": {"content": response_text}}
        yield {"event": "artifact_ready", "data": artifact}
        yield {"event": "done", "data": {}}

    # Edit the picture currently in view as the main model chose to, streaming
    # the same artifact lifecycle a diagram uses and persisting the turn -- the
    # gap this closes is exactly the one reported: an edit request that changed
    # a picture but left no reply and no trace in conversation history.
    async def _process_image_edit(
        self,
        user_id: str,
        query: str,
        artifact_id: str,
        instruction: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if self.image_refinement is None:
            raise RuntimeError("Image refinement is not configured")
        pending: dict[str, Any] = {}
        ready = asyncio.Event()

        async def _on_pending(artifact: dict[str, Any]) -> None:
            pending["id"] = str(artifact["id"])
            ready.set()

        task: asyncio.Task[dict[str, Any]] = asyncio.create_task(
            self.image_refinement.refine(
                user_id=user_id,
                artifact_id=artifact_id,
                feedback=instruction,
                conversation_id=conversation_id,
                trace_id=trace_id,
                on_pending=_on_pending,
            )
        )
        async for event in self._stream_pending_started(
            task, pending, ready, "generated_image"
        ):
            yield event

        try:
            artifact = await task
        except RefinementError as exc:
            response_text = str(exc)
            await self._persist_completed_turn(
                user_id,
                conversation_id,
                query,
                response_text,
                trace_id,
                history,
                metadata,
            )
            yield {"event": "delta", "data": {"content": response_text}}
            yield {"event": "done", "data": {}}
            return
        except Exception as exc:
            logger.exception(
                "Chat-initiated image edit failed for trace %s", trace_id
            )
            response_text = _image_provider_failure_message(exc, "edit")
            await self._persist_completed_turn(
                user_id,
                conversation_id,
                query,
                response_text,
                trace_id,
                history,
                {
                    **metadata,
                    "artifact_ids": [pending["id"]] if pending else [],
                    "artifact_status": "failed",
                },
            )
            yield {"event": "delta", "data": {"content": response_text}}
            if pending.get("id"):
                yield {
                    "event": "artifact_error",
                    "data": {"id": pending["id"], "message": response_text},
                }
            yield {"event": "done", "data": {}}
            return

        response_text = "Here's the edited image."
        await self._persist_completed_turn(
            user_id,
            conversation_id,
            query,
            response_text,
            trace_id,
            history,
            {**metadata, "artifact_ids": [str(artifact["id"])]},
        )
        yield {"event": "delta", "data": {"content": response_text}}
        yield {"event": "artifact_ready", "data": artifact}
        yield {"event": "done", "data": {}}

    # Route an edit-image decision to the real edit, or explain that nothing
    # is in view to apply it to - a check only the application can make, since
    # the model that chose this action has no way to know whether the
    # interface actually has a picture selected.
    async def _dispatch_edit_image_action(
        self,
        user_id: str,
        query: str,
        action: EditImageAction,
        active_image_artifact_id: str | None,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if active_image_artifact_id is not None:
            async for event in self._process_image_edit(
                user_id,
                query,
                active_image_artifact_id,
                action.instruction,
                conversation_id,
                trace_id,
                metadata,
                history,
            ):
                yield event
            return
        async for event in self._process_missing_edit_target(
            user_id, query, conversation_id, trace_id, metadata, history
        ):
            yield event

    # Tell the user plainly that an edit has nothing to apply to, rather than
    # answering the message as if it never mentioned a picture at all.
    async def _process_missing_edit_target(
        self,
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        response_text = (
            "I don't see a picture in view to edit. Select the one you want "
            'changed - click "Ask or edit" on it, or ask me to show it again '
            "- and I'll make the change from there."
        )
        await self._persist_completed_turn(
            user_id,
            conversation_id,
            query,
            response_text,
            trace_id,
            history,
            metadata,
        )
        yield {"event": "delta", "data": {"content": response_text}}
        yield {"event": "done", "data": {}}

    # Select and execute at most one safe MCP tool while streaming its lifecycle.
    async def _stream_tool_context(
        self,
        context: dict[str, Any],
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        action: MainAction,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if self.tool_orchestration is None or not isinstance(action, ToolboxAction):
            return
        plan = action.plan

        yield {
            "event": "tool_started",
            "data": {
                "server_id": plan.server_id,
                "tool_name": plan.tool_name,
            },
        }
        try:
            result = await self.tool_orchestration.execute(
                plan,
                request_context={
                    "anios_user_id": user_id,
                    "anios_conversation_id": conversation_id,
                    "anios_trace_id": trace_id,
                },
            )
        except MCPInvocationError as exc:
            logger.warning(
                "Trace %s MCP call %s/%s was refused (%s)",
                trace_id,
                plan.server_id,
                plan.tool_name,
                exc.reason,
            )
            refused = exc.reason.endswith("required") or (
                exc.reason == "argument_withheld"
            )
            status = "refused" if refused else "failed"
            message = (
                "Tool call was withheld by AniOS privacy or approval controls."
                if status == "refused"
                else "The tool could not complete its request."
            )
            context.setdefault("tool_notices", []).append(
                {
                    "server_id": plan.server_id,
                    "tool_name": plan.tool_name,
                    "status": status,
                    "message": message,
                }
            )
            yield {
                "event": "tool_finished",
                "data": {
                    "server_id": plan.server_id,
                    "tool_name": plan.tool_name,
                    "status": status,
                    "message": message,
                },
            }
            return
        except Exception:
            logger.warning(
                "Trace %s MCP call %s/%s failed",
                trace_id,
                plan.server_id,
                plan.tool_name,
                exc_info=True,
            )
            context.setdefault("tool_notices", []).append(
                {
                    "server_id": plan.server_id,
                    "tool_name": plan.tool_name,
                    "status": "failed",
                    "message": "The tool could not complete its request.",
                }
            )
            yield {
                "event": "tool_finished",
                "data": {
                    "server_id": plan.server_id,
                    "tool_name": plan.tool_name,
                    "status": "failed",
                    "message": "The tool could not complete its request.",
                },
            }
            return

        status = "failed" if result.is_error else "succeeded"
        context.setdefault("tool_results", []).append(
            {
                "server_id": result.server_id,
                "tool_name": result.tool_name,
                "content": result.content,
                "status": status,
                "warning_markers": list(result.markers),
            }
        )
        yield {
            "event": "tool_finished",
            "data": {
                "server_id": result.server_id,
                "tool_name": result.tool_name,
                "status": status,
                "message": (
                    "Tool completed."
                    if status == "succeeded"
                    else "The tool returned an error."
                ),
            },
        }

    # Stream every optional retrieval and tool event into one prompt context.
    async def _stream_optional_context(
        self,
        context: dict[str, Any],
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        query_embedding: list[float] | None,
        action: MainAction,
        active_image_artifact_id: str | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        async for event in self._stream_retrieved_context(
            context,
            user_id,
            query,
            trace_id,
            query_embedding,
            action,
            active_image_artifact_id,
        ):
            yield event
        async for event in self._stream_tool_context(
            context,
            user_id,
            query,
            conversation_id,
            trace_id,
            action,
        ):
            yield event

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
        decision = await self.image_recall.decide(query)
        if not decision.should_search:
            return []

        logger.info(
            "Trace %s routing to image search (reason=%s)", trace_id, decision.reason
        )
        try:
            vector = query_embedding or await self.memory.embed_query(query)
            # Over-fetch so the leading cluster is measured against true nearest
            # hits, then let a distinctive named subject in the query (a brand,
            # for example) narrow the candidates by their generation prompt, since
            # the visual embedding alone clusters every car as just "a car".
            ranked = await self.image_search.search_by_embedding(
                user_id,
                vector,
                max(self.image_search_limit, 2),
                ImageRetrievalPolicy.CANDIDATE_CEILING,
            )
            # Presentation slide images belong to their deck, not general image
            # recall, so they never surface as a chat image match.
            ranked = [
                hit
                for hit in ranked
                if not (hit.get("metadata") or {}).get("presentation_id")
            ]
            # Collapse refinement chains so an image and its revisions are not all
            # returned; only the latest revision of each lineage remains.
            ranked = collapse_revision_chains(ranked)
            # The same file uploaded more than once (observed: re-uploading the
            # same photo across separate conversations while testing) is not
            # a revision chain - each row is independent - but it is still one
            # picture, not several, so an exact-content duplicate collapses too.
            ranked = collapse_duplicate_content(ranked)
            ranked = prefer_prompt_matches(query, ranked)
            return self.image_retrieval.select(ranked)[: self.image_search_limit]
        except Exception:
            # A retrieval failure degrades the answer; it must not fail the turn.
            logger.warning("Trace %s image search failed", trace_id, exc_info=True)
            return []

    # What each match was derived from, keyed by artifact id.
    #
    # One query for the whole page of results, and it asks the parent edge
    # rather than the result set — so an edited photograph says it is a
    # photograph whether or not the original was itself retrieved. A failure
    # here costs provenance, never the answer.
    #
    # Deliberately returned beside the matches rather than merged into them.
    # Merged, it rode along into the `image_matches` event, which is serialized
    # to the browser as JSON — and a dataclass is not JSON, so every chat turn
    # that recalled an image died in the encoder. The interface displays these
    # artifacts; provenance is for the prompt, and the two do not travel
    # together.
    async def _resolve_lineage(
        self,
        user_id: str,
        matches: list[dict[str, Any]],
    ) -> dict[str, Lineage]:
        if self.lineage is None or not matches:
            return {}
        try:
            return await self.lineage.resolve_lineage(
                user_id,
                [str(match.get("id")) for match in matches],
            )
        except Exception:
            logger.warning("Image lineage lookup failed", exc_info=True)
            return {}

    # Resolve an explicitly active image only when it is ready and owned by the caller.
    async def _load_active_image(
        self,
        user_id: str,
        artifact_id: str | None,
    ) -> dict[str, Any] | None:
        repository = getattr(self, "image_artifacts", None)
        if repository is None or artifact_id is None:
            return None
        try:
            artifact = await repository.get_owned(user_id, artifact_id)
        except Exception:
            logger.warning("Active image lookup failed", exc_info=True)
            return None
        if artifact is None or artifact.get("status") != "ready":
            return None
        if artifact.get("kind") not in {"generated_image", "uploaded_image"}:
            return None
        return artifact

    # Semantically select older owned image memories when no image is active.
    async def _load_visual_memory_matches(
        self,
        user_id: str,
        query: str,
        query_embedding: list[float] | None,
    ) -> list[dict[str, Any]]:
        selector = getattr(self, "visual_memory", None)
        repository = getattr(self, "image_artifacts", None)
        memory = getattr(self, "memory", None)
        candidate_loader = getattr(memory, "get_visual_memory_candidates", None)
        if selector is None or repository is None or candidate_loader is None:
            return []
        try:
            vector = query_embedding or await memory.embed_query(query)
            candidates = await candidate_loader(user_id, vector)
            artifact_ids = await selector.select(query, candidates)
            matches = []
            for artifact_id in artifact_ids:
                artifact = await repository.get_owned(user_id, artifact_id)
                if (
                    artifact is not None
                    and artifact.get("status") == "ready"
                    and artifact.get("kind") in {"generated_image", "uploaded_image"}
                ):
                    matches.append(artifact)
            # The same file uploaded more than once selects as several distinct
            # candidates - each is a real, independent row - but showing every
            # copy is the same picture repeated, not several relevant ones.
            return collapse_duplicate_content(matches)
        except Exception:
            logger.warning("Visual-memory recall failed", exc_info=True)
            return []

    # Convert one stored image and its optional lineage into bounded prompt context.
    def _image_context_item(
        self,
        match: dict[str, Any],
        lineage: Lineage | None,
    ) -> dict[str, Any]:
        return {
            "kind": match.get("kind"),
            "title": match.get("title"),
            "created_at": match.get("created_at"),
            "description": _effective_image_description(match, lineage),
            "generation_prompt": (match.get("metadata") or {}).get("generation_prompt"),
            **_image_lineage(lineage),
        }

    # Put the explicitly active image first without duplicating a recalled match.
    def _prompt_images(
        self,
        active_image: dict[str, Any] | None,
        image_matches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prompt_images = list(image_matches)
        if active_image is None:
            return prompt_images
        if any(
            str(match.get("id")) == str(active_image.get("id"))
            for match in prompt_images
        ):
            return prompt_images
        return [active_image, *prompt_images]

    # Attach optional image and search context in place, streaming progress so
    # the interface can show retrieval and cite what it used.
    async def _stream_retrieved_context(
        self,
        context: dict[str, Any],
        user_id: str,
        query: str,
        trace_id: str,
        query_embedding: list[float] | None,
        action: MainAction,
        active_image_artifact_id: str | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        active_image = await self._load_active_image(
            user_id,
            active_image_artifact_id,
        )
        image_matches = await self._load_image_matches(
            user_id,
            query,
            trace_id,
            query_embedding,
        )
        if active_image is None and not image_matches:
            image_matches = await self._load_visual_memory_matches(
                user_id,
                query,
                query_embedding,
            )
        prompt_images = self._prompt_images(active_image, image_matches)
        if prompt_images:
            lineages = await self._resolve_lineage(user_id, prompt_images)
            # Tell the model the images exist and are already shown, so it
            # describes them rather than claiming it cannot display images.
            context["images"] = [
                {
                    "kind": match.get("kind"),
                    "title": match.get("title"),
                    "created_at": match.get("created_at"),
                    "description": _effective_image_description(
                        match,
                        lineages.get(str(match.get("id"))),
                    ),
                    "generation_prompt": (match.get("metadata") or {}).get(
                        "generation_prompt"
                    ),
                    # Where an edited picture came from. Without it a photograph
                    # the user supplied, once edited, reads as something the
                    # assistant invented — and what the original showed is lost
                    # even though it is the thing being asked about.
                    **_image_lineage(lineages.get(str(match.get("id")))),
                }
                for match in prompt_images
            ]
        if image_matches:
            yield {"event": "image_matches", "data": {"artifacts": image_matches}}

        if (
            isinstance(action, SearchAction)
            and self.search is not None
            and self.search.is_enabled()
        ):
            logger.info("Trace %s routing to web search (reason=tool_call)", trace_id)
            search_results: list[dict[str, Any]]
            outbound_query = _image_aware_search_query(action.query, image_matches)
            screened = self.search_privacy.sanitize(outbound_query)
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
                tool_identity = getattr(self.search, "tool_identity", None)
                if tool_identity:
                    yield {
                        "event": "tool_started",
                        "data": {
                            "server_id": tool_identity[0],
                            "tool_name": tool_identity[1],
                        },
                    }
                search_results, search_succeeded = await self._load_search_context(
                    screened.query, trace_id, action.max_results
                )
                if tool_identity:
                    yield {
                        "event": "tool_finished",
                        "data": {
                            "server_id": tool_identity[0],
                            "tool_name": tool_identity[1],
                            "status": ("succeeded" if search_succeeded else "failed"),
                            "message": (
                                "Tool completed."
                                if search_succeeded
                                else "The tool could not complete its request."
                            ),
                        },
                    }
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
                            **(
                                {"provider": item["provider"]}
                                if item.get("provider")
                                else {}
                            ),
                            # A short snippet lets the reader judge a source
                            # without opening it; the full text stays in the
                            # prompt rather than being shipped to the browser.
                            "snippet": _plain_snippet(item["content"]),
                        }
                        for item in search_results
                    ]
                },
            }

    # Fetch live results for the query the model chose when it called search_web.
    async def _load_search_context(
        self,
        query: str,
        trace_id: str,
        max_results: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        if self.search is None:
            return [], False
        try:
            found = await self.search.search(query, max_results=max_results)
        except SearchBudgetExceededError as exhausted:
            # Distinct from an outage: nothing is broken and retrying will not
            # help. Returning silently would read as "the internet had nothing",
            # which is the failure that makes a quota impossible to diagnose, so
            # the limit is stated as context for the model to relay.
            logger.info(
                "Trace %s web search budget exhausted for %s",
                trace_id,
                exhausted.window,
            )
            return (
                [
                    {
                        "title": "Internet search limit reached",
                        "url": "",
                        "content": (
                            f"This account has used its internet search "
                            f"allowance for {exhausted.window}. Searching "
                            f"resumes at "
                            f"{exhausted.resets_at.strftime('%Y-%m-%d %H:%M UTC')}. "
                            "Answer from what you already know and say plainly "
                            "that you could not search."
                        ),
                    }
                ],
                False,
            )
        except Exception:
            # A search outage degrades the answer; it must not fail the turn.
            logger.warning("Trace %s web search failed", trace_id, exc_info=True)
            return [], False
        return (
            [
                {
                    "title": item.title,
                    "url": item.url,
                    "content": item.content,
                    **({"provider": item.provider} if item.provider else {}),
                }
                for item in found.results
            ],
            True,
        )

    # Stream either ordinary assistant text or an explicit diagram artifact request.
    async def process_request(
        self,
        user_id: str,
        query: str,
        conversation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        active_image_artifact_id: str | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        trace_id = self.tracer.start_trace(user_id)
        resolved_conversation_id = conversation_id or str(uuid.uuid4())
        logger.info("Started conversation trace %s", trace_id)

        yield {
            "event": "start",
            "data": {
                "trace_id": trace_id,
                "conversation_id": resolved_conversation_id,
            },
        }

        # One native tool-calling decision covers every candidate action for
        # this turn. Recent history lets it recognize context (a location, an
        # earlier answer) already given, rather than re-asking for it.
        history = await self.repository.get_history(
            resolved_conversation_id,
            user_id,
            self.history_turn_limit,
        )
        action = await self._select_main_action(
            user_id, query, history, active_image_artifact_id
        )

        if (
            isinstance(action, CreateDiagramAction)
            and self.diagram_artifacts is not None
        ):
            async for event in self._process_diagram_request(
                user_id,
                query,
                resolved_conversation_id,
                trace_id,
                metadata or {},
            ):
                yield event
            return

        if (
            isinstance(action, DelegateAction)
            and action.capability_id == "presentation_agent"
            and self.presentation_jobs is not None
        ):
            async for event in self._process_presentation_delegation(
                user_id,
                query,
                resolved_conversation_id,
                trace_id,
                metadata or {},
            ):
                yield event
            return

        if (
            isinstance(action, GenerateImageAction)
            and self.image_generation is not None
        ):
            async for event in self._process_image_generation(
                user_id,
                query,
                action.prompt,
                resolved_conversation_id,
                trace_id,
                metadata or {},
                history,
            ):
                yield event
            return

        if isinstance(action, EditImageAction) and self.image_refinement is not None:
            async for event in self._dispatch_edit_image_action(
                user_id,
                query,
                action,
                active_image_artifact_id,
                resolved_conversation_id,
                trace_id,
                metadata or {},
                history,
            ):
                yield event
            return

        async for event in self._process_assistant_request(
            user_id,
            query,
            resolved_conversation_id,
            trace_id,
            metadata or {},
            active_image_artifact_id,
            preselected_action=action,
        ):
            yield event

    # The interests this person already follows, or nothing when the profile
    # cannot be read. A missing catalogue costs deduplication, never the turn.
    async def _known_interests(self, user_id: str) -> tuple[str, ...]:
        if self.discovery_profile is None:
            return ()
        try:
            profile = await self.discovery_profile.get_profile(user_id)
        except Exception:
            return ()
        return tuple(interest.label for interest in profile.interests)

    # Ask the focused local model for typed memory without blocking the chat turn.
    async def _classify_memory_proposals(
        self,
        query: str,
        trace_id: str,
        user_id: str,
    ) -> tuple[dict[str, Any], ...]:
        if self.memory_proposals is None:
            return ()
        try:
            result = await self.memory_proposals.propose(
                query, await self._known_interests(user_id)
            )
            return result.proposals
        except Exception:
            logger.warning(
                "Semantic memory proposal classification failed for trace %s",
                trace_id,
                exc_info=True,
            )
            return ()

    # Save a classified name preference immediately - no approval round-trip.
    async def _save_preferred_name_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        await self.memory.approve_preferred_name(
            user_id, candidate["value"], conversation_id, trace_id
        )
        return True

    # Save a classified reply-length preference immediately.
    async def _save_response_style_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        await self.memory.approve_fact(
            user_id=user_id,
            fact_type="profile",
            fact_key="response_style",
            value=candidate["value"],
            purpose="personalization",
            source_conversation_id=conversation_id,
            source_trace_id=trace_id,
            expires_at=None,
            metadata={"source": "chat_auto_save"},
        )
        return True

    # Save a classified home locality immediately, projected the same way an
    # approved one always was.
    async def _save_discovery_locality_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        fact = locality_fact(candidate["label"], candidate.get("region"))
        await self.memory.approve_fact(
            user_id=user_id,
            fact_type=fact.fact_type,
            fact_key=fact.fact_key,
            value=fact.value,
            purpose=fact.purpose,
            source_conversation_id=conversation_id,
            source_trace_id=trace_id,
            expires_at=None,
            metadata={"source": "chat_auto_save"},
        )
        return True

    # Save every classified Scout interest label in one projection.
    async def _save_discovery_interests_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        await self.memory.approve_discovery_interests(
            user_id=user_id,
            labels=candidate["labels"],
            source_conversation_id=conversation_id,
            source_trace_id=trace_id,
        )
        return True

    # Save a classified person/organization relationship, when agent memory is wired.
    async def _save_entity_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        if self.agent_memory is None:
            return False
        await self.agent_memory.entities.upsert(
            user_id,
            candidate["entity_type"],
            candidate["canonical_name"],
            candidate.get("attributes") or {},
            conversation_id,
            trace_id,
            None,
        )
        return True

    # Save a classified reusable workflow, when agent memory is wired.
    async def _save_procedure_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        if self.agent_memory is None:
            return False
        await self.agent_memory.procedures.approve(
            user_id,
            candidate["name"],
            candidate["description"],
            candidate["steps"],
            conversation_id,
            trace_id,
            None,
            {},
        )
        return True

    # Save a classified titled reference document, when agent memory is wired.
    async def _save_knowledge_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        if self.agent_memory is None:
            return False
        await self.agent_memory.knowledge.ingest(
            user_id,
            candidate["title"],
            candidate["content"],
            None,
            "user_knowledge",
            conversation_id,
            trace_id,
        )
        return True

    # Save a classified stable personal fact as a semantic memory.
    async def _save_semantic_fact_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        await self.memory.save_semantic_memory(
            user_id, candidate["content"], {"source": "chat_auto_save"}
        )
        return True

    # Save a classified one-off event as an episodic memory.
    async def _save_episodic_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        await self.memory.save_episodic_memory(
            user_id, candidate["content"], {"source": "chat_auto_save"}
        )
        return True

    # Persist every classified proposal immediately - this app's memory design
    # is blanket auto-save with no approval round-trip. Asking the user to
    # confirm the same small facts turn after turn earns no accuracy and costs
    # real friction; what a small local classifier extracts from something the
    # user just said is treated as said, not as a guess awaiting sign-off.
    # What ships instead of a gate is visibility: the caller still emits one
    # event per record actually written, so every save is visible and can be
    # audited or deleted, same as any other memory record. A single bad
    # candidate is dropped rather than raised, so it costs one save, never the
    # turn's answer or every other save alongside it.
    async def _persist_memory_proposals(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidates: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        saved: list[dict[str, Any]] = []
        for candidate in candidates:
            kind = candidate.get("kind")
            saver = self._memory_proposal_savers.get(str(kind))
            if saver is None:
                continue
            try:
                persisted = await saver(user_id, conversation_id, trace_id, candidate)
            except Exception:
                logger.warning(
                    "Trace %s failed to auto-save a %s memory proposal",
                    trace_id,
                    kind,
                    exc_info=True,
                )
                continue
            if persisted:
                saved.append(
                    {
                        **candidate,
                        "conversation_id": conversation_id,
                        "trace_id": trace_id,
                    }
                )
        return tuple(saved)

    # Retrieve context, run the primary response model, and persist one turn.
    async def _process_assistant_request(
        self,
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
        active_image_artifact_id: str | None = None,
        preselected_action: MainAction = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
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
            conversation_id,
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
        # Scout's profile is deliberately not added here. It was, on the
        # reasoning that an ordinary turn may as well know what the user likes
        # — but a standing list of interests with strengths in every prompt is
        # a thumb on the scale for all of them. Unrelated questions came back
        # bent toward hiking because hiking was sitting in the context.
        #
        # What the assistant should know about someone belongs in memory, which
        # is retrieved per question and only when it is relevant. Scout's
        # profile exists to steer a scheduled sweep, not conversation.
        async for retrieval_event in self._stream_optional_context(
            context,
            user_id,
            query,
            conversation_id,
            trace_id,
            query_embedding,
            preselected_action,
            active_image_artifact_id,
        ):
            yield retrieval_event

        if self.memory_coordinator is not None:
            context = await self.memory_coordinator.prepare_context(
                user_id,
                conversation_id,
                query,
                trace_id,
                context,
                plan_result,
                query_embedding=query_embedding,
            )

        # Decided and persisted before the answer is generated, not after, so
        # the model can be told what actually just happened. Told only "you
        # cannot save", it answered "your personal memory has been updated" -
        # true-sounding, passive, and wrong. This app auto-saves every
        # candidate the classifier selects, with no approval round-trip, so
        # the honest state to hand the model is "saved", not "offered".
        candidates = await self._classify_memory_proposals(query, trace_id, user_id)
        proposals = await self._persist_memory_proposals(
            user_id, conversation_id, trace_id, candidates
        )
        context["memory_save"] = {
            "saved": bool(proposals),
            "value": _proposal_summaries(proposals),
        }

        initial_state = AgentState(
            conversation_id=conversation_id,
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
            metadata,
        )
        # Emitted after the turn is saved, as before; each one was already
        # persisted before the answer was generated, so the reply could
        # describe it honestly and the interface can show what was written.
        for proposal in proposals:
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
