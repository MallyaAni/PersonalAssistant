import uuid
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.artifacts.types import DiagramSpecification, StoredBinary
from backend.core.interfaces import ArtifactEmbeddingStore, BinaryArtifactRepository
from backend.models.artifact import VisualArtifact


class SQLAlchemyArtifactRepository(BinaryArtifactRepository, ArtifactEmbeddingStore):
    # Bind artifact persistence to the request's asynchronous transaction session.
    def __init__(self, session: AsyncSession):
        self.session = session

    # Persist a pending visual artifact before provider work begins.
    async def create_pending(
        self,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        provider: str,
        model: str | None,
    ) -> dict[str, Any]:
        artifact = VisualArtifact(
            user_id=user_id,
            conversation_id=uuid.UUID(conversation_id),
            trace_id=uuid.UUID(trace_id),
            kind="diagram",
            status="pending",
            provider=provider,
            model=model,
            extra_data={},
        )
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(artifact)
        return artifact.to_dict()

    # Mark a pending artifact ready with validated editable source.
    async def mark_ready(
        self,
        artifact_id: str,
        user_id: str,
        specification: DiagramSpecification,
    ) -> dict[str, Any]:
        artifact = await self._owned_artifact(artifact_id, user_id)
        if artifact is None:
            raise LookupError("Artifact was not found")
        artifact.status = "ready"
        artifact.title = specification.title
        artifact.source_format = "mermaid"
        artifact.source = specification.source
        artifact.mime_type = "image/svg+xml"
        artifact.error_code = None
        artifact.extra_data = {"diagram_type": specification.diagram_type}
        await self.session.commit()
        await self.session.refresh(artifact)
        return artifact.to_dict()

    # Mark a pending artifact failed without storing provider internals.
    async def mark_failed(
        self,
        artifact_id: str,
        user_id: str,
        error_code: str,
    ) -> dict[str, Any]:
        artifact = await self._owned_artifact(artifact_id, user_id)
        if artifact is None:
            raise LookupError("Artifact was not found")
        artifact.status = "failed"
        artifact.error_code = error_code
        artifact.source = None
        artifact.storage_key = None
        await self.session.commit()
        await self.session.refresh(artifact)
        return artifact.to_dict()

    # Persist a pending generated or uploaded binary artifact.
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
        if kind not in {"generated_image", "uploaded_image"}:
            raise ValueError("Binary artifact kind is not supported")
        artifact = VisualArtifact(
            user_id=user_id,
            conversation_id=uuid.UUID(conversation_id),
            trace_id=uuid.UUID(trace_id),
            kind=kind,
            status="pending",
            title=title,
            provider=provider,
            model=model,
            extra_data={},
        )
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(artifact)
        return artifact.to_dict()

    # Mark a pending binary artifact ready without exposing its opaque storage key.
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
        artifact = await self._owned_artifact(artifact_id, user_id)
        if artifact is None:
            raise LookupError("Artifact was not found")
        artifact.status = "ready"
        artifact.mime_type = mime_type
        artifact.storage_key = stored.storage_key
        artifact.byte_size = stored.byte_size
        artifact.sha256 = stored.sha256
        artifact.width = width
        artifact.height = height
        artifact.error_code = None
        artifact.extra_data = metadata
        await self.session.commit()
        await self.session.refresh(artifact)
        return artifact.to_dict()

    # Return one owned artifact plus its private storage key for service use only.
    async def get_owned(
        self,
        user_id: str,
        artifact_id: str,
    ) -> dict[str, Any] | None:
        artifact = await self._owned_artifact(artifact_id, user_id)
        if artifact is None:
            return None
        return {**artifact.to_dict(), "_storage_key": artifact.storage_key}

    # Merge bounded analysis metadata into one owned artifact record.
    async def update_metadata(
        self,
        artifact_id: str,
        user_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        artifact = await self._owned_artifact(artifact_id, user_id)
        if artifact is None:
            raise LookupError("Artifact was not found")
        artifact.extra_data = {**(artifact.extra_data or {}), **metadata}
        await self.session.commit()
        await self.session.refresh(artifact)
        return artifact.to_dict()

    # Attach one aligned image vector to an owned artifact.
    async def set_embedding(
        self,
        artifact_id: str,
        user_id: str,
        embedding: list[float],
        model: str,
    ) -> None:
        artifact = await self._owned_artifact(artifact_id, user_id)
        if artifact is None:
            raise LookupError("Artifact was not found")
        artifact.embedding = embedding
        artifact.embedding_model = model
        artifact.embedding_dimension = len(embedding)
        await self.session.commit()

    # Rank one user's embedded images against a query vector by cosine distance.
    async def search_by_embedding(
        self,
        user_id: str,
        embedding: list[float],
        limit: int,
        max_distance: float,
    ) -> list[dict[str, Any]]:
        distance = VisualArtifact.embedding.cosine_distance(embedding)
        result = await self.session.execute(
            select(VisualArtifact, distance.label("distance"))
            .where(
                VisualArtifact.user_id == user_id,
                VisualArtifact.embedding.is_not(None),
                VisualArtifact.status == "ready",
                distance <= max_distance,
            )
            .order_by(distance)
            .limit(limit)
        )
        return [
            {**artifact.to_dict(), "distance": float(value)}
            for artifact, value in result.all()
        ]

    # List artifacts owned by one user conversation in creation order.
    async def list_for_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(VisualArtifact)
            .where(
                VisualArtifact.user_id == user_id,
                VisualArtifact.conversation_id == uuid.UUID(conversation_id),
            )
            .order_by(VisualArtifact.created_at, VisualArtifact.id)
        )
        return [artifact.to_dict() for artifact in result.scalars().all()]

    # List recent user-owned artifacts across conversations, newest first.
    async def list_for_user(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        result = await self.session.execute(
            select(VisualArtifact)
            .where(VisualArtifact.user_id == user_id)
            .order_by(VisualArtifact.created_at.desc(), VisualArtifact.id.desc())
            .limit(limit)
        )
        return [artifact.to_dict() for artifact in result.scalars().all()]

    # Delete one user-owned artifact and report whether it existed.
    async def delete(self, user_id: str, artifact_id: str) -> bool:
        result = await self.session.execute(
            delete(VisualArtifact).where(
                VisualArtifact.id == uuid.UUID(artifact_id),
                VisualArtifact.user_id == user_id,
            )
        )
        await self.session.commit()
        return bool(getattr(result, "rowcount", 0))

    # Load one artifact only when it belongs to the requested user.
    async def _owned_artifact(
        self,
        artifact_id: str,
        user_id: str,
    ) -> VisualArtifact | None:
        return cast(
            VisualArtifact | None,
            await self.session.scalar(
                select(VisualArtifact).where(
                    VisualArtifact.id == uuid.UUID(artifact_id),
                    VisualArtifact.user_id == user_id,
                )
            ),
        )
