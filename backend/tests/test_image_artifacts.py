import asyncio
import io
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import Request
from PIL import Image

from backend.api.v1.images import ImageClientDisconnectedError, _run_until_disconnect
from backend.artifacts.image import validate_image_bytes
from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.artifacts.types import (
    GeneratedImage,
    ImageGenerationRequest,
    StoredBinary,
    VisionAnalysis,
)
from backend.services.image_artifact_service import ImageArtifactService
from backend.services.vision_analysis_service import (
    ArtifactNotFoundError,
    VisionAnalysisError,
    VisionAnalysisService,
)


# Create a small valid PNG for deterministic binary lifecycle tests.
def _png_bytes(color: tuple[int, int, int] = (15, 80, 200)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(output, format="PNG")
    return output.getvalue()


class StaticImageProvider:
    # Return one deterministic image with provider provenance.
    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        return GeneratedImage(
            content=_png_bytes(),
            mime_type="image/png",
            width=8,
            height=6,
            provider_job_id="provider-job-1",
            metadata={"seed": request.seed, "steps": 28},
        )


class FailingImageProvider:
    # Raise a private provider error for sanitized failure-state validation.
    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        raise RuntimeError("private provider detail")


class CapturingBinaryRepository:
    # Initialize one in-memory binary artifact lifecycle.
    def __init__(self) -> None:
        self.record: dict[str, Any] | None = None

    # Persist one pending binary record for the test request.
    async def create_binary_pending(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        kind: str,
        provider: str,
        model: str | None,
        title: str | None,
    ) -> dict[str, Any]:
        self.record = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "kind": kind,
            "status": "pending",
            "provider": provider,
            "model": model,
            "title": title,
        }
        return dict(self.record)

    # Mark the in-memory binary record ready with integrity metadata.
    async def mark_binary_ready(
        self,
        artifact_id: str,
        user_id: str,
        stored: StoredBinary,
        mime_type: str,
        width: int,
        height: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        assert self.record is not None
        self.record.update(
            status="ready",
            mime_type=mime_type,
            byte_size=stored.byte_size,
            sha256=stored.sha256,
            width=width,
            height=height,
            metadata=metadata,
            _storage_key=stored.storage_key,
        )
        return {
            key: value for key, value in self.record.items() if key != "_storage_key"
        }

    # Mark the in-memory binary record failed with a sanitized code.
    async def mark_failed(
        self,
        artifact_id: str,
        user_id: str,
        error_code: str,
    ) -> dict[str, Any]:
        assert self.record is not None
        self.record.update(status="failed", error_code=error_code)
        return dict(self.record)

    # Return the record only for its owning user and artifact identifier.
    async def get_owned(
        self,
        user_id: str,
        artifact_id: str,
    ) -> dict[str, Any] | None:
        if (
            self.record
            and self.record["user_id"] == user_id
            and self.record["id"] == artifact_id
        ):
            return dict(self.record)
        return None

    # Delete the record only for its owning user.
    async def delete(self, user_id: str, artifact_id: str) -> bool:
        if await self.get_owned(user_id, artifact_id) is None:
            return False
        self.record = None
        return True

    # Merge analysis metadata into the owned in-memory record.
    async def update_metadata(
        self,
        artifact_id: str,
        user_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        assert await self.get_owned(user_id, artifact_id) is not None
        assert self.record is not None
        self.record["metadata"] = {**self.record.get("metadata", {}), **metadata}
        return {
            key: value for key, value in self.record.items() if key != "_storage_key"
        }


class StaticVisionProvider:
    # Return grounded deterministic text for upload orchestration tests.
    async def analyze(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> VisionAnalysis:
        assert prompt == "Describe the validation image"
        assert content == _png_bytes()
        assert mime_type == "image/png"
        return VisionAnalysis(
            content="A small blue rectangle.",
            model="test-vision-model",
            metadata={"usage": {"total_tokens": 12}},
        )


class FailingVisionProvider:
    # Raise a private provider error for visible analysis-failure state tests.
    async def analyze(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> VisionAnalysis:
        raise RuntimeError("private vision provider detail")


class ThreadVisionProvider:
    # Record each threaded call and echo a deterministic grounded answer.
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def analyze_thread(
        self,
        content: bytes,
        mime_type: str,
        history: list[dict[str, str]],
        prompt: str,
    ) -> VisionAnalysis:
        self.calls.append(
            {
                "history": [dict(entry) for entry in history],
                "prompt": prompt,
                "mime_type": mime_type,
                "content": content,
            }
        )
        return VisionAnalysis(
            content=f"answer to: {prompt}",
            model="thread-model",
            metadata={},
        )


class FailingThreadVisionProvider:
    # Raise a private provider error for followup-failure state validation.
    async def analyze_thread(
        self,
        content: bytes,
        mime_type: str,
        history: list[dict[str, str]],
        prompt: str,
    ) -> VisionAnalysis:
        raise RuntimeError("private thread provider detail")


# Generate one ready owned image and return the vision service under test.
async def _ready_image_and_vision(
    tmp_path: Path,
    provider: Any,
    *,
    thread_context_turns: int = 8,
    thread_max_stored: int = 40,
) -> tuple[dict[str, Any], VisionAnalysisService, CapturingBinaryRepository]:
    repository = CapturingBinaryRepository()
    image_service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
    )
    ready = await image_service.generate(
        "vision-user",
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        ImageGenerationRequest("blue square", 2048, 2048, 42),
    )
    service = VisionAnalysisService(
        image_service,
        repository,  # type: ignore[arg-type]
        provider,
        thread_context_turns=thread_context_turns,
        thread_max_stored=thread_max_stored,
    )
    return ready, service, repository


# Verify followups on a generated image accumulate a persisted question thread.
@pytest.mark.asyncio
async def test_followup_accumulates_thread_and_replays_history(tmp_path: Path) -> None:
    provider = ThreadVisionProvider()
    ready, service, repository = await _ready_image_and_vision(tmp_path, provider)

    first = await service.ask_about_artifact("vision-user", ready["id"], "What color?")
    assert first["analysis"] == "answer to: What color?"
    assert provider.calls[0]["history"] == []
    assert provider.calls[0]["content"] == _png_bytes()

    await service.ask_about_artifact("vision-user", ready["id"], "How many shapes?")
    assert provider.calls[1]["history"] == [
        {
            "prompt": "What color?",
            "answer": "answer to: What color?",
            "model": "thread-model",
        }
    ]

    assert repository.record is not None
    thread = repository.record["metadata"]["analysis_thread"]
    assert [entry["prompt"] for entry in thread] == ["What color?", "How many shapes?"]
    assert repository.record["metadata"]["analysis"] == "answer to: How many shapes?"


# Verify the replayed context and stored thread are both bounded independently.
@pytest.mark.asyncio
async def test_followup_thread_context_and_storage_are_bounded(tmp_path: Path) -> None:
    provider = ThreadVisionProvider()
    ready, service, repository = await _ready_image_and_vision(
        tmp_path,
        provider,
        thread_context_turns=2,
        thread_max_stored=3,
    )

    for index in range(5):
        await service.ask_about_artifact("vision-user", ready["id"], f"Q{index}")

    # The final call replays only the two most recent prior answers.
    assert [entry["prompt"] for entry in provider.calls[-1]["history"]] == ["Q2", "Q3"]
    assert repository.record is not None
    stored = repository.record["metadata"]["analysis_thread"]
    assert [entry["prompt"] for entry in stored] == ["Q2", "Q3", "Q4"]


# Verify a prior flat analysis seeds the thread as the first question/answer pair.
@pytest.mark.asyncio
async def test_followup_seeds_thread_from_legacy_analysis(tmp_path: Path) -> None:
    provider = ThreadVisionProvider()
    ready, service, repository = await _ready_image_and_vision(tmp_path, provider)
    assert repository.record is not None
    repository.record["metadata"] = {
        "analysis": "A small blue rectangle.",
        "analysis_model": "legacy-model",
    }

    await service.ask_about_artifact("vision-user", ready["id"], "Is it centered?")

    assert provider.calls[0]["history"][0]["answer"] == "A small blue rectangle."
    stored = repository.record["metadata"]["analysis_thread"]
    assert [entry["prompt"] for entry in stored] == [
        "Describe this image.",
        "Is it centered?",
    ]


# Verify unowned or unknown artifacts raise a not-found signal without provider work.
@pytest.mark.asyncio
async def test_followup_rejects_unowned_or_unknown_image(tmp_path: Path) -> None:
    provider = ThreadVisionProvider()
    ready, service, _ = await _ready_image_and_vision(tmp_path, provider)

    with pytest.raises(ArtifactNotFoundError):
        await service.ask_about_artifact("vision-user", str(uuid.uuid4()), "Q")
    with pytest.raises(ArtifactNotFoundError):
        await service.ask_about_artifact("other-user", ready["id"], "Q")
    assert provider.calls == []


# Verify a failed followup surfaces safely and leaves the prior thread intact.
@pytest.mark.asyncio
async def test_followup_failure_preserves_existing_thread(tmp_path: Path) -> None:
    ready, service, repository = await _ready_image_and_vision(
        tmp_path, ThreadVisionProvider()
    )
    await service.ask_about_artifact("vision-user", ready["id"], "First question")
    assert repository.record is not None
    thread_before = list(repository.record["metadata"]["analysis_thread"])

    service.provider = FailingThreadVisionProvider()  # type: ignore[assignment]
    with pytest.raises(VisionAnalysisError) as failure:
        await service.ask_about_artifact("vision-user", ready["id"], "Second question")

    assert failure.value.artifact_id == ready["id"]
    assert repository.record["metadata"]["analysis_thread"] == thread_before


class DisconnectedRequest:
    # Report an immediate client disconnect to the image request monitor.
    async def is_disconnected(self) -> bool:
        return True


# Stay pending until the request monitor cancels this operation.
async def _wait_for_request_cancellation() -> dict[str, Any]:
    await asyncio.Event().wait()
    return {}


# Verify an HTTP disconnect cancels provider work instead of abandoning it pending.
@pytest.mark.asyncio
async def test_image_request_disconnect_cancels_operation() -> None:
    operation = asyncio.create_task(_wait_for_request_cancellation())
    with pytest.raises(ImageClientDisconnectedError):
        await _run_until_disconnect(
            cast(Request, DisconnectedRequest()),
            operation,
        )
    assert operation.cancelled()


# Verify supported media is decoded from content rather than trusted headers.
def test_validate_image_bytes_accepts_real_png_and_rejects_mismatch() -> None:
    validated = validate_image_bytes(
        _png_bytes(),
        "image/png",
        max_bytes=1024 * 1024,
        max_pixels=1000,
    )
    assert (validated.mime_type, validated.width, validated.height) == (
        "image/png",
        8,
        6,
    )

    with pytest.raises(ValueError, match="does not match"):
        validate_image_bytes(
            _png_bytes(),
            "image/jpeg",
            max_bytes=1024 * 1024,
            max_pixels=1000,
        )


# Verify generation persists, reads, integrity-checks, and deletes owned bytes.
@pytest.mark.asyncio
async def test_image_artifact_service_completes_binary_lifecycle(
    tmp_path: Path,
) -> None:
    repository = CapturingBinaryRepository()
    store = LocalBinaryArtifactStore(tmp_path)
    service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        store,
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
    )
    request = ImageGenerationRequest("blue square", 2048, 2048, 42)
    ready = await service.generate(
        "image-user",
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        request,
    )

    assert ready["status"] == "ready"
    assert ready["byte_size"] == len(_png_bytes())
    assert ready["metadata"]["generation_prompt"] == "blue square"
    restored = await service.read_owned("image-user", ready["id"])
    assert restored is not None
    assert restored[1] == _png_bytes()
    assert await service.read_owned("other-user", ready["id"]) is None
    assert await service.delete_owned("image-user", ready["id"]) is True
    assert list(tmp_path.rglob("*.png")) == []


# Verify provider failures leave a terminal sanitized artifact without bytes.
@pytest.mark.asyncio
async def test_image_artifact_service_records_provider_failure(tmp_path: Path) -> None:
    repository = CapturingBinaryRepository()
    service = ImageArtifactService(
        FailingImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
    )

    with pytest.raises(RuntimeError, match="private provider detail"):
        await service.generate(
            "image-user",
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            ImageGenerationRequest("failure", 2048, 2048, 42),
        )

    assert repository.record is not None
    assert repository.record["status"] == "failed"
    assert repository.record["error_code"] == "generation_failed"
    assert list(tmp_path.rglob("*.*")) == []


# Verify a validated upload is stored before analysis and retains grounded metadata.
@pytest.mark.asyncio
async def test_vision_analysis_service_persists_upload_and_analysis(
    tmp_path: Path,
) -> None:
    repository = CapturingBinaryRepository()
    image_service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
    )
    service = VisionAnalysisService(
        image_service,
        repository,  # type: ignore[arg-type]
        StaticVisionProvider(),  # type: ignore[arg-type]
    )

    result = await service.analyze_upload(
        "vision-user",
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "Describe the validation image",
        _png_bytes(),
        "image/png",
    )

    assert result["analysis"] == "A small blue rectangle."
    assert result["artifact"]["kind"] == "uploaded_image"
    assert result["artifact"]["metadata"]["analysis_status"] == "ready"
    assert result["artifact"]["metadata"]["analysis_model"] == ("test-vision-model")


# Verify invalid upload bytes are rejected before any artifact is created.
@pytest.mark.asyncio
async def test_invalid_upload_does_not_create_artifact(tmp_path: Path) -> None:
    repository = CapturingBinaryRepository()
    service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
    )

    with pytest.raises(ValueError, match="validated"):
        await service.store_upload(
            "vision-user",
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            b"not an image",
            "image/png",
        )

    assert repository.record is None


# Verify VLM failure preserves the upload and records a retryable visible state.
@pytest.mark.asyncio
async def test_vision_failure_preserves_upload_with_failed_analysis(
    tmp_path: Path,
) -> None:
    repository = CapturingBinaryRepository()
    image_service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
    )
    service = VisionAnalysisService(
        image_service,
        repository,  # type: ignore[arg-type]
        FailingVisionProvider(),  # type: ignore[arg-type]
    )

    with pytest.raises(VisionAnalysisError) as failure:
        await service.analyze_upload(
            "vision-user",
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "Describe the validation image",
            _png_bytes(),
            "image/png",
        )

    assert repository.record is not None
    assert repository.record["id"] == failure.value.artifact_id
    assert repository.record["status"] == "ready"
    assert repository.record["metadata"]["analysis_status"] == "failed"
    assert list(tmp_path.rglob("*.png")) != []
