from typing import Any

import pytest

from backend.artifacts.types import (
    GeneratedImage,
    ImageGenerationRequest,
    StoredBinary,
)
from backend.services.image_artifact_service import ImageArtifactService

USER = "embed_user"
CONVERSATION = "55555555-5555-4555-8555-555555555555"
TRACE = "66666666-6666-4666-8666-666666666666"
REQUEST = ImageGenerationRequest(prompt="a red car", width=2048, height=2048, seed=7)


class StubProvider:
    async def generate(self, request):
        return GeneratedImage(
            content=b"generated-bytes",
            mime_type="image/png",
            width=64,
            height=64,
            provider_job_id="job-1",
            metadata={"seed": 1},
        )


class StubStore:
    async def write(self, user_id, artifact_id, extension, content):
        return StoredBinary(
            storage_key=f"{user_id}/{artifact_id}.{extension}",
            byte_size=len(content),
            sha256="0" * 64,
        )

    async def delete(self, storage_key):
        return None


class StubRepository:
    def __init__(self) -> None:
        self.embeddings: list[dict[str, Any]] = []

    async def create_binary_pending(self, **kwargs):
        return {"id": "44444444-4444-4444-8444-444444444444", **kwargs}

    async def mark_binary_ready(self, artifact_id, user_id, stored, **kwargs):
        return {"id": artifact_id, "status": "ready"}

    async def mark_failed(self, artifact_id, user_id, error_code):
        return {"id": artifact_id, "status": "failed"}

    async def set_embedding(self, artifact_id, user_id, embedding, model):
        self.embeddings.append(
            {
                "artifact_id": artifact_id,
                "user_id": user_id,
                "dimension": len(embedding),
                "model": model,
            }
        )


class StubVisionEmbeddings:
    def __init__(self, enabled: bool = True, fail: bool = False) -> None:
        self.enabled = enabled
        self.fail = fail
        self.calls = 0

    def is_enabled(self) -> bool:
        return self.enabled

    def embed_image(self, content: bytes) -> list[float]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("onnx session unavailable")
        return [0.5] * 768


def _service(embeddings, repository) -> ImageArtifactService:
    return ImageArtifactService(
        provider=StubProvider(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        store=StubStore(),  # type: ignore[arg-type]
        provider_name="stub",
        model_name="stub-model",
        max_upload_bytes=10_000_000,
        max_pixels=20_000_000,
        vision_embeddings=embeddings,  # type: ignore[arg-type]
        embedding_store=repository,  # type: ignore[arg-type]
        vision_embedding_model="nomic-embed-vision-v1.5",
    )


@pytest.mark.asyncio
async def test_generated_image_is_embedded_at_store_time():
    embeddings = StubVisionEmbeddings()
    repository = StubRepository()

    await _service(embeddings, repository).generate(USER, CONVERSATION, TRACE, REQUEST)

    # Pixels remain the semantic index even though prompt provenance is stored.
    assert embeddings.calls == 1
    assert len(repository.embeddings) == 1
    assert repository.embeddings[0]["dimension"] == 768
    assert repository.embeddings[0]["model"] == "nomic-embed-vision-v1.5"
    assert repository.embeddings[0]["user_id"] == USER


@pytest.mark.asyncio
async def test_embedding_failure_still_returns_a_usable_image():
    embeddings = StubVisionEmbeddings(fail=True)
    repository = StubRepository()

    result = await _service(embeddings, repository).generate(
        USER, CONVERSATION, TRACE, REQUEST
    )

    # An unembedded image is still a usable image.
    assert result["status"] == "ready"
    assert repository.embeddings == []


@pytest.mark.asyncio
async def test_disabled_embedder_is_never_invoked():
    embeddings = StubVisionEmbeddings(enabled=False)
    repository = StubRepository()

    await _service(embeddings, repository).generate(USER, CONVERSATION, TRACE, REQUEST)

    assert embeddings.calls == 0
    assert repository.embeddings == []


@pytest.mark.asyncio
async def test_service_without_embedding_configured_still_generates():
    repository = StubRepository()
    service = ImageArtifactService(
        provider=StubProvider(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        store=StubStore(),  # type: ignore[arg-type]
        provider_name="stub",
        model_name="stub-model",
        max_upload_bytes=10_000_000,
        max_pixels=20_000_000,
    )

    result = await service.generate(USER, CONVERSATION, TRACE, REQUEST)

    assert result["status"] == "ready"
    assert repository.embeddings == []
