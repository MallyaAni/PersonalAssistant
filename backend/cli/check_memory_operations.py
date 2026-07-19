import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from backend.config.settings import settings
from backend.core.dependencies import get_embedding_provider
from backend.database.session import AsyncSessionLocal
from backend.services.memory_operations_service import MemoryOperationsService


# Define command-line options for the memory operations check.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect AniOS memory counts, backlog, vectors, and invariants.",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id")
    scope.add_argument("--all-users", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Fail on expired, stale-vector, or indexing backlog as well as "
            "invariants."
        ),
    )
    return parser


# Inspect memory operations through a non-blocking database session.
async def _run(args: argparse.Namespace) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        return await MemoryOperationsService(
            session,
            get_embedding_provider(),
            settings.EMBEDDING_MODEL_VERSION,
            settings.EMBEDDING_DIMENSION,
        ).inspect(args.user_id)


# Run the operations check and return a monitoring-friendly exit code.
def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(_run(args))
    print(json.dumps(result, sort_keys=True))
    invariant_total = sum(result["invariant_violations"].values())
    if not result["database"]["query_ok"] or invariant_total:
        return 1
    if args.strict and result["status"] != "healthy":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
