from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.diagram import DiagramAgent
from backend.artifacts.diagram import LLMDiagramProvider
from backend.artifacts.image import ComfyUIImageProvider
from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.config.settings import settings
from backend.core.interfaces import SearchProvider, VisionEmbeddingProvider
from backend.core.llm import LLMClient, LMStudioLLM
from backend.database.session import get_db
from backend.embeddings.base import EmbeddingProvider
from backend.embeddings.lm_studio import LMStudioEmbeddingProvider
from backend.embeddings.nomic_vision import NomicVisionEmbeddingProvider
from backend.memory.coordinator import MemoryCoordinatorAgent
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.search.cascade import CascadingSearchRouter
from backend.search.classifier import LMStudioFreshnessClassifier
from backend.search.image_retrieval import ImageRetrievalPolicy
from backend.search.image_routing import ImageRecallPolicy
from backend.search.routing import SearchRoutingPolicy
from backend.search.tavily import TavilySearchProvider
from backend.services.agent_memory_manager import AgentMemoryManager
from backend.services.artifact_repository import SQLAlchemyArtifactRepository
from backend.services.conversation_service import ConversationService
from backend.services.diagram_artifact_service import DiagramArtifactService
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.memory_operations_service import MemoryOperationsService
from backend.services.memory_reembedding_service import MemoryReembeddingService
from backend.services.memory_retention_service import MemoryRetentionService
from backend.services.postgres_memory_service import PostgresMemoryService
from backend.services.repository import SQLAlchemyConversationRepository
from backend.services.tool_memory_service import ToolMemoryService
from backend.services.tracing import LoggingConversationTracer
from backend.services.vision_analysis_service import VisionAnalysisService
from backend.vision.lm_studio import LMStudioVisionProvider


# Reuse one concurrency-limited embedding adapter across application requests.
@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return LMStudioEmbeddingProvider(
        base_url=settings.LLM_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimension=settings.EMBEDDING_DIMENSION,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_concurrency=settings.EMBEDDING_MAX_CONCURRENCY,
    )


# Reuse one configured search adapter; it is disabled when no key is present.
@lru_cache(maxsize=1)
def get_search_provider() -> SearchProvider:
    return TavilySearchProvider(
        base_url=settings.SEARCH_BASE_URL,
        api_key=settings.SEARCH_API_KEY,
        max_results=settings.SEARCH_MAX_RESULTS,
        timeout_seconds=settings.SEARCH_TIMEOUT_SECONDS,
        max_content_chars=settings.SEARCH_MAX_CONTENT_CHARS,
        min_score=settings.SEARCH_MIN_SCORE,
        search_depth=settings.SEARCH_DEPTH,
    )


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


def get_llm_client() -> LLMClient:
    return LMStudioLLM(
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=settings.LLM_REASONING_EFFORT,
    )


def get_conversation_repository(
    db: DbDependency,
) -> SQLAlchemyConversationRepository:
    return SQLAlchemyConversationRepository(session=db)


def get_conversation_tracer() -> LoggingConversationTracer:
    return LoggingConversationTracer()


MemoryDependency = Annotated[
    PostgresMemoryService,
    Depends(get_memory_service),
]
LlmDependency = Annotated[LLMClient, Depends(get_llm_client)]
RepositoryDependency = Annotated[
    SQLAlchemyConversationRepository,
    Depends(get_conversation_repository),
]
TracerDependency = Annotated[
    LoggingConversationTracer,
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


# Reuse one concurrency-limited ComfyUI image provider across requests.
@lru_cache(maxsize=1)
def get_image_provider() -> ComfyUIImageProvider:
    return ComfyUIImageProvider(
        base_url=settings.IMAGE_PROVIDER_BASE_URL,
        model=settings.IMAGE_MODEL,
        timeout_seconds=settings.IMAGE_PROVIDER_TIMEOUT_SECONDS,
        poll_seconds=settings.IMAGE_PROVIDER_POLL_SECONDS,
        max_concurrency=settings.IMAGE_MAX_CONCURRENCY,
        max_output_bytes=settings.IMAGE_MAX_OUTPUT_BYTES,
        max_pixels=settings.IMAGE_MAX_PIXELS,
    )


ImageProviderDependency = Annotated[
    ComfyUIImageProvider,
    Depends(get_image_provider),
]


# Coordinate image generation, storage, integrity, and terminal lifecycle state.
def get_image_artifact_service(
    provider: ImageProviderDependency,
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
    )


ImageArtifactDependency = Annotated[
    ImageArtifactService,
    Depends(get_image_artifact_service),
]


# Reuse one local Gemma vision adapter without granting it storage authority.
@lru_cache(maxsize=1)
def get_vision_provider() -> LMStudioVisionProvider:
    return LMStudioVisionProvider(
        base_url=settings.LLM_BASE_URL,
        model=settings.VISION_MODEL,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=settings.LLM_REASONING_EFFORT,
        max_tokens=settings.VISION_MAX_TOKENS,
    )


VisionProviderDependency = Annotated[
    LMStudioVisionProvider,
    Depends(get_vision_provider),
]


# Coordinate validated uploads with grounded local vision analysis.
def get_vision_analysis_service(
    images: ImageArtifactDependency,
    repository: ArtifactRepositoryDependency,
    provider: VisionProviderDependency,
    memory: MemoryDependency,
) -> VisionAnalysisService:
    return VisionAnalysisService(
        images,
        repository,
        provider,
        thread_context_turns=settings.VISION_THREAD_CONTEXT_TURNS,
        thread_max_stored=settings.VISION_THREAD_MAX_STORED,
        memory=memory,
    )


VisionAnalysisDependency = Annotated[
    VisionAnalysisService,
    Depends(get_vision_analysis_service),
]


# Build the replaceable diagram provider around the configured local model.
def get_diagram_provider(llm: LlmDependency) -> LLMDiagramProvider:
    return LLMDiagramProvider(llm, settings.LLM_MODEL)


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
        provider_name="lm_studio",
        model_name=settings.LLM_MODEL,
    )


DiagramArtifactDependency = Annotated[
    DiagramArtifactService,
    Depends(get_diagram_artifact_service),
]


DependencyMemoryService = Annotated[PostgresMemoryService, Depends(get_memory_service)]


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


ImageRecallDependency = Annotated[
    ImageRecallPolicy,
    Depends(get_image_recall_policy),
]


# Serve the routing classifier from a dedicated model when one is configured,
# otherwise reuse the chat model.
@lru_cache(maxsize=1)
def get_classifier_llm() -> LLMClient:
    if not settings.SEARCH_CLASSIFIER_MODEL:
        return get_llm_client()
    return LMStudioLLM(
        base_url=settings.LLM_BASE_URL,
        model=settings.SEARCH_CLASSIFIER_MODEL,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        reasoning_effort=settings.LLM_REASONING_EFFORT,
    )


# Compose free deterministic patterns with a bounded classifier fallback. The
# classifier returns a judgement about the question, never a tool call, so the
# application keeps ownership of routing.
@lru_cache(maxsize=1)
def get_search_router() -> CascadingSearchRouter:
    classifier = (
        LMStudioFreshnessClassifier(
            get_classifier_llm(),
            max_tokens=settings.SEARCH_CLASSIFIER_MAX_TOKENS,
        )
        if settings.SEARCH_CLASSIFIER_ENABLED
        else None
    )
    return CascadingSearchRouter(
        patterns=SearchRoutingPolicy(current_year=datetime.now(UTC).year),
        classifier=classifier,
    )


SearchRoutingDependency = Annotated[
    CascadingSearchRouter,
    Depends(get_search_router),
]


def get_conversation_service(
    memory: MemoryDependency,
    llm: LlmDependency,
    repository: RepositoryDependency,
    tracer: TracerDependency,
    memory_coordinator: MemoryCoordinatorDependency,
    diagram_artifacts: DiagramArtifactDependency,
    search: SearchDependency,
    search_routing: SearchRoutingDependency,
    artifacts: ArtifactRepositoryDependency,
    image_recall: ImageRecallDependency,
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
        search_routing=search_routing,
        image_recall=image_recall,
        image_search=artifacts,
        image_search_limit=settings.VISION_SEARCH_MAX_RESULTS,
        image_retrieval=ImageRetrievalPolicy(
            max_distance=settings.VISION_SEARCH_MAX_COSINE_DISTANCE,
            min_margin=settings.VISION_SEARCH_MIN_MARGIN,
        ),
    )


DependencyConversationService = Annotated[
    ConversationService, Depends(get_conversation_service)
]
