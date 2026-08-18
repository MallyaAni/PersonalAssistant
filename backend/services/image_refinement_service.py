import logging
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from backend.artifacts.types import ImageGenerationRequest
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
        # Writes the scene description a restaged edit is generated from. With
        # no client the service still works and simply never restages, which is
        # the same behaviour as before this existed.
        llm: Any | None = None,
    ) -> None:
        self.images = images
        self.vision = vision
        self.llm = llm

    # What this picture shows, in whatever form the record already holds.
    #
    # Ordered by how well each describes the pixels as they are now. The stored
    # analysis is written from the image itself, so it is right for an upload
    # and still right for an edited descendant whose own generation prompt is
    # empty. A generation prompt is what was asked for rather than what came
    # back, which is close enough when nothing better exists. Asking the vision
    # service is last because it costs a model call, and it is what makes this
    # work for a picture nobody has described yet.
    async def _describe_source(
        self, user_id: str, artifact_id: str, record: dict[str, Any]
    ) -> str:
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        for field in ("analysis", "generation_prompt"):
            value = str(metadata.get(field) or "").strip()
            if value:
                return value
        if self.vision is None:
            return ""
        try:
            observed = await self.vision.observe_artifact(user_id, artifact_id)
        except Exception:
            logger.warning("Could not describe the source image", exc_info=True)
            return ""
        fresh = observed.get("metadata") if isinstance(observed, dict) else None
        fresh = fresh if isinstance(fresh, dict) else {}
        return str(fresh.get("analysis") or "").strip()

    # Turn "what is in the picture" plus "what to change" into one scene to draw.
    #
    # The description and the instruction cannot simply be concatenated: the
    # description states what is there now, including the parts the change
    # replaces, and a diffusion model draws every token it is given. One model
    # call resolves them into a single consistent scene.
    def _compose_scene(self, description: str, feedback: str) -> str:
        reply = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Write one image-generation prompt, at most 90 words, "
                        "describing the scene after the requested change. Keep "
                        "the same items, the same kinds and the same "
                        "quantities as the scene given. Describe only what is "
                        "visible. No preamble, no lists, no commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Scene:\n{description}\n\nRequested change: {feedback}"
                    ),
                },
            ],
            400,
        )
        return str(reply.get("content") or "").strip()

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
        # An edit that needs the scene rebuilt is not something the editor can
        # do, and no wording makes it one. Measured against the shipped model
        # (`flux-2-klein-4b`): reference-conditioned editing left the picture
        # unchanged at 4 and at 20 steps, raising CFG to 3.0 shifted colour
        # without carrying out the instruction, and true img2img from the
        # source latent at denoise 0.70 also left it unchanged. The editor
        # conditions on the source and is trained to preserve it. Generating
        # from a description of that source is the one path that produces the
        # requested change, so that is what a restaging edit does - and it is
        # reported as a new picture rather than passed off as an edit.
        if restages_the_scene and self.llm is not None:
            restaged = await self._restage(
                user_id=user_id,
                artifact_id=artifact_id,
                record=record,
                feedback=instruction,
                conversation_id=conversation_id,
                trace_id=trace_id,
                on_pending=on_pending,
            )
            if restaged is not None:
                return restaged
            # Nothing described the source, so there is nothing to generate
            # from. An in-place edit is the weaker answer and still better than
            # refusing the turn.
            logger.info("Restaging unavailable; editing in place instead")

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

    # Build the requested scene as a new picture, still owned by its source.
    #
    # Returns None when the source cannot be described, so the caller can fall
    # back rather than generating from nothing.
    async def _restage(
        self,
        user_id: str,
        artifact_id: str,
        record: dict[str, Any],
        feedback: str,
        conversation_id: str,
        trace_id: str,
        on_pending: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> dict[str, Any] | None:
        description = await self._describe_source(user_id, artifact_id, record)
        if not description:
            return None
        try:
            scene = self._compose_scene(description, feedback)
        except Exception:
            logger.warning("Could not compose a restaged scene", exc_info=True)
            return None
        if not scene:
            return None

        # Kept in the record because it is the only place the reasoning is
        # visible afterwards: the picture is generated, and without the scene
        # text nothing explains why it shows what it shows.
        revision = await self.images.generate(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            request=ImageGenerationRequest(
                prompt=scene,
                width=1024,
                height=1536,
                seed=secrets.randbelow(2**63),
                depicts_a_person=False,
            ),
            extra_metadata={
                "edit_mode": "restaged",
                "refinement_feedback": feedback,
                "restaged_from_description": description[:2000],
                "parent_artifact_id": str(record.get("id") or ""),
            },
            on_pending=on_pending,
            parent=record,
            title="Restaged image",
        )
        if self.vision is None:
            return revision
        try:
            return await self.vision.observe_artifact(user_id, str(revision["id"]))
        except Exception:
            logger.warning(
                "Post-restage vision observation failed for artifact %s",
                revision.get("id"),
                exc_info=True,
            )
            return revision
