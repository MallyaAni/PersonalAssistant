import argparse
import asyncio
import json
from collections.abc import Sequence

from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.services.memory_reembedding_service import MemoryReembeddingService


# Define safe command-line options for vector re-embedding.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory or re-embed AniOS vector memory records.",
    )
    parser.add_argument("--user-id", help="Limit re-embedding to one user.")
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Explicitly allow an apply run across every user.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write replacement embeddings; the default is a dry run.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        choices=range(1, 501),
        metavar="1..500",
    )
    return parser


# Build the re-embedding service and execute the requested mode.
async def _run(
    user_id: str | None,
    *,
    apply: bool,
    batch_size: int,
) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        service = MemoryReembeddingService(
            session,
            get_embedding_provider(),
            settings.EMBEDDING_MODEL_VERSION,
            settings.EMBEDDING_DIMENSION,
        )
        return await service.reembed(
            user_id,
            dry_run=not apply,
            batch_size=batch_size,
        )


# Preview or apply re-embedding with explicit scope checks.
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.user_id and args.all_users:
        parser.error("--user-id and --all-users are mutually exclusive")
    if args.apply and not args.user_id and not args.all_users:
        parser.error("--apply requires --user-id or --all-users")

    result = asyncio.run(
        _run(
            args.user_id,
            apply=args.apply,
            batch_size=args.batch_size,
        )
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
