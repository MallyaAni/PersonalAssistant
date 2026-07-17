from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.config.settings import settings
from backend.core.llm import LLMClient, LMStudioLLM
from backend.database.session import get_db
from backend.embeddings.base import EmbeddingProvider
from backend.embeddings.lm_studio import LMStudioEmbeddingProvider
from backend.memory.retrieval import SemanticRetrievalPolicy
from backend.services.conversation_service import ConversationService
from backend.services.postgres_memory_service import PostgresMemoryService
from backend.services.repository import SQLAlchemyConversationRepository
from backend.services.tool_memory_service import ToolMemoryService
from backend.services.tracing import LoggingConversationTracer


def get_embedding_provider() -> EmbeddingProvider:
    return LMStudioEmbeddingProvider(
        base_url=settings.LLM_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimension=settings.EMBEDDING_DIMENSION,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )


DbDependency = Annotated[Session, Depends(get_db)]
EmbeddingDependency = Annotated[
    EmbeddingProvider,
    Depends(get_embedding_provider),
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


def get_conversation_service(
    memory: MemoryDependency,
    llm: LlmDependency,
    repository: RepositoryDependency,
    tracer: TracerDependency,
) -> ConversationService:
    return ConversationService(
        memory=memory,
        llm=llm,
        repository=repository,
        tracer=tracer,
        history_turn_limit=settings.CONVERSATION_HISTORY_TURNS,
    )


DependencyMemoryService = Annotated[PostgresMemoryService, Depends(get_memory_service)]
DependencyConversationService = Annotated[
    ConversationService, Depends(get_conversation_service)
]


def get_tool_memory_service(
    db: DbDependency,
    embeddings: EmbeddingDependency,
) -> ToolMemoryService:
    return ToolMemoryService(
        db,
        embeddings,
        SemanticRetrievalPolicy(
            max_cosine_distance=settings.MEMORY_SEMANTIC_MAX_COSINE_DISTANCE,
            max_results=settings.MEMORY_SEMANTIC_MAX_RESULTS,
            max_content_chars=settings.MEMORY_SEMANTIC_MAX_CONTENT_CHARS,
        ),
        settings.EMBEDDING_MODEL_VERSION,
    )


DependencyToolMemoryService = Annotated[
    ToolMemoryService, Depends(get_tool_memory_service)
]
