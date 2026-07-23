import asyncio
import hashlib
import logging
from typing import Any

from backend.artifacts.image import validate_image_bytes
from backend.artifacts.types import ImageGenerationRequest
from backend.core.interfaces import (
    ArtifactEmbeddingStore,
    BinaryArtifactRepository,
    BinaryArtifactStore,
    ImageProvider,
    VisionEmbeddingProvider,
)

logger = logging.getLogger(__name__)


class ImageArtifactService:
    # Coordinate provider work, binary storage, and artifact state outside the model.
    def __init__(
        self,
        provider: ImageProvider,
        repository: BinaryArtifactRepository,
        store: BinaryArtifactStore,
        provider_name: str,
        model_name: str,
        max_upload_bytes: int,
        max_pixels: int,
        vision_embeddings: VisionEmbeddingProvider | None = None,
        embedding_store: ArtifactEmbeddingStore | None = None,
        vision_embedding_model: str = "",
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.store = store
        self.provider_name = provider_name
        self.model_name = model_name
        self.max_upload_bytes = max_upload_bytes
        self.max_pixels = max_pixels
        self.vision_embeddings = vision_embeddings
        self.embedding_store = embedding_store
        self.vision_embedding_model = vision_embedding_model

    # Embed one stored image so it is retrievable by meaning, not just caption.
    # Runs for generated and uploaded images alike; the pixels are what change,
    # so this happens once at store time and never on a followup question.
    async def _index_embedding(
        self,
        user_id: str,
        artifact_id: str,
        content: bytes,
    ) -> None:
        if self.vision_embeddings is None or self.embedding_store is None:
            return
        if not self.vision_embeddings.is_enabled():
            return
        try:
            # ONNX inference is blocking, so keep it off the event loop.
            vector = await asyncio.to_thread(
                self.vision_embeddings.embed_image,
                content,
            )
            await self.embedding_store.set_embedding(
                artifact_id,
                user_id,
                vector,
                self.vision_embedding_model,
            )
        except Exception:
            # An unembedded image is still a usable image; never fail the turn.
            logger.warning(
                "Failed to embed image artifact %s",
                artifact_id,
                exc_info=True,
            )

    # Generate and persist one ready image or leave a sanitized terminal failure.
    async def generate(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        request: ImageGenerationRequest,
    ) -> dict[str, Any]:
        artifact = await self.repository.create_binary_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            kind="generated_image",
            provider=self.provider_name,
            model=self.model_name,
            title="Generated image",
        )
        artifact_id = str(artifact["id"])
        storage_key: str | None = None
        try:
            generated = await self.provider.generate(request)
            extension = generated.mime_type.removeprefix("image/").replace(
                "jpeg", "jpg"
            )
            stored = await self.store.write(
                user_id,
                artifact_id,
                extension,
                generated.content,
            )
            storage_key = stored.storage_key
            ready_generated = await self.repository.mark_binary_ready(
                artifact_id=artifact_id,
                user_id=user_id,
                stored=stored,
                mime_type=generated.mime_type,
                width=generated.width,
                height=generated.height,
                metadata={
                    **generated.metadata,
                    "provider_job_id": generated.provider_job_id,
                    "generation_prompt": request.prompt,
                },
            )
            await self._index_embedding(user_id, artifact_id, generated.content)
            return ready_generated
        except asyncio.CancelledError:
            if storage_key:
                await self.store.delete(storage_key)
            await asyncio.shield(
                self.repository.mark_failed(artifact_id, user_id, "cancelled")
            )
            raise
        except Exception:
            if storage_key:
                await self.store.delete(storage_key)
            await self.repository.mark_failed(
                artifact_id,
                user_id,
                "generation_failed",
            )
            raise

    # Return owned binary content only when integrity metadata still matches.
    async def read_owned(
        self,
        user_id: str,
        artifact_id: str,
    ) -> tuple[dict[str, Any], bytes] | None:
        artifact = await self.repository.get_owned(user_id, artifact_id)
        if not artifact or artifact.get("status") != "ready":
            return None
        storage_key = artifact.get("_storage_key")
        if not isinstance(storage_key, str) or not storage_key:
            return None
        content = await self.store.read(storage_key)
        if len(content) != artifact.get("byte_size"):
            raise RuntimeError("Stored artifact size does not match its record")
        if hashlib.sha256(content).hexdigest() != artifact.get("sha256"):
            raise RuntimeError("Stored artifact hash does not match its record")
        artifact.pop("_storage_key", None)
        return artifact, content

    # Validate and persist one uploaded image before any model receives it.
    async def store_upload(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        content: bytes,
        declared_mime_type: str | None,
    ) -> tuple[dict[str, Any], bytes]:
        validated = validate_image_bytes(
            content,
            declared_mime_type,
            self.max_upload_bytes,
            self.max_pixels,
        )
        artifact = await self.repository.create_binary_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            kind="uploaded_image",
            provider="user_upload",
            model=None,
            title="Uploaded image",
        )
        artifact_id = str(artifact["id"])
        storage_key: str | None = None
        try:
            stored = await self.store.write(
                user_id,
                artifact_id,
                validated.extension,
                content,
            )
            storage_key = stored.storage_key
            ready = await self.repository.mark_binary_ready(
                artifact_id=artifact_id,
                user_id=user_id,
                stored=stored,
                mime_type=validated.mime_type,
                width=validated.width,
                height=validated.height,
                metadata={"analysis_status": "pending"},
            )
            await self._index_embedding(user_id, artifact_id, content)
            return ready, content
        except Exception:
            if storage_key:
                await self.store.delete(storage_key)
            await self.repository.mark_failed(
                artifact_id,
                user_id,
                "upload_persistence_failed",
            )
            raise

    # Delete owned binary content before removing its artifact record.
    async def delete_owned(self, user_id: str, artifact_id: str) -> bool:
        artifact = await self.repository.get_owned(user_id, artifact_id)
        if artifact is None:
            return False
        storage_key = artifact.get("_storage_key")
        if isinstance(storage_key, str) and storage_key:
            await self.store.delete(storage_key)
        return await self.repository.delete(user_id, artifact_id)
