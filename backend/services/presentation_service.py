import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from backend.agents.presentation import PresentationAgent
from backend.core.interfaces import BinaryArtifactRepository, BinaryArtifactStore
from backend.presentations.renderer import PptxGenJSRenderer
from backend.presentations.types import (
    DeckSpec,
    ImageElement,
    SlideElement,
    SlideSpec,
    TextElement,
)
from backend.presentations.validation import validate_presentation_structure
from backend.services.presentation_repository import SQLAlchemyPresentationRepository


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
    ) -> None:
        self.agent = agent
        self.renderer = renderer
        self.repository = repository
        self.store = store
        self.provider_name = provider_name
        self.model_name = model_name
        self.artifact_repository = artifact_repository

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
