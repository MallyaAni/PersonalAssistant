"""Create an experience review for one person, on request.

    docker compose exec backend python -m backend.cli.review_experience --user ani.mallya
    docker compose exec backend python -m backend.cli.review_experience --user ani.mallya --hours 48 --run

The daily schedule creates these on its own (`run_worker.schedule_experience_reviews`);
this is for looking at a day the person complained about, now. Without
`--run` the run is created and the worker claims it; with `--run` it is
driven here to completion and the result printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.runs.repository import AgentRunRepository


async def run(user: str, hours: int, drive: bool, channel: str) -> int:
    since = datetime.now(UTC) - timedelta(hours=hours)
    async with AsyncSessionLocal() as db:
        repo = AgentRunRepository(db)
        created = await repo.create(
            user,
            "agent:experience",
            "experience_review",
            f"review experience for {user} since {since.isoformat()}",
            ["read", "judged", "reported"],
            budget_seconds=float(settings.AGENT_RUN_DEFAULT_BUDGET_SECONDS),
            max_steps=40,
            max_creates=1,
            channel=channel,
        )
    print(f"created run {created['id']} for {user} since {since.isoformat()}")
    if not drive:
        return 0
    from backend.runs.controller import RunController
    from backend.workers.run_worker import GRANTS, WORLDS

    async with AsyncSessionLocal() as db:
        claimed = await AgentRunRepository(db).claim_next(
            "review-experience-cli", float(settings.AGENT_RUN_DEFAULT_BUDGET_SECONDS) + 300, kinds=("experience_review",), user_id=user
        )
    if claimed is None:
        print("nothing claimable; another worker took it")
        return 1
    outcome = await RunController(AsyncSessionLocal, "review-experience-cli").execute(
        claimed, WORLDS["experience_review"](claimed), GRANTS["experience_review"]
    )
    async with AsyncSessionLocal() as db:
        final = await AgentRunRepository(db).get_owned(user, claimed["id"])
    print(f"status {outcome.status} ({outcome.stopped}) error={outcome.error_code}")
    result = (final or {}).get("result") or {}
    print("summary:", result.get("summary"))
    print(json.dumps(result.get("evidence") or {}, indent=2, default=str)[:6000])
    return 0 if outcome.status in ("completed", "waiting_approval") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--user", required=True)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--channel", default="web", choices=("web", "imessage", "imessage_group"))
    parser.add_argument("--run", action="store_true", help="drive the run here instead of leaving it to the worker")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.user, args.hours, args.run, args.channel))


if __name__ == "__main__":
    sys.exit(main())
