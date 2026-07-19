import argparse
import asyncio
import json
from collections.abc import Sequence

from backend.database.session import AsyncSessionLocal
from backend.services.memory_retention_service import MemoryRetentionService


# Define safe command-line options for memory retention cleanup.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report or purge expired AniOS memory records.",
    )
    parser.add_argument("--user-id", help="Limit retention to one user.")
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Explicitly allow an apply run across every user.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete expired records; the default is a dry run.",
    )
    return parser


# Purge expired memory through a non-blocking database session.
async def _run(args: argparse.Namespace) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        return await MemoryRetentionService(session).purge_expired(
            args.user_id,
            dry_run=not args.apply,
        )


# Preview or apply retention cleanup with explicit scope checks.
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.user_id and args.all_users:
        parser.error("--user-id and --all-users are mutually exclusive")
    if args.apply and not args.user_id and not args.all_users:
        parser.error("--apply requires --user-id or --all-users")

    result = asyncio.run(_run(args))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
