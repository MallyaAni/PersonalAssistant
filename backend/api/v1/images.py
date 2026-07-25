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
    ImageRefinementDependency,
    TracerDependency,
)
from backend.models.image import ImageGenerationBody, ImageRefineBody
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
    tracer: TracerDependency,
    identity: IdentityDependency,
) -> dict[str, Any] | Response:
    authorize_user(body.user_id, identity)
    authorize_scope(identity, SCOPE_VISION)
    trace_id = tracer.start_trace(body.user_id)
    seed = body.seed if body.seed is not None else secrets.randbelow(2**63)
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


# Regenerate one owned generated image from its prompt plus the user's feedback,
# returning a new revision linked to the original.
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
