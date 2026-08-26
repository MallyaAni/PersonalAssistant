import asyncio
import io
import uuid
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import Request
from PIL import Image

from backend.api.v1.images import ImageClientDisconnectedError, _run_until_disconnect
from backend.artifacts.image import validate_image_bytes
from backend.artifacts.storage import LocalBinaryArtifactStore
from backend.artifacts.types import (
    GeneratedImage,
    ImageEditRequest,
    ImageGenerationRequest,
    StoredBinary,
    VisionAnalysis,
    VisionUploadInspection,
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


class StaticImageEditProvider:
    def __init__(self) -> None:
        self.requests: list[ImageEditRequest] = []

    # Return a deterministic red image while recording the exact source request.
    async def edit(self, request: ImageEditRequest) -> GeneratedImage:
        self.requests.append(request)
        return GeneratedImage(
            content=_png_bytes((200, 20, 20)),
            mime_type="image/png",
            width=8,
            height=6,
            provider_job_id="edit-job-1",
            metadata={"seed": request.seed, "steps": 4},
        )


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
        parent_artifact_id: str | None = None,
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
            "parent_artifact_id": parent_artifact_id,
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
    # Return one structured upload result from a single simulated image call.
    async def inspect_upload(
        self,
        question: str,
        content: bytes,
        mime_type: str,
    ) -> VisionUploadInspection:
        assert content == _png_bytes()
        assert mime_type == "image/png"
        return VisionUploadInspection(
            intent="ask",
            observation="A small blue rectangle.",
            answer="The validation image contains a small blue rectangle.",
            grounding="not_needed",
            search_query="",
            needs_reasoning=False,
            unsupported_reason="not_applicable",
            model="test-vision-model",
            metadata={"usage": {"total_tokens": 12}},
        )

    # Return grounded deterministic text for upload orchestration tests.
    async def analyze(
        self,
        prompt: str,
        content: bytes,
        mime_type: str,
    ) -> VisionAnalysis:
        assert content == _png_bytes()
        assert mime_type == "image/png"
        answer = (
            "A small blue rectangle."
            if prompt != "Describe the validation image"
            else "The validation image contains a small blue rectangle."
        )
        return VisionAnalysis(
            content=answer,
            model="test-vision-model",
            metadata={"usage": {"total_tokens": 12}},
        )


class FailingVisionProvider:
    # Fail the only structured upload inspection with a private provider error.
    async def inspect_upload(self, question, content, mime_type):
        raise RuntimeError("private vision provider detail")

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
        question = prompt.rsplit("User question:\n", 1)[-1]
        self.calls.append(
            {
                "history": [dict(entry) for entry in history],
                "prompt": prompt,
                "mime_type": mime_type,
                "content": content,
            }
        )
        return VisionAnalysis(
            content=f"answer to: {question}",
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
    assert "analysis" not in repository.record["metadata"]


# A follow-up answer must not replace the neutral description used for recall.
@pytest.mark.asyncio
async def test_followup_preserves_the_canonical_visual_analysis(tmp_path: Path) -> None:
    provider = ThreadVisionProvider()
    ready, service, repository = await _ready_image_and_vision(tmp_path, provider)
    assert repository.record is not None
    repository.record["metadata"].update(
        {
            "analysis": "A person wearing a tailored navy jacket.",
            "analysis_model": "vision-model",
        }
    )

    await service.ask_about_artifact(
        "vision-user",
        ready["id"],
        "Would a straw hat suit this outfit?",
    )

    assert repository.record["metadata"]["analysis"] == (
        "A person wearing a tailored navy jacket."
    )
    assert repository.record["metadata"]["analysis_model"] == "vision-model"
    assert repository.record["metadata"]["analysis_thread"][-1]["prompt"] == (
        "Would a straw hat suit this outfit?"
    )


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


def _jpeg_bytes(color: tuple[int, int, int] = (200, 100, 50)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(output, format="JPEG")
    return output.getvalue()


# Verify a real JPEG survives the names Windows actually gives it.
#
# Windows resolves a .jpg upload's type from the registry, which in some
# configurations reports `image/jpg` or the legacy `image/pjpeg`; Chrome
# forwards that verbatim, and a strict equality check rejected the user's own
# photographs as a content mismatch. The aliases must resolve, and a genuinely
# contradictory declaration must still be refused - that is the case the
# mismatch check exists for.
@pytest.mark.parametrize(
    "declared",
    ["image/jpeg", "image/jpg", "image/pjpeg", " IMAGE/JPG ", None],
)
def test_validate_image_bytes_accepts_jpeg_under_its_windows_aliases(
    declared: str | None,
) -> None:
    validated = validate_image_bytes(
        _jpeg_bytes(),
        declared,
        max_bytes=1024 * 1024,
        max_pixels=1000,
    )
    assert validated.mime_type == "image/jpeg"
    assert validated.extension == "jpg"


def _mpo_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (200, 100, 50)).save(
        output,
        format="MPO",
        append_images=[Image.new("RGB", (8, 6), (20, 60, 120))],
    )
    return output.getvalue()


# Verify a phone photograph carrying a companion frame is accepted as a JPEG.
#
# Most phone cameras embed a second frame (depth map or wide-angle companion),
# which Pillow reports as MPO while the browser still declares image/jpeg. The
# format allow-list did not know the name and the frame count read as animation,
# so two separate checks rejected an ordinary photograph.
def test_validate_image_bytes_accepts_a_multi_frame_phone_jpeg() -> None:
    validated = validate_image_bytes(
        _mpo_bytes(),
        "image/jpeg",
        max_bytes=1024 * 1024,
        max_pixels=1000,
    )
    assert (validated.mime_type, validated.extension) == ("image/jpeg", "jpg")


# The companion-frame exemption must not readmit genuine animation.
def test_validate_image_bytes_still_rejects_animated_media() -> None:
    output = io.BytesIO()
    Image.new("P", (8, 6)).save(
        output,
        format="GIF",
        save_all=True,
        append_images=[Image.new("P", (8, 6))],
    )
    with pytest.raises(ValueError, match="not supported"):
        validate_image_bytes(
            output.getvalue(),
            None,
            max_bytes=1024 * 1024,
            max_pixels=1000,
        )


def test_validate_image_bytes_still_rejects_a_contradictory_declaration() -> None:
    with pytest.raises(ValueError, match="does not match"):
        validate_image_bytes(
            _jpeg_bytes(),
            "image/png",
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


# Verify source-conditioned editing persists immutable lineage and exact feedback.
@pytest.mark.asyncio
async def test_image_artifact_service_persists_source_conditioned_edit(
    tmp_path: Path,
) -> None:
    repository = CapturingBinaryRepository()
    editor = StaticImageEditProvider()
    service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
        edit_provider=editor,
        edit_provider_name="comfyui",
        edit_model_name="flux2-klein",
    )
    parent = {
        "id": "parent-image",
        "kind": "generated_image",
        "mime_type": "image/png",
        "metadata": {"generation_prompt": "a black sports car by the coast"},
    }

    ready = await service.edit(
        "image-user",
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        parent,
        _png_bytes(),
        "make only the car red",
        42,
        user_feedback="make this car red",
    )

    assert editor.requests[0].source_content == _png_bytes()
    assert editor.requests[0].instruction == "make only the car red"
    assert ready["status"] == "ready"
    assert ready["model"] == "flux2-klein"
    assert ready["metadata"]["parent_artifact_id"] == "parent-image"
    assert ready["metadata"]["edit_mode"] == "source_conditioned"
    # Recorded as an edge on the row itself, not only as a note in metadata:
    # provenance is resolved by joining on it, and it is set when the row is
    # created so an edit that fails halfway still says what it came from.
    assert repository.record is not None
    assert repository.record["parent_artifact_id"] == "parent-image"
    assert ready["metadata"]["refinement_feedback"] == "make this car red"
    assert ready["metadata"]["generation_prompt"] == ("a black sports car by the coast")


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

    assert result["analysis"] == (
        "The validation image contains a small blue rectangle."
    )
    assert result["artifact"]["kind"] == "uploaded_image"
    assert result["artifact"]["metadata"]["analysis_status"] == "ready"
    assert result["artifact"]["metadata"]["analysis_model"] == ("test-vision-model")
    assert result["artifact"]["metadata"]["analysis"] == "A small blue rectangle."


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


def test_an_edit_never_asks_for_more_pixels_than_the_source_has():
    import io as _io

    from PIL import Image as _Image

    from backend.artifacts.image import ComfyUIImageEditProvider

    provider = ComfyUIImageEditProvider(
        base_url="http://localhost:8188",
        model="m.safetensors",
        text_encoder="t.safetensors",
        vae="v.safetensors",
        timeout_seconds=1,
        poll_seconds=0.1,
        max_concurrency=1,
        max_output_bytes=10_000_000,
        max_pixels=20_000_000,
        steps=4,
        megapixels=2.0,
    )

    def png(width: int, height: int) -> bytes:
        buffer = _io.BytesIO()
        _Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
        return buffer.getvalue()

    # A 206x206 upload was being enlarged to 1440x1440 and came back as a large
    # blurry thumbnail. An edit can rewrite pixels; it cannot invent them.
    assert provider._target_megapixels(png(206, 206)) < 0.05
    # A source with room to spare still gets the configured budget.
    assert provider._target_megapixels(png(3000, 3000)) == 2.0
    # Unreadable bytes fall back rather than failing the edit.
    assert provider._target_megapixels(b"not an image") == 2.0


def test_an_edit_comes_back_at_exactly_the_size_it_was_given():
    import io as _io

    from PIL import Image as _Image

    from backend.artifacts.image import _match_source_size

    def png(width: int, height: int) -> bytes:
        buffer = _io.BytesIO()
        _Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
        return buffer.getvalue()

    # The model works on a 16-pixel latent grid, so 206 comes back as 208. An
    # edit is a change to an image, not to its size.
    corrected = _match_source_size(png(208, 208), png(206, 206))
    with _Image.open(_io.BytesIO(corrected)) as image:
        assert image.size == (206, 206)

    # Already correct: returned untouched rather than re-encoded.
    same = png(512, 512)
    assert _match_source_size(same, png(512, 512)) is same

    # An unreadable source must not lose a finished edit.
    edited = png(64, 64)
    assert _match_source_size(edited, b"not an image") is edited


# Each image-provider fault must read as the thing the user should do next.
#
# A refused connection means the service is down and needs starting; a
# connection accepted and then dropped means it went away mid-job and will
# likely be back. Reported identically, the second read as a flat refusal and
# nobody knew that retrying was the right move.
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.ConnectError("refused"), "Try again later"),
        (httpx.ConnectTimeout("timed out"), "Try again later"),
        (httpx.RemoteProtocolError("Server disconnected"), "stopped partway"),
        (httpx.ReadTimeout("read timed out"), "stopped partway"),
        (ValueError("something else"), "Please try again"),
    ],
)
def test_image_failures_are_reported_as_different_faults(exc, expected):
    from backend.services.conversation_service import _image_provider_failure_message

    assert expected in _image_provider_failure_message(exc, "generate")


# The Klein 9B on a 16 GB card may have to run as a GGUF quantization. The
# loader must follow the file name the way the Kontext editor's already does,
# so the fallback is an IMAGE_MODEL change and never a code change.
def test_the_klein_loader_follows_the_model_file_type():
    from backend.artifacts.image import ComfyUIImageEditProvider, ComfyUIImageProvider
    from backend.artifacts.types import ImageGenerationRequest

    def provider(model: str) -> ComfyUIImageProvider:
        return ComfyUIImageProvider(
            base_url="http://localhost:8188",
            model=model,
            timeout_seconds=1,
            poll_seconds=0.1,
            max_concurrency=1,
            max_output_bytes=10_000_000,
            max_pixels=20_000_000,
            text_encoder="t.safetensors",
            vae="v.safetensors",
            steps=4,
        )

    request = ImageGenerationRequest(prompt="a lamp", width=1024, height=1024, seed=1)
    gguf = provider("flux-2-klein-9b-Q6_K.gguf")._workflow(request)["1"]
    assert gguf["class_type"] == "UnetLoaderGGUF"
    assert "weight_dtype" not in gguf["inputs"]
    plain = provider("flux-2-klein-9b-fp8.safetensors")._workflow(request)["1"]
    assert plain["class_type"] == "UNETLoader"
    # The Klein editor shares the switch; nothing there is spelled twice.
    editor = ComfyUIImageEditProvider(
        base_url="http://localhost:8188",
        model="flux-2-klein-9b-Q6_K.gguf",
        text_encoder="t.safetensors",
        vae="v.safetensors",
        timeout_seconds=1,
        poll_seconds=0.1,
        max_concurrency=1,
        max_output_bytes=10_000_000,
        max_pixels=20_000_000,
        steps=4,
        megapixels=2.0,
    )
    assert editor._model_loader()["class_type"] == "UnetLoaderGGUF"


class RecordingDescriptions:
    # Capture what the image service indexes as a picture's description.
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    async def replace_visual_semantic_memory(
        self, user_id: str, artifact_id: str, content: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((user_id, artifact_id, content, metadata))
        return {"id": "memory-1"}


# A generated picture must be findable by what it shows, exactly as an upload
# is after the vision model describes it. The prompt is that description.
@pytest.mark.asyncio
async def test_a_generated_picture_is_indexed_by_its_prompt(tmp_path: Path):
    repository = CapturingBinaryRepository()
    descriptions = RecordingDescriptions()
    service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
        descriptions=descriptions,
    )
    ready = await service.generate(
        "image-user",
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        ImageGenerationRequest("a red bicycle leaning against a brick wall", 1024, 1024, 7),
    )
    assert ready["status"] == "ready"
    assert len(descriptions.calls) == 1
    user_id, artifact_id, content, metadata = descriptions.calls[0]
    assert user_id == "image-user"
    assert artifact_id == ready["id"]
    assert content == "a red bicycle leaning against a brick wall"
    assert metadata["artifact_id"] == ready["id"]
    assert metadata["source"] == "generation_prompt"


# Indexing is an enhancement: a description store that fails must not fail
# the picture that was just generated.
@pytest.mark.asyncio
async def test_a_failing_description_index_never_fails_the_picture(tmp_path: Path):
    class Broken:
        async def replace_visual_semantic_memory(self, *args: Any, **kwargs: Any):
            raise RuntimeError("index unavailable")

    repository = CapturingBinaryRepository()
    service = ImageArtifactService(
        StaticImageProvider(),
        repository,  # type: ignore[arg-type]
        LocalBinaryArtifactStore(tmp_path),
        "test-provider",
        "test-model",
        1024 * 1024,
        1000,
        descriptions=Broken(),
    )
    ready = await service.generate(
        "image-user",
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        ImageGenerationRequest("blue square", 512, 512, 1),
    )
    assert ready["status"] == "ready"


# ComfyUI on the desktop exits cleanly at the VM's memory ceiling and Docker
# brings it back within seconds. A job it dropped is resubmitted exactly once
# after it answers again; a job it rejected or one that times out is not.
def _comfy_handler(posts: list[int], comes_back: bool):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/prompt":
            posts.append(1)
            if len(posts) == 1:
                raise httpx.RemoteProtocolError("Server disconnected", request=request)
            return httpx.Response(200, json={"prompt_id": "second"})
        if path == "/system_stats":
            if not comes_back:
                raise httpx.ConnectError("refused", request=request)
            return httpx.Response(200, json={"system": {}})
        if path.startswith("/history/"):
            return httpx.Response(
                200,
                json={
                    "second": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"13": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}},
                    }
                },
            )
        if path == "/view":
            return httpx.Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        return httpx.Response(404)

    return handler


def _comfy_provider(handler, restart_wait_seconds: float):
    from backend.artifacts.image import ComfyUIImageProvider

    return ComfyUIImageProvider(
        base_url="http://comfy",
        model="m.safetensors",
        timeout_seconds=5,
        poll_seconds=0.01,
        max_concurrency=1,
        max_output_bytes=10_000_000,
        max_pixels=20_000_000,
        text_encoder="t.safetensors",
        vae="v.safetensors",
        steps=4,
        restart_wait_seconds=restart_wait_seconds,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_a_job_comfyui_dropped_is_resubmitted_once_when_it_returns():
    posts: list[int] = []
    provider = _comfy_provider(_comfy_handler(posts, comes_back=True), restart_wait_seconds=1.0)

    image = await provider.generate(ImageGenerationRequest("a lamp", 1024, 1024, 1))

    assert image.content == _png_bytes()
    # The whole recipe is on the record: the composed prompt with its
    # suffixes, the person flag, and the steps the workflow actually ran
    # (the record said 28 for a 4-step Klein generation until 2026-08-26).
    assert image.metadata["positive_prompt"].startswith("a lamp")
    assert image.metadata["depicts_a_person"] is False
    assert image.metadata["steps"] == provider.steps
    assert image.provider_job_id == "second"
    assert len(posts) == 2, "exactly one resubmission"


@pytest.mark.asyncio
async def test_a_job_comfyui_dropped_still_fails_when_it_stays_away():
    posts: list[int] = []
    provider = _comfy_provider(_comfy_handler(posts, comes_back=False), restart_wait_seconds=0.2)

    with pytest.raises(httpx.RemoteProtocolError):
        await provider.generate(ImageGenerationRequest("a lamp", 1024, 1024, 1))
    assert len(posts) == 1, "no blind resubmission"
