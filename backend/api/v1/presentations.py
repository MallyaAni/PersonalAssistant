import asyncio
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
    PresentationJobDependency,
    TracerDependency,
)
from backend.models.presentation_api import (
    AddPresentationSlideBody,
    CreatePresentationBody,
    GeneratePresentationSlideImageBody,
    RevisePresentationSlideBody,
)
from backend.services.image_refinement_service import RefinementError
from backend.services.presentation_repository import PresentationConflictError

router = APIRouter(prefix="/presentations", tags=["presentations"])


# Encode one presentation lifecycle event as a valid SSE frame.
def _presentation_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Queue one editable deck without keeping model work in the API request.
@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_presentation(
    body: CreatePresentationBody,
    jobs: PresentationJobDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    trace_id = tracer.start_trace(body.user_id)
    try:
        return await jobs.enqueue(
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


# Queue a durable job and stream its persisted progress for legacy clients.
@router.post("/stream")
async def stream_presentation(
    body: CreatePresentationBody,
    jobs: PresentationJobDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> StreamingResponse:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    trace_id = tracer.start_trace(body.user_id)

    job = await jobs.enqueue(
        body.user_id,
        str(body.conversation_id),
        trace_id,
        body.prompt,
    )

    # Poll durable state so disconnecting this stream never cancels model work.
    async def events() -> AsyncIterator[str]:
        yield _presentation_event(
            "started",
            {
                "job_id": job["id"],
                "presentation_id": job["presentation_id"],
                "revision_id": job["revision_id"],
                "trace_id": trace_id,
            },
        )
        last_draft = ""
        while True:
            current = await jobs.get(body.user_id, str(job["id"]))
            if current is None:
                yield _presentation_event(
                    "error",
                    {"message": "Presentation job was not found."},
                )
                break
            draft = current.get("draft_specification")
            if isinstance(draft, dict):
                encoded = json.dumps(draft, sort_keys=True)
                if encoded != last_draft:
                    last_draft = encoded
                    yield _presentation_event(
                        "draft",
                        {
                            "specification": draft,
                            "expected_slide_count": current.get("expected_slide_count"),
                        },
                    )
            if current["status"] == "ready":
                yield _presentation_event(
                    "ready",
                    {"presentation": current["presentation"]},
                )
                break
            if current["status"] in {"failed", "cancelled"}:
                yield _presentation_event(
                    "error",
                    {
                        "message": "Unable to create the presentation.",
                        "presentation_id": current["presentation_id"],
                    },
                )
                break
            await asyncio.sleep(0.5)
        yield _presentation_event("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# Return reconnectable progress for one user-owned presentation job.
@router.get("/jobs/{user_id}/{job_id}")
async def get_presentation_job(
    user_id: str,
    job_id: UUID,
    jobs: PresentationJobDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    job = await jobs.get(user_id, str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Presentation job was not found")
    return job


# Request cooperative cancellation of one queued or running presentation job.
@router.delete("/jobs/{user_id}/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_presentation_job(
    user_id: str,
    job_id: UUID,
    jobs: PresentationJobDependency,
    identity: IdentityDependency,
) -> Response:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    if not await jobs.cancel(user_id, str(job_id)):
        raise HTTPException(status_code=404, detail="Presentation job was not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


# Add one slide to an existing deck as a linked revision. Distinct from a slide
# revision: this leaves every existing slide exactly as the user accepted it.
@router.post(
    "/{user_id}/{presentation_id}/slides",
    status_code=status.HTTP_201_CREATED,
)
async def add_presentation_slide(
    user_id: str,
    presentation_id: UUID,
    body: AddPresentationSlideBody,
    service: PresentationDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    try:
        return await service.add_slide(
            user_id,
            str(presentation_id),
            str(body.base_revision_id),
            body.brief,
            body.after_slide_id,
        )
    except PresentationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to add the slide.",
        ) from exc


# Remove one slide as a linked revision. The base revision travels as a query
# parameter because a DELETE body is not reliably transmitted.
@router.delete(
    "/{user_id}/{presentation_id}/slides/{slide_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_presentation_slide(
    user_id: str,
    presentation_id: UUID,
    slide_id: str,
    base_revision_id: UUID,
    service: PresentationDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_PRESENTATIONS)
    try:
        return await service.delete_slide(
            user_id,
            str(presentation_id),
            str(base_revision_id),
            slide_id,
        )
    except PresentationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to delete the slide.",
        ) from exc


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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RefinementError as exc:
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
