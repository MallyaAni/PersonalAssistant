from typing import Any

from backend.services.memory_operations_service import MemoryOperationsService
from backend.services.memory_reembedding_service import MemoryReembeddingService
from backend.services.memory_retention_service import MemoryRetentionService


class MemoryMaintenanceService:
    """Run retention, optional re-embedding, and health inspection as one cycle."""

    # Store the lifecycle services used by each maintenance cycle.
    def __init__(
        self,
        retention: MemoryRetentionService,
        reembedding: MemoryReembeddingService,
        operations: MemoryOperationsService,
    ) -> None:
        self.retention = retention
        self.reembedding = reembedding
        self.operations = operations

    # Apply due cleanup, optionally refresh vectors, and report final health.
    async def run_cycle(
        self,
        user_id: str | None,
        *,
        reembed: bool = False,
        batch_size: int = 50,
    ) -> dict[str, Any]:
        retention = await self.retention.purge_expired(user_id, dry_run=False)
        vectors = await self.reembedding.reembed(
            user_id,
            dry_run=not reembed,
            batch_size=batch_size,
        )
        operations = await self.operations.inspect(user_id)
        return {
            "status": operations["status"],
            "user_id": user_id,
            "retention": retention,
            "reembedding": vectors,
            "operations": operations,
        }
