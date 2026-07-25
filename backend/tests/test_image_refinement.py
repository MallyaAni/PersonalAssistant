from collections.abc import Iterator
from typing import Any

import pytest

from backend.services.image_refinement_service import (
    ImageRefinementService,
    RefinementError,
)


class StubLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def generate_text(self, prompt: str, max_tokens: int = 512) -> str:
        return ""

    def chat(self, messages: Any, max_tokens: int = 512) -> dict[str, Any]:
        return {"content": self.reply}

    def stream_chat(self, messages: Any, max_tokens: int = 512) -> Iterator[str]:
        yield ""


class StubImages:
    def __init__(self, record: dict[str, Any] | None) -> None:
        self.record = record
        self.generate_calls: list[dict[str, Any]] = []

    async def get_owned_record(
        self, user_id: str, artifact_id: str
    ) -> dict[str, Any] | None:
        return self.record

    async def generate(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        request: Any,
        extra_metadata: dict[str, Any] | None = None,
        extra_style: str = "",
    ) -> dict[str, Any]:
        self.generate_calls.append(
            {
                "request": request,
                "extra_metadata": extra_metadata or {},
                "extra_style": extra_style,
            }
        )
        return {"id": "revision", "kind": "generated_image"}


def _service(record: dict[str, Any] | None, reply: str) -> ImageRefinementService:
    return ImageRefinementService(StubImages(record), StubLLM(reply))  # type: ignore[arg-type]


_GENERATED = {
    "id": "orig",
    "kind": "generated_image",
    "width": 2048,
    "height": 2048,
    "metadata": {"generation_prompt": "a cat on a sofa"},
}


@pytest.mark.asyncio
async def test_refine_regenerates_a_linked_revision_with_the_merged_prompt() -> None:
    service = _service(_GENERATED, "a cat on a sofa, warm golden lighting, realistic")
    images: Any = service.images

    await service.refine("u", "orig", "warmer lighting, more realistic", "c", "t")

    call = images.generate_calls[0]
    assert call["request"].prompt == "a cat on a sofa, warm golden lighting, realistic"
    # The revision links back to its parent and records the feedback.
    assert call["extra_metadata"]["parent_artifact_id"] == "orig"
    assert "realistic" in call["extra_metadata"]["refinement_feedback"]


@pytest.mark.asyncio
async def test_refine_falls_back_to_a_merge_when_the_model_returns_nothing() -> None:
    service = _service(_GENERATED, "")
    images: Any = service.images

    await service.refine("u", "orig", "make it blue", "c", "t")

    # The feedback is never silently dropped.
    assert images.generate_calls[0]["request"].prompt == "a cat on a sofa, make it blue"


@pytest.mark.asyncio
async def test_refine_rejects_a_missing_or_non_generated_image() -> None:
    with pytest.raises(RefinementError):
        await _service(None, "x").refine("u", "missing", "x", "c", "t")

    upload = {"id": "up", "kind": "uploaded_image", "metadata": {}}
    with pytest.raises(RefinementError):
        await _service(upload, "x").refine("u", "up", "x", "c", "t")
