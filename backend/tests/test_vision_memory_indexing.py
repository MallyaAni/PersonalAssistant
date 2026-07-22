from typing import Any

import pytest

from backend.artifacts.types import VisionAnalysis
from backend.services.vision_analysis_service import (
    VISUAL_ANALYSIS_PURPOSE,
    VisionAnalysisService,
)


class RecordingMemory:
    """Capture semantic writes, optionally failing, without a database."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.saved: list[dict[str, Any]] = []

    async def save_semantic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: Any = None,
    ) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("embedding backend unavailable")
        self.saved.append(
            {
                "user_id": user_id,
                "content": content,
                "metadata": metadata,
                "purpose": purpose,
            }
        )
        return {"id": "stub"}


class StubImages:
    async def store_upload(self, user_id, conversation_id, trace_id, content, mime):
        artifact = {
            "id": "11111111-1111-4111-8111-111111111111",
            "conversation_id": conversation_id,
            "kind": "uploaded_image",
            "mime_type": "image/png",
        }
        return artifact, content


class StubRepository:
    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}

    async def update_metadata(self, artifact_id, user_id, metadata):
        self.metadata.update(metadata)
        return {
            "id": artifact_id,
            "conversation_id": "22222222-2222-4222-8222-222222222222",
            "kind": "uploaded_image",
            "metadata": dict(self.metadata),
        }


class StubVision:
    def __init__(self, content: str = "A magenta fox on a green platform.") -> None:
        self.content = content

    async def analyze(self, prompt, content, mime_type):
        return VisionAnalysis(content=self.content, model="gemma-test", metadata={})


def _service(memory: RecordingMemory | None) -> VisionAnalysisService:
    return VisionAnalysisService(
        StubImages(),  # type: ignore[arg-type]
        StubRepository(),  # type: ignore[arg-type]
        StubVision(),  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )


async def _analyze(service: VisionAnalysisService) -> dict[str, Any]:
    return await service.analyze_upload(
        "index_user",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "Describe this image.",
        b"fake-png-bytes",
        "image/png",
    )


@pytest.mark.asyncio
async def test_analysis_is_indexed_as_derived_memory_with_artifact_reference():
    memory = RecordingMemory()

    result = await _analyze(_service(memory))

    assert len(memory.saved) == 1
    entry = memory.saved[0]
    # Derived text must not be filed as a user-stated fact.
    assert entry["purpose"] == VISUAL_ANALYSIS_PURPOSE
    assert entry["purpose"] != "user_explicit"
    assert entry["user_id"] == "index_user"
    # Only content reaches the prompt, so it must describe its own provenance.
    assert entry["content"].startswith(
        "Description of an image the user has (uploaded)"
    )
    assert "A magenta fox on a green platform." in entry["content"]
    # The reference back to the artifact makes retrieval actionable.
    assert entry["metadata"]["artifact_id"] == result["artifact"]["id"]
    assert entry["metadata"]["source"] == "vision_analysis"
    assert entry["metadata"]["analysis_model"] == "gemma-test"


@pytest.mark.asyncio
async def test_indexing_failure_never_loses_the_analysis():
    memory = RecordingMemory(fail=True)

    result = await _analyze(_service(memory))

    # The caller still receives the analysis even though indexing failed.
    assert result["analysis"] == "A magenta fox on a green platform."
    assert memory.saved == []


@pytest.mark.asyncio
async def test_service_without_memory_configured_still_analyses():
    result = await _analyze(_service(None))

    assert result["analysis"] == "A magenta fox on a green platform."


@pytest.mark.asyncio
async def test_blank_analysis_is_not_indexed():
    memory = RecordingMemory()
    service = VisionAnalysisService(
        StubImages(),  # type: ignore[arg-type]
        StubRepository(),  # type: ignore[arg-type]
        StubVision(content="   "),  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )

    await _analyze(service)

    assert memory.saved == []
