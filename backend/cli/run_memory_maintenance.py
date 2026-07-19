import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.services.memory_maintenance_service import MemoryMaintenanceService
from backend.services.memory_operations_service import MemoryOperationsService
from backend.services.memory_reembedding_service import MemoryReembeddingService
from backend.services.memory_retention_service import MemoryRetentionService


# Define explicit scope, vector, and scheduling options for maintenance.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AniOS memory retention, vector, and health maintenance.",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id")
    scope.add_argument("--all-users", action="store_true")
    parser.add_argument(
        "--reembed",
        action="store_true",
        help="Replace stale embeddings; the default only inventories them.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        choices=range(1, 501),
        metavar="1..500",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        help="Repeat after this delay; omit it to run exactly once.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return failure when the post-maintenance report needs attention.",
    )
    return parser


# Run one maintenance cycle through a fresh non-blocking database session.
async def _run_cycle(args: argparse.Namespace) -> dict[str, Any]:
    embeddings = get_embedding_provider()
    async with AsyncSessionLocal() as session:
        service = MemoryMaintenanceService(
            MemoryRetentionService(session),
            MemoryReembeddingService(
                session,
                embeddings,
                settings.EMBEDDING_MODEL_VERSION,
                settings.EMBEDDING_DIMENSION,
            ),
            MemoryOperationsService(
                session,
                embeddings,
                settings.EMBEDDING_MODEL_VERSION,
                settings.EMBEDDING_DIMENSION,
            ),
        )
        return await service.run_cycle(
            args.user_id,
            reembed=args.reembed,
            batch_size=args.batch_size,
        )


# Emit one monitoring event without exposing stored memory content.
def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


# Run once or continue across transient cycle failures at a fixed interval.
async def _run(args: argparse.Namespace) -> int:
    if args.interval_seconds is not None and args.interval_seconds < 1:
        _emit({"status": "invalid", "message": "interval-seconds must be at least 1"})
        return 2

    while True:
        try:
            result = await _run_cycle(args)
            _emit(result)
            exit_code = int(args.strict and result["status"] != "healthy")
        except Exception as exc:
            _emit(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:300],
                }
            )
            exit_code = 1
        if args.interval_seconds is None:
            return exit_code
        await asyncio.sleep(args.interval_seconds)


# Start the maintenance scheduler and expose monitoring-friendly exit codes.
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
