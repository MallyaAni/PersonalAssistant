from typing import Any

import pytest

from backend.artifacts.types import VisionAnalysis
from backend.memory.purposes import VISUAL_ANALYSIS_PURPOSE
from backend.services.vision_analysis_service import VisionAnalysisService


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

    # Return an existing ready child so post-edit observation can inspect it.
    async def read_owned(self, user_id, artifact_id):
        return (
            {
                "id": artifact_id,
                "conversation_id": "22222222-2222-4222-8222-222222222222",
                "kind": "generated_image",
                "mime_type": "image/png",
            },
            b"edited-pixels",
        )


class StubRepository:
    def __init__(self, kind: str = "uploaded_image") -> None:
        self.metadata: dict[str, Any] = {}
        self.kind = kind

    async def update_metadata(self, artifact_id, user_id, metadata):
        self.metadata.update(metadata)
        return {
            "id": artifact_id,
            "conversation_id": "22222222-2222-4222-8222-222222222222",
            "kind": self.kind,
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


# A refined image receives its own current-pixel analysis and semantic index.
@pytest.mark.asyncio
async def test_existing_edited_artifact_is_observed_and_indexed() -> None:
    memory = RecordingMemory()
    service = VisionAnalysisService(
        StubImages(),  # type: ignore[arg-type]
        StubRepository("generated_image"),  # type: ignore[arg-type]
        StubVision(),  # type: ignore[arg-type]
        memory=memory,  # type: ignore[arg-type]
    )

    artifact = await service.observe_artifact(
        "index_user",
        "11111111-1111-4111-8111-111111111111",
    )

    assert artifact["metadata"]["analysis"] == "A magenta fox on a green platform."
    assert memory.saved[0]["metadata"]["artifact_id"] == artifact["id"]
    assert memory.saved[0]["metadata"]["kind"] == "generated_image"


@pytest.mark.asyncio
async def test_a_long_analysis_is_trimmed_before_it_is_indexed():
    from backend.services.vision_analysis_service import MAX_INDEXED_CHARS

    memory = RecordingMemory()
    service = _service(memory)
    service.provider.content = (
        "A magenta fox on a green platform. "
        + "It also has a lot to say about the composition and the light. " * 40
    )

    await _analyze(service)

    content = memory.saved[0]["content"]
    # The subject is named in the opening sentences; the rest is conversational
    # tail. One real reply ran to 1,371 characters, and every image was adding a
    # paragraph of prose to the database and to this panel.
    assert len(content) < MAX_INDEXED_CHARS + 100, len(content)
    assert "A magenta fox on a green platform." in content


@pytest.mark.asyncio
async def test_a_derived_description_is_not_listed_back_as_a_fact():
    from backend.memory.purposes import VISUAL_ANALYSIS_PURPOSE
    from backend.services.postgres_memory_service import DERIVED_PURPOSES

    # The snapshot that feeds "facts and preferences" filters on this set. An
    # image description is written so a picture can be found by describing it;
    # listing it as a fact once showed the assistant's own refusal to edit an
    # image back to the user as something they had said about themselves.
    assert VISUAL_ANALYSIS_PURPOSE in DERIVED_PURPOSES
