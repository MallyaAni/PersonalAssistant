"""Report, and optionally reclaim, stored files no row points at any more.

Reports by default. `--apply` is the only way to delete anything, and it prints
what it is about to do first.
"""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from backend.artifacts.collection import (
    DEFAULT_GRACE_SECONDS,
    apply_collection,
    plan_collection,
    referenced_keys,
)
from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report or reclaim unreferenced artifact storage.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the unreferenced files. Without this, only report.",
    )
    parser.add_argument(
        "--grace-seconds",
        type=int,
        default=DEFAULT_GRACE_SECONDS,
        help=(
            "Leave files written more recently than this alone, because a job "
            "may have written bytes it has not yet recorded a row for."
        ),
    )
    parser.add_argument(
        "--show",
        type=int,
        default=10,
        help="How many of the largest unreferenced files to list.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        help="Repeat after this delay; omit it to run exactly once.",
    )
    return parser


def _megabytes(value: int) -> str:
    return f"{value / 1048576:.1f} MB"


# One sweep: report, and reclaim when asked.
async def sweep(arguments: argparse.Namespace) -> int:
    root = Path(settings.ARTIFACT_STORAGE_ROOT).resolve()
    if not root.exists():
        print(f"No storage root at {root}")
        return 0

    async with AsyncSessionLocal() as session:
        # Raises rather than returning a partial set, so a database that could
        # not be read fails the command instead of emptying the disk.
        live = await referenced_keys(session)

    plan = plan_collection(root, live, grace_seconds=arguments.grace_seconds)
    print(f"root           {root}")
    print(f"referenced     {plan.referenced_files:5} files  "
          f"{_megabytes(plan.referenced_bytes)}   ({len(live)} keys on record)")
    print(f"unreferenced   {len(plan.orphans):5} files  "
          f"{_megabytes(plan.reclaimable_bytes)}")
    print(f"held back      {plan.kept_young:5} files  "
          f"(written within {arguments.grace_seconds}s)")
    for key, size in sorted(plan.orphans, key=lambda item: -item[1])[: arguments.show]:
        print(f"    {_megabytes(size):>10}  {key}")

    if not plan.orphans:
        return 0
    if not arguments.apply:
        print("\nReport only. Pass --apply to reclaim these.")
        return 0

    removed, reclaimed = apply_collection(root, plan)
    print(f"\nRemoved {removed} files, reclaimed {_megabytes(reclaimed)}.")
    return 0


# Run once, or on an interval so leaked bytes are bounded in time.
#
# Row deletion and file deletion cannot be made atomic across a database and a
# filesystem, so a leak stays possible however carefully each call site deletes.
# A periodic sweep is what turns "leaked forever" into "leaked until Tuesday".
async def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.interval_seconds is None:
        return await sweep(arguments)
    while True:
        try:
            await sweep(arguments)
        except Exception:
            # A sweep that cannot read its references refuses, which is the
            # correct outcome and must not stop the sweeps after it.
            logger.warning("Storage collection sweep failed", exc_info=True)
        await asyncio.sleep(arguments.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
