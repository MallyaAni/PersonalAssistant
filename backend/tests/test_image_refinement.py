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

# Build one refinement service around an isolated image-service double.
def _service(record: dict[str, Any] | None) -> ImageRefinementService:
    return ImageRefinementService(StubImages(record))  # type: ignore[arg-type]


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


# Missing, uploaded, and blank-feedback inputs must fail before provider work.
@pytest.mark.asyncio
async def test_refine_rejects_invalid_parent_or_feedback() -> None:
    with pytest.raises(RefinementError):
        await _service(None).refine("u", "missing", "x", "c", "t")

    upload = {"id": "up", "kind": "uploaded_image", "metadata": {}}
    with pytest.raises(RefinementError):
        await _service(upload).refine("u", "up", "x", "c", "t")

    with pytest.raises(RefinementError):
        await _service(_GENERATED).refine("u", "orig", "   ", "c", "t")
