from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.core.auth import IdentityDependency, authorize_user
from backend.core.dependencies import (
    get_artifact_repository,
    get_conversation_repository,
)
from backend.services.artifact_repository import SQLAlchemyArtifactRepository
from backend.services.repository import SQLAlchemyConversationRepository

router = APIRouter(prefix="/conversations/{user_id}", tags=["conversations"])

ConversationRepositoryDependency = Annotated[
    SQLAlchemyConversationRepository,
    Depends(get_conversation_repository),
]
ArtifactRepositoryDependency = Annotated[
    SQLAlchemyArtifactRepository,
    Depends(get_artifact_repository),
]


# Return persisted turns and artifacts needed to restore one owned conversation.
@router.get("/{conversation_id}")
async def get_conversation_snapshot(
    user_id: str,
    conversation_id: UUID,
    identity: IdentityDependency,
    conversations: ConversationRepositoryDependency,
    artifacts: ArtifactRepositoryDependency,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    conversation_key = str(conversation_id)
    return {
        "conversation_id": conversation_key,
        "turns": await conversations.get_history(
            conversation_key,
            user_id,
            limit,
        ),
        "artifacts": await artifacts.list_for_conversation(
            user_id,
            conversation_key,
        ),
    }
