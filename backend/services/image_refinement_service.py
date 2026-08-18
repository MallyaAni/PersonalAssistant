import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from backend.services.image_artifact_service import ImageArtifactService
from backend.services.vision_analysis_service import VisionAnalysisService

logger = logging.getLogger(__name__)

_MAX_FEEDBACK_CHARS = 2000

# What to protect when the edit is confined to something already in the
# picture: recolour a hat, remove a sign, relabel a box. Everything else must
# survive untouched, and without this the image model rebuilds the whole scene
# around one small change.
_KEEP_THE_SCENE = (
    "Preserve every unmentioned subject attribute, object identity, geometry, "
    "position, camera angle, background, lighting, reflections, and composition. "
    "Do not add, remove, or move anything unless the instruction explicitly asks."
)

# What to protect when the edit *is* a change of scene: the same wording would
# forbid the thing being asked for. "Make it look like it came in its original
# packaging" cannot be carried out without introducing packaging that is not in
# the photograph, and sent with the clause above the model returned the picture
# essentially unchanged - it obeyed the stronger, more specific prohibition.
# What must survive here is which things these are, not where they sit.
_KEEP_THE_SUBJECTS = (
    "Keep the identity of the subjects exactly as they are: the same items, "
    "the same number of them, the same species, materials, colours and "
    "markings, recognisably the same objects. Everything else serving the "
    "instruction may change, including the setting, surfaces, containers, "
    "arrangement, lighting and framing, and you may add whatever the "
    "instruction requires. Carry the instruction out fully rather than "
    "conservatively; the result should be visibly different."
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
        on_pending: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        restages_the_scene: bool = False,
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
        # "Apply only this edit" is itself a restraint, and it reads as one
        # more reason not to act when the edit is a change of scene.
        if restages_the_scene:
            provider_instruction = (
                f"Edit image 1 as follows: {instruction}. {_KEEP_THE_SUBJECTS}"
            )
        else:
            provider_instruction = (
                f"Apply only this edit to image 1: {instruction}. {_KEEP_THE_SCENE}"
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
            on_pending=on_pending,
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
