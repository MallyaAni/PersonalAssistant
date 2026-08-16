import secrets
from typing import Any

from backend.artifacts.types import ImageGenerationRequest
from backend.presentations.types import DeckSpec, ImageElement, SlideSpec
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.image_refinement_service import ImageRefinementService
from backend.services.presentation_service import PresentationService


class PresentationImageService:
    """Coordinate one optional local image microtask with a selected slide revision."""

    # Keep image generation and presentation ownership behind their existing services.
    def __init__(
        self,
        presentations: PresentationService,
        images: ImageArtifactService,
        refinements: ImageRefinementService,
    ) -> None:
        self.presentations = presentations
        self.images = images
        self.refinements = refinements

    # Generate an initial visual or refine the slide's existing visual with FLUX.
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
        existing_image = _first_image(slide)
        user_prompt = (prompt or "").strip()
        if existing_image is not None:
            if not user_prompt:
                raise ValueError("Image feedback cannot be empty")
            artifact = await self.refinements.refine(
                user_id=user_id,
                artifact_id=str(existing_image.artifact_id),
                feedback=user_prompt,
                conversation_id=str(presentation["conversation_id"]),
                trace_id=trace_id,
            )
            artifact_id = str(artifact["id"])
            alt_text = (f"{existing_image.alt_text}. Refined: {user_prompt}")[:500]
            try:
                return await self.presentations.attach_image(
                    user_id,
                    presentation_id,
                    base_revision_id,
                    slide_id,
                    artifact_id,
                    alt_text,
                    f"Refined the local image for {slide.title}: {user_prompt}",
                )
            except Exception:
                await self.images.delete_owned(user_id, artifact_id)
                raise
        # Ground every image in both the deck's overall topic and the slide's own,
        # so the picture matches what is being discussed - a "history of cars" deck
        # with a "progress of cars" slide asks for period-accurate cars, not a
        # generic photo. The user's own direction, when given, still leads.
        deck_topic = specification.title
        slide_context = f"{slide.title}: {slide.purpose}"
        if user_prompt:
            image_prompt = (
                f"{user_prompt}. This illustrates the slide '{slide.title}' "
                f"({slide.purpose}) in a presentation about {deck_topic}. "
                "Clean composition, realistic detail, no text, no labels, no watermark."
            )
        else:
            image_prompt = (
                f"Editorial presentation photograph for a presentation about "
                f"{deck_topic}, illustrating {slide_context}. Clean composition, "
                "realistic detail, no text, no labels, no watermark."
            )
        artifact = await self.images.generate(
            user_id=user_id,
            conversation_id=str(presentation["conversation_id"]),
            trace_id=trace_id,
            # Measured on HiDream-O1, which was trained at 2048x2048 and looked
            # noticeably worse at wider sizes such as 2560x1440. Kept on the
            # FLUX.2 Klein swap because the square also matches the square slide
            # placement box, but the size itself is no longer model-justified
            # and is worth re-measuring.
            # A square image also matches the square slide placement box, so it is
            # not stretched. (Off-list sizes like 1280x720 crash the sampler.)
            request=ImageGenerationRequest(
                prompt=image_prompt,
                width=2_048,
                height=2_048,
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


# Return the replaceable visual already attached to one slide, when present.
def _first_image(slide: SlideSpec) -> ImageElement | None:
    return next(
        (element for element in slide.elements if isinstance(element, ImageElement)),
        None,
    )
