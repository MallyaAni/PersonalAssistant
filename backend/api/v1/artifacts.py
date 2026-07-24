from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.artifacts.image_retrieval import ImageRetrievalPolicy
from backend.config.settings import settings
from backend.core.auth import (
    SCOPE_VISION,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import (
    ImageArtifactDependency,
    MemoryDependency,
    get_artifact_repository,
)
from backend.services.artifact_repository import SQLAlchemyArtifactRepository

router = APIRouter(prefix="/artifacts/{user_id}", tags=["artifacts"])

ArtifactRepositoryDependency = Annotated[
    SQLAlchemyArtifactRepository,
    Depends(get_artifact_repository),
]


# Find owned images whose pixels match a text query, using the aligned space.
# This is deliberately a separate route from text memory search: cross-modal
# cosine scores are not comparable to text-text scores, so the two rankings
# cannot be merged into one list by raw distance.
@router.get("/search/images")
async def search_images(
    user_id: str,
    repository: ArtifactRepositoryDependency,
    memory: MemoryDependency,
    identity: IdentityDependency,
    query: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, Any]]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
    # The text embedder applies the search_query prefix Nomic requires for
    # multimodal retrieval, placing the query in the shared image/text space.
    vector = await memory.embed_query(query)
    # Over-fetch so the policy can inspect the runner up before filtering.
    policy = ImageRetrievalPolicy(
        max_distance=settings.VISION_SEARCH_MAX_COSINE_DISTANCE,
        min_margin=settings.VISION_SEARCH_MIN_MARGIN,
    )
    ranked = await repository.search_by_embedding(
        user_id,
        vector,
        max(limit, 2),
        ImageRetrievalPolicy.CANDIDATE_CEILING,
    )
    return policy.select(ranked)[:limit]


# List recent visual artifacts owned by one user across conversations.
@router.get("")
async def list_user_artifacts(
    user_id: str,
    repository: ArtifactRepositoryDependency,
    identity: IdentityDependency,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
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
    authorize_scope(identity, SCOPE_VISION)
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
    authorize_scope(identity, SCOPE_VISION)
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
    authorize_scope(identity, SCOPE_VISION)
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
