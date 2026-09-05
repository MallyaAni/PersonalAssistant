"""Review one commit as a durable run, and print the report.

    REPO_MCP_ROOT=/path/to/repo python -m backend.cli.review_commit --commit abc1234 --user ani

Creates a `code_review` run for the person, then drives it here with the
real controller - the same code the worker runs - so a review can be had
before the worker loop is switched on, and so a restart drill can kill this
process and run it again to watch the review resume from its recorded reads.
Every read goes through the `repo` MCP server, which must be configured in
`MCP_SERVERS_JSON` as read-only with `REPO_MCP_ROOT` in its `inherit_env`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from backend.config.settings import settings
from backend.core.dependencies import (
    get_mcp_invocation_service,
    get_structured_llm_client,
)
from backend.database.session import AsyncSessionLocal
from backend.runs.controller import RunController
from backend.runs.repository import AgentRunRepository


# Create the run (or reuse one) and drive it to its next stop.
async def review(commit: str, user_id: str, run_id: str | None, server_id: str) -> int:
    from backend.agents.review.prompts import ReviewPrompts
    from backend.agents.review.world import ReviewWorld

    invocation = get_mcp_invocation_service()
    if not invocation.can_auto_invoke(server_id):
        print(f"{server_id} is not configured as an auto-invocable MCP server", file=sys.stderr)
        return 2
    async with AsyncSessionLocal() as db:
        repo = AgentRunRepository(db)
        if run_id is None:
            created = await repo.create(
                user_id,
                "agent:review",
                "code_review",
                f"review commit {commit}",
                ["the commit, its diff and the chosen files were read", "every finding cites a line that exists"],
                budget_seconds=settings.AGENT_RUN_DEFAULT_BUDGET_SECONDS,
                max_steps=settings.AGENT_RUN_DEFAULT_MAX_STEPS,
                max_creates=1,
            )
            run_id = created["id"]
        claimed = await repo.claim_next("review-cli", settings.AGENT_RUN_LEASE_SECONDS)
    if claimed is None or claimed["id"] != run_id:
        print("could not claim the run (another worker holds it?)", file=sys.stderr)
        return 3
    world = ReviewWorld(claimed, invocation, ReviewPrompts(get_structured_llm_client()), server_id)
    outcome = await RunController(AsyncSessionLocal, "review-cli").execute(claimed, world)
    async with AsyncSessionLocal() as db:
        final = await AgentRunRepository(db).get_owned(user_id, run_id)
    print(json.dumps({"run_id": run_id, "status": outcome.status, "stopped": outcome.stopped, "error": outcome.error_code}, indent=2))
    if final and final.get("result"):
        print(json.dumps(final["result"], indent=2, default=str))
    return 0 if outcome.status == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--run-id", default=None, help="resume an existing run instead of creating one")
    parser.add_argument("--server", default="repo")
    arguments = parser.parse_args()
    if not os.environ.get("REPO_MCP_ROOT"):
        print("set REPO_MCP_ROOT to the repository the repo server is rooted at", file=sys.stderr)
        return 2
    return asyncio.run(review(arguments.commit, arguments.user, arguments.run_id, arguments.server))


if __name__ == "__main__":
    raise SystemExit(main())
