import logging

from backend.core.interfaces import ArtifactRepository, BinaryArtifactStore

logger = logging.getLogger(__name__)


class ArtifactDeletionError(RuntimeError):
    """Reports that database deletion completed but binary cleanup was incomplete."""


class ArtifactDeletionService:
    # Coordinate owned artifact-row deletion with best-effort binary cleanup.
    def __init__(
        self,
        repository: ArtifactRepository,
        store: BinaryArtifactStore,
    ) -> None:
        self.repository = repository
        self.store = store

    # Delete every owned artifact and surface any incomplete file cleanup.
    async def delete_all_owned(self, user_id: str) -> int:
        count, storage_keys = await self.repository.delete_all_owned(user_id)
        failures = 0
        for storage_key in storage_keys:
            try:
                await self.store.delete(storage_key)
            except Exception:
                failures += 1
                logger.exception(
                    "Artifact binary cleanup failed after owned rows were deleted"
                )
        if failures:
            raise ArtifactDeletionError(
                f"Unable to remove {failures} artifact file(s); "
                "storage collection is required."
            )
        return count
