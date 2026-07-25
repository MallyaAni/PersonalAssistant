import hashlib
from collections.abc import AsyncIterator
from typing import Any

import pytest

from backend.artifacts.types import StoredBinary
from backend.presentations.planner import DeckDraft
from backend.presentations.types import (
    DeckSpec,
    RenderedPresentation,
    SlideSpec,
    TextElement,
)
from backend.services.presentation_image_service import PresentationImageService
from backend.services.presentation_service import PresentationService


# Build a two-slide deck whose untouched sibling can be compared exactly.
def _deck() -> DeckSpec:
    return DeckSpec(
        title="Service acceptance",
        slides=[
            SlideSpec(
                slide_id="slide-a",
                title="Opening",
                purpose="Introduce",
                elements=[
                    TextElement(
                        element_id="a",
                        text="Opening",
                        x=0.5,
                        y=0.5,
                        w=4,
                        h=0.7,
                    )
                ],
            ),
            SlideSpec(
                slide_id="slide-b",
                title="Evidence",
                purpose="Explain",
                elements=[
                    TextElement(
                        element_id="b",
                        text="Evidence",
                        x=0.5,
                        y=0.5,
                        w=4,
                        h=0.7,
                    )
                ],
            ),
        ],
    )


class StubAgent:
    """Return deterministic creation and selected-slide revision plans."""

    # Return the fixed initial deck.
    async def create(self, prompt: str) -> DeckSpec:
        return _deck()

    # Yield one partial slide followed by the complete deterministic deck.
    async def create_progress(self, prompt: str) -> AsyncIterator[DeckDraft]:
        deck = _deck()
        yield DeckDraft(
            deck.model_copy(update={"slides": deck.slides[:1]}),
            2,
        )
        yield DeckDraft(deck, 2)

    # Replace only the requested slide.
    async def revise_slide(
        self,
        deck: DeckSpec,
        slide_id: str,
        feedback: str,
    ) -> SlideSpec:
        selected = next(slide for slide in deck.slides if slide.slide_id == slide_id)
        return selected.model_copy(update={"title": "Revised evidence"})


class StubRenderer:
    """Capture rendered specs and return a deterministic OOXML marker."""

    # Initialize the render capture.
    def __init__(self) -> None:
        self.specifications: list[DeckSpec] = []
        self.images: list[dict[str, tuple[str, bytes]]] = []

    # Return one deterministic renderer result.
    async def render(
        self,
        specification: DeckSpec,
        images: dict[str, tuple[str, bytes]] | None = None,
    ) -> RenderedPresentation:
        self.specifications.append(specification)
        self.images.append(images or {})
        return RenderedPresentation(
            content=b"PK test-ooxml",
            slide_count=len(specification.slides),
            renderer="pptxgenjs",
            renderer_version="4.0.1",
        )


class StubStore:
    """Capture binary lifecycle operations without using the filesystem."""

    # Initialize stored and deleted binary state.
    def __init__(self) -> None:
        self.content: dict[str, bytes] = {}
        self.deleted: list[str] = []

    # Store one deterministic binary by revision identifier.
    async def write(
        self,
        user_id: str,
        artifact_id: str,
        extension: str,
        content: bytes,
    ) -> StoredBinary:
        key = f"{user_id}/{artifact_id}.{extension}"
        self.content[key] = content
        return StoredBinary(
            storage_key=key,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    # Return a previously stored binary.
    async def read(self, storage_key: str) -> bytes:
        return self.content[storage_key]

    # Remove one previously stored binary.
    async def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)
        self.content.pop(storage_key, None)


class StubRepository:
    """Capture canonical specs and simulate append-only revision lineage."""

    # Initialize the deterministic repository state.
    def __init__(self) -> None:
        self.specifications: list[DeckSpec] = []
        self.failed: list[str] = []
        self.revision_arguments: tuple[Any, ...] | None = None

    # Return the first pending presentation and revision.
    async def create_pending(self, *args: Any) -> tuple[dict[str, str], dict[str, str]]:
        return {"id": "presentation"}, {"id": "revision-1"}

    # Store one canonical revision spec.
    async def set_specification(
        self,
        user_id: str,
        presentation_id: str,
        revision_id: str,
        specification: DeckSpec,
    ) -> None:
        self.specifications.append(specification)

    # Promote one ready revision and return its current detail.
    async def mark_ready(self, *args: Any) -> dict[str, Any]:
        return {
            "id": "presentation",
            "current_revision": {
                "id": args[2],
                "specification": self.specifications[-1].model_dump(mode="json"),
            },
        }

    # Capture one sanitized terminal failure.
    async def mark_failed(self, *args: Any) -> None:
        self.failed.append(str(args[2]))

    # Return the ready base deck and a pending child revision.
    async def create_revision_pending(
        self,
        *args: Any,
    ) -> tuple[DeckSpec, dict[str, str]]:
        self.revision_arguments = args
        return _deck(), {"id": "revision-2"}


class StubArtifactRepository:
    """Return one owned ready image for renderer hydration tests."""

    # Return a ready generated image with an opaque storage key.
    async def get_owned(
        self,
        user_id: str,
        artifact_id: str,
    ) -> dict[str, Any] | None:
        return {
            "id": artifact_id,
            "status": "ready",
            "kind": "generated_image",
            "mime_type": "image/png",
            "_storage_key": "user/image.png",
        }


class StubPresentationCoordinator:
    """Expose a ready deck and capture one image-attachment microtask."""

    # Initialize the captured attachment arguments.
    def __init__(self) -> None:
        self.attachment: tuple[Any, ...] | None = None

    # Return one ready owned presentation for image prompt grounding.
    async def get(
        self,
        user_id: str,
        presentation_id: str,
    ) -> dict[str, Any]:
        return {
            "id": presentation_id,
            "conversation_id": "33333333-3333-4333-8333-333333333333",
            "current_revision": {
                "specification": _deck().model_dump(mode="json"),
            },
        }

    # Capture the generated artifact link and return a promoted revision.
    async def attach_image(self, *args: Any) -> dict[str, Any]:
        self.attachment = args
        return {"id": "presentation", "current_revision_id": "revision-2"}


class StubImageCoordinator:
    """Capture one local generation request for the presentation coordinator."""

    # Initialize generation and cleanup capture.
    def __init__(self) -> None:
        self.generated: dict[str, Any] | None = None
        self.deleted: list[str] = []

    # Return one deterministic artifact after capturing the bounded request.
    async def generate(self, **kwargs: Any) -> dict[str, Any]:
        self.generated = kwargs
        return {"id": "44444444-4444-4444-8444-444444444444"}

    # Record cleanup if presentation attachment fails.
    async def delete_owned(self, user_id: str, artifact_id: str) -> bool:
        self.deleted.append(artifact_id)
        return True


# Bypass package inspection here because the renderer boundary has its own real test.
def _accept_structure(content: bytes, specification: DeckSpec) -> None:
    assert content.startswith(b"PK")


# Verify a slide revision preserves every sibling specification exactly.
@pytest.mark.asyncio
async def test_slide_revision_changes_only_the_selected_slide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.presentation_service.validate_presentation_structure",
        _accept_structure,
    )
    repository = StubRepository()
    renderer = StubRenderer()
    service = PresentationService(
        StubAgent(),  # type: ignore[arg-type]
        renderer,  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        StubStore(),  # type: ignore[arg-type]
        "test",
        "test-model",
    )
    base = _deck()
    result = await service.revise_slide(
        "user",
        "presentation",
        "revision-1",
        "slide-b",
        "Make it clearer",
    )
    revised = DeckSpec.model_validate(result["current_revision"]["specification"])
    assert revised.slides[0] == base.slides[0]
    assert revised.slides[1].title == "Revised evidence"
    assert revised.slides[1].slide_id == base.slides[1].slide_id
    assert repository.revision_arguments is not None
    assert repository.revision_arguments[3] == "slide-b"


# Verify progressive drafts precede one validated ready promotion.
@pytest.mark.asyncio
async def test_progressive_creation_yields_partial_slides_before_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.presentation_service.validate_presentation_structure",
        _accept_structure,
    )
    repository = StubRepository()
    service = PresentationService(
        StubAgent(),  # type: ignore[arg-type]
        StubRenderer(),  # type: ignore[arg-type]
        repository,  # type: ignore[arg-type]
        StubStore(),  # type: ignore[arg-type]
        "test",
        "test-model",
    )

    events = [
        event
        async for event in service.create_progress(
            "user",
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "Create two slides",
        )
    ]

    assert [event["event"] for event in events] == [
        "started",
        "draft",
        "draft",
        "ready",
        "done",
    ]
    assert len(events[1]["data"]["specification"]["slides"]) == 1
    assert len(events[2]["data"]["specification"]["slides"]) == 2


# Verify a selected-slide image becomes an editable reference and renderer input.
@pytest.mark.asyncio
async def test_attach_image_hydrates_owned_bytes_and_preserves_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.presentation_service.validate_presentation_structure",
        _accept_structure,
    )
    store = StubStore()
    store.content["user/image.png"] = b"image-bytes"
    renderer = StubRenderer()
    service = PresentationService(
        StubAgent(),  # type: ignore[arg-type]
        renderer,  # type: ignore[arg-type]
        StubRepository(),  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        "test",
        "test-model",
        StubArtifactRepository(),  # type: ignore[arg-type]
    )
    artifact_id = "11111111-1111-4111-8111-111111111111"

    result = await service.attach_image(
        "user",
        "presentation",
        "revision-1",
        "slide-a",
        artifact_id,
        "A horse in a field",
        "Generated a local image",
    )

    revised = DeckSpec.model_validate(result["current_revision"]["specification"])
    assert revised.slides[1] == _deck().slides[1]
    image = next(
        element for element in revised.slides[0].elements if element.type == "image"
    )
    assert str(image.artifact_id) == artifact_id
    assert renderer.images == [{artifact_id: ("image/png", b"image-bytes")}]


# Verify optional imagery is a fast bounded microtask outside initial deck creation.
@pytest.mark.asyncio
async def test_image_enrichment_uses_slide_context_and_fast_dimensions() -> None:
    presentations = StubPresentationCoordinator()
    images = StubImageCoordinator()
    service = PresentationImageService(
        presentations,  # type: ignore[arg-type]
        images,  # type: ignore[arg-type]
    )

    result = await service.enrich_slide(
        "user",
        "presentation",
        "revision-1",
        "slide-a",
        "55555555-5555-4555-8555-555555555555",
        None,
    )

    assert result["current_revision_id"] == "revision-2"
    assert images.generated is not None
    request = images.generated["request"]
    assert request.width == 2_048
    assert request.height == 2_048
    # The prompt carries the slide's own topic and the deck's overall topic, so
    # the image matches what is being discussed.
    assert "Opening: Introduce" in request.prompt
    assert "Service acceptance" in request.prompt


# A user's own image direction leads but is still grounded in the slide and deck.
@pytest.mark.asyncio
async def test_image_enrichment_keeps_user_prompt_and_adds_context() -> None:
    presentations = StubPresentationCoordinator()
    images = StubImageCoordinator()
    service = PresentationImageService(
        presentations,  # type: ignore[arg-type]
        images,  # type: ignore[arg-type]
    )

    await service.enrich_slide(
        "user",
        "presentation",
        "revision-1",
        "slide-a",
        "55555555-5555-4555-8555-555555555555",
        "a vintage red convertible",
    )

    assert images.generated is not None
    prompt = images.generated["request"].prompt
    assert prompt.startswith("a vintage red convertible")
    assert "Opening" in prompt
    assert "Service acceptance" in prompt
    assert presentations.attachment is not None
    assert presentations.attachment[3] == "slide-a"
    assert presentations.attachment[4] == "44444444-4444-4444-8444-444444444444"
