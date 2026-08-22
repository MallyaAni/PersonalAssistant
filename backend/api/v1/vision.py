import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from backend.config.settings import settings
from backend.core.auth import (
    SCOPE_VISION,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import (
    TracerDependency,
    VisionAnalysisDependency,
    build_deferred_vision_service,
)
from backend.database.session import AsyncSessionLocal
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


# Finish one deferred reasoning pass on its own session, after the reply went out.
#
# Builds its own service rather than reusing the request's: that one holds a
# session which closes with the response. Every failure is swallowed after
# logging, because the user already has a usable answer on screen and the only
# thing at stake here is replacing it with a better one.
async def _finish_reasoning(user_id: str, artifact_id: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            service = build_deferred_vision_service(db)
            improved = await service.finish_deferred_reasoning(user_id, artifact_id)
        if improved:
            logger.info("Reasoned answer stored for artifact %s", artifact_id)
    except Exception:
        logger.warning(
            "Deferred visual reasoning failed for artifact %s",
            artifact_id,
            exc_info=True,
        )


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
    background: BackgroundTasks,
    # Deferred by default for the browser, whose phone can lock mid-upload:
    # it gets a fast answer and the reasoned one lands on the artifact behind
    # it. A caller that delivers over a channel with no second look - the
    # iMessage worker - asks for the reasoning inline instead, because the
    # reply it sends is the only answer its reader will ever see.
    defer_reasoning: Annotated[bool, Form()] = True,
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
        result = await service.analyze_upload(
            user_id=normalized_user_id,
            conversation_id=str(conversation_id),
            trace_id=trace_id,
            prompt=normalized_prompt,
            content=content,
            declared_mime_type=image.content_type,
            defer_reasoning=defer_reasoning,
        )
        # Runs after this response is delivered, on its own session, because
        # the request's session closes with the reply. Holding the connection
        # open for the reasoning chain instead is what made a phone that locks
        # mid-upload report a failure for work the server completed.
        if result.get("reasoning_pending"):
            background.add_task(
                _finish_reasoning,
                normalized_user_id,
                str(result["artifact"]["id"]),
            )
        return result
    except ValueError as exc:
        # The reply to the user stays deliberately vague, but the log must not:
        # this branch previously recorded nothing at all, so a rejected upload
        # was indistinguishable from any other - format, dimensions, a declared
        # type that did not match, or a ValueError raised much deeper in the
        # call - and the only way to tell was to guess and redeploy.
        logger.warning(
            "Rejected image upload: %s (declared_type=%r, bytes=%d)",
            exc,
            image.content_type,
            len(content),
            extra={"trace_id": trace_id},
        )
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
