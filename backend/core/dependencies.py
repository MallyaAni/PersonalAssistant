from typing import Annotated
from fastapi import Depends
from backend.database.session import SessionLocal
from backend.services.impl_placeholder import (
    MockKnowledgeService, 
    MockInternetService, 
    MockNotificationService, 
    MockToolService,
    MockConversationRepository,
    MockContextBuilder,
    MockStreamer,
    MockTracer
)
from backend.services.postgres_memory_service import PostgresMemoryService
from backend.services.conversation_service import ConversationService
from backend.services.repository import SQLAlchemyConversationRepository

# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Production Services
def get_memory_service(db=Depends(get_db)) -> PostgresMemoryService:
    return PostgresMemoryService(db)

knowledge_service = MockKnowledgeService()
internet_service = MockInternetService()
notification_service = MockNotificationService()
tool_service = MockToolService()

# Repository Factory (Session-Scoped)
def get_conversation_repository(db=Depends(get_db)) -> SQLAlchemyConversationRepository:
    return SQLAlchemyConversationRepository(session=db)

# Conversation Service Factory
def get_conversation_service(
    memory: PostgresMemoryService = Depends(get_memory_service),
    knowledge: MockKnowledgeService = Depends(lambda: knowledge_service),
    internet: MockInternetService = Depends(lambda: internet_service),
    notifications: MockNotificationService = Depends(lambda: notification_service),
    tools: MockToolService = Depends(lambda: tool_service),
    repository: SQLAlchemyConversationRepository = Depends(get_conversation_repository),
    context_builder: MockContextBuilder = Depends(lambda: MockContextBuilder()),
    streamer: MockStreamer = Depends(lambda: MockStreamer()),
    tracer: MockTracer = Depends(lambda: MockTracer())
) -> ConversationService:
    return ConversationService(
        memory=memory,
        knowledge=knowledge,
        internet=internet,
        notifications=notifications,
        tools=tools,
        repository=repository,
        context_builder=context_builder,
        streamer=streamer,
        tracer=tracer
    )

# Dependency Aliases for FastAPI route handlers
DependencyGetDb = Annotated[SessionLocal, Depends(get_db)]
DependencyConversationService = Annotated[ConversationService, Depends(get_conversation_service)]