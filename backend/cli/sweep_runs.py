"""Report or delete finished runs older than the retention window.

    python -m backend.cli.sweep_runs              # report only
    python -m backend.cli.sweep_runs --apply      # delete what the report names
    python -m backend.cli.sweep_runs --keep-days 30

Open runs are never touched. See backend/runs/retention.py.
"""

from __future__ import annotations

import argparse
import asyncio

from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.runs.retention import sweep_runs


async def _sweep(keep_days: int, apply: bool) -> int:
    async with AsyncSessionLocal() as db:
        report = await sweep_runs(db, keep_days=keep_days, apply=apply)
    verb = "deleted" if apply else "would delete"
    print(
        f"finished runs completed before {report.cutoff:%Y-%m-%d}: {report.expired}; "
        f"{verb} {report.deleted if apply else report.expired}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-days", type=int, default=settings.AGENT_RUN_RETENTION_DAYS)
    parser.add_argument("--apply", action="store_true", help="delete rather than report")
    arguments = parser.parse_args()
    return asyncio.run(_sweep(arguments.keep_days, arguments.apply))


if __name__ == "__main__":
    raise SystemExit(main())
