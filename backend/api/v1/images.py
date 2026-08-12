import asyncio
import logging
import secrets
from contextlib import suppress
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status

from backend.artifacts.types import ImageGenerationRequest
from backend.config.settings import settings
from backend.core.auth import (
    SCOPE_VISION,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import (
    ImageArtifactDependency,
    ImageIntentDependency,
    ImageRefinementDependency,
    ImageStyleDependency,
    TracerDependency,
)
from backend.models.image import (
    ImageGenerationBody,
    ImageIntentBody,
    ImageRefineBody,
)
from backend.services.image_intent import ASK, EDIT
from backend.services.image_refinement_service import RefinementError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])


class ImageClientDisconnectedError(Exception):
    """Signals that provider work was cancelled because its client left."""


# Cancel provider work when the HTTP client is no longer waiting for its result.
async def _run_until_disconnect(
    request: Request,
    operation: "asyncio.Task[dict[str, Any]]",
) -> dict[str, Any]:
    try:
        while not operation.done():
            if await request.is_disconnected():
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation
                raise ImageClientDisconnectedError
            await asyncio.sleep(0.1)
        return await operation
    except asyncio.CancelledError:
        operation.cancel()
        with suppress(asyncio.CancelledError):
            await operation
        raise


# Generate and persist one local image before returning its ready artifact record.
@router.post("/generate", status_code=status.HTTP_201_CREATED, response_model=None)
async def generate_image(
    body: ImageGenerationBody,
    request: Request,
    service: ImageArtifactDependency,
    style: ImageStyleDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any] | Response:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
    trace_id = tracer.start_trace(body.user_id)
    seed = body.seed if body.seed is not None else secrets.randbelow(2**63)
    learned_style = await style.get_style(body.user_id)
    try:
        return await _run_until_disconnect(
            request,
            asyncio.create_task(
                service.generate(
                    user_id=body.user_id,
                    conversation_id=str(body.conversation_id),
                    trace_id=trace_id,
                    request=ImageGenerationRequest(
                        prompt=body.prompt,
                        width=body.width,
                        height=body.height,
                        seed=seed,
                    ),
                    extra_style=learned_style,
                )
            ),
        )
    except ImageClientDisconnectedError:
        return Response(status_code=499)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        # The provider process (ComfyUI) is not reachable, which is distinct from
        # a generation failure. Name the cause so the interface can be specific.
        logger.warning(
            "Image provider unreachable at %s (trace=%s)",
            settings.IMAGE_PROVIDER_BASE_URL,
            trace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "reason": "image_provider_unreachable",
                "message": (
                    "The image generation backend (ComfyUI) isn't running. "
                    "Start it and try again."
                ),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Image generation failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to generate the image.",
        ) from exc


# Decide whether words typed while a picture is in view ask for it to change.
#
# Declared before the routes that take an artifact id so a literal "intent" can
# never be matched as one. The caller acts on the answer; this only reads.
@router.post("/intent", status_code=status.HTTP_200_OK)
async def classify_image_intent(
    body: ImageIntentBody,
    service: ImageIntentDependency,
    images: ImageArtifactDependency,
    identity: IdentityDependency,
) -> dict[str, Any]:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
    recent_context = ""
    if body.artifact_id is not None:
        artifact = await images.get_owned_record(body.user_id, str(body.artifact_id))
        if artifact is None:
            raise HTTPException(status_code=404, detail="Image not found.")
        metadata = artifact.get("metadata") or {}
        thread = metadata.get("analysis_thread")
        if isinstance(thread, list):
            recent_context = "\n".join(
                f"User: {str(item.get('prompt', ''))[:300]}\n"
                f"Assistant: {str(item.get('answer', ''))[:500]}"
                for item in thread[-3:]
                if isinstance(item, dict)
            )
        elif isinstance(metadata.get("analysis"), str):
            recent_context = f"Image description: {metadata['analysis'][:1_000]}"
    edits = await service.edits_the_image(body.text, recent_context)
    return {"intent": EDIT if edits else ASK}


# Edit one owned generated or uploaded image from its source pixels plus the
# user's feedback, returning a new immutable revision linked to the original.
@router.post(
    "/{artifact_id}/refine",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def refine_image(
    artifact_id: UUID,
    body: ImageRefineBody,
    request: Request,
    service: ImageRefinementDependency,
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any] | Response:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
    trace_id = tracer.start_trace(body.user_id)
    try:
        return await _run_until_disconnect(
            request,
            asyncio.create_task(
                service.refine(
                    user_id=body.user_id,
                    artifact_id=str(artifact_id),
                    feedback=body.feedback,
                    conversation_id=str(body.conversation_id),
                    trace_id=trace_id,
                )
            ),
        )
    except ImageClientDisconnectedError:
        return Response(status_code=499)
    except RefinementError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        logger.warning(
            "Image provider unreachable at %s (trace=%s)",
            settings.IMAGE_PROVIDER_BASE_URL,
            trace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "reason": "image_provider_unreachable",
                "message": (
                    "The image generation backend (ComfyUI) isn't running. "
                    "Start it and try again."
                ),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Image refinement failed", extra={"trace_id": trace_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to refine the image.",
        ) from exc
