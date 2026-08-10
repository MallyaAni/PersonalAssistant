import asyncio
import logging
import re
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

from backend.agents.deck.agent import PresentationAgent
from backend.artifacts.types import ImageGenerationRequest
from backend.core.interfaces import BinaryArtifactRepository, BinaryArtifactStore
from backend.presentations.planner import DeckDraft
from backend.presentations.renderer import PptxGenJSRenderer
from backend.presentations.types import (
    DeckSpec,
    ImageElement,
    SlideElement,
    SlideSpec,
    TextElement,
)
from backend.presentations.validation import validate_presentation_structure
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.presentation_repository import SQLAlchemyPresentationRepository

logger = logging.getLogger(__name__)


class PresentationService:
    """Coordinate planning, rendering, persistence, and revision lineage."""

    # Assemble the application-owned presentation workflow from narrow boundaries.
    def __init__(
        self,
        agent: PresentationAgent,
        renderer: PptxGenJSRenderer,
        repository: SQLAlchemyPresentationRepository,
        store: BinaryArtifactStore,
        provider_name: str,
        model_name: str | None,
        artifact_repository: BinaryArtifactRepository | None = None,
        image_service: ImageArtifactService | None = None,
        auto_image_max: int = 0,
        auto_image_size: int = 1_024,
    ) -> None:
        self.agent = agent
        self.renderer = renderer
        self.repository = repository
        self.store = store
        self.provider_name = provider_name
        self.model_name = model_name
        self.artifact_repository = artifact_repository
        self.image_service = image_service
        self.auto_image_max = auto_image_max
        self.auto_image_size = auto_image_size

    # Plan, compile, validate, and persist one initial ready presentation.
    async def create(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        presentation, revision = await self.repository.create_pending(
            user_id,
            conversation_id,
            trace_id,
            self.provider_name,
            self.model_name,
        )
        presentation_id = str(presentation["id"])
        revision_id = str(revision["id"])
        try:
            specification = await self.agent.create(prompt)
            return await self._complete_revision(
                user_id,
                presentation_id,
                revision_id,
                specification,
            )
        except Exception:
            await self.repository.mark_failed(
                user_id,
                presentation_id,
                revision_id,
                "generation_failed",
            )
            raise

    # Stream progressive deck drafts before rendering and promoting the final revision.
    async def create_progress(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        prompt: str,
    ) -> AsyncIterator[dict[str, Any]]:
        presentation, revision = await self.repository.create_pending(
            user_id,
            conversation_id,
            trace_id,
            self.provider_name,
            self.model_name,
        )
        presentation_id = str(presentation["id"])
        revision_id = str(revision["id"])
        yield {
            "event": "started",
            "data": {
                "presentation_id": presentation_id,
                "revision_id": revision_id,
                "trace_id": trace_id,
            },
        }
        specification: DeckSpec | None = None
        try:
            async for draft in self.agent.create_progress(prompt):
                specification = draft.specification
                yield {
                    "event": "draft",
                    "data": {
                        "specification": specification.model_dump(mode="json"),
                        "expected_slide_count": draft.expected_slide_count,
                    },
                }
            if specification is None:
                raise ValueError("Presentation provider returned no slides")
            ready = await self._complete_revision(
                user_id,
                presentation_id,
                revision_id,
                specification,
            )
            yield {"event": "ready", "data": {"presentation": ready}}
        except asyncio.CancelledError:
            await asyncio.shield(
                self.repository.mark_failed(
                    user_id,
                    presentation_id,
                    revision_id,
                    "cancelled",
                )
            )
            raise
        except Exception:
            await self.repository.mark_failed(
                user_id,
                presentation_id,
                revision_id,
                "generation_failed",
            )
            yield {
                "event": "error",
                "data": {
                    "message": "Unable to create the presentation.",
                    "presentation_id": presentation_id,
                },
            }
        yield {"event": "done", "data": {}}

    # Execute one already-persisted job and checkpoint each graph-produced draft.
    async def execute_pending_create(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
        prompt: str,
        on_draft: Callable[[DeckDraft], Awaitable[None]],
    ) -> dict[str, Any]:
        specification: DeckSpec | None = None
        generated_artifact_ids: list[str] = []
        try:
            async for draft in self.agent.create_progress(prompt):
                specification = draft.specification
                await on_draft(draft)
            if specification is None:
                raise ValueError("Presentation provider returned no slides")
            if self.image_service is not None and self.auto_image_max > 0:
                presentation = await self.repository.get_owned(
                    user_id,
                    presentation_id,
                )
                if presentation is None:
                    raise LookupError("Presentation was not found")
                (
                    specification,
                    generated_artifact_ids,
                ) = await self._enrich_default_images(
                    user_id,
                    presentation_id,
                    str(presentation["conversation_id"]),
                    str(presentation["trace_id"]),
                    specification,
                    on_draft,
                )
            return await self._complete_revision(
                user_id,
                presentation_id,
                revision_id,
                specification,
            )
        except Exception:
            if self.image_service is not None:
                for artifact_id in generated_artifact_ids:
                    await self.image_service.delete_owned(user_id, artifact_id)
            raise

    # Generate the highest-value declared visuals and checkpoint each visible result.
    async def _enrich_default_images(
        self,
        user_id: str,
        presentation_id: str,
        conversation_id: str,
        trace_id: str,
        specification: DeckSpec,
        on_draft: Callable[[DeckDraft], Awaitable[None]],
    ) -> tuple[DeckSpec, list[str]]:
        if self.image_service is None:
            return specification, []
        candidates = [
            (index, slide)
            for index, slide in enumerate(specification.slides)
            if slide.visual_prompt
            and slide.visual_priority > 0
            and not any(isinstance(element, ImageElement) for element in slide.elements)
        ]
        candidates.sort(
            key=lambda candidate: (-candidate[1].visual_priority, candidate[0])
        )
        generated_artifact_ids: list[str] = []
        enriched = specification
        for _, planned_slide in candidates[: self.auto_image_max]:
            visual_prompt = planned_slide.visual_prompt
            if not visual_prompt:
                continue
            image_prompt = (
                f"{visual_prompt}. Editorial presentation image for "
                f"the slide '{planned_slide.title}' in a presentation about "
                f"{specification.title}. {planned_slide.purpose}. Clean composition, "
                "realistic detail, no text, no labels, no logos, no watermark."
            )
            try:
                artifact = await self.image_service.generate(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    request=ImageGenerationRequest(
                        prompt=image_prompt,
                        width=self.auto_image_size,
                        height=self.auto_image_size,
                        seed=secrets.randbelow(2**63),
                    ),
                    extra_metadata={
                        "presentation_id": presentation_id,
                        "slide_id": planned_slide.slide_id,
                        "presentation_auto_generated": True,
                    },
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "presentation_auto_image_failed",
                    extra={"slide_id": planned_slide.slide_id},
                    exc_info=True,
                )
                continue
            artifact_id = str(artifact["id"])
            generated_artifact_ids.append(artifact_id)
            alt_text = (f"{visual_prompt[:320]}. Visual for {planned_slide.title}")[
                :400
            ]
            slides = [
                (
                    _attach_image_to_slide(slide, artifact_id, alt_text)
                    if slide.slide_id == planned_slide.slide_id
                    else slide
                )
                for slide in enriched.slides
            ]
            enriched = enriched.model_copy(update={"slides": slides})
            await on_draft(DeckDraft(enriched, len(specification.slides)))
        return enriched, generated_artifact_ids

    # Replace one selected slide while preserving every sibling slide byte-for-byte.
    async def revise_slide(
        self,
        user_id: str,
        presentation_id: str,
        base_revision_id: str,
        slide_id: str,
        feedback: str,
    ) -> dict[str, Any]:
        base, revision = await self.repository.create_revision_pending(
            user_id,
            presentation_id,
            base_revision_id,
            slide_id,
            feedback,
            self.provider_name,
            self.model_name,
        )
        revision_id = str(revision["id"])
        try:
            replacement = await self.agent.revise_slide(base, slide_id, feedback)
        except Exception:
            await self.repository.mark_failed(
                user_id,
                presentation_id,
                revision_id,
                "generation_failed",
            )
            raise
        slides = [
            replacement if slide.slide_id == slide_id else slide
            for slide in base.slides
        ]
        revised = base.model_copy(update={"slides": slides})
        return await self._complete_revision(
            user_id,
            presentation_id,
            revision_id,
            revised,
        )

    # Append or insert one new slide as a linked revision of the current deck.
    async def add_slide(
        self,
        user_id: str,
        presentation_id: str,
        base_revision_id: str,
        brief: str,
        # 0-based index the new slide takes. None appends. An index rather than
        # an "after this slide" reference so the very first position, which has
        # no slide before it, is expressible.
        position: int | None = None,
    ) -> dict[str, Any]:
        base, revision = await self.repository.create_revision_pending(
            user_id,
            presentation_id,
            base_revision_id,
            # The new slide has no id until it is planned, so the revision is
            # not associated with a target slide the way an edit is.
            None,
            brief,
            self.provider_name,
            self.model_name,
        )
        revision_id = str(revision["id"])
        if position is not None and not 0 <= position <= len(base.slides):
            await self.repository.mark_failed(
                user_id, presentation_id, revision_id, "position_out_of_range"
            )
            raise ValueError("The requested position is outside the deck.")
        slide_id = _next_slide_id(base)
        try:
            neighbour = (
                base.slides[position - 1].slide_id
                if position is not None and position > 0
                else None
            )
            added = await self.agent.add_slide(base, brief, slide_id, neighbour)
        except Exception:
            await self.repository.mark_failed(
                user_id,
                presentation_id,
                revision_id,
                "generation_failed",
            )
            raise
        await self.repository.set_revision_target(
            presentation_id, revision_id, added.slide_id
        )
        slides = list(base.slides)
        slides.insert(len(slides) if position is None else position, added)
        return await self._complete_revision(
            user_id,
            presentation_id,
            revision_id,
            base.model_copy(update={"slides": slides}),
        )

    # Remove one slide as a linked revision. Revising replaces a slide's content
    # and can never remove it, so deletion needs its own path.
    async def delete_slide(
        self,
        user_id: str,
        presentation_id: str,
        base_revision_id: str,
        slide_id: str,
    ) -> dict[str, Any]:
        base, revision = await self.repository.create_revision_pending(
            user_id,
            presentation_id,
            base_revision_id,
            slide_id,
            f"Removed slide {slide_id}",
            self.provider_name,
            self.model_name,
        )
        revision_id = str(revision["id"])
        remaining = [slide for slide in base.slides if slide.slide_id != slide_id]
        if len(remaining) == len(base.slides):
            await self.repository.mark_failed(
                user_id, presentation_id, revision_id, "slide_not_found"
            )
            raise LookupError("The slide to delete was not found")
        # A deck must keep at least one slide, so refuse rather than let the
        # specification fail validation and lose the whole presentation.
        if not remaining:
            await self.repository.mark_failed(
                user_id, presentation_id, revision_id, "last_slide"
            )
            raise ValueError("A presentation must keep at least one slide.")
        return await self._complete_revision(
            user_id,
            presentation_id,
            revision_id,
            base.model_copy(update={"slides": remaining}),
        )

    # Reorder the deck as a linked revision. No model is involved: the caller
    # supplies the new order and the deck is permuted deterministically.
    async def reorder_slides(
        self,
        user_id: str,
        presentation_id: str,
        base_revision_id: str,
        slide_ids: list[str],
    ) -> dict[str, Any]:
        base, revision = await self.repository.create_revision_pending(
            user_id,
            presentation_id,
            base_revision_id,
            None,
            "Reordered slides",
            self.provider_name,
            self.model_name,
        )
        revision_id = str(revision["id"])
        by_id = {slide.slide_id: slide for slide in base.slides}
        # The new order must be a permutation of the deck. Anything else would
        # silently add or drop a slide, so it is refused rather than applied.
        if sorted(slide_ids) != sorted(by_id):
            await self.repository.mark_failed(
                user_id, presentation_id, revision_id, "order_mismatch"
            )
            raise ValueError(
                "The new order must list every existing slide exactly once."
            )
        return await self._complete_revision(
            user_id,
            presentation_id,
            revision_id,
            base.model_copy(update={"slides": [by_id[key] for key in slide_ids]}),
        )

    # Attach one owned generated image to the selected slide in a linked revision.
    async def attach_image(
        self,
        user_id: str,
        presentation_id: str,
        base_revision_id: str,
        slide_id: str,
        artifact_id: str,
        alt_text: str,
        change_summary: str,
    ) -> dict[str, Any]:
        base, revision = await self.repository.create_revision_pending(
            user_id,
            presentation_id,
            base_revision_id,
            slide_id,
            change_summary,
            self.provider_name,
            self.model_name,
        )
        revision_id = str(revision["id"])
        try:
            slides = [
                (
                    _attach_image_to_slide(slide, artifact_id, alt_text)
                    if slide.slide_id == slide_id
                    else slide
                )
                for slide in base.slides
            ]
            return await self._complete_revision(
                user_id,
                presentation_id,
                revision_id,
                base.model_copy(update={"slides": slides}),
            )
        except Exception:
            await self.repository.mark_failed(
                user_id,
                presentation_id,
                revision_id,
                "generation_failed",
            )
            raise

    # Return one owned deck with its active specification and revision history.
    async def get(
        self,
        user_id: str,
        presentation_id: str,
    ) -> dict[str, Any] | None:
        return await self.repository.get_owned(user_id, presentation_id)

    # List recent owned presentations without loading every historical spec.
    async def list(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await self.repository.list_for_user(user_id, limit)

    # Load a ready PPTX plus a safe filename for one owned revision.
    async def download(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
    ) -> tuple[str, bytes] | None:
        revision = await self.repository.get_revision_content(
            user_id,
            presentation_id,
            revision_id,
        )
        if revision is None:
            return None
        content = await self.store.read(str(revision["_storage_key"]))
        safe_title = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            str(revision["presentation_title"]).strip(),
        ).strip("-")[:80]
        filename = f"{safe_title or 'presentation'}-r{revision['revision_number']}.pptx"
        return filename, content

    # Delete deck metadata and each linked binary after ownership is established.
    async def delete(self, user_id: str, presentation_id: str) -> bool:
        storage_keys = await self.repository.delete(user_id, presentation_id)
        if storage_keys is None:
            return False
        for storage_key in storage_keys:
            await self.store.delete(storage_key)
        return True

    # Render a validated spec and make the revision current only after all checks pass.
    async def _complete_revision(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
        specification: DeckSpec,
    ) -> dict[str, Any]:
        stored = None
        try:
            await self.repository.set_specification(
                user_id,
                presentation_id,
                revision_id,
                specification,
            )
            rendered = await self.renderer.render(
                specification,
                await self._resolve_images(user_id, specification),
            )
            validate_presentation_structure(rendered.content, specification)
            stored = await self.store.write(
                user_id,
                revision_id,
                "pptx",
                rendered.content,
            )
            return await self.repository.mark_ready(
                user_id,
                presentation_id,
                revision_id,
                stored,
                rendered.renderer,
                rendered.renderer_version,
            )
        except Exception:
            if stored is not None:
                await self.store.delete(stored.storage_key)
            await self.repository.mark_failed(
                user_id,
                presentation_id,
                revision_id,
                "generation_failed",
            )
            raise

    # Resolve every owned image reference only at the trusted rendering boundary.
    async def _resolve_images(
        self,
        user_id: str,
        specification: DeckSpec,
    ) -> dict[str, tuple[str, bytes]]:
        artifact_ids = {
            str(element.artifact_id)
            for slide in specification.slides
            for element in slide.elements
            if isinstance(element, ImageElement)
        }
        if not artifact_ids:
            return {}
        if self.artifact_repository is None:
            raise RuntimeError("Presentation image resolver is unavailable")
        images: dict[str, tuple[str, bytes]] = {}
        for artifact_id in artifact_ids:
            artifact = await self.artifact_repository.get_owned(user_id, artifact_id)
            if (
                artifact is None
                or artifact.get("status") != "ready"
                or artifact.get("kind") not in {"generated_image", "uploaded_image"}
                or artifact.get("mime_type")
                not in {"image/png", "image/jpeg", "image/webp"}
                or not isinstance(artifact.get("_storage_key"), str)
            ):
                raise LookupError("Presentation image was not found")
            images[artifact_id] = (
                str(artifact["mime_type"]),
                await self.store.read(str(artifact["_storage_key"])),
            )
        return images


# Add or replace a right-side image while preserving the slide's editable content.
def _attach_image_to_slide(
    slide: SlideSpec,
    artifact_id: str,
    alt_text: str,
) -> SlideSpec:
    image_id = f"{slide.slide_id}_image"
    replaced = False
    elements: list[SlideElement] = []
    for element in slide.elements:
        if isinstance(element, ImageElement):
            elements.append(
                element.model_copy(
                    update={"artifact_id": artifact_id, "alt_text": alt_text}
                )
            )
            replaced = True
        elif isinstance(element, TextElement) and element.y >= 1.55 and element.x < 8:
            elements.append(element.model_copy(update={"w": min(element.w, 6.65)}))
        else:
            elements.append(element)
    if not replaced:
        # A square box matches the square generated image so it is not distorted,
        # and it sits in the right column beside the text narrowed above.
        elements.append(
            ImageElement(
                element_id=image_id,
                artifact_id=UUID(artifact_id),
                alt_text=alt_text,
                x=8.45,
                y=1.95,
                w=4.4,
                h=4.4,
            )
        )
    return slide.model_copy(update={"elements": elements})


# Mint a slide identifier that cannot collide with one already in the deck.
# Identifiers are identities rather than positions, so inserting in the middle
# does not renumber the slides around it and existing revisions keep resolving.
def _next_slide_id(deck: DeckSpec) -> str:
    highest = 0
    for slide in deck.slides:
        suffix = slide.slide_id.rsplit("_", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"slide_{max(highest + 1, len(deck.slides) + 1):03d}"
