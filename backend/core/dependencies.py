import logging
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.deck.agent import PresentationAgent
from backend.agents.diagram import DiagramAgent
from backend.agents.registry import AgentRegistry
from backend.agents.scout.digesting import DigestWriter
from backend.agents.scout.place_suggest import PlaceSuggester
from backend.agents.vision.memory import VisualMemorySelector
from backend.artifacts.diagram import LLMDiagramProvider
from backend.artifacts.image import (
    ComfyUIImageEditProvider,
    ComfyUIImageProvider,
)
from backend.artifacts.image_recall_classifier import LMStudioImageRecallClassifier
from backend.artifacts.image_recall_router import CascadingImageRecallRouter
from backend.artifacts.image_retrieval import ImageRetrievalPolicy
from backend.artifacts.image_routing import ImageRecallPolicy
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
    FallbackInferenceProvider,
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
from backend.services.repository import SQLAlchemyConversationRepository
from backend.services.tool_memory_service import ToolMemoryService
from backend.services.tracing import (
    LoggingConversationTracer,
    OpenTelemetryConversationTracer,
)
from backend.services.vision_analysis_service import VisionAnalysisService
from backend.services.visual_search_grounding import VisualSearchGrounding
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
    return BudgetedSearchProvider(_build_search_provider(), get_search_budget())


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
# Wrapped in a standby when one is configured, because the main model now runs
# on a separate machine that is not always powered on. Without this the whole
# assistant is down whenever that host is - every reply, route and
# classification raising a connection error - while a perfectly healthy smaller
# model sits unused on this box.
def get_llm_client() -> LLMClient:
    primary = _build_llm_client(
        settings.MAIN_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        settings.MAIN_LLM_BASE_URL or settings.LLM_BASE_URL,
        settings.MAIN_LLM_MODEL or settings.LLM_MODEL,
        settings.MAIN_LLM_REASONING_EFFORT,
    )
    if not settings.MAIN_LLM_STANDBY_BASE_URL:
        return primary
    return FallbackInferenceProvider(
        primary,
        _build_llm_client(
            settings.MAIN_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
            settings.MAIN_LLM_STANDBY_BASE_URL,
            settings.MAIN_LLM_STANDBY_MODEL or settings.LLM_MODEL,
            settings.MAIN_LLM_STANDBY_REASONING_EFFORT,
        ),
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


# Build the focused presentation model independently from the main agent.
def get_presentation_llm_client() -> LLMClient:
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


# Build the small structured classifier independently from the response role.
def get_memory_proposal_llm_client() -> LLMClient:
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
        model=settings.IMAGE_MODEL,
        timeout_seconds=settings.IMAGE_PROVIDER_TIMEOUT_SECONDS,
        poll_seconds=settings.IMAGE_PROVIDER_POLL_SECONDS,
        max_concurrency=settings.IMAGE_MAX_CONCURRENCY,
        max_output_bytes=settings.IMAGE_MAX_OUTPUT_BYTES,
        max_pixels=settings.IMAGE_MAX_PIXELS,
        style_suffix=settings.IMAGE_STYLE_SUFFIX,
        portrait_suffix=settings.IMAGE_PORTRAIT_SUFFIX,
        negative_prompt=settings.IMAGE_NEGATIVE_PROMPT,
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
    return ComfyUIImageEditProvider(
        base_url=settings.IMAGE_PROVIDER_BASE_URL,
        model=settings.IMAGE_EDIT_MODEL,
        text_encoder=settings.IMAGE_EDIT_TEXT_ENCODER,
        vae=settings.IMAGE_EDIT_VAE,
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
) -> ImageArtifactService:
    return ImageArtifactService(
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
        edit_model_name=settings.IMAGE_EDIT_MODEL,
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
    return ImageRefinementService(images=images, vision=observer)


ImageRefinementDependency = Annotated[
    ImageRefinementService,
    Depends(get_image_refinement_service),
]


# Coordinate initial HiDream slide imagery and source-conditioned FLUX revisions.
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


VisionProviderDependency = Annotated[
    VisionProvider,
    Depends(get_vision_provider),
]


# Give both image paths one routing decision, made by the main conversation
# model — the same model that used to answer "I cannot edit images" when an edit
# request reached it as chat.
def get_image_intent_classifier(llm: RoutingLlmDependency) -> ImageIntentClassifier:
    # The routing model, not the main one. This is a constrained classification
    # into a 16-token JSON schema, which is the routing model's proven job and
    # not what the main model was promoted for: pointed at DeepSeek it returned
    # unparseable content on every upload, and because the classifier answers
    # False on any failure, that silently disabled edit-intent detection - an
    # "edit this photo" upload was quietly treated as a question about it.
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
    intent: ImageIntentDependency,
    llm: LlmDependency,
    routing_llm: RoutingLlmDependency,
) -> VisionAnalysisService:
    return VisionAnalysisService(
        images,
        repository,
        provider,
        thread_context_turns=settings.VISION_THREAD_CONTEXT_TURNS,
        thread_max_stored=settings.VISION_THREAD_MAX_STORED,
        memory=memory,
        intent=intent,
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
    )


VisionAnalysisDependency = Annotated[
    VisionAnalysisService,
    Depends(get_vision_analysis_service),
]


# Build the replaceable diagram provider around its configured local model.
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
@lru_cache(maxsize=1)
def get_place_suggester() -> PlaceSuggester:
    return PlaceSuggester(get_llm_client())


DependencyPlaceSuggester = Annotated[
    PlaceSuggester,
    Depends(get_place_suggester),
]


# Writes the digest message. Assembled here rather than inside delivery so the
# same runtime that describes a find also words the message about it, and so a
# deployment with no model still delivers — `DigestWriter(None)` renders the
# assembled shape instead of failing.
def get_digest_writer() -> DigestWriter:
    return DigestWriter(get_llm_client())


# Reads tapbacks off the bubbles already sent, through the same trusted MCP
# boundary the send itself uses, so the same allowlist and audit apply.
def get_reaction_collector(session: AsyncSession) -> ReactionCollector:
    return ReactionCollector(
        SentFindRepository(session),
        _invoke_discovery_tool,
        settings.DISCOVERY_REACTIONS_TOOL,
    )


def get_discovery_runner(
    db: DbDependency,
    embeddings: EmbeddingDependency,
) -> DiscoveryRunner:
    return DiscoveryRunner(
        sources=DiscoverySourceRepository(db),
        seen=SeenItemRepository(db),
        embeddings=embeddings,
        search=get_search_provider(),
        writer=get_llm_client(),
        search_budget=get_search_budget(),
        cross_encoder=get_cross_encoder(),
    )


DependencyDiscoveryRunner = Annotated[
    DiscoveryRunner,
    Depends(get_discovery_runner),
]


# The same runner, assembled for a background worker that owns its own session
# rather than receiving one from a request.
def get_discovery_runner_for_session(session: AsyncSession) -> DiscoveryRunner:
    return DiscoveryRunner(
        sources=DiscoverySourceRepository(session),
        seen=SeenItemRepository(session),
        embeddings=get_embedding_provider(),
        search=get_search_provider(),
        writer=get_llm_client(),
        search_budget=get_search_budget(),
        cross_encoder=get_cross_encoder(),
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
    )


MemoryCoordinatorDependency = Annotated[
    MemoryCoordinatorAgent, Depends(get_memory_coordinator)
]


# Assemble the conversation service with model, memory, and repository dependencies.
# Reuse one deterministic image-recall policy; the model never selects it.
@lru_cache(maxsize=1)
def get_image_recall_policy() -> ImageRecallPolicy:
    return ImageRecallPolicy()


# Serve the routing classifier from a dedicated model when one is configured,
# otherwise reuse the chat model's configuration.
#
# Deliberately not cached. A provider serializes its own calls on an internal
# lock, so one shared instance would make every concurrent chat queue behind
# another chat's classifier call. A fresh client per router keeps the routing
# decisions independent, and the runtime already serves several sequences.
def get_classifier_llm() -> LLMClient:
    if not settings.SEARCH_CLASSIFIER_MODEL:
        return get_llm_client()
    return _build_llm_client(
        settings.MAIN_INFERENCE_ADAPTER or settings.INFERENCE_ADAPTER,
        base_url=settings.MAIN_LLM_BASE_URL or settings.LLM_BASE_URL,
        model=settings.SEARCH_CLASSIFIER_MODEL,
        reasoning_effort=settings.MAIN_LLM_REASONING_EFFORT,
    )


# Deterministic recall patterns with a bounded classifier fallback for novel
# phrasings; the classifier is gated to plausibly-image queries so unrelated
# turns never pay for it, and it judges intent rather than selecting a tool.
@lru_cache(maxsize=1)
def get_image_recall_router() -> CascadingImageRecallRouter:
    classifier = (
        LMStudioImageRecallClassifier(
            get_classifier_llm(),
            max_tokens=settings.IMAGE_RECALL_CLASSIFIER_MAX_TOKENS,
        )
        if settings.IMAGE_RECALL_CLASSIFIER_ENABLED
        else None
    )
    return CascadingImageRecallRouter(get_image_recall_policy(), classifier)


ImageRecallDependency = Annotated[
    CascadingImageRecallRouter,
    Depends(get_image_recall_router),
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


def get_conversation_service(
    memory: MemoryDependency,
    llm: LlmDependency,
    repository: RepositoryDependency,
    tracer: TracerDependency,
    memory_coordinator: MemoryCoordinatorDependency,
    diagram_artifacts: DiagramArtifactDependency,
    search: SearchDependency,
    artifacts: ArtifactRepositoryDependency,
    image_recall: ImageRecallDependency,
    tool_orchestration: MCPToolOrchestrationDependency,
    main_action_selector: MainActionSelectorDependency,
    image_generation: ImageArtifactDependency,
    image_style: ImageStyleDependency,
    image_refinement: ImageRefinementDependency,
    presentation_jobs: PresentationJobDependency,
    discovery_profile: DependencyDiscoveryProfileService,
    memory_proposals: MemoryProposalDependency,
    agent_memory: DependencyAgentMemoryManager,
) -> ConversationService:
    return ConversationService(
        memory=memory,
        llm=llm,
        repository=repository,
        tracer=tracer,
        history_turn_limit=settings.CONVERSATION_HISTORY_TURNS,
        memory_coordinator=memory_coordinator,
        diagram_artifacts=diagram_artifacts,
        search=search,
        image_recall=image_recall,
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
        presentation_jobs=presentation_jobs,
        presentation_model=(
            settings.PRESENTATION_LLM_MODEL
            or settings.MAIN_LLM_MODEL
            or settings.LLM_MODEL
        ),
        discovery_profile=discovery_profile,
        memory_proposals=memory_proposals,
        visual_memory=VisualMemorySelector(get_classifier_llm()),
        agent_memory=agent_memory,
    )


DependencyConversationService = Annotated[
    ConversationService, Depends(get_conversation_service)
]
