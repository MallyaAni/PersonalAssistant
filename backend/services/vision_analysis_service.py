import logging
from typing import Any

from backend.core.interfaces import (
    BinaryArtifactRepository,
    SemanticMemoryWriter,
    VisionProvider,
)
from backend.services.image_artifact_service import ImageArtifactService

logger = logging.getLogger(__name__)

# Derived index entries are kept distinct from user-stated facts, which follow
# the explicit approval path. This purpose marks application-generated text.
VISUAL_ANALYSIS_PURPOSE = "visual_artifact_analysis"


class VisionAnalysisError(RuntimeError):
    # Retain the valid upload identifier while exposing only a safe public failure.
    def __init__(self, artifact_id: str) -> None:
        super().__init__("Vision analysis failed")
        self.artifact_id = artifact_id


class ArtifactNotFoundError(LookupError):
    """Signals that no ready owned image matched the requested artifact."""


class VisionAnalysisService:
    # Coordinate upload persistence and grounded VLM analysis outside the model.
    def __init__(
        self,
        images: ImageArtifactService,
        repository: BinaryArtifactRepository,
        provider: VisionProvider,
        thread_context_turns: int = 8,
        thread_max_stored: int = 40,
        memory: SemanticMemoryWriter | None = None,
    ) -> None:
        self.images = images
        self.repository = repository
        self.provider = provider
        self.thread_context_turns = thread_context_turns
        self.thread_max_stored = thread_max_stored
        self.memory = memory

    # Index one image's description so images become semantically retrievable.
    # Only `content` reaches the assistant prompt, so it must name its own
    # provenance rather than read as a user-stated fact.
    async def _index_analysis(
        self,
        user_id: str,
        artifact: dict[str, Any],
        analysis_text: str,
        model: str,
    ) -> None:
        if self.memory is None or not analysis_text.strip():
            return
        raw_kind = str(artifact.get("kind") or "image")
        kind_label = raw_kind.removesuffix("_image") or "stored"
        artifact_id = str(artifact.get("id"))
        try:
            await self.memory.save_semantic_memory(
                user_id,
                f"Description of an image the user has ({kind_label}): "
                f"{analysis_text}",
                {
                    "artifact_id": artifact_id,
                    "conversation_id": str(artifact.get("conversation_id") or ""),
                    "kind": str(artifact.get("kind") or ""),
                    "source": "vision_analysis",
                    "analysis_model": model,
                },
                purpose=VISUAL_ANALYSIS_PURPOSE,
            )
        except Exception:
            # Indexing is an enhancement; a failure must not lose the analysis.
            logger.warning(
                "Failed to index analysis for artifact %s",
                artifact_id,
                exc_info=True,
            )

    # Persist one validated upload and attach its successful grounded analysis.
    async def analyze_upload(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        prompt: str,
        content: bytes,
        declared_mime_type: str | None,
    ) -> dict[str, Any]:
        artifact, validated_content = await self.images.store_upload(
            user_id,
            conversation_id,
            trace_id,
            content,
            declared_mime_type,
        )
        artifact_id = str(artifact["id"])
        try:
            analysis = await self.provider.analyze(
                prompt,
                validated_content,
                str(artifact["mime_type"]),
            )
        except Exception as exc:
            await self.repository.update_metadata(
                artifact_id,
                user_id,
                {"analysis_status": "failed"},
            )
            raise VisionAnalysisError(artifact_id) from exc
        updated = await self.repository.update_metadata(
            artifact_id,
            user_id,
            {
                "analysis_status": "ready",
                "analysis": analysis.content,
                "analysis_model": analysis.model,
                **analysis.metadata,
            },
        )
        await self._index_analysis(user_id, updated, analysis.content, analysis.model)
        return {
            "artifact": updated,
            "analysis": analysis.content,
            "model": analysis.model,
        }

    # Answer one followup question about an owned image and persist the thread.
    async def ask_about_artifact(
        self,
        user_id: str,
        artifact_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        owned = await self.images.read_owned(user_id, artifact_id)
        if owned is None:
            raise ArtifactNotFoundError("No ready owned image matched the request")
        artifact, content = owned
        metadata = artifact.get("metadata") or {}
        thread = self._existing_thread(metadata)
        recent = thread[-self.thread_context_turns :]
        try:
            analysis = await self.provider.analyze_thread(
                content=content,
                mime_type=str(artifact["mime_type"]),
                history=recent,
                prompt=prompt,
            )
        except Exception as exc:
            raise VisionAnalysisError(artifact_id) from exc
        thread.append(
            {"prompt": prompt, "answer": analysis.content, "model": analysis.model}
        )
        bounded = thread[-self.thread_max_stored :]
        updated = await self.repository.update_metadata(
            artifact_id,
            user_id,
            {
                "analysis_status": "ready",
                "analysis": analysis.content,
                "analysis_model": analysis.model,
                "analysis_thread": bounded,
            },
        )
        return {
            "artifact": updated,
            "analysis": analysis.content,
            "model": analysis.model,
        }

    # Recover a prior question/answer thread, seeding it from legacy flat analysis.
    def _existing_thread(self, metadata: dict[str, Any]) -> list[dict[str, str]]:
        raw = metadata.get("analysis_thread")
        if isinstance(raw, list):
            return [
                {
                    "prompt": str(entry.get("prompt", "")),
                    "answer": str(entry.get("answer", "")),
                    "model": str(entry.get("model", "")),
                }
                for entry in raw
                if isinstance(entry, dict)
            ]
        legacy = metadata.get("analysis")
        if isinstance(legacy, str) and legacy.strip():
            return [
                {
                    "prompt": "Describe this image.",
                    "answer": legacy.strip(),
                    "model": str(metadata.get("analysis_model", "")),
                }
            ]
        return []
