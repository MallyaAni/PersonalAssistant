from typing import Any

from backend.core.interfaces import BinaryArtifactRepository, VisionProvider
from backend.services.image_artifact_service import ImageArtifactService


class VisionAnalysisError(RuntimeError):
    # Retain the valid upload identifier while exposing only a safe public failure.
    def __init__(self, artifact_id: str) -> None:
        super().__init__("Vision analysis failed")
        self.artifact_id = artifact_id


class VisionAnalysisService:
    # Coordinate upload persistence and grounded VLM analysis outside the model.
    def __init__(
        self,
        images: ImageArtifactService,
        repository: BinaryArtifactRepository,
        provider: VisionProvider,
    ) -> None:
        self.images = images
        self.repository = repository
        self.provider = provider

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
        return {
            "artifact": updated,
            "analysis": analysis.content,
            "model": analysis.model,
        }
