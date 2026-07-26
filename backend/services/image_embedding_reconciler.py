import asyncio
import logging
from contextlib import suppress

from sqlalchemy import select

from backend.config.settings import settings
from backend.core.interfaces import BinaryArtifactStore, VisionEmbeddingProvider
from backend.database.session import AsyncSessionLocal
from backend.models.artifact import VisualArtifact
from backend.services.artifact_repository import SQLAlchemyArtifactRepository

logger = logging.getLogger(__name__)

# Diagrams hold Mermaid source rather than pixels, so the image encoder cannot
# describe them and they are excluded, matching the backfill CLI.
_EMBEDDABLE_KINDS = ("generated_image", "uploaded_image")


# Embed every ready image that still has no vector, up to a bounded batch. This
# is the reconciliation that guarantees the invariant "every ready image is
# embedded" converges, whatever happened at write time. Returns the count fixed.
async def reconcile_missing_embeddings(
    provider: VisionEmbeddingProvider,
    store: BinaryArtifactStore,
    *,
    batch_limit: int = 200,
) -> int:
    if not provider.is_enabled():
        return 0
    embedded = 0
    async with AsyncSessionLocal() as session:
        artifacts = list(
            (
                await session.execute(
                    select(VisualArtifact)
                    .where(
                        VisualArtifact.status == "ready",
                        VisualArtifact.embedding.is_(None),
                        VisualArtifact.kind.in_(_EMBEDDABLE_KINDS),
                        VisualArtifact.storage_key.is_not(None),
                    )
                    .order_by(VisualArtifact.created_at.desc())
                    .limit(batch_limit)
                )
            )
            .scalars()
            .all()
        )
        repository = SQLAlchemyArtifactRepository(session)
        for artifact in artifacts:
            try:
                content = await store.read(str(artifact.storage_key))
                vector = await asyncio.to_thread(provider.embed_image, content)
                await repository.set_embedding(
                    str(artifact.id),
                    artifact.user_id,
                    vector,
                    settings.VISION_EMBEDDING_MODEL,
                )
                embedded += 1
            except Exception:
                # One bad image must not stop the rest; it is retried next pass.
                logger.warning(
                    "Reconciler could not embed image %s", artifact.id, exc_info=True
                )
    if embedded:
        logger.info("Reconciled %d missing image embedding(s)", embedded)
    return embedded


class ImageEmbeddingReconciler:
    """Keep every ready image embedded via a bounded self-healing loop.

    Newest images are embedded first so a just-created image becomes recallable
    quickly even if its write-time embedding failed.
    """

    def __init__(
        self,
        provider: VisionEmbeddingProvider,
        store: BinaryArtifactStore,
        interval_seconds: float,
    ) -> None:
        self._provider = provider
        self._store = store
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def _loop(self) -> None:
        while True:
            try:
                await reconcile_missing_embeddings(self._provider, self._store)
            except Exception:
                logger.warning("Image-embedding reconcile pass failed", exc_info=True)
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None and self._provider.is_enabled():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
