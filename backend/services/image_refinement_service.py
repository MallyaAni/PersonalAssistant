import logging
import secrets
from typing import Any

from backend.services.image_artifact_service import ImageArtifactService
from backend.services.vision_analysis_service import VisionAnalysisService

logger = logging.getLogger(__name__)

_MAX_FEEDBACK_CHARS = 2000
_PRESERVATION_SUFFIX = (
    "Preserve every unmentioned subject attribute, object identity, geometry, "
    "position, camera angle, background, lighting, reflections, and composition. "
    "Do not add, remove, or move anything unless the instruction explicitly asks."
)


class RefinementError(RuntimeError):
    """The artifact cannot be refined: missing, not owned, or not an image."""


class ImageRefinementService:
    """Edit a generated image from its owned pixels plus the user's feedback.

    This is a non-destructive revision: a new artifact is created that links to
    its parent, so the progression is preserved rather than overwritten.
    """

    def __init__(
        self,
        images: ImageArtifactService,
        vision: VisionAnalysisService | None = None,
    ) -> None:
        self.images = images
        self.vision = vision

    # Resolve the owned parent bytes and create one source-conditioned child edit.
    async def refine(
        self,
        user_id: str,
        artifact_id: str,
        feedback: str,
        conversation_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        owned = await self.images.read_owned(user_id, artifact_id)
        if owned is None:
            raise RefinementError("No owned image matched the request")
        record, source_content = owned
        if record is None or record.get("kind") not in {
            "generated_image",
            "uploaded_image",
        }:
            raise RefinementError("No owned image matched the request")
        instruction = feedback.strip()[:_MAX_FEEDBACK_CHARS]
        if not instruction:
            raise RefinementError("Image feedback cannot be empty")
        provider_instruction = (
            f"Apply only this edit to image 1: {instruction}. {_PRESERVATION_SUFFIX}"
        )
        revision = await self.images.edit(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            parent=record,
            source_content=source_content,
            instruction=provider_instruction,
            seed=secrets.randbelow(2**63),
            user_feedback=instruction,
        )
        if self.vision is None:
            return revision
        try:
            return await self.vision.observe_artifact(user_id, str(revision["id"]))
        except Exception:
            # The edited pixels remain valid even when semantic observation fails.
            logger.warning(
                "Post-refinement vision observation failed for artifact %s",
                revision.get("id"),
                exc_info=True,
            )
            return revision
