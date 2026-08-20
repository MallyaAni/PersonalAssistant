from typing import Any

import pytest

from backend.services.image_refinement_service import (
    ImageRefinementService,
    RefinementError,
)


class StubImages:
    def __init__(self, record: dict[str, Any] | None) -> None:
        self.record = record
        self.edit_calls: list[dict[str, Any]] = []

    # Return the owned parent and its exact bytes for a refinement.
    async def read_owned(
        self,
        user_id: str,
        artifact_id: str,
    ) -> tuple[dict[str, Any], bytes] | None:
        if self.record is None:
            return None
        return self.record, b"source pixels"

    # Record the source-conditioned edit request without invoking a real provider.
    async def edit(self, **kwargs: Any) -> dict[str, Any]:
        self.edit_calls.append(kwargs)
        return {"id": "revision", "kind": "generated_image"}


class StubVision:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    # Return the observed child metadata or simulate an unavailable VLM.
    async def observe_artifact(self, user_id: str, artifact_id: str) -> dict[str, Any]:
        self.calls.append((user_id, artifact_id))
        if self.fail:
            raise RuntimeError("vision unavailable")
        return {
            "id": artifact_id,
            "kind": "generated_image",
            "metadata": {"analysis": "A blue sofa in the edited image."},
        }


# Build one refinement service around an isolated image-service double.
def _service(record: dict[str, Any] | None) -> ImageRefinementService:
    return ImageRefinementService(StubImages(record))  # type: ignore[arg-type]


# Build a refinement service that observes the child after the pixel edit.
def _observed_service(
    record: dict[str, Any] | None,
    vision: StubVision,
) -> ImageRefinementService:
    return ImageRefinementService(  # type: ignore[arg-type]
        StubImages(record),
        vision,
    )


_GENERATED = {
    "id": "orig",
    "kind": "generated_image",
    "mime_type": "image/png",
    "width": 2048,
    "height": 2048,
    "metadata": {"generation_prompt": "a cat on a sofa"},
}


# A refinement must pass the parent's exact pixels and feedback to the editor.
@pytest.mark.asyncio
async def test_refine_creates_a_source_conditioned_child_revision() -> None:
    service = _service(_GENERATED)
    images: Any = service.images

    revision = await service.refine(
        "u",
        "orig",
        "make only the sofa blue",
        "c",
        "t",
    )

    assert revision["id"] == "revision"
    call = images.edit_calls[0]
    assert call["parent"] == _GENERATED
    assert call["source_content"] == b"source pixels"
    assert call["instruction"].startswith(
        "Apply only this edit to image 1: make only the sofa blue."
    )
    assert "Preserve every unmentioned subject attribute" in call["instruction"]
    assert call["user_feedback"] == "make only the sofa blue"
    assert call["conversation_id"] == "c"
    assert call["trace_id"] == "t"


# A named-color request must use the same qualified source-conditioned editor.
@pytest.mark.asyncio
async def test_refine_routes_named_color_change_to_source_editor() -> None:
    service = _service(_GENERATED)
    images: Any = service.images

    revision = await service.refine(
        "u",
        "orig",
        "can you make this car red?",
        "c",
        "t",
    )

    assert revision["id"] == "revision"
    call = images.edit_calls[0]
    assert call["instruction"].startswith(
        "Apply only this edit to image 1: can you make this car red?."
    )
    assert "Preserve every unmentioned subject attribute" in call["instruction"]
    assert call["user_feedback"] == "can you make this car red?"


# An uploaded image uses the same owned-pixel editor and becomes a linked child.
@pytest.mark.asyncio
async def test_refine_accepts_an_owned_uploaded_image() -> None:
    upload = {
        "id": "up",
        "kind": "uploaded_image",
        "mime_type": "image/png",
        "metadata": {"analysis": "A blue car"},
    }
    service = _service(upload)
    images: Any = service.images

    revision = await service.refine("u", "up", "make the car red", "c", "t")

    assert revision["id"] == "revision"
    assert images.edit_calls[0]["parent"] == upload
    assert images.edit_calls[0]["source_content"] == b"source pixels"


# Successful refinement returns the child after Qwen observes its current pixels.
@pytest.mark.asyncio
async def test_refine_observes_the_ready_child() -> None:
    vision = StubVision()
    service = _observed_service(_GENERATED, vision)

    revision = await service.refine("u", "orig", "make it blue", "c", "t")

    assert vision.calls == [("u", "revision")]
    assert revision["metadata"]["analysis"].startswith("A blue sofa")


# Observation failure preserves the valid edited child rather than losing the work.
@pytest.mark.asyncio
async def test_refine_survives_post_edit_observation_failure() -> None:
    vision = StubVision(fail=True)
    service = _observed_service(_GENERATED, vision)

    revision = await service.refine("u", "orig", "make it blue", "c", "t")

    assert vision.calls == [("u", "revision")]
    assert revision["id"] == "revision"


# Missing, non-image, and blank-feedback inputs must fail before provider work.
@pytest.mark.asyncio
async def test_refine_rejects_invalid_parent_or_feedback() -> None:
    with pytest.raises(RefinementError):
        await _service(None).refine("u", "missing", "x", "c", "t")

    upload = {"id": "up", "kind": "diagram", "metadata": {}}
    with pytest.raises(RefinementError):
        await _service(upload).refine("u", "up", "x", "c", "t")

    with pytest.raises(RefinementError):
        await _service(_GENERATED).refine("u", "orig", "   ", "c", "t")


# The reported failure. "Make the image look like it came in its original
# packaging" came back as the same photograph. The editor conditions on the
# source and is trained to preserve it, so an edit that needs the scene rebuilt
# is generated from a description of the source instead - and stays that
# source's child, so the lineage still reads.
class StubSceneWriter:
    """Return one fixed scene without reaching a model."""

    def __init__(self, scene: str = "the same seafood, sealed in packaging") -> None:
        self.scene = scene
        self.prompts: list[str] = []

    def chat(self, messages, *args, **kwargs):
        self.prompts.append(messages[-1]["content"])
        return {"content": self.scene}


class StubGeneratingImages(StubImages):
    """Record generation as well as editing, so the path taken is visible."""

    def __init__(self, record) -> None:
        super().__init__(record)
        self.generate_calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> dict[str, Any]:
        self.generate_calls.append(kwargs)
        return {"id": "restaged", "kind": "generated_image"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["uploaded_image", "generated_image"])
async def test_a_restaging_edit_is_generated_from_the_source_description(kind: str):
    record = {**_GENERATED, "kind": kind, "metadata": {"analysis": "fish on a board"}}
    images = StubGeneratingImages(record)
    writer = StubSceneWriter()
    service = ImageRefinementService(images, llm=writer)  # type: ignore[arg-type]

    revision = await service.refine(
        "ani.mallya",
        "artifact-1",
        "Make the image look like it came in its original packaging",
        "conversation-1",
        "trace-1",
        restages_the_scene=True,
    )

    assert revision["id"] == "restaged"
    # Generated, not edited: the editor cannot carry this out.
    assert images.edit_calls == []
    call = images.generate_calls[0]
    assert call["request"].prompt == "the same seafood, sealed in packaging"
    # Both halves reached the writer, or the scene cannot be consistent.
    assert "fish on a board" in writer.prompts[0]
    assert "original packaging" in writer.prompts[0]
    # Lineage survives for an upload exactly as it does for a generated image.
    assert call["parent"] == record
    assert call["extra_metadata"]["edit_mode"] == "restaged"
    assert call["extra_metadata"]["refinement_feedback"].startswith("Make the image")


# Without a description there is nothing to generate from, and refusing the
# turn would be worse than the weaker answer.
@pytest.mark.asyncio
async def test_a_restaging_edit_falls_back_to_editing_when_nothing_describes_it():
    record = {**_GENERATED, "metadata": {}}
    images = StubGeneratingImages(record)
    service = ImageRefinementService(images, llm=StubSceneWriter())  # type: ignore[arg-type]

    await service.refine(
        "ani.mallya",
        "artifact-1",
        "put it in packaging",
        "c",
        "t",
        restages_the_scene=True,
    )

    assert images.generate_calls == []
    assert images.edit_calls, "the turn must still produce something"


# The other half must not regress: a local change still has to leave the rest
# of the picture alone, or one recoloured hat rebuilds the whole scene.
@pytest.mark.asyncio
async def test_a_local_edit_still_protects_everything_it_did_not_mention():
    images = StubGeneratingImages(_GENERATED)
    service = ImageRefinementService(images, llm=StubSceneWriter())  # type: ignore[arg-type]

    await service.refine(
        "ani.mallya",
        "artifact-1",
        "make the hat black",
        "c",
        "t",
        restages_the_scene=False,
    )

    assert images.generate_calls == []
    instruction = images.edit_calls[0]["instruction"]
    assert "Do not add, remove, or move anything" in instruction
