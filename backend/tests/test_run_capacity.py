"""Many runs, several workers, one table: every run completes once.

The capacity drill Phase 7 asks for, in its first size: twenty-four runs
for six principals, driven by three workers claiming concurrently from the
same table. What is asserted is not speed but correctness under contention:
every run completes, every effect lands exactly once, no two workers hold
the same run, and every recorded step carries its receipt. The elapsed time
is printed so a slower machine is noticed, not asserted so a slower machine
does not fail.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pytest

from backend.database.session import AsyncSessionLocal
from backend.runs.controller import RunController
from backend.runs.grants import grant_of
from backend.runs.repository import AgentRunRepository
from backend.runs.worlds import Verification
from backend.services.turn_steps import Act, Done, TurnResult

pytestmark = pytest.mark.asyncio

PRINCIPALS = 6
RUNS_PER_PRINCIPAL = 4
WORKERS = 3
PLAN = ("a", "b", "c")


class CountingWorld:
    """Three effects, each counted in a ledger shared by every worker."""

    def __init__(self, run_id: str, ledger: dict[str, list[str]]) -> None:
        self.run_id = run_id
        self.ledger = ledger
        self.done: set[str] = set()

    async def decide(self, lines: list[str]):
        seen = {line.split(":", 1)[0] for line in lines} | self.done
        for action in PLAN:
            if action not in seen:
                return Act(action)
        return Done()

    async def apply(self, action: str):
        await asyncio.sleep(0.01)
        self.ledger.setdefault(self.run_id, []).append(action)
        self.done.add(action)
        return "step", {"kind": "done", "did": action}

    def tool_name(self, action: str) -> str:
        return f"tool_{action}"

    def arguments(self, action: str) -> dict[str, Any]:
        return {"what": action}

    def key(self, action: str) -> str | None:
        return f"k:{action}"

    def creates(self, action: str) -> bool:
        return True

    def describe(self, action: str, kind: str, outcome: dict[str, Any] | None) -> str:
        return f"{action}: {kind}"

    def needs_approval(self, action: str) -> bool:
        return False

    def approval_summary(self, action: str) -> str:
        return ""

    async def reconcile(self, action: str, prior: dict[str, Any]):
        return None

    async def verify(self, result: TurnResult, run: dict[str, Any]) -> Verification:
        done = set(self.done) | {line.split(":", 1)[0] for step in result.steps for line in [step.line]}
        return Verification(set(PLAN) <= done, {"effects": sorted(done)}, "all done")


# One worker: claim until the table has nothing left for this kind.
async def _drive(worker_id: str, kind: str, ledger: dict[str, list[str]], claimed: list[tuple[str, str]]) -> None:
    controller = RunController(AsyncSessionLocal, worker_id)
    grant = grant_of(*(f"tool_{action}" for action in PLAN))
    idle = 0
    while idle < 2:
        async with AsyncSessionLocal() as db:
            run = await AgentRunRepository(db).claim_next(worker_id, 60.0, kinds=(kind,))
        if run is None:
            idle += 1
            await asyncio.sleep(0.05)
            continue
        idle = 0
        claimed.append((str(run["id"]), worker_id))
        await controller.execute(run, CountingWorld(str(run["id"]), ledger), grant)


async def test_concurrent_workers_complete_every_run_exactly_once():
    kind = f"cap_{uuid.uuid4().hex[:8]}"
    users = [f"cap_{uuid.uuid4().hex[:10]}" for _ in range(PRINCIPALS)]
    ledger: dict[str, list[str]] = {}
    claimed: list[tuple[str, str]] = []
    try:
        async with AsyncSessionLocal() as db:
            repo = AgentRunRepository(db)
            created = [
                await repo.create(user, "agent:test", kind, "a, b, c", list(PLAN), budget_seconds=30.0, max_steps=6, max_creates=6)
                for _ in range(RUNS_PER_PRINCIPAL)
                for user in users
            ]
        started = time.monotonic()
        await asyncio.gather(*(_drive(f"cap-w{n}", kind, ledger, claimed) for n in range(WORKERS)))
        elapsed = time.monotonic() - started

        total = PRINCIPALS * RUNS_PER_PRINCIPAL
        assert len(created) == total
        # Every run completed, its effects landed once each, in order.
        async with AsyncSessionLocal() as db:
            repo = AgentRunRepository(db)
            for run in created:
                found = await repo.get_owned(run["user_id"], run["id"])
                assert found is not None and found["status"] == "completed", (run["id"], found and found["status"], found and found["error_code"])
                assert ledger.get(str(run["id"])) == list(PLAN), ledger.get(str(run["id"]))
                assert [row["status"] for row in found["actions"]] == ["succeeded"] * len(PLAN)
            # No two workers held the same run.
            assert len({run_id for run_id, _ in claimed}) == total
            assert len(claimed) == total
            # Every worker did some of the work.
            assert len({worker for _, worker in claimed}) == WORKERS
            # Every recorded effect carries its receipt and its principal.
            assert await repo.effects_without_receipt(users) == []
        print(f"\ncapacity drill: {total} runs, {WORKERS} workers, {elapsed:.1f}s")
    finally:
        async with AsyncSessionLocal() as db:
            repo = AgentRunRepository(db)
            for user in users:
                await repo.delete_for_user(user)
