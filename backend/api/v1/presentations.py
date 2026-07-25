import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from backend.core.auth import (
    SCOPE_PRESENTATIONS,
    SCOPE_VISION,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import (
    PresentationDependency,
    PresentationImageDependency,
    TracerDependency,
)
from backend.models.presentation_api import (
    CreatePresentationBody,
    GeneratePresentationSlideImageBody,
    RevisePresentationSlideBody,
)
from backend.services.presentation_repository import PresentationConflictError

router = APIRouter(prefix="/presentations", tags=["presentations"])


# Encode one presentation lifecycle event as a valid SSE frame.
def _presentation_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Create one editable deck and return its active specification and revision.
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_presentation(
    body: CreatePresentationBody,
    service: PresentationDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    trace_id = tracer.start_trace(body.user_id)
    try:
        return await service.create(
            body.user_id,
            str(body.conversation_id),
            trace_id,
            body.prompt,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to create the presentation.",
        ) from exc


# Stream slide previews as Gemma plans them, then return the promoted ready deck.
@router.post("/stream")
async def stream_presentation(
    body: CreatePresentationBody,
    service: PresentationDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> StreamingResponse:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    trace_id = tracer.start_trace(body.user_id)

    # Keep dependency-owned persistence alive for the complete streamed lifecycle.
    async def events() -> AsyncIterator[str]:
        async for item in service.create_progress(
            body.user_id,
            str(body.conversation_id),
            trace_id,
            body.prompt,
        ):
            yield _presentation_event(item["event"], item["data"])

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# List recent presentations owned by one user.
@router.get("/{user_id}")
async def list_presentations(
    user_id: str,
    service: PresentationDependency,
    identity: IdentityDependency,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    return await service.list(user_id, limit)


# Return one owned deck with its current spec and append-only revision history.
@router.get("/{user_id}/{presentation_id}")
async def get_presentation(
    user_id: str,
    presentation_id: UUID,
    service: PresentationDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    presentation = await service.get(user_id, str(presentation_id))
    if presentation is None:
        raise HTTPException(status_code=404, detail="Presentation was not found")
    return presentation


# Apply feedback to one selected slide and create a new linked revision.
@router.post(
    "/{user_id}/{presentation_id}/slides/{slide_id}/revisions",
    status_code=status.HTTP_201_CREATED,
)
async def revise_presentation_slide(
    user_id: str,
    presentation_id: UUID,
    slide_id: str,
    body: RevisePresentationSlideBody,
    service: PresentationDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    try:
        return await service.revise_slide(
            user_id,
            str(presentation_id),
            str(body.base_revision_id),
            slide_id,
            body.feedback,
        )
    except PresentationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to revise the presentation.",
        ) from exc


# Generate and attach one local image as a new selected-slide revision.
@router.post(
    "/{user_id}/{presentation_id}/slides/{slide_id}/image",
    status_code=status.HTTP_201_CREATED,
)
async def generate_presentation_slide_image(
    user_id: str,
    presentation_id: UUID,
    slide_id: str,
    body: GeneratePresentationSlideImageBody,
    service: PresentationImageDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    authorize_scope(identity, SCOPE_VISION)
    trace_id = tracer.start_trace(user_id)
    try:
        return await service.enrich_slide(
            user_id,
            str(presentation_id),
            str(body.base_revision_id),
            slide_id,
            trace_id,
            body.prompt,
        )
    except PresentationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to generate imagery for the presentation.",
        ) from exc


# Download one owned ready revision as an editable PowerPoint file.
@router.get("/{user_id}/{presentation_id}/revisions/{revision_id}/content")
async def download_presentation(
    user_id: str,
    presentation_id: UUID,
    revision_id: UUID,
    service: PresentationDependency,
    identity: IdentityDependency,
) -> Response:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    result = await service.download(
        user_id,
        str(presentation_id),
        str(revision_id),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Presentation file was not found")
    filename, content = result
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


# Delete one owned deck, every revision row, and each linked binary.
@router.delete("/{user_id}/{presentation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_presentation(
    user_id: str,
    presentation_id: UUID,
    service: PresentationDependency,
    identity: IdentityDependency,
) -> Response:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    deleted = await service.delete(user_id, str(presentation_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Presentation was not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
