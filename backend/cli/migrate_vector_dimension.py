import argparse
import asyncio
import json
from collections.abc import Sequence

from backend.config.settings import settings
from backend.database.session import async_engine
from backend.embeddings.lm_studio import LMStudioEmbeddingProvider
from backend.services.vector_dimension_migration_service import (
    VectorDimensionMigrationService,
)


# Define preview and explicitly offline apply options for dimension migration.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill and atomically switch AniOS pgvector dimensions.",
    )
    parser.add_argument("--target-dimension", type=int, required=True)
    parser.add_argument("--target-model", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        choices=range(1, 501),
        metavar="1..500",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-offline",
        action="store_true",
        help="Confirm chat and memory writers are stopped for the final switch.",
    )
    return parser


# Inventory or migrate every vector store using the target embedding model.
async def _run(args: argparse.Namespace) -> dict[str, object]:
    provider = LMStudioEmbeddingProvider(
        base_url=settings.LLM_BASE_URL,
        model=args.target_model,
        dimension=args.target_dimension,
        api_key=settings.LLM_API_KEY,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_concurrency=settings.EMBEDDING_MAX_CONCURRENCY,
    )
    service = VectorDimensionMigrationService(
        async_engine,
        provider,
        args.target_version,
        args.target_dimension,
    )
    return await service.migrate(
        dry_run=not args.apply,
        batch_size=args.batch_size,
    )


# Enforce the maintenance-window acknowledgement and print migration state.
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.apply and not args.confirm_offline:
        parser.error("--apply requires --confirm-offline")
    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:300],
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
