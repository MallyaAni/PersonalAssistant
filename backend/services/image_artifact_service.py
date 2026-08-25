import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from backend.artifacts.image import validate_image_bytes
from backend.artifacts.types import (
    ImageEditRequest,
    ImageGenerationRequest,
)
from backend.core.interfaces import (
    ArtifactEmbeddingStore,
    BinaryArtifactRepository,
    BinaryArtifactStore,
    ImageEditProvider,
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
        edit_provider: ImageEditProvider | None = None,
        edit_provider_name: str = "",
        edit_model_name: str = "",
        descriptions: Any | None = None,
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
        self.edit_provider = edit_provider
        self.edit_provider_name = edit_provider_name
        self.edit_model_name = edit_model_name
        self.descriptions = descriptions

    # Index what a generated or edited picture shows, so the referent resolver
    # and description recall can find it later. An upload gets this from the
    # vision model's observation; a generated picture's own prompt is the
    # description it was made from, and an edit is what it was made from plus
    # the instruction applied. Without this only uploads could be found by
    # description - measured 2026-08-25: "edit the bicycle picture" found
    # nothing, and an unselected edit right after a generation had no
    # candidate at all. An enhancement, never a failure of the artifact.
    async def _index_description(
        self,
        user_id: str,
        artifact_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        if self.descriptions is None or not content.strip():
            return
        try:
            await self.descriptions.replace_visual_semantic_memory(
                user_id,
                artifact_id,
                " ".join(content.split())[:2_000],
                {"artifact_id": artifact_id, **metadata},
            )
        except Exception:
            logger.warning(
                "Could not index the description of image %s",
                artifact_id,
                exc_info=True,
            )

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
        # Retry briefly: embedding failures are usually transient (CPU/ONNX under
        # load), and a missing vector makes the image unrecallable. Anything that
        # still fails here is caught later by the background reconciler, so the
        # turn is never failed for it.
        for attempt in range(3):
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
                return
            except Exception:
                if attempt == 2:
                    logger.warning(
                        "Failed to embed image artifact %s after retries; "
                        "the reconciler will backfill it",
                        artifact_id,
                        exc_info=True,
                    )
                else:
                    await asyncio.sleep(0.5 * (attempt + 1))

    async def get_owned_record(
        self,
        user_id: str,
        artifact_id: str,
    ) -> dict[str, Any] | None:
        artifact = await self.repository.get_owned(user_id, artifact_id)
        if artifact is None:
            return None
        artifact.pop("_storage_key", None)
        return artifact

    # Generate and persist one ready image or leave a sanitized terminal failure.
    async def generate(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        request: ImageGenerationRequest,
        extra_metadata: dict[str, Any] | None = None,
        extra_style: str = "",
        on_pending: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        # Set when this picture was built from one the user already has, rather
        # than from nothing. The source-conditioned editor cannot restage a
        # scene, so an edit that needs the scene rebuilt is carried out by
        # generating from a description of the original - and the result is
        # still that original's child. Without this the lineage breaks and the
        # new picture looks unrelated to the one it came from.
        parent: dict[str, Any] | None = None,
        title: str = "Generated image",
    ) -> dict[str, Any]:
        artifact = await self.repository.create_binary_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            kind="generated_image",
            provider=self.provider_name,
            model=self.model_name,
            title=title,
            parent_artifact_id=(
                str(parent.get("id") or "") or None if parent else None
            ),
        )
        artifact_id = str(artifact["id"])
        storage_key: str | None = None
        if on_pending is not None:
            await on_pending(artifact)
        # The user's learned style steers the pixels but is not the recorded
        # intent, so it is applied to the provider request while the stored
        # generation_prompt stays the base prompt a later refinement builds on.
        #
        # A diffusion model draws every token it is given, so the prompt has to
        # be the subject rather than the sentence that asked for it - leaving
        # "generate an image of" in front of "a car" spends most of the prompt
        # on words that describe nothing. The model that writes this states the
        # subject directly, which is what its tool schema asks for, so there is
        # nothing left to strip and no phrasing to pattern-match.
        subject = request.prompt.strip()
        style = extra_style.strip()
        provider_prompt = f"{subject}, {style}" if style else subject
        provider_request = (
            request
            if provider_prompt == request.prompt
            else ImageGenerationRequest(
                prompt=provider_prompt,
                width=request.width,
                height=request.height,
                seed=request.seed,
            )
        )
        try:
            generated = await self.provider.generate(provider_request)
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
                    **(extra_metadata or {}),
                },
            )
            await self._index_embedding(user_id, artifact_id, generated.content)
            await self._index_description(
                user_id,
                artifact_id,
                request.prompt,
                {"kind": "generated_image", "source": "generation_prompt"},
            )
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

    # Edit owned source pixels and persist the result as an immutable child revision.
    async def edit(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        parent: dict[str, Any],
        source_content: bytes,
        instruction: str,
        seed: int,
        user_feedback: str | None = None,
        on_pending: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        if self.edit_provider is None:
            raise RuntimeError("No source-conditioned image editor is configured")
        artifact = await self.repository.create_binary_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            kind="generated_image",
            provider=self.edit_provider_name or self.provider_name,
            model=self.edit_model_name or None,
            title="Edited image",
            parent_artifact_id=str(parent.get("id") or "") or None,
        )
        artifact_id = str(artifact["id"])
        storage_key: str | None = None
        if on_pending is not None:
            await on_pending(artifact)
        try:
            edited = await self.edit_provider.edit(
                ImageEditRequest(
                    instruction=instruction,
                    source_content=source_content,
                    source_mime_type=str(parent.get("mime_type") or "image/png"),
                    seed=seed,
                )
            )
            extension = edited.mime_type.removeprefix("image/").replace("jpeg", "jpg")
            stored = await self.store.write(
                user_id,
                artifact_id,
                extension,
                edited.content,
            )
            storage_key = stored.storage_key
            parent_metadata = parent.get("metadata") or {}
            ready = await self.repository.mark_binary_ready(
                artifact_id=artifact_id,
                user_id=user_id,
                stored=stored,
                mime_type=edited.mime_type,
                width=edited.width,
                height=edited.height,
                metadata={
                    **edited.metadata,
                    "provider_job_id": edited.provider_job_id,
                    "generation_prompt": str(
                        parent_metadata.get("generation_prompt") or ""
                    ),
                    "parent_artifact_id": str(parent.get("id") or ""),
                    "refinement_feedback": user_feedback or instruction,
                    "edit_instruction": instruction,
                    "edit_mode": "source_conditioned",
                },
            )
            await self._index_embedding(user_id, artifact_id, edited.content)
            origin = str(
                parent_metadata.get("generation_prompt")
                or parent.get("title")
                or "a picture"
            )
            await self._index_description(
                user_id,
                artifact_id,
                f"{origin}. Edited: {instruction}",
                {
                    "kind": "edited_image",
                    "source": "edit_instruction",
                    "parent_artifact_id": str(parent.get("id") or ""),
                },
            )
            return ready
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
                "edit_failed",
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
