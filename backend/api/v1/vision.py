import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from backend.config.settings import settings
from backend.core.auth import (
    SCOPE_VISION,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import TracerDependency, VisionAnalysisDependency
from backend.models.image import ImageQuestionBody
from backend.services.vision_analysis_service import (
    ArtifactNotFoundError,
    VisionAnalysisError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vision", tags=["vision"])


class UploadTooLargeError(ValueError):
    """Signals that a streamed upload crossed the configured byte limit."""


# Read an upload in bounded chunks without trusting its declared length.
async def _read_bounded_upload(upload: UploadFile, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(min(1024 * 1024, maximum_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_bytes:
            raise UploadTooLargeError("Uploaded image exceeds the byte limit")
    return b"".join(chunks)


# Validate, persist, and analyze one owned image upload with the local VLM.
@router.post("/analyze", status_code=status.HTTP_201_CREATED)
async def analyze_image_upload(
    user_id: Annotated[str, Form(min_length=1, max_length=50)],
    conversation_id: Annotated[UUID, Form()],
    prompt: Annotated[str, Form(min_length=1, max_length=2_000)],
    image: Annotated[UploadFile, File()],
    service: VisionAnalysisDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    normalized_user_id = user_id.strip()
    normalized_prompt = prompt.strip()
    if not normalized_user_id or not normalized_prompt:
        raise HTTPException(status_code=422, detail="Text fields must not be blank")
    authorize_user(normalized_user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
    trace_id = tracer.start_trace(normalized_user_id)
    try:
        content = await _read_bounded_upload(
            image,
            settings.IMAGE_MAX_UPLOAD_BYTES,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Uploaded image is too large.",
        ) from exc
    finally:
        await image.close()
    try:
        return await service.analyze_upload(
            user_id=normalized_user_id,
            conversation_id=str(conversation_id),
            trace_id=trace_id,
            prompt=normalized_prompt,
            content=content,
            declared_mime_type=image.content_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded image is invalid or unsupported.",
        ) from exc
    except VisionAnalysisError as exc:
        logger.exception("Vision analysis failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Unable to analyze the uploaded image.",
                "artifact_id": exc.artifact_id,
            },
        ) from exc
    except Exception as exc:
        logger.exception("Image upload failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to store the uploaded image.",
        ) from exc


# Answer one followup question about an already-owned generated or uploaded image.
@router.post("/artifacts/{artifact_id}/ask", status_code=status.HTTP_200_OK)
async def ask_about_image(
    artifact_id: UUID,
    body: ImageQuestionBody,
    service: VisionAnalysisDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
    trace_id = tracer.start_trace(body.user_id)
    try:
        return await service.ask_about_artifact(
            user_id=body.user_id,
            artifact_id=str(artifact_id),
            prompt=body.prompt,
        )
    except ArtifactNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found.",
        ) from exc
    except VisionAnalysisError as exc:
        logger.exception("Vision followup failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Unable to answer the question about this image.",
                "artifact_id": exc.artifact_id,
            },
        ) from exc
    except Exception as exc:
        logger.exception("Image followup failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to process the question about this image.",
        ) from exc
