from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.core.auth import IdentityDependency, authorize_user
from backend.core.dependencies import (
    ImageArtifactDependency,
    get_artifact_repository,
)
from backend.services.artifact_repository import SQLAlchemyArtifactRepository

router = APIRouter(prefix="/artifacts/{user_id}", tags=["artifacts"])

ArtifactRepositoryDependency = Annotated[
    SQLAlchemyArtifactRepository,
    Depends(get_artifact_repository),
]


# List recent visual artifacts owned by one user across conversations.
@router.get("")
async def list_user_artifacts(
    user_id: str,
    repository: ArtifactRepositoryDependency,
    identity: IdentityDependency,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    authorize_user(user_id, identity)
    return await repository.list_for_user(user_id, limit)


# List visual artifacts persisted for one user-owned conversation.
@router.get("/conversations/{conversation_id}")
async def list_conversation_artifacts(
    user_id: str,
    conversation_id: UUID,
    repository: ArtifactRepositoryDependency,
    identity: IdentityDependency,
) -> list[dict[str, Any]]:
    authorize_user(user_id, identity)
    return await repository.list_for_conversation(user_id, str(conversation_id))


# Delete one visual artifact only when it belongs to the requested user.
@router.delete("/{artifact_id}")
async def delete_artifact(
    user_id: str,
    artifact_id: UUID,
    service: ImageArtifactDependency,
    identity: IdentityDependency,
) -> dict[str, str]:
    authorize_user(user_id, identity)
    if not await service.delete_owned(user_id, str(artifact_id)):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"status": "deleted", "id": str(artifact_id)}


# Return one owned binary artifact with strict private response headers.
@router.get("/{artifact_id}/content")
async def get_artifact_content(
    user_id: str,
    artifact_id: UUID,
    service: ImageArtifactDependency,
    identity: IdentityDependency,
) -> Response:
    authorize_user(user_id, identity)
    result = await service.read_owned(user_id, str(artifact_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Artifact content not found")
    artifact, content = result
    return Response(
        content=content,
        media_type=str(artifact["mime_type"]),
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{artifact_id}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
