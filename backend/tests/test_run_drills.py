"""Two Phase 7 drills: a worker process killed mid-step, and retention.

The in-process tests raise a BaseException to stand in for a kill. This one
kills a real process. A child claims a run and drives a world whose effects
are files in a scratch directory, and that stops to wait mid-step; the test
kills it, lets the lease lapse, resumes the run here, and asserts the step
that landed before the kill is not done twice and the run completes.

Retention: a finished run past the window is deleted with its records; an
open run of any age and a finished run inside the window are kept; the
report never deletes unless asked.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backend.database.session import AsyncSessionLocal
from backend.models.agent_run import AgentRun
from backend.runs.controller import RunController
from backend.runs.repository import AgentRunRepository
from backend.runs.retention import sweep_runs
from backend.runs.worlds import Verification
from backend.services.turn_steps import Act, Done, TurnResult

pytestmark = pytest.mark.asyncio


class FileWorld:
    """Effects are files: a is written, then b, then c. `stall_on` names the
    step during which the process sleeps after its effect landed, which is
    where the kill arrives. Effects survive the process; state is rebuilt from
    the lines the controller shows."""

    def __init__(self, folder: Path, stall_on: str | None = None) -> None:
        self.folder = folder
        self.stall_on = stall_on

    async def decide(self, lines: list[str]):
        done = {line.split(":", 1)[0] for line in lines}
        for step in ("a", "b", "c"):
            if step not in done:
                return Act(step)
        return Done()

    async def apply(self, action: str):
        marker = self.folder / f"{action}.txt"
        count = int(marker.read_text()) + 1 if marker.exists() else 1
        marker.write_text(str(count))
        if action == self.stall_on:
            await asyncio.sleep(600)
        return "step", {"kind": "done"}

    def tool_name(self, action):
        return f"tool_{action}"

    def arguments(self, action):
        return {"what": action}

    def key(self, action):
        return f"k:{action}"

    def creates(self, action):
        return True

    def describe(self, action, kind, outcome):
        return f"{action}: {kind} [{(outcome or {}).get('kind', '')}]"

    def needs_approval(self, action):
        return False

    def approval_summary(self, action):
        return ""

    # The effect is a file: the world can say whether it landed.
    async def reconcile(self, action, prior):
        return {"kind": "done"} if (self.folder / f"{action}.txt").exists() else {"kind": "failed"}

    async def verify(self, result: TurnResult, run: dict[str, Any]) -> Verification:
        landed = {name for name in ("a", "b", "c") if (self.folder / f"{name}.txt").exists()}
        return Verification(landed == {"a", "b", "c"}, {"landed": sorted(landed)})

    def observe(self, action, kind, outcome):
        return None


_CHILD = r'''
import asyncio, sys
sys.path.insert(0, r"{root}")
from backend.database.session import AsyncSessionLocal
from backend.runs.controller import RunController
from backend.runs.repository import AgentRunRepository
from backend.tests.test_run_drills import FileWorld
from pathlib import Path

async def main():
    async with AsyncSessionLocal() as db:
        run = await AgentRunRepository(db).claim_next("drill-child", 20.0, kinds=("drill",), user_id="{user}")
    assert run is not None, "child could not claim"
    print("claimed", flush=True)
    await RunController(AsyncSessionLocal, "drill-child").execute(run, FileWorld(Path(r"{folder}"), stall_on="b"))

asyncio.run(main())
'''


async def _make_run(user: str) -> dict:
    async with AsyncSessionLocal() as db:
        return await AgentRunRepository(db).create(
            user, "agent:drill", "drill", "a then b then c", ["a", "b", "c"],
            budget_seconds=900.0, max_steps=6, max_creates=6,
        )


async def _clean(user: str) -> None:
    async with AsyncSessionLocal() as db:
        await AgentRunRepository(db).delete_for_user(user)


async def test_a_worker_process_killed_mid_step_is_resumed_without_a_second_effect(tmp_path: Path):
    user = f"drill_{uuid.uuid4().hex[:10]}"
    try:
        run = await _make_run(user)
        env = {**os.environ, "PYTHONUTF8": "1"}
        child = subprocess.Popen(
            [sys.executable, "-c", _CHILD.format(root=Path(__file__).resolve().parents[2], user=user, folder=tmp_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        try:
            # Wait for the child to claim and to land a and b, then kill it
            # while it stalls inside b.
            for _ in range(600):
                if (tmp_path / "b.txt").exists():
                    break
                await asyncio.sleep(0.1)
            assert (tmp_path / "b.txt").exists(), child.stderr.read() if child.poll() is not None else "child never reached b"
            child.kill()
            child.wait(timeout=30)
        finally:
            if child.poll() is None:
                child.kill()

        async with AsyncSessionLocal() as db:
            rows = await AgentRunRepository(db).actions_for(run["id"])
        assert [(row["tool"], row["status"]) for row in rows] == [("tool_a", "succeeded"), ("tool_b", "dispatched")]

        # The lease lapses; another worker picks the run up.
        async with AsyncSessionLocal() as db:
            resumed = await AgentRunRepository(db).claim_next(
                "drill-here", 60.0, now=datetime.now(UTC) + timedelta(seconds=120), kinds=("drill",), user_id=user
            )
        assert resumed is not None
        outcome = await RunController(AsyncSessionLocal, "drill-here").execute(resumed, FileWorld(tmp_path))
        assert outcome.status == "completed", outcome
        # a and b happened exactly once; c once.
        assert {name: int((tmp_path / f"{name}.txt").read_text()) for name in ("a", "b", "c")} == {"a": 1, "b": 1, "c": 1}
        async with AsyncSessionLocal() as db:
            after = await AgentRunRepository(db).actions_for(run["id"])
        assert [(row["tool"], row["status"]) for row in after] == [
            ("tool_a", "succeeded"), ("tool_b", "succeeded"), ("tool_c", "succeeded")
        ]
    finally:
        await _clean(user)


async def test_retention_deletes_only_finished_runs_past_the_window():
    user = f"drill_{uuid.uuid4().hex[:10]}"
    try:
        old_done = await _make_run(user)
        recent_done = await _make_run(user)
        old_open = await _make_run(user)
        long_ago = datetime.now(UTC) - timedelta(days=400)
        async with AsyncSessionLocal() as db:
            repo = AgentRunRepository(db)
            await repo.finish(old_done["id"], "completed")
            await repo.finish(recent_done["id"], "completed")
            for run_id, when in ((old_done["id"], long_ago), (old_open["id"], long_ago)):
                row = await db.get(AgentRun, uuid.UUID(run_id))
                row.completed_at = when if run_id == old_done["id"] else None
                row.created_at = when
            await db.commit()

            report = await sweep_runs(db, keep_days=90)
            assert report.expired >= 1
            assert report.deleted == 0, "a report never deletes"
            kept = {r["id"] for r in await repo.list_for_user(user)}
            assert kept == {old_done["id"], recent_done["id"], old_open["id"]}

            applied = await sweep_runs(db, keep_days=90, apply=True)
            assert applied.deleted >= 1
            remaining = {r["id"] for r in await repo.list_for_user(user)}
            assert old_done["id"] not in remaining
            assert recent_done["id"] in remaining
            assert old_open["id"] in remaining, "an open run is never swept"
    finally:
        await _clean(user)


def test_child_script_is_valid_python():
    compile(_CHILD.format(root="r", user="u", folder="f"), "<child>", "exec")
    json.dumps({"ok": True})
