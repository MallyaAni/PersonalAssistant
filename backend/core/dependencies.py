import logging
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.deck.agent import PresentationAgent
from backend.agents.diagram import DiagramAgent
from backend.agents.memory.artifact_context import ArtifactContextRouter
from backend.agents.registry import AgentRegistry
from backend.agents.scout.digesting import DigestWriter
from backend.agents.scout.place_suggest import PlaceSuggester
from backend.agents.vision.memory import VisualMemorySelector
from backend.artifacts.diagram import LLMDiagramProvider
from backend.artifacts.image import (
    ComfyUIImageEditProvider,
    ComfyUIImageProvider,
    FluxKontextImageEditProvider,
)
from backend.artifacts.image_retrieval import ImageRetrievalPolicy
from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.config.settings import settings
from backend.core.gpu_handoff import (
    GpuHandoffImageEditProvider,
    GpuHandoffImageProvider,
    InferenceGpuHandoff,
)
from backend.core.interfaces import (
    ConversationTracer,
    ImageEditProvider,
    ImageProvider,
    RerankProvider,
    SearchProvider,
    VisionEmbeddingProvider,
    VisionProvider,
)
from backend.core.llm import (
    LLMClient,
    create_inference_provider,
)
from backend.core.model_gate import ModelExecutionGate
from backend.database.session import get_db
from backend.discovery.channels import (
    ChannelRefusedError,
    MessagesAppChannel,
    NotificationChannel,
    NullChannel,
    PullOnlyChannel,
)
from backend.discovery.fact_recorder import MemoryFactRecorder
from backend.discovery.familiarity import FamiliarItemRepository
from backend.discovery.feedback import SentFindRepository
from backend.discovery.locating import (
    DisabledPlaceResolver,
    NominatimPlaceResolver,
    PlaceResolver,
)
from backend.discovery.novelty import SeenItemRepository
from backend.discovery.reactions import ReactionCollector
from backend.discovery.repository import DiscoveryProfileRepository
from backend.discovery.runner import DiscoveryRunner
from backend.discovery.runs import DiscoveryRunRepository
from backend.discovery.search_budget import SearchBudget
from backend.discovery.service import DiscoveryProfileService
from backend.discovery.setup_service import DiscoverySetupService
from backend.discovery.sources_repository import DiscoverySourceRepository
from backend.discovery.subscribers import SubscriberRepository
from backend.embeddings.base import EmbeddingProvider
from backend.embeddings.cross_encoder import OnnxCrossEncoder
from backend.embeddings.lm_studio import create_embedding_provider
from backend.embeddings.nomic_vision import NomicVisionEmbeddingProvider
from backend.mcp.client import SessionMCPToolLister
from backend.mcp.config import parse_server_configs
from backend.mcp.invocation import SessionMCPToolInvoker
from backend.mcp.types import MCPServerConfig
from backend.memory.coordinator import MemoryCoordinatorAgent
from backend.memory.proposal_agent import MemoryProposalAgent
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.presentations.provider import LLMPresentationProvider
from backend.presentations.renderer import PptxGenJSRenderer
from backend.presentations.research import DeckResearch
from backend.search.tavily import TavilyUsageClient
from backend.search.budgeted import BudgetedSearchProvider
from backend.search.mcp import MCPWebSearchProvider
from backend.search.tavily import TavilySearchProvider
from backend.services.agent_memory_manager import AgentMemoryManager
from backend.services.artifact_deletion_service import ArtifactDeletionService
from backend.services.artifact_repository import SQLAlchemyArtifactRepository
from backend.services.conversation_service import ConversationService
from backend.services.diagram_artifact_service import DiagramArtifactService
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.image_intent import ImageIntentClassifier
from backend.services.image_refinement_service import ImageRefinementService
from backend.services.image_style_service import ImageStyleService
from backend.services.main_action_selector import MainActionSelector
from backend.services.mcp_invocation_service import MCPInvocationService
from backend.services.mcp_tool_orchestration_service import MCPToolOrchestrationService
from backend.services.memory_operations_service import MemoryOperationsService
from backend.services.memory_reembedding_service import MemoryReembeddingService
from backend.services.memory_retention_service import MemoryRetentionService
from backend.services.postgres_memory_service import PostgresMemoryService
from backend.services.presentation_image_service import PresentationImageService
from backend.services.presentation_job_repository import (
    SQLAlchemyPresentationJobRepository,
)
from backend.services.presentation_job_service import PresentationJobService
from backend.services.presentation_repository import SQLAlchemyPresentationRepository
from backend.services.presentation_service import PresentationService
from backend.services.referent_resolution import ReferentResolver
from backend.services.repository import SQLAlchemyConversationRepository
from backend.services.search_planner import SearchPlanner
from backend.services.tool_memory_service import ToolMemoryService
from backend.services.tracing import (
    LoggingConversationTracer,
    OpenTelemetryConversationTracer,
)
from backend.services.vision_analysis_service import VisionAnalysisService
from backend.services.visual_search_grounding import VisualSearchGrounding
from backend.skills.repository import SkillRepository
from backend.tasks.repository import ScheduledTaskRepository
from backend.vision.lm_studio import create_vision_provider

logger = logging.getLogger(__name__)


# Reuse one concurrency-limited embedding adapter across application requests.
@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return create_embedding_provider(
        adapter=(settings.EMBEDDING_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER),
        base_url=settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimension=settings.EMBEDDING_DIMENSION,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_concurrency=settings.EMBEDDING_MAX_CONCURRENCY,
    )


# Reuse one configured search adapter; it is disabled when no key is present.
#
# Wrapped so every interactive query is charged to the calling account. The
# wrapper goes here rather than at each call site because this is the single
# place all of them resolve through, including the ones built outside a request.
@lru_cache(maxsize=1)
def get_search_provider() -> SearchProvider:
    return BudgetedSearchProvider(
        _build_search_provider(),
        get_search_budget(),
        # Tavily bills an advanced search at two credits; the ceiling is in
        # credits, so the local counter must spend what the key spends.
        credits_per_search=2 if settings.SEARCH_DEPTH == "advanced" else 1,
        usage=TavilyUsageClient(
            base_url=settings.SEARCH_BASE_URL or "https://api.tavily.com",
            api_key=settings.SEARCH_API_KEY,
        ),
        brave_monthly_limit=(
            settings.BRAVE_SEARCH_MONTHLY_LIMIT if settings.BRAVE_SEARCH_API_KEY else 0
        ),
    )


def _build_search_provider() -> SearchProvider:
    if settings.SEARCH_PROVIDER_NAME == "mcp":
        return MCPWebSearchProvider(
            get_mcp_invocation_service(),
            settings.SEARCH_MCP_SERVER_ID,
            settings.SEARCH_MCP_TOOL_NAME,
            settings.SEARCH_MAX_RESULTS,
            settings.SEARCH_MAX_CONTENT_CHARS,
            settings.SEARCH_MIN_SCORE,
        )
    return TavilySearchProvider(
        base_url=settings.SEARCH_BASE_URL,
        api_key=settings.SEARCH_API_KEY,
        max_results=settings.SEARCH_MAX_RESULTS,
        timeout_seconds=settings.SEARCH_TIMEOUT_SECONDS,
        max_content_chars=settings.SEARCH_MAX_CONTENT_CHARS,
        min_score=settings.SEARCH_MIN_SCORE,
        search_depth=settings.SEARCH_DEPTH,
    )


# Parse configured MCP servers once. Trust is declared here by the operator and
# is never taken from a server describing itself.
@lru_cache(maxsize=1)
def get_mcp_servers() -> tuple[MCPServerConfig, ...]:
    return parse_server_configs(settings.MCP_SERVERS_JSON)


# Reuse one invocation service; every call re-reads the live catalogue anyway.
@lru_cache(maxsize=1)
def get_mcp_invocation_service() -> MCPInvocationService:
    return MCPInvocationService(
        SessionMCPToolInvoker(timeout_seconds=settings.MCP_LIST_TIMEOUT_SECONDS),
        SessionMCPToolLister(timeout_seconds=settings.MCP_LIST_TIMEOUT_SECONDS),
        get_mcp_servers(),
    )


MCPInvocationDependency = Annotated[
    MCPInvocationService,
    Depends(get_mcp_invocation_service),
]

DbDependency = Annotated[AsyncSession, Depends(get_db)]
EmbeddingDependency = Annotated[
    EmbeddingProvider,
    Depends(get_embedding_provider),
]
SearchDependency = Annotated[
    SearchProvider,
    Depends(get_search_provider),
]


def get_memory_service(
    db: DbDependency,
    embeddings: EmbeddingDependency,
) -> PostgresMemoryService:
    return PostgresMemoryService(
        db,
        embeddings,
        SemanticRetrievalPolicy(
            max_cosine_distance=settings.MEMORY_SEMANTIC_MAX_COSINE_DISTANCE,
            max_results=settings.MEMORY_SEMANTIC_MAX_RESULTS,
            max_content_chars=settings.MEMORY_SEMANTIC_MAX_CONTENT_CHARS,
        ),
        settings.EMBEDDING_MODEL_VERSION,
    )


# Build one inference client from a role's adapter and endpoint configuration.
def _build_llm_client(
    adapter: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
) -> LLMClient:
    return create_inference_provider(
        adapter=adapter,
        base_url=base_url,
        model=model,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=reasoning_effort,
    )


# Build the primary conversation and supervisor model with legacy fallbacks.
#
# The one conversational model. There is deliberately no standby behind it.
#
# A standby was wired here while the main model ran on a host that was not
# always powered on, and it pointed at a model a third as capable - so an
# outage did not fail, it silently answered worse, and nothing in the reply
# said which model had written it. Both Sparks are always on now, and a
# reachability problem should read as one rather than as the assistant
# quietly getting dimmer.
def get_llm_client() -> LLMClient:
    return _build_llm_client(
        settings.MAIN_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        settings.MAIN_LLM_BASE_URL or settings.LLM_BASE_URL,
        settings.MAIN_LLM_MODEL or settings.LLM_MODEL,
        settings.MAIN_LLM_REASONING_EFFORT,
    )


# Build MainActionSelector's tool-calling model independently from the
# conversational reply model. Falls back to MAIN_LLM_* so leaving this unset
# reproduces today's behaviour exactly: one model does both jobs.
def get_routing_llm_client() -> LLMClient:
    return _build_llm_client(
        settings.ROUTING_INFERENCE_ADAPTER
        or settings.MAIN_INFERENCE_ADAPTER
        or settings.INFERENCE_ADAPTER,
        settings.ROUTING_LLM_BASE_URL
        or settings.MAIN_LLM_BASE_URL
        or settings.LLM_BASE_URL,
        settings.ROUTING_LLM_MODEL or settings.MAIN_LLM_MODEL or settings.LLM_MODEL,
        settings.ROUTING_LLM_REASONING_EFFORT,
    )


# Reasoning that returns prose or a free-form judgement.
#
# Follows the main model by design: this is the work a better main model makes
# better, and it should not need a settings change per call site to benefit.
def get_reasoning_llm_client() -> LLMClient:
    return get_llm_client()


# Reasoning that must come back as strict JSON against a schema this
# application owns.
#
# Also follows the main model — but only when its engine actually enforces the
# schema it is given. When it does not, this falls back to the routing role
# rather than to a named model, so there is one place to change rather than one
# per caller. That mattered: the same engine defect was found and patched three
# times at three different call sites before it was expressed as a capability.
#
# The fallback is a real cost, not a neutral choice. The 4B classifier behind it
# is measurably weaker at understanding an utterance — it extracts a locality
# and interests from "I'm in Raleigh, NC and I'm into ..." and returns nothing
# at all for the same sentence naming Durham, while the main model reads both
# correctly and only fails to shape its answer. Flipping
# MAIN_LLM_STRUCTURED_OUTPUT is what buys that back.
def get_structured_llm_client() -> LLMClient:
    if settings.MAIN_LLM_STRUCTURED_OUTPUT:
        return get_llm_client()
    return get_routing_llm_client()


# Build the focused presentation model independently from the main agent.
def get_presentation_llm_client() -> LLMClient:
    # Deck planning answers into a strict typed specification, so unpinned it
    # follows the structured role rather than the main model directly. This is
    # the role the capability was learned on: promoting the main model here on
    # 2026-08-14 produced well-formed JSON in the wrong field names
    # (`statistic` where the contract wants `statistic_value`), and the fix was
    # to pin this one call site to Qwen. Expressed as a capability, the same
    # promotion is safe and reverses itself.
    if not (settings.PRESENTATION_LLM_BASE_URL or settings.PRESENTATION_LLM_MODEL):
        return get_structured_llm_client()
    return _build_llm_client(
        settings.PRESENTATION_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        settings.PRESENTATION_LLM_BASE_URL
        or settings.MAIN_LLM_BASE_URL
        or settings.LLM_BASE_URL,
        settings.PRESENTATION_LLM_MODEL
        or settings.MAIN_LLM_MODEL
        or settings.LLM_MODEL,
        settings.PRESENTATION_LLM_REASONING_EFFORT,
    )


# Build the diagram-planning model independently from the main agent.
def get_diagram_llm_client() -> LLMClient:
    return _build_llm_client(
        settings.DIAGRAM_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        settings.DIAGRAM_LLM_BASE_URL
        or settings.MAIN_LLM_BASE_URL
        or settings.LLM_BASE_URL,
        settings.DIAGRAM_LLM_MODEL or settings.MAIN_LLM_MODEL or settings.LLM_MODEL,
        settings.DIAGRAM_LLM_REASONING_EFFORT,
    )


# Build the typed-memory classifier, pinned only when an operator pins it.
#
# Left unset it follows the structured role rather than naming a model, so
# promoting a main model whose engine enforces schemas moves extraction with it.
# That is the difference this indirection buys: extraction quality is a
# reasoning problem, and it was stuck on a 4B model purely because the engine
# behind the better one would not honour the contract.
def get_memory_proposal_llm_client() -> LLMClient:
    if not (
        settings.MEMORY_PROPOSAL_LLM_BASE_URL or settings.MEMORY_PROPOSAL_LLM_MODEL
    ):
        return get_structured_llm_client()
    return _build_llm_client(
        settings.MEMORY_PROPOSAL_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        settings.MEMORY_PROPOSAL_LLM_BASE_URL
        or settings.MAIN_LLM_BASE_URL
        or settings.LLM_BASE_URL,
        settings.MEMORY_PROPOSAL_LLM_MODEL
        or settings.MAIN_LLM_MODEL
        or settings.LLM_MODEL,
        settings.MEMORY_PROPOSAL_LLM_REASONING_EFFORT,
    )


# Give chat one semantic typed-memory classifier with no persistence capability.
def get_memory_proposal_agent() -> MemoryProposalAgent:
    return MemoryProposalAgent(
        get_memory_proposal_llm_client(),
        max_tokens=settings.MEMORY_PROPOSAL_MAX_TOKENS,
    )


def get_conversation_repository(
    db: DbDependency,
) -> SQLAlchemyConversationRepository:
    return SQLAlchemyConversationRepository(session=db)


def get_conversation_tracer() -> ConversationTracer:
    logging_tracer = LoggingConversationTracer()
    if settings.OTEL_ENABLED:
        return OpenTelemetryConversationTracer(logging_tracer)
    return logging_tracer


MemoryDependency = Annotated[
    PostgresMemoryService,
    Depends(get_memory_service),
]
LlmDependency = Annotated[LLMClient, Depends(get_llm_client)]
RoutingLlmDependency = Annotated[LLMClient, Depends(get_routing_llm_client)]
PresentationLlmDependency = Annotated[
    LLMClient,
    Depends(get_presentation_llm_client),
]
DiagramLlmDependency = Annotated[
    LLMClient,
    Depends(get_diagram_llm_client),
]
MemoryProposalDependency = Annotated[
    MemoryProposalAgent,
    Depends(get_memory_proposal_agent),
]
RepositoryDependency = Annotated[
    SQLAlchemyConversationRepository,
    Depends(get_conversation_repository),
]
TracerDependency = Annotated[
    ConversationTracer,
    Depends(get_conversation_tracer),
]


# Build user-scoped visual artifact persistence for the current request.
def get_artifact_repository(db: DbDependency) -> SQLAlchemyArtifactRepository:
    return SQLAlchemyArtifactRepository(db)


ArtifactRepositoryDependency = Annotated[
    SQLAlchemyArtifactRepository,
    Depends(get_artifact_repository),
]


# Reuse one ONNX session across requests; loading 358MB per request is not viable.
@lru_cache(maxsize=1)
def get_vision_embedding_provider() -> VisionEmbeddingProvider:
    return NomicVisionEmbeddingProvider(
        model_path=settings.VISION_EMBEDDING_MODEL_PATH,
        dimension=settings.VISION_EMBEDDING_DIMENSION,
        intra_op_threads=settings.VISION_EMBEDDING_THREADS,
    )


# Reuse one ONNX session across sweeps for the same reason the vision embedder
# does: the weights load once, not once per run. Returns None when the feature
# is switched off, so the caller holds nothing rather than holding a provider
# that always refuses.
@lru_cache(maxsize=1)
def get_cross_encoder() -> RerankProvider | None:
    if not settings.DISCOVERY_CROSS_ENCODER_ENABLED:
        return None
    # The served reranker and the local ONNX model answer the same contract,
    # so which one scores a sweep is a deployment decision, not a code path.
    if settings.DISCOVERY_RERANKER_SOURCE == "service":
        from backend.embeddings.service_reranker import ServiceCrossEncoder

        return ServiceCrossEncoder()
    return OnnxCrossEncoder(
        model_path=settings.DISCOVERY_CROSS_ENCODER_MODEL_PATH,
        tokenizer_path=settings.DISCOVERY_CROSS_ENCODER_TOKENIZER_PATH,
        intra_op_threads=settings.DISCOVERY_CROSS_ENCODER_THREADS,
    )


VisionEmbeddingDependency = Annotated[
    VisionEmbeddingProvider,
    Depends(get_vision_embedding_provider),
]


# Reuse one opaque local binary store across application requests.
@lru_cache(maxsize=1)
def get_binary_artifact_store() -> LocalBinaryArtifactStore:
    return LocalBinaryArtifactStore(settings.ARTIFACT_STORAGE_ROOT)


BinaryArtifactStoreDependency = Annotated[
    LocalBinaryArtifactStore,
    Depends(get_binary_artifact_store),
]


# Build the lightweight cross-store service used by the forget-me boundary.
def get_artifact_deletion_service(
    repository: ArtifactRepositoryDependency,
    store: BinaryArtifactStoreDependency,
) -> ArtifactDeletionService:
    return ArtifactDeletionService(repository, store)


ArtifactDeletionDependency = Annotated[
    ArtifactDeletionService,
    Depends(get_artifact_deletion_service),
]


# Reuse one Redis-backed priority gate across model-backed request lifecycles.
@lru_cache(maxsize=1)
def get_model_execution_gate() -> ModelExecutionGate:
    return ModelExecutionGate(
        settings.REDIS_URL,
        settings.MODEL_GATE_ENABLED,
        settings.MODEL_GATE_LEASE_SECONDS,
        settings.MODEL_GATE_POLL_SECONDS,
    )


ModelGateDependency = Annotated[
    ModelExecutionGate,
    Depends(get_model_execution_gate),
]


# Reuse one stateless PptxGenJS worker adapter across application requests.
@lru_cache(maxsize=1)
def get_presentation_renderer() -> PptxGenJSRenderer:
    return PptxGenJSRenderer(
        settings.PRESENTATION_RENDERER_BASE_URL,
        settings.PRESENTATION_RENDERER_TIMEOUT_SECONDS,
        settings.PRESENTATION_MAX_OUTPUT_BYTES,
        require_office_validation=settings.PRESENTATION_REQUIRE_OFFICE_VALIDATION,
    )


# Build the deck-grounding boundary, or nothing when the operator disabled it.
# A deck plans from recollection without this, which is what produced invented
# statistics; the planning contract still forbids unsupported figures either way.
def get_deck_research() -> DeckResearch | None:
    if not settings.PRESENTATION_RESEARCH_ENABLED:
        return None
    return DeckResearch(get_search_provider())


# Build the configured presentation planner without storage or file authority.
def get_presentation_agent(llm: PresentationLlmDependency) -> PresentationAgent:
    return PresentationAgent(
        LLMPresentationProvider(
            llm,
            settings.PRESENTATION_MAX_TOKENS,
            settings.PRESENTATION_PLAN_MAX_TOKENS,
            settings.PRESENTATION_REVISION_MAX_TOKENS,
            research=get_deck_research(),
        )
    )


# Build the presentation planner with lower-priority per-slide model leases.
def get_background_presentation_agent() -> PresentationAgent:
    return PresentationAgent(
        LLMPresentationProvider(
            get_presentation_llm_client(),
            settings.PRESENTATION_MAX_TOKENS,
            settings.PRESENTATION_PLAN_MAX_TOKENS,
            settings.PRESENTATION_REVISION_MAX_TOKENS,
            model_gate=get_model_execution_gate(),
            background=True,
            research=get_deck_research(),
        )
    )


PresentationAgentDependency = Annotated[
    PresentationAgent,
    Depends(get_presentation_agent),
]


# Bind presentation persistence to the current asynchronous request transaction.
def get_presentation_repository(
    db: DbDependency,
) -> SQLAlchemyPresentationRepository:
    return SQLAlchemyPresentationRepository(db)


PresentationRepositoryDependency = Annotated[
    SQLAlchemyPresentationRepository,
    Depends(get_presentation_repository),
]


# Coordinate planning, native rendering, revision lineage, and binary storage.
def get_presentation_service(
    agent: PresentationAgentDependency,
    repository: PresentationRepositoryDependency,
    store: BinaryArtifactStoreDependency,
    artifacts: ArtifactRepositoryDependency,
) -> PresentationService:
    return PresentationService(
        agent,
        get_presentation_renderer(),
        repository,
        store,
        provider_name=settings.INFERENCE_PROVIDER_NAME,
        model_name=(
            settings.PRESENTATION_LLM_MODEL
            or settings.MAIN_LLM_MODEL
            or settings.LLM_MODEL
        ),
        artifact_repository=artifacts,
    )


PresentationDependency = Annotated[
    PresentationService,
    Depends(get_presentation_service),
]


# Bind durable presentation-job persistence to the current request session.
def get_presentation_job_repository(
    db: DbDependency,
) -> SQLAlchemyPresentationJobRepository:
    return SQLAlchemyPresentationJobRepository(db)


PresentationJobRepositoryDependency = Annotated[
    SQLAlchemyPresentationJobRepository,
    Depends(get_presentation_job_repository),
]


# Queue and inspect presentation work without executing the model in the API.
def get_presentation_job_service(
    jobs: PresentationJobRepositoryDependency,
    presentations: PresentationRepositoryDependency,
) -> PresentationJobService:
    return PresentationJobService(
        jobs,
        presentations,
        provider_name=settings.INFERENCE_PROVIDER_NAME,
        model_name=(
            settings.PRESENTATION_LLM_MODEL
            or settings.MAIN_LLM_MODEL
            or settings.LLM_MODEL
        ),
        auto_image_max=settings.PRESENTATION_AUTO_IMAGE_MAX,
    )


PresentationJobDependency = Annotated[
    PresentationJobService,
    Depends(get_presentation_job_service),
]


# Share one handoff so generation and editing use the same sleep endpoint.
@lru_cache(maxsize=1)
def get_gpu_handoff() -> InferenceGpuHandoff:
    return InferenceGpuHandoff(
        base_url=settings.MAIN_LLM_BASE_URL or settings.LLM_BASE_URL,
        enabled=settings.GPU_HANDOFF_ENABLED,
        sleep_level=settings.GPU_HANDOFF_SLEEP_LEVEL,
        timeout_seconds=settings.GPU_HANDOFF_TIMEOUT_SECONDS,
    )


# Reuse one concurrency-limited ComfyUI image provider across requests, wrapped
# so each job runs with local inference weights offloaded.
@lru_cache(maxsize=1)
def get_image_provider() -> ImageProvider:
    return GpuHandoffImageProvider(_build_comfyui_image_provider(), get_gpu_handoff())


def _build_comfyui_image_provider() -> ComfyUIImageProvider:
    return ComfyUIImageProvider(
        base_url=settings.IMAGE_PROVIDER_BASE_URL,
        restart_wait_seconds=settings.IMAGE_PROVIDER_RESTART_WAIT_SECONDS,
        model=settings.IMAGE_MODEL,
        timeout_seconds=settings.IMAGE_PROVIDER_TIMEOUT_SECONDS,
        poll_seconds=settings.IMAGE_PROVIDER_POLL_SECONDS,
        max_concurrency=settings.IMAGE_MAX_CONCURRENCY,
        max_output_bytes=settings.IMAGE_MAX_OUTPUT_BYTES,
        max_pixels=settings.IMAGE_MAX_PIXELS,
        text_encoder=settings.IMAGE_TEXT_ENCODER,
        vae=settings.IMAGE_VAE,
        steps=settings.IMAGE_GENERATION_STEPS,
        style_suffix=settings.IMAGE_STYLE_SUFFIX,
        portrait_suffix=settings.IMAGE_PORTRAIT_SUFFIX,
        text_suffix=settings.IMAGE_TEXT_SUFFIX,
    )


ImageProviderDependency = Annotated[
    ImageProvider,
    Depends(get_image_provider),
]


# Reuse one source-conditioned FLUX.2 editor on the shared ComfyUI runtime,
# wrapped in the same handoff because editing loads the same diffusion weights.
@lru_cache(maxsize=1)
def get_image_edit_provider() -> ImageEditProvider:
    return GpuHandoffImageEditProvider(
        _build_comfyui_image_edit_provider(), get_gpu_handoff()
    )


def _build_comfyui_image_edit_provider() -> ComfyUIImageEditProvider:
    # Kontext when one is configured, the FLUX.2 editor otherwise. Both satisfy
    # the same contract, so nothing above this cares which is running.
    if settings.IMAGE_EDIT_MODEL:
        return FluxKontextImageEditProvider(
            base_url=settings.IMAGE_PROVIDER_BASE_URL,
        restart_wait_seconds=settings.IMAGE_PROVIDER_RESTART_WAIT_SECONDS,
            model=settings.IMAGE_EDIT_MODEL,
            clip_name=settings.IMAGE_EDIT_CLIP,
            t5_name=settings.IMAGE_EDIT_T5,
            vae=settings.IMAGE_EDIT_VAE,
            timeout_seconds=settings.IMAGE_PROVIDER_TIMEOUT_SECONDS,
            poll_seconds=settings.IMAGE_PROVIDER_POLL_SECONDS,
            max_concurrency=settings.IMAGE_MAX_CONCURRENCY,
            max_output_bytes=settings.IMAGE_MAX_OUTPUT_BYTES,
            max_pixels=settings.IMAGE_MAX_PIXELS,
            steps=settings.IMAGE_EDIT_KONTEXT_STEPS,
            guidance=settings.IMAGE_EDIT_GUIDANCE,
            megapixels=settings.IMAGE_EDIT_MEGAPIXELS,
            scale_method=settings.IMAGE_EDIT_SCALE_METHOD,
        )
    return ComfyUIImageEditProvider(
        base_url=settings.IMAGE_PROVIDER_BASE_URL,
        restart_wait_seconds=settings.IMAGE_PROVIDER_RESTART_WAIT_SECONDS,
        model=settings.IMAGE_MODEL,
        text_encoder=settings.IMAGE_TEXT_ENCODER,
        vae=settings.IMAGE_VAE,
        timeout_seconds=settings.IMAGE_PROVIDER_TIMEOUT_SECONDS,
        poll_seconds=settings.IMAGE_PROVIDER_POLL_SECONDS,
        max_concurrency=settings.IMAGE_MAX_CONCURRENCY,
        max_output_bytes=settings.IMAGE_MAX_OUTPUT_BYTES,
        max_pixels=settings.IMAGE_MAX_PIXELS,
        steps=settings.IMAGE_EDIT_STEPS,
        megapixels=settings.IMAGE_EDIT_MEGAPIXELS,
        scale_method=settings.IMAGE_EDIT_SCALE_METHOD,
    )


ImageEditProviderDependency = Annotated[
    ImageEditProvider,
    Depends(get_image_edit_provider),
]


# Coordinate image generation, storage, integrity, and terminal lifecycle state.
def get_image_artifact_service(
    provider: ImageProviderDependency,
    edit_provider: ImageEditProviderDependency,
    repository: ArtifactRepositoryDependency,
    store: BinaryArtifactStoreDependency,
    vision_embeddings: VisionEmbeddingDependency,
    # Optional so the manual callers (the visual MCP facade, the chat service
    # assembly) keep working; under FastAPI it is injected, and a generated or
    # edited picture is then indexed by its description like an upload is.
    memory: Annotated[PostgresMemoryService | None, Depends(get_memory_service)] = None,
) -> ImageArtifactService:
    return ImageArtifactService(
        descriptions=memory,
        provider=provider,
        repository=repository,
        store=store,
        provider_name=settings.IMAGE_PROVIDER_NAME,
        model_name=settings.IMAGE_MODEL,
        max_upload_bytes=settings.IMAGE_MAX_UPLOAD_BYTES,
        max_pixels=settings.IMAGE_MAX_PIXELS,
        vision_embeddings=vision_embeddings,
        embedding_store=repository,
        vision_embedding_model=settings.VISION_EMBEDDING_MODEL,
        edit_provider=edit_provider,
        edit_provider_name=settings.IMAGE_PROVIDER_NAME,
        edit_model_name=settings.IMAGE_MODEL,
    )


ImageArtifactDependency = Annotated[
    ImageArtifactService,
    Depends(get_image_artifact_service),
]


# Assemble the durable worker with automatic presentation imagery enabled.
def get_background_presentation_service(
    session: AsyncSession,
) -> PresentationService:
    artifacts = get_artifact_repository(session)
    store = get_binary_artifact_store()
    images = get_image_artifact_service(
        get_image_provider(),
        get_image_edit_provider(),
        artifacts,
        store,
        get_vision_embedding_provider(),
    )
    return PresentationService(
        get_background_presentation_agent(),
        get_presentation_renderer(),
        get_presentation_repository(session),
        store,
        provider_name=settings.INFERENCE_PROVIDER_NAME,
        model_name=(
            settings.PRESENTATION_LLM_MODEL
            or settings.MAIN_LLM_MODEL
            or settings.LLM_MODEL
        ),
        artifact_repository=artifacts,
        image_service=images,
        auto_image_max=settings.PRESENTATION_AUTO_IMAGE_MAX,
        auto_image_size=settings.PRESENTATION_AUTO_IMAGE_SIZE,
    )


# Learn and apply a durable per-user image style from refinement feedback.
def get_image_style_service(
    memory: MemoryDependency,
    llm: LlmDependency,
) -> ImageStyleService:
    return ImageStyleService(memory, llm)


ImageStyleDependency = Annotated[
    ImageStyleService,
    Depends(get_image_style_service),
]


# Edit a generated or uploaded image from its owned pixels plus user feedback.
def get_image_refinement_service(
    images: ImageArtifactDependency,
    db: DbDependency,
    memory: MemoryDependency,
) -> ImageRefinementService:
    observer = VisionAnalysisService(
        images,
        get_artifact_repository(db),
        get_vision_provider(),
        thread_context_turns=settings.VISION_THREAD_CONTEXT_TURNS,
        thread_max_stored=settings.VISION_THREAD_MAX_STORED,
        memory=memory,
    )
    # The reasoning role writes the scene a restaging edit is generated from.
    # It is prose describing a picture, not a schema to honour, so it belongs
    # with the model that writes prose rather than with the structured roles.
    return ImageRefinementService(
        images=images, vision=observer, llm=get_reasoning_llm_client()
    )


ImageRefinementDependency = Annotated[
    ImageRefinementService,
    Depends(get_image_refinement_service),
]


# Coordinate initial slide imagery and source-conditioned revisions, both FLUX.
def get_presentation_image_service(
    presentations: PresentationDependency,
    images: ImageArtifactDependency,
    refinements: ImageRefinementDependency,
) -> PresentationImageService:
    return PresentationImageService(presentations, images, refinements)


PresentationImageDependency = Annotated[
    PresentationImageService,
    Depends(get_presentation_image_service),
]


# Reuse one configured vision adapter without granting it storage authority.
@lru_cache(maxsize=1)
def get_vision_provider() -> VisionProvider:
    return create_vision_provider(
        adapter=settings.VISION_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        base_url=settings.VISION_LLM_BASE_URL or settings.LLM_BASE_URL,
        model=settings.VISION_MODEL,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=settings.VISION_LLM_REASONING_EFFORT,
        max_tokens=settings.VISION_MAX_TOKENS,
    )


# Build the optional stronger VLM used only for genuine model uncertainty.
@lru_cache(maxsize=1)
def get_vision_escalation_provider() -> VisionProvider | None:
    if not (
        settings.VISION_ESCALATION_LLM_BASE_URL.strip()
        and settings.VISION_ESCALATION_MODEL.strip()
    ):
        return None
    return create_vision_provider(
        adapter=settings.VISION_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        base_url=settings.VISION_ESCALATION_LLM_BASE_URL,
        model=settings.VISION_ESCALATION_MODEL,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=settings.VISION_ESCALATION_LLM_REASONING_EFFORT,
        max_tokens=settings.VISION_MAX_TOKENS,
    )


VisionProviderDependency = Annotated[
    VisionProvider,
    Depends(get_vision_provider),
]


# Give both image paths one routing decision, made by the main conversation
# model — the same model that used to answer "I cannot edit images" when an edit
# request reached it as chat.
def get_image_intent_classifier(llm: RoutingLlmDependency) -> ImageIntentClassifier:
    # The routing model, not the main one - schema-bound work needs an engine
    # that enforces schemas (MAIN_LLM_STRUCTURED_OUTPUT).
    #
    # The earlier note here recorded the wrong lesson. "Pointed at DeepSeek it
    # returned unparseable content on every upload" was read as the main model
    # being unsuited to constrained classification. It was not a capability
    # problem: the budget was then 16 tokens, a reasoning model is guaranteed
    # to truncate mid-thought at 16, and ds4-server responds to truncation by
    # putting the raw thinking into `content`. The failure was the cap meeting
    # a reasoning engine, and because the classifier answers False on any
    # failure it silently disabled edit-intent detection. The budget now
    # leaves thinking headroom, so the trap cannot re-arm when these callers
    # move engines.
    return ImageIntentClassifier(llm, max_tokens=settings.IMAGE_INTENT_MAX_TOKENS)


ImageIntentDependency = Annotated[
    ImageIntentClassifier,
    Depends(get_image_intent_classifier),
]


# Coordinate validated uploads with grounded local vision analysis.
def get_vision_analysis_service(
    images: ImageArtifactDependency,
    repository: ArtifactRepositoryDependency,
    provider: VisionProviderDependency,
    memory: MemoryDependency,
    llm: LlmDependency,
    routing_llm: RoutingLlmDependency,
    db: DbDependency,
) -> VisionAnalysisService:
    return VisionAnalysisService(
        images,
        repository,
        provider,
        thread_context_turns=settings.VISION_THREAD_CONTEXT_TURNS,
        thread_max_stored=settings.VISION_THREAD_MAX_STORED,
        memory=memory,
        # The vision model sees; the main model reasons. This is the only place
        # the two are combined, and it is deliberately the main client rather
        # than the vision one - the whole point is to answer image questions
        # with the strongest configured model instead of the VLM's own
        # reasoning.
        reasoner=llm if settings.VISION_REASONING_ENABLED else None,
        reasoning_max_tokens=settings.VISION_REASONING_MAX_TOKENS,
        # The decision to search is made by the routing model, for the same
        # reason routing itself is: it is a tool call, which is that model's
        # proven job. The search then grounds the main model's reasoning.
        grounding=(
            VisualSearchGrounding(
                routing_llm,
                get_mcp_invocation_service(),
                settings.SEARCH_MCP_SERVER_ID,
                settings.SEARCH_MCP_TOOL_NAME,
                decision_max_tokens=settings.VISION_SEARCH_DECISION_MAX_TOKENS,
            )
            if settings.VISION_SEARCH_GROUNDING_ENABLED
            else None
        ),
        escalation_provider=get_vision_escalation_provider(),
        # The user's own stated home locality, which narrows which regionally
        # common candidates to weigh first when identifying something. Built
        # from the session rather than taking the request-scoped alias, which
        # is declared further down this module than this factory.
        profile=DiscoveryProfileService(DiscoveryProfileRepository(db)),
    )


VisionAnalysisDependency = Annotated[
    VisionAnalysisService,
    Depends(get_vision_analysis_service),
]


# Build the minimum needed to finish a deferred reasoning pass off-request.
#
# Only the repository, the reasoner and the grounding are wired: this path
# neither sees pixels nor reindexes anything, it rewrites one stored answer. A
# background task cannot borrow the request's session, so it is given its own.
def build_deferred_vision_service(db: AsyncSession) -> VisionAnalysisService:
    return VisionAnalysisService(
        images=None,
        repository=get_artifact_repository(db),
        provider=get_vision_provider(),
        reasoner=(get_llm_client() if settings.VISION_REASONING_ENABLED else None),
        reasoning_max_tokens=settings.VISION_REASONING_MAX_TOKENS,
        grounding=(
            VisualSearchGrounding(
                get_routing_llm_client(),
                get_mcp_invocation_service(),
                settings.SEARCH_MCP_SERVER_ID,
                settings.SEARCH_MCP_TOOL_NAME,
                decision_max_tokens=settings.VISION_SEARCH_DECISION_MAX_TOKENS,
            )
            if settings.VISION_SEARCH_GROUNDING_ENABLED
            else None
        ),
        # The user's own stated home locality, which is a strong prior for
        # identifying anything regional. Built from this task's own session
        # rather than injected, like everything else this service is given here.
        profile=DiscoveryProfileService(DiscoveryProfileRepository(db)),
    )


# Build the replaceable diagram provider around its configured local model.
#
# The spec validator still gates every answer, but the model writing them is
# now the main one: since the reply engine began enforcing JSON schemas there
# is nothing for a second, weaker model to catch. It used to be the parse
# fallback, which meant a malformed spec was silently answered by a 4B whose
# own code comment records 0-of-8 scoring streaks.
def get_diagram_provider(llm: DiagramLlmDependency) -> LLMDiagramProvider:
    return LLMDiagramProvider(
        llm,
        settings.DIAGRAM_LLM_MODEL or settings.MAIN_LLM_MODEL or settings.LLM_MODEL,
    )


DiagramProviderDependency = Annotated[
    LLMDiagramProvider,
    Depends(get_diagram_provider),
]


# Build the focused diagram graph around the replaceable provider.
def get_diagram_agent(provider: DiagramProviderDependency) -> DiagramAgent:
    return DiagramAgent(provider)


DiagramAgentDependency = Annotated[
    DiagramAgent,
    Depends(get_diagram_agent),
]


# Coordinate diagram generation and persistence outside the model boundary.
def get_diagram_artifact_service(
    agent: DiagramAgentDependency,
    repository: ArtifactRepositoryDependency,
) -> DiagramArtifactService:
    return DiagramArtifactService(
        agent,
        repository,
        provider_name=settings.INFERENCE_PROVIDER_NAME,
        model_name=(
            settings.DIAGRAM_LLM_MODEL or settings.MAIN_LLM_MODEL or settings.LLM_MODEL
        ),
    )


DiagramArtifactDependency = Annotated[
    DiagramArtifactService,
    Depends(get_diagram_artifact_service),
]


DependencyMemoryService = Annotated[PostgresMemoryService, Depends(get_memory_service)]


# The discovery profile is per-request session state like every other repository
# boundary, so it is built per request rather than cached.
def get_discovery_profile_service(db: DbDependency) -> DiscoveryProfileService:
    # The profile is a projection of memory, so an edit here records the fact
    # too. Otherwise the user maintains where they live in two places and the
    # assistant only knows about one of them.
    return DiscoveryProfileService(
        DiscoveryProfileRepository(db), MemoryFactRecorder(db)
    )


DependencyDiscoveryProfileService = Annotated[
    DiscoveryProfileService,
    Depends(get_discovery_profile_service),
]


def get_discovery_setup_service(
    db: DbDependency, search: SearchDependency
) -> DiscoverySetupService:
    return DiscoverySetupService(db, search)


DependencyDiscoverySetup = Annotated[
    DiscoverySetupService,
    Depends(get_discovery_setup_service),
]


# Reverse geocoding is a replaceable outbound boundary like search or images,
# and it is disabled unless configured so a deployment never reaches a third
# party by default.
@lru_cache(maxsize=1)
def get_place_resolver() -> PlaceResolver:
    if settings.DISCOVERY_PLACE_RESOLVER != "nominatim":
        return DisabledPlaceResolver()
    return NominatimPlaceResolver(
        base_url=settings.DISCOVERY_PLACE_RESOLVER_URL,
        user_agent=settings.DISCOVERY_PLACE_RESOLVER_USER_AGENT,
    )


DependencyPlaceResolver = Annotated[PlaceResolver, Depends(get_place_resolver)]


def get_agent_registry(db: DbDependency) -> AgentRegistry:
    return AgentRegistry(db)


DependencyAgentRegistry = Annotated[AgentRegistry, Depends(get_agent_registry)]


def get_discovery_source_repository(db: DbDependency) -> DiscoverySourceRepository:
    return DiscoverySourceRepository(db)


DependencyDiscoverySources = Annotated[
    DiscoverySourceRepository,
    Depends(get_discovery_source_repository),
]


def get_discovery_subscriber_repository(db: DbDependency) -> SubscriberRepository:
    return SubscriberRepository(db)


DependencyDiscoverySubscribers = Annotated[
    SubscriberRepository,
    Depends(get_discovery_subscriber_repository),
]


def get_discovery_familiar_repository(db: DbDependency) -> FamiliarItemRepository:
    return FamiliarItemRepository(db)


DependencyDiscoveryFamiliar = Annotated[
    FamiliarItemRepository,
    Depends(get_discovery_familiar_repository),
]


def get_discovery_seen_repository(db: DbDependency) -> SeenItemRepository:
    return SeenItemRepository(db)


DependencyDiscoverySeenItems = Annotated[
    SeenItemRepository,
    Depends(get_discovery_seen_repository),
]


def get_discovery_run_repository(db: DbDependency) -> DiscoveryRunRepository:
    return DiscoveryRunRepository(db)


DependencyDiscoveryRuns = Annotated[
    DiscoveryRunRepository,
    Depends(get_discovery_run_repository),
]


def get_scheduled_task_repository(db: DbDependency) -> ScheduledTaskRepository:
    return ScheduledTaskRepository(db)


DependencyScheduledTasks = Annotated[
    ScheduledTaskRepository,
    Depends(get_scheduled_task_repository),
]


def get_skill_repository(db: DbDependency) -> SkillRepository:
    return SkillRepository(db)


DependencySkills = Annotated[SkillRepository, Depends(get_skill_repository)]


# One budget shared by the API and the worker, so a sweep cannot dodge the
# ceiling by running from the other process.
@lru_cache(maxsize=1)
def get_search_budget() -> SearchBudget:
    return SearchBudget(
        settings.REDIS_URL,
        enabled=settings.MODEL_GATE_ENABLED,
        monthly_credits=settings.SEARCH_MONTHLY_CREDITS,
    )


# One suggester shared across requests; it holds only the model client.
#
# On the routing role because it returns a strict-JSON shortlist against an
# owned schema, and on the chat
# model it came back as an empty tuple every time - a locality lookup that
# silently found nothing rather than failing loudly.
@lru_cache(maxsize=1)
def get_place_suggester() -> PlaceSuggester:
    return PlaceSuggester(get_structured_llm_client())


DependencyPlaceSuggester = Annotated[
    PlaceSuggester,
    Depends(get_place_suggester),
]


# Writes the digest message. Assembled here rather than inside delivery so the
# same runtime that describes a find also words the message about it, and so a
# deployment with no model still delivers — `DigestWriter(None)` renders the
# assembled shape instead of failing.
def get_digest_writer() -> DigestWriter:
    # The model that writes the message a person reads also enforces the
    # schema now, so there is no second engine behind it and no path where a
    # digest silently degrades to the assembled form letter.
    return DigestWriter(get_llm_client())


# Reads tapbacks off the bubbles already sent, through the same trusted MCP
# boundary the send itself uses, so the same allowlist and audit apply.
def get_reaction_collector(session: AsyncSession) -> ReactionCollector:
    return ReactionCollector(
        SentFindRepository(session),
        _invoke_discovery_tool,
        settings.DISCOVERY_REACTIONS_TOOL,
    )


# Whose search allowance a sweep spends. The runner charges its budget with a
# flag fixed at construction, so a factory that never looks the account up
# silently bills every sweep - including the operator's - against the guest
# allowance, and the operator's sweeps stop searching the day guests run dry.
async def resolve_search_account(
    db: AsyncSession, user_id: str
) -> tuple[bool, int | None]:
    from sqlalchemy import select

    from backend.models.auth import UserAccount

    account = await db.scalar(select(UserAccount).where(UserAccount.user_id == user_id))
    if account is None:
        return False, None
    return bool(account.is_admin), account.search_monthly_limit


async def get_discovery_runner(
    db: DbDependency,
    embeddings: EmbeddingDependency,
    user_id: Annotated[str, Path(min_length=1, max_length=50)],
) -> DiscoveryRunner:
    is_operator, search_limit = await resolve_search_account(db, user_id)
    return DiscoveryRunner(
        sources=DiscoverySourceRepository(db),
        seen=SeenItemRepository(db),
        embeddings=embeddings,
        search=get_search_provider(),
        writer=get_llm_client(),
        structured_writer=get_structured_llm_client(),
        search_budget=get_search_budget(),
        cross_encoder=get_cross_encoder(),
        is_operator=is_operator,
        search_limit=search_limit,
    )


DependencyDiscoveryRunner = Annotated[
    DiscoveryRunner,
    Depends(get_discovery_runner),
]


# The same runner, assembled for a background worker that owns its own session
# rather than receiving one from a request. The caller supplies the account's
# budget standing (via resolve_search_account) because a worker has no request
# to read it from.
def get_discovery_runner_for_session(
    session: AsyncSession,
    is_operator: bool = False,
    search_limit: int | None = None,
) -> DiscoveryRunner:
    return DiscoveryRunner(
        sources=DiscoverySourceRepository(session),
        seen=SeenItemRepository(session),
        embeddings=get_embedding_provider(),
        search=get_search_provider(),
        writer=get_llm_client(),
        structured_writer=get_structured_llm_client(),
        search_budget=get_search_budget(),
        cross_encoder=get_cross_encoder(),
        is_operator=is_operator,
        search_limit=search_limit,
    )


# Which channels may actually deliver. Egress ships disabled, so the default map
# refuses to send and says so rather than silently dropping a digest.
@lru_cache(maxsize=1)
def get_discovery_channels() -> dict[str, NotificationChannel]:
    channels: dict[str, NotificationChannel] = {
        # The recipient's own device fetches; this never sends.
        "shortcuts_pull": PullOnlyChannel(),
    }
    if not settings.DISCOVERY_EGRESS_ENABLED:
        channels["imessage"] = NullChannel("imessage")
        return channels
    channels["imessage"] = MessagesAppChannel(
        _invoke_discovery_tool, settings.DISCOVERY_IMESSAGE_TOOL
    )
    return channels


# Deliver through the operator-trusted MCP server that owns the Apple device.
# Routed through the ordinary invocation service so the same trust, allowlist,
# and audit apply as to any other tool call.
#
# `confirmed` is set because the approval for this specific send already exists
# and is stronger than a prompt: a per-subscriber consent record the user wrote
# deliberately, which a scheduled sweep running at 9am cannot ask for again.
async def _invoke_discovery_tool(tool_name: str, arguments: dict[str, str]) -> object:
    result = await get_mcp_invocation_service().invoke(
        settings.DISCOVERY_IMESSAGE_SERVER_ID,
        tool_name,
        dict(arguments),
        confirmed=True,
    )
    # The service reports a tool-side failure in the result rather than raising,
    # and a channel must never report a success it did not have.
    if result.is_error:
        raise ChannelRefusedError(_refusal_code(result))
    return result


# Why the bridge refused, as a code rather than its own words.
#
# The text is deliberately not propagated — it is written by another machine and
# can name the recipient. But collapsing every refusal to one opaque failure had
# a real cost: a digest was built on time, refused because the recipient was not
# on the Mac's allowlist, and recorded only as `channel_failed`. Finding that out
# took a hand-written probe against the bridge. The distinction below is the one
# an operator can act on: fix the allowlist, or fix the bridge.
# The reason is also logged, once, because twice now a delivery failure has been
# diagnosable only by hand-probing the Mac — the second time costing an evening
# and a dozen test messages to a real phone to establish that one digest failed
# and a dozen similar strings did not. The bridge's own contract is that its
# error text is the first line of stderr with the arguments stripped, so it
# names a cause and never a recipient. Logging that is the difference between
# "channel_failed" and "Messages timed out".
def _refusal_code(result: object) -> str:
    raw = str(getattr(result, "content", "") or "")
    text = raw.casefold()
    if "allowlist" in text or "not on this bridge" in text:
        code = "recipient_not_allowed"
    elif "timed out" in text or "timeout" in text or "-1712" in text:
        code = "channel_timeout"
    else:
        code = "channel_failed"
    logger.warning(
        "discovery_channel_refused",
        extra={"code": code, "bridge_reason": raw[:200]},
    )
    return code


# Ask the bridge to permit an address the operator has just approved.
#
# Never raises into the approval. A bridge that is asleep, older than this
# feature, or configured to refuse grants must not turn a successful approval
# into a failed request — the approval is real either way, and the digest path
# already reports its own delivery failures.
async def grant_recipient_on_bridge(channel: str, address: str) -> str:
    if channel != "imessage" or not settings.DISCOVERY_EGRESS_ENABLED:
        return "not_applicable"
    try:
        result = await get_mcp_invocation_service().invoke(
            settings.DISCOVERY_IMESSAGE_SERVER_ID,
            "allow_recipient",
            {"to": address},
            confirmed=True,
        )
    except Exception:
        logger.warning("bridge_grant_unreachable", extra={"channel": channel})
        return "unreachable"
    if result.is_error:
        # Most likely an older bridge with no such tool, or one whose operator
        # has not opted into grants. Both are states a person has to resolve on
        # the Mac, so they are reported rather than retried.
        logger.warning("bridge_grant_refused", extra={"channel": channel})
        return "refused"
    return "granted"


def get_tool_memory_service(
    db: DbDependency,
    embeddings: EmbeddingDependency,
) -> ToolMemoryService:
    return ToolMemoryService(
        db,
        embeddings,
        # Tool descriptors need their own bound: a natural-language query sits
        # further from short structured tool text than memory text sits from
        # memory text, so the general memory threshold discards correct tools.
        SemanticRetrievalPolicy(
            max_cosine_distance=settings.TOOL_SEARCH_MAX_COSINE_DISTANCE,
            max_results=settings.TOOL_SEARCH_MAX_RESULTS,
            max_content_chars=settings.MEMORY_SEMANTIC_MAX_CONTENT_CHARS,
        ),
        settings.EMBEDDING_MODEL_VERSION,
    )


DependencyToolMemoryService = Annotated[
    ToolMemoryService, Depends(get_tool_memory_service)
]


# Compose the model's bounded tool selection with the guarded MCP boundary.
def get_mcp_tool_orchestration_service(
    toolbox: DependencyToolMemoryService,
    invocation: MCPInvocationDependency,
    llm: LlmDependency,
) -> MCPToolOrchestrationService:
    return MCPToolOrchestrationService(
        toolbox,
        invocation,
        llm,
        top_k=settings.TOOL_SEARCH_MAX_RESULTS,
        excluded_tools=(
            frozenset({(settings.SEARCH_MCP_SERVER_ID, settings.SEARCH_MCP_TOOL_NAME)})
            if settings.SEARCH_PROVIDER_NAME == "mcp"
            else frozenset()
        ),
    )


MCPToolOrchestrationDependency = Annotated[
    MCPToolOrchestrationService,
    Depends(get_mcp_tool_orchestration_service),
]


# Build the typed manager for all agent-memory stores.
def get_agent_memory_manager(
    db: DbDependency,
    embeddings: EmbeddingDependency,
) -> AgentMemoryManager:
    return AgentMemoryManager(
        db,
        embeddings,
        SemanticRetrievalPolicy(
            max_cosine_distance=settings.MEMORY_SEMANTIC_MAX_COSINE_DISTANCE,
            max_results=settings.MEMORY_SEMANTIC_MAX_RESULTS,
            max_content_chars=settings.MEMORY_SEMANTIC_MAX_CONTENT_CHARS,
        ),
        settings.EMBEDDING_MODEL_VERSION,
    )


DependencyAgentMemoryManager = Annotated[
    AgentMemoryManager, Depends(get_agent_memory_manager)
]


# Build the service that previews and purges expired memory.
def get_memory_retention_service(db: DbDependency) -> MemoryRetentionService:
    return MemoryRetentionService(db)


DependencyMemoryRetentionService = Annotated[
    MemoryRetentionService, Depends(get_memory_retention_service)
]


# Build the service that inventories and replaces stale vectors.
def get_memory_reembedding_service(
    db: DbDependency,
    embeddings: EmbeddingDependency,
) -> MemoryReembeddingService:
    return MemoryReembeddingService(
        db,
        embeddings,
        settings.EMBEDDING_MODEL_VERSION,
        settings.EMBEDDING_DIMENSION,
    )


DependencyMemoryReembeddingService = Annotated[
    MemoryReembeddingService, Depends(get_memory_reembedding_service)
]


# Build the service that reports memory operational health.
def get_memory_operations_service(
    db: DbDependency,
    embeddings: EmbeddingDependency,
) -> MemoryOperationsService:
    return MemoryOperationsService(
        db,
        embeddings,
        settings.EMBEDDING_MODEL_VERSION,
        settings.EMBEDDING_DIMENSION,
    )


DependencyMemoryOperationsService = Annotated[
    MemoryOperationsService, Depends(get_memory_operations_service)
]


# Build the coordinator that plans memory retrieval and turn updates.
def get_memory_coordinator(
    stores: DependencyAgentMemoryManager,
    toolbox: DependencyToolMemoryService,
) -> MemoryCoordinatorAgent:
    return MemoryCoordinatorAgent(
        stores,
        toolbox,
        summary_interval=settings.CONVERSATION_SUMMARY_INTERVAL,
        max_context_items=settings.MEMORY_CONTEXT_MAX_ITEMS,
        max_context_chars=settings.MEMORY_CONTEXT_MAX_CHARS,
        # The reply model, not the routing one. Compressing a conversation is
        # prose reasoning and is not schema-bound, so it avoids the engine
        # defect that pins the bounded classifiers to the 4B - and a weak model
        # here is worse than none, because a summary that invents a detail
        # enters every later prompt as though the user had said it.
        #
        # It runs once per interval, after the reply is already sent, so its
        # latency is never on a user's path. When it fails the coordinator
        # keeps its bounded truncation.
        summariser=get_reasoning_llm_client(),
    )


MemoryCoordinatorDependency = Annotated[
    MemoryCoordinatorAgent, Depends(get_memory_coordinator)
]


# Compose the built-in actions (search, image generation/editing, diagrams,
# specialist handoff) with the user's own registered tools into one native
# tool-calling decision -- not a battery of independent regexes and
# classifiers guessing beforehand. By default this is the same model that
# answers the user (ROUTING_LLM_* unset falls back to MAIN_LLM_*); the two
# can be split when a main-model swap should not also inherit that model's
# untested native tool-calling behaviour.
def get_main_action_selector(
    llm: RoutingLlmDependency,
    invocation: MCPInvocationDependency,
    tool_orchestration: MCPToolOrchestrationDependency,
    diagram_artifacts: DiagramArtifactDependency,
    presentation_jobs: PresentationJobDependency,
) -> MainActionSelector:
    return MainActionSelector(
        llm,
        invocation,
        settings.SEARCH_MCP_SERVER_ID,
        settings.SEARCH_MCP_TOOL_NAME,
        tool_orchestration,
        diagram_enabled=diagram_artifacts is not None,
        presentation_enabled=presentation_jobs is not None,
    )


MainActionSelectorDependency = Annotated[
    MainActionSelector,
    Depends(get_main_action_selector),
]


# Assemble the user-scoped conversation workflow from its application boundaries.
def get_conversation_service(
    memory: MemoryDependency,
    llm: LlmDependency,
    repository: RepositoryDependency,
    tracer: TracerDependency,
    memory_coordinator: MemoryCoordinatorDependency,
    diagram_artifacts: DiagramArtifactDependency,
    search: SearchDependency,
    artifacts: ArtifactRepositoryDependency,
    tool_orchestration: MCPToolOrchestrationDependency,
    main_action_selector: MainActionSelectorDependency,
    image_generation: ImageArtifactDependency,
    image_style: ImageStyleDependency,
    image_refinement: ImageRefinementDependency,
    image_intent: ImageIntentDependency,
    presentation_jobs: PresentationJobDependency,
    discovery_profile: DependencyDiscoveryProfileService,
    discovery_runs: DependencyDiscoveryRuns,
    scheduled_tasks: DependencyScheduledTasks,
    skills: DependencySkills,
    memory_proposals: MemoryProposalDependency,
    agent_memory: DependencyAgentMemoryManager,
    agent_registry: DependencyAgentRegistry,
) -> ConversationService:
    return ConversationService(
        memory=memory,
        llm=llm,
        repository=repository,
        tracer=tracer,
        history_turn_limit=settings.CONVERSATION_HISTORY_TURNS,
        memory_coordinator=memory_coordinator,
        diagram_artifacts=diagram_artifacts,
        agent_registry=agent_registry,
        search=search,
        image_search=artifacts,
        image_artifacts=artifacts,
        # The same repository, asked a different question: what a match was
        # derived from, resolved from the parent edge rather than from whatever
        # else the query happened to return.
        lineage=artifacts,
        image_search_limit=settings.VISION_SEARCH_MAX_RESULTS,
        image_retrieval=ImageRetrievalPolicy(
            max_distance=settings.VISION_SEARCH_MAX_COSINE_DISTANCE,
            cluster_delta=settings.VISION_SEARCH_CLUSTER_DELTA,
        ),
        tool_orchestration=tool_orchestration,
        main_action_selector=main_action_selector,
        image_generation=image_generation,
        image_style=image_style,
        image_refinement=image_refinement,
        image_intent=image_intent,
        presentation_jobs=presentation_jobs,
        presentation_model=(
            settings.PRESENTATION_LLM_MODEL
            or settings.MAIN_LLM_MODEL
            or settings.LLM_MODEL
        ),
        discovery_profile=discovery_profile,
        discovery_runs=discovery_runs,
        scheduled_tasks=scheduled_tasks,
        skills=skills,
        memory_proposals=memory_proposals,
        visual_memory=VisualMemorySelector(get_structured_llm_client()),
        # The modality gate runs before any owner-scoped artifact vector index.
        # Only images have a conversational context loader today; documents,
        # audio and video can join by adding sources to the same contract.
        artifact_context_router=ArtifactContextRouter(
            get_structured_llm_client(), ("image",)
        ),
        agent_memory=agent_memory,
        # A bounded strict-JSON judgement, so it belongs on the routing role
        # with the rest of them rather than on whichever model writes prose.
        referent_resolver=ReferentResolver(get_structured_llm_client()),
        # On the reasoning role deliberately, unlike the strict-JSON
        # callers around it. Writing a search query and judging whether
        # the results answered it are prose, not a schema, so neither is
        # bound to the routing model - and the model that has to use the
        # results is the one that should say what it needs.
        search_planner=SearchPlanner(
            get_reasoning_llm_client(),
            cutoff=settings.MAIN_LLM_TRAINING_CUTOFF,
        ),
    )


DependencyConversationService = Annotated[
    ConversationService, Depends(get_conversation_service)
]
