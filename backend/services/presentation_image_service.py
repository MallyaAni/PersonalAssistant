import secrets
from typing import Any

from backend.artifacts.types import ImageGenerationRequest
from backend.presentations.types import DeckSpec
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.presentation_service import PresentationService


class PresentationImageService:
    """Coordinate one optional local image microtask with a selected slide revision."""

    # Keep image generation and presentation ownership behind their existing services.
    def __init__(
        self,
        presentations: PresentationService,
        images: ImageArtifactService,
    ) -> None:
        self.presentations = presentations
        self.images = images

    # Generate one local visual and attach it without delaying initial deck creation.
    async def enrich_slide(
        self,
        user_id: str,
        presentation_id: str,
        base_revision_id: str,
        slide_id: str,
        trace_id: str,
        prompt: str | None,
    ) -> dict[str, Any]:
        presentation = await self.presentations.get(user_id, presentation_id)
        if presentation is None or presentation.get("current_revision") is None:
            raise LookupError("Presentation was not found")
        specification = DeckSpec.model_validate(
            presentation["current_revision"].get("specification")
        )
        slide = next(
            (
                candidate
                for candidate in specification.slides
                if candidate.slide_id == slide_id
            ),
            None,
        )
        if slide is None:
            raise LookupError("Presentation slide was not found")
        image_prompt = (prompt or "").strip() or (
            "Editorial presentation photograph illustrating "
            f"{slide.title}: {slide.purpose}. "
            "Clean composition, realistic detail, no text, no labels, no watermark."
        )
        artifact = await self.images.generate(
            user_id=user_id,
            conversation_id=str(presentation["conversation_id"]),
            trace_id=trace_id,
            request=ImageGenerationRequest(
                prompt=image_prompt,
                width=1_280,
                height=720,
                seed=secrets.randbelow(2**63),
            ),
            extra_metadata={
                "presentation_id": presentation_id,
                "slide_id": slide_id,
            },
        )
        artifact_id = str(artifact["id"])
        try:
            return await self.presentations.attach_image(
                user_id,
                presentation_id,
                base_revision_id,
                slide_id,
                artifact_id,
                image_prompt[:500],
                f"Generated a local image for {slide.title}",
            )
        except Exception:
            await self.images.delete_owned(user_id, artifact_id)
            raise
