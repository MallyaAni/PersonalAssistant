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
from backend.agents.memory.artifact_context import ArtifactContextRouter
from backend.agents.state import AgentState
from backend.agents.vision.memory import VisualMemorySelector
from backend.artifacts.image_lineage import (
    collapse_duplicate_content,
    collapse_revision_chains,
)
from backend.artifacts.image_prompt_match import prefer_prompt_matches
from backend.artifacts.image_retrieval import ImageRetrievalPolicy
from backend.artifacts.lineage import Lineage
from backend.artifacts.types import ImageGenerationRequest
from backend.config.settings import settings
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
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.schedule import Cadence
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
from backend.services.referent_resolution import (
    Referent,
    ReferentResolution,
    ReferentResolver,
)
from backend.services.referent_sources import ImageReferentSource
from backend.services.search_planner import SearchPlanner

logger = logging.getLogger(__name__)

# Snippet length shown beneath each cited source in the interface.
_SNIPPET_CHARS = 240
_IMAGE_DESCRIPTION_CHARS = 500
# Long enough to identify a picture in a sentence, short enough to stay a label.
_REFERENT_LABEL_CHARS = 90

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
    # A connection accepted and then dropped is a different fault from one
    # refused: the image service was up, took the job, and went away during it.
    # Observed live as `RemoteProtocolError: Server disconnected without
    # sending a response`, with the container restarting in the same second and
    # generation working again once it came back. Reported as the generic
    # failure it read as a flat refusal, so nobody knew a retry was the right
    # move - which is the same mistake the message above exists to correct.
    if isinstance(exc, httpx.RemoteProtocolError | httpx.ReadTimeout | httpx.ReadError):
        return (
            "The image generation backend stopped partway through this "
            f"request, so I couldn't {action} that image. It usually comes "
            "back on its own within a few minutes - try again then."
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


# Name one resolved referent the way a person would refer to it, preferring
# what it is over what it is called: an artifact's stored title is often
# "Edited image", which identifies nothing.
def _referent_label(referent: Referent) -> str:
    description = " ".join(str(referent.description or "").split())
    if description:
        trimmed = description[:_REFERENT_LABEL_CHARS].rstrip(" .,;:")
        if len(description) > _REFERENT_LABEL_CHARS:
            trimmed = trimmed.rsplit(" ", 1)[0]
        return trimmed
    title = str(referent.title or "").strip()
    return title or "the picture you saved"


# Say which picture is being changed, before changing it.
def _editing_announcement(referent: Referent) -> str:
    return f"Editing {_referent_label(referent)} -\n\n"


# Ask which of several equally plausible pictures was meant.
def _which_one_question(matched: tuple[Referent, ...]) -> str:
    options = "\n".join(f"- {_referent_label(item)}" for item in matched)
    return (
        "I found more than one picture that could be the one you mean:\n\n"
        f"{options}\n\n"
        "Which of these should I change?"
    )


# Describe the pending save in one short line for the prompt. Only the value the
# user themselves stated is echoed, so nothing new is disclosed to the model.
def _proposal_summary(proposal: dict[str, Any]) -> str:
    labels = proposal.get("labels")
    if isinstance(labels, list):
        return ", ".join(str(label) for label in labels)[:200]
    # A cadence has no single value field, and unnamed it reached the reply as
    # an empty string - so the model was told something had been saved without
    # being told what, which is exactly when it invents the detail.
    if proposal.get("kind") == "discovery_schedule":
        cadence = str(proposal.get("cadence") or "").strip()
        hour = proposal.get("hour")
        minute = proposal.get("minute")
        when = (
            f"{cadence} at {int(hour):02d}:{int(minute or 0):02d}"
            if isinstance(hour, int)
            else cadence
        )
        return f"a {when} schedule for Scout"[:200] if cadence else ""
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
        agent_registry: Any | None = None,
        search: SearchProvider | None = None,
        image_search: ArtifactEmbeddingStore | None = None,
        image_artifacts: BinaryArtifactRepository | None = None,
        lineage: ArtifactLineageStore | None = None,
        image_search_limit: int = 5,
        image_retrieval: ImageRetrievalPolicy | None = None,
        search_privacy: OutboundPrivacyPolicy | None = None,
        # Writes the search query and judges whether the results answered
        # it. Optional: without one the router's own query is used once,
        # which is exactly the behaviour this replaces.
        search_planner: SearchPlanner | None = None,
        tool_orchestration: MCPToolOrchestrationService | None = None,
        main_action_selector: MainActionSelector | None = None,
        image_generation: ImageArtifactService | None = None,
        image_style: ImageStyleService | None = None,
        image_refinement: ImageRefinementService | None = None,
        presentation_jobs: PresentationJobService | None = None,
        presentation_model: str | None = None,
        discovery_profile: DiscoveryProfileService | None = None,
        discovery_runs: DiscoveryRunRepository | None = None,
        memory_proposals: MemoryProposalAgent | None = None,
        visual_memory: VisualMemorySelector | None = None,
        artifact_context_router: ArtifactContextRouter | None = None,
        agent_memory: AgentMemoryManager | None = None,
        referent_resolver: ReferentResolver | None = None,
    ):
        self.memory = memory
        self.assistant_graph = build_assistant_graph(llm)
        self.repository = repository
        self.tracer = tracer
        self.history_turn_limit = history_turn_limit
        self.memory_coordinator = memory_coordinator
        self.diagram_artifacts = diagram_artifacts
        self.agent_registry = agent_registry
        self.search = search
        self.image_search = image_search
        self.image_artifacts = image_artifacts
        self.lineage = lineage
        self.image_search_limit = image_search_limit
        # Screening is not optional: a missing policy would mean raw queries
        # leaving the machine, so one is always constructed.
        self.search_privacy = search_privacy or OutboundPrivacyPolicy()
        self.search_planner = search_planner
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
        self.discovery_runs = discovery_runs
        self.memory_proposals = memory_proposals
        self.visual_memory = visual_memory
        self.artifact_context_router = artifact_context_router
        self.agent_memory = agent_memory
        self.referent_resolver = referent_resolver
        # Built here rather than injected: it is a thin adapter over the two
        # dependencies this service already holds, and the resolver it feeds is
        # deliberately ignorant of what kind of thing it is choosing between.
        self.image_referents = (
            ImageReferentSource(memory, self.image_artifacts)
            if referent_resolver is not None
            else None
        )
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
            "discovery_schedule": self._save_discovery_schedule_proposal,
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

    # Answer the turn as though no tool had been chosen.
    #
    # Every branch below decides for itself whether it can actually act. When
    # it cannot - nothing in view to edit, the service behind it unavailable -
    # the turn is not a failure to report, it is a routing mistake, and the
    # user asked a real question that still deserves an answer. Asked to make
    # a drafted email "more casual", the router chose edit_image and the reply
    # became "I don't have a picture of yours that matches what you're
    # describing": a false premise that read as the assistant losing the
    # thread, when the thread was intact and only the branch was wrong. A
    # misroute should cost nothing more than an ordinary answer, so the action
    # is dropped rather than carried into the reply path where it would shape
    # the context all over again.
    def _answer_without_the_tool(
        self,
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
        active_image_artifact_id: str | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        return self._process_assistant_request(
            user_id,
            query,
            conversation_id,
            trace_id,
            metadata,
            active_image_artifact_id,
            preselected_action=None,
        )

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
        depicts_a_person: bool = False,
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
                    depicts_a_person=depicts_a_person,
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
        # Named ahead of the work when the target was resolved rather than
        # selected. Streamed first and kept in the persisted turn, so history
        # records which picture was chosen and not merely that one was.
        lead_in: str = "",
        # Carried from the routing decision rather than judged here: whether
        # the edit needs the scene changed decides which preservation wording
        # the image model is given, and the two are opposites.
        restages_the_scene: bool = False,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if self.image_refinement is None:
            raise RuntimeError("Image refinement is not configured")
        if lead_in:
            yield {"event": "delta", "data": {"content": lead_in}}
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
                restages_the_scene=restages_the_scene,
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
            logger.exception("Chat-initiated image edit failed for trace %s", trace_id)
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

        # A restaged request was not edited, it was rebuilt: the editor
        # conditions on the source and will not change a scene, so the picture
        # was generated from a description of the original. Calling that "the
        # edited image" would misrepresent what the user is looking at - the
        # subjects are theirs, the surfaces and framing are not.
        artifact_metadata = artifact.get("metadata")
        artifact_metadata = (
            artifact_metadata if isinstance(artifact_metadata, dict) else {}
        )
        if artifact_metadata.get("edit_mode") == "restaged":
            response_text = (
                "That change needed the whole scene rebuilt rather than "
                "touched up, so this is a new image based on your picture "
                "rather than an edit of it - the original is untouched."
            )
        else:
            response_text = "Here's the edited image."
        await self._persist_completed_turn(
            user_id,
            conversation_id,
            query,
            f"{lead_in}{response_text}",
            trace_id,
            history,
            {**metadata, "artifact_ids": [str(artifact["id"])]},
        )
        yield {"event": "delta", "data": {"content": response_text}}
        yield {"event": "artifact_ready", "data": artifact}
        yield {"event": "done", "data": {}}

    # Route an edit-image decision to the real edit, resolving which picture
    # the user meant when the interface has none selected.
    #
    # An explicit selection is an override and still wins outright. Without
    # one this used to dead-end, telling the user to go click something -
    # answering a conversational request by sending them back to the
    # interface. It now resolves the reference the same way recall does, and
    # asks when it genuinely cannot tell.
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
                restages_the_scene=action.restages_the_scene,
            ):
                yield event
            return

        resolution, offered = await self._resolve_edit_target(
            user_id, action.instruction
        )
        if not offered:
            # Nothing this user owns was even a candidate, so this turn has no
            # visual context at all and the edit decision was a misroute.
            async for event in self._answer_without_the_tool(
                user_id, query, conversation_id, trace_id, metadata
            ):
                yield event
            return
        target = resolution.only
        if target is not None:
            # Naming what it chose is what makes choosing acceptable at all: a
            # wrong guess is visible in the same breath and costs one
            # generation, never the original, since an edit is an immutable
            # child of the picture it came from.
            async for event in self._process_image_edit(
                user_id,
                query,
                target.handle,
                action.instruction,
                conversation_id,
                trace_id,
                metadata,
                history,
                lead_in=_editing_announcement(target),
                restages_the_scene=action.restages_the_scene,
            ):
                yield event
            return

        async for event in self._process_missing_edit_target(
            user_id,
            query,
            conversation_id,
            trace_id,
            metadata,
            history,
            resolution,
        ):
            yield event

    # Work out which owned picture an edit instruction is pointing at.
    #
    # Costs nothing on the ordinary path: it runs only when an edit arrived
    # with no explicit selection, which is exactly the case that used to fail.
    # A resolver failure degrades to "nothing matched", which asks rather than
    # edits the wrong picture.
    # Returns the resolution and whether anything was offered to resolve
    # against. Those are different answers: no candidate at all means the turn
    # had no visual context and the edit decision was wrong, while candidates
    # that none matched means the user does own pictures and none is the one.
    async def _resolve_edit_target(
        self,
        user_id: str,
        instruction: str,
    ) -> tuple[ReferentResolution, bool]:
        if self.referent_resolver is None or self.image_referents is None:
            return ReferentResolution(matched=()), False
        try:
            candidates = await self.image_referents.candidates(
                user_id, instruction, None
            )
            resolved = await self.referent_resolver.resolve(instruction, candidates)
            return resolved, bool(candidates)
        except Exception:
            logger.warning("Edit-target resolution failed", exc_info=True)
            return ReferentResolution(matched=()), False

    # Ask which picture was meant, or say plainly that there is none.
    #
    # Both are questions the conversation can carry: the next turn's routing
    # sees this exchange in its history, so "the beach one" resolves without
    # any pending-state machine. When several matched they are streamed as
    # image matches too, so the interface offers the actual pictures to choose
    # between rather than a sentence describing them.
    async def _process_missing_edit_target(
        self,
        user_id: str,
        query: str,
        conversation_id: str,
        trace_id: str,
        metadata: dict[str, Any],
        history: list[dict[str, Any]],
        resolution: ReferentResolution | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        matched = resolution.matched if resolution is not None else ()
        artifact_ids: list[str] = []
        if matched:
            response_text = _which_one_question(matched)
            artifact_ids = [item.handle for item in matched]
            shown = await self._load_referent_artifacts(user_id, artifact_ids)
            if shown:
                yield {"event": "image_matches", "data": {"matches": shown}}
        else:
            response_text = (
                "I don't have a picture of yours that matches what you're "
                "describing. Upload one, or tell me more about which picture "
                "you mean and I'll find it."
            )
        await self._persist_completed_turn(
            user_id,
            conversation_id,
            query,
            response_text,
            trace_id,
            history,
            {**metadata, "artifact_ids": artifact_ids} if artifact_ids else metadata,
        )
        yield {"event": "delta", "data": {"content": response_text}}
        yield {"event": "done", "data": {}}

    # Load the owned artifact rows behind resolved handles, for display.
    async def _load_referent_artifacts(
        self,
        user_id: str,
        handles: list[str],
    ) -> list[dict[str, Any]]:
        if self.image_artifacts is None:
            return []
        found: list[dict[str, Any]] = []
        for handle in handles:
            try:
                artifact = await self.image_artifacts.get_owned(user_id, handle)
            except Exception:
                logger.warning("Referent artifact unavailable", exc_info=True)
                continue
            if artifact is not None and artifact.get("status") == "ready":
                found.append(artifact)
        return found

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

    # Find stored images whose pixels match a semantically approved recall.
    async def _load_image_matches(
        self,
        user_id: str,
        query: str,
        trace_id: str,
        query_embedding: list[float] | None,
    ) -> list[dict[str, Any]]:
        if self.image_search is None:
            return []
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
        if (
            selector is None
            or repository is None
            or memory is None
            or candidate_loader is None
        ):
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
            return collapse_duplicate_content(collapse_revision_chains(matches))
        except Exception:
            logger.warning("Visual-memory recall failed", exc_info=True)
            return []

    # Decide once which private artifact indexes this turn is allowed to query.
    async def _required_artifact_modalities(self, query: str) -> tuple[str, ...]:
        router = getattr(self, "artifact_context_router", None)
        if router is None:
            return ()
        return await router.required_modalities(query)

    # Recall an image through one semantic gate and the two ranked image indexes.
    async def _recall_image_matches(
        self,
        user_id: str,
        query: str,
        trace_id: str,
        query_embedding: list[float] | None,
    ) -> list[dict[str, Any]]:
        required_modalities = await self._required_artifact_modalities(query)
        if "image" not in required_modalities:
            return []
        logger.info("Trace %s semantically approved image recall", trace_id)
        matches = await self._load_image_matches(
            user_id,
            query,
            trace_id,
            query_embedding,
        )
        if matches:
            return matches
        return await self._load_visual_memory_matches(
            user_id,
            query,
            query_embedding,
        )

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
        image_matches: list[dict[str, Any]] = []
        if active_image is None:
            image_matches = await self._recall_image_matches(
                user_id,
                query,
                trace_id,
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

        async for event in self._stream_web_search(
            context, query, action, image_matches, trace_id
        ):
            yield event

    # Run the turn's web search and report it, including when it found
    # nothing: the interface has to retract its indicator either way.
    async def _stream_web_search(
        self,
        context: dict[str, Any],
        query: str,
        action: MainAction,
        image_matches: list[dict[str, Any]],
        trace_id: str,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        if (
            isinstance(action, SearchAction)
            and self.search is not None
            and self.search.is_enabled()
        ):
            logger.info("Trace %s routing to web search (reason=tool_call)", trace_id)
            search_results: list[dict[str, Any]]
            # The router decides *whether* to search; what to ask for is
            # written by the model that has to use the answer. A 4B choosing
            # the query as one field of its tool call, having never seen the
            # results, is how a four-part question became one generic query
            # and the reply fell back on training.
            chosen_query = action.query
            if self.search_planner is not None:
                composed = self.search_planner.compose(query, [])
                if composed:
                    chosen_query = composed
            outbound_query = _image_aware_search_query(chosen_query, image_matches)
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
                search_results, search_succeeded = await self._research(
                    query, screened.query, trace_id, action.max_results
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

    # Search, look at what came back, and ask again when it did not answer.
    #
    # One search per turn was the ceiling on how good an answer could be: five
    # results that are about the subject but never state the answer look
    # exactly like five that do, and nothing in the turn could tell the
    # difference or try again. Bounded because each extra round costs a search
    # and a model call, and because a model asked to keep improving a query
    # will always find something to change.
    async def _research(
        self,
        question: str,
        first_query: str,
        trace_id: str,
        max_results: int | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        gathered: list[dict[str, Any]] = []
        seen: set[str] = set()
        tried: list[str] = []
        succeeded = False
        current = first_query

        for round_number in range(max(1, settings.SEARCH_MAX_ROUNDS)):
            tried.append(current)
            found, ok = await self._load_search_context(
                current, trace_id, max_results
            )
            succeeded = succeeded or ok
            for item in found:
                url = str(item.get("url") or "")
                if url and url not in seen:
                    seen.add(url)
                    gathered.append(item)
            if self.search_planner is None:
                break
            if round_number + 1 >= max(1, settings.SEARCH_MAX_ROUNDS):
                break
            better = self.search_planner.refine(question, gathered, tried)
            if not better:
                break
            # Every outbound query is screened, not just the first: a refined
            # one is written by a model and can reintroduce what the original
            # had minimized away.
            screened = self.search_privacy.sanitize(better)
            if not screened.allowed:
                logger.info(
                    "Trace %s blocked a refined search (categories=%s)",
                    trace_id,
                    ",".join(screened.categories),
                )
                break
            logger.info(
                "Trace %s searching again (round %d)", trace_id, round_number + 2
            )
            current = screened.query

        return gathered, succeeded

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
                action.depicts_a_person,
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

        # Reached when a branch above matched the action but not the service
        # behind it - a diagram routed with no diagram service configured, a
        # deck with no job queue. The chosen action cannot run, so it is
        # dropped rather than carried into the reply as though it had: search
        # and the user's own tools are the two that survive to here, because
        # those are the ones the reply path can still execute.
        runnable = isinstance(action, SearchAction | ToolboxAction)
        async for event in self._process_assistant_request(
            user_id,
            query,
            resolved_conversation_id,
            trace_id,
            metadata or {},
            active_image_artifact_id,
            preselected_action=action if runnable else None,
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
    # Read the live agent roster, or nothing when it cannot be read.
    #
    # A failure here must not cost the user their reply: the roster only enriches
    # what the assistant can say about itself, and an answer without it is the
    # behaviour that shipped for months.
    async def _describe_agents(self, user_id: str) -> list[dict[str, Any]]:
        if self.agent_registry is None:
            return []
        try:
            summaries = await self.agent_registry.describe_all(user_id)
        except Exception:
            logger.warning("Agent roster unavailable for context", exc_info=True)
            return []
        return [
            {
                "name": summary.name,
                "role": summary.role,
                "trigger": summary.trigger,
                "setup_needs": summary.setup_needs,
                # Live state, not just capability. Without it the assistant can
                # describe what Scout needs and cannot tell whether the user
                # already has it, so it asks for things they supplied minutes
                # ago and confirms an agent as ready when it is not. Each agent
                # computes these from the tables it owns.
                "status": summary.status,
                "detail": summary.detail,
                "facts": {fact.label: fact.value for fact in summary.facts},
            }
            for summary in summaries
        ]

    # Read the built-in capabilities the selector offers, or nothing when there
    # is no selector wired.
    #
    # Failing here must not cost the user their reply, for the same reason the
    # agent roster above degrades quietly: this only enriches what the
    # assistant can say about itself.
    def _describe_capabilities(self) -> list[dict[str, str]]:
        if self.main_action_selector is None:
            return []
        try:
            return self.main_action_selector.describe_capabilities()
        except Exception:
            logger.warning("Capability list unavailable for context", exc_info=True)
            return []

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

    # Save a classified sweep cadence, when the schedule store is wired.
    #
    # The timezone is read from the user's own locality rather than guessed: a
    # locality already carries a real one, and asking a model to infer a
    # timezone from a city name is asking it to state a personal fact it does
    # not know. With no locality yet there is nothing to anchor a local hour to,
    # so the cadence is not saved and the reply asks for the place first.
    async def _save_discovery_schedule_proposal(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        candidate: dict[str, Any],
    ) -> bool:
        if self.discovery_runs is None or self.discovery_profile is None:
            return False
        timezone = await self._primary_timezone(user_id)
        if timezone is None:
            return False
        await self.discovery_runs.upsert_schedule(
            user_id,
            Cadence(
                cadence=str(candidate["cadence"]),
                hour=int(candidate["hour"]),
                minute=int(candidate.get("minute") or 0),
                weekday=int(candidate.get("weekday") or 0),
                timezone=timezone,
            ),
        )
        return True

    # The timezone of the user's primary locality, or None when they have none.
    async def _primary_timezone(self, user_id: str) -> str | None:
        try:
            profile = await self.discovery_profile.get_profile(user_id)
        except Exception:
            logger.warning("Discovery profile unavailable for schedule", exc_info=True)
            return None
        localities = getattr(profile, "localities", ()) or ()
        for locality in localities:
            if getattr(locality, "is_primary", False):
                return str(getattr(locality, "timezone", "") or "") or None
        for locality in localities:
            zone = str(getattr(locality, "timezone", "") or "")
            if zone:
                return zone
        return None

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
        # What specialized agents exist, read from the registry rather than
        # listed in the prompt: each agent describes itself from its own
        # tables, so this cannot advertise a capability an agent stopped
        # having, and adding an agent needs no prompt edit.
        context["agents"] = await self._describe_agents(user_id)
        # What the turn router can actually do, read from the router itself
        # rather than listed again in the prompt: the same rows it offers as
        # tools are what the assistant is told it can do, so the two cannot
        # drift apart into one wording for conversation and another for
        # routing.
        context["capabilities"] = self._describe_capabilities()
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
