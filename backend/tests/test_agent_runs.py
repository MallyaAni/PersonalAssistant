"""Durable runs keep their guarantees across a kill, a cancel and an approval.

Each test drives the real repository and the real controller against the
real schema (rows tagged with a throwaway user id, removed afterwards) with a
scripted world standing in for the agent - because the world is where a step
touches its domain, and the guarantees under test are the controller's:

  * a worker killed after an effect and before its record closed does not
    redo the effect on resume;
  * a worker killed after dispatching and before the effect is asked what
    happened, and stops the run when it cannot say;
  * a cancel is honoured between steps;
  * a step needing approval parks the run, a yes is spent by that exact call,
    a no ends the run, and an expired yes is refused;
  * completion is the world's verification, never the router declining.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.database.session import AsyncSessionLocal
from backend.runs.controller import RunController
from backend.runs.repository import AgentRunRepository
from backend.runs.worlds import Verification
from backend.services.turn_steps import Act, Done, TurnResult

pytestmark = pytest.mark.asyncio


class Crash(BaseException):
    """The worker dies here.

    A BaseException, like a kill or a cancellation, because the controller
    rightly treats an ordinary exception from a step as that step failing
    and carries on; a process death is the thing it cannot catch.
    """


class ScriptedWorld:
    """An agent whose decisions and effects are a script.

    `plan` is the sequence of actions to decide, then Done. `apply` records
    each effect in `effects`; `crash_before` and `crash_after` name an action
    the worker dies on (before or after the effect lands); `approve` names
    actions that need a person; `reconciled` is what the world can say about
    an unheard-from action, keyed by action.
    """

    def __init__(
        self,
        plan: list[str],
        *,
        crash_before: str | None = None,
        crash_after: str | None = None,
        approve: set[str] | None = None,
        reconciled: dict[str, dict[str, Any] | None] | None = None,
        accept_when: set[str] | None = None,
    ) -> None:
        self.plan = list(plan)
        self.effects: list[str] = []
        self.crash_before = crash_before
        self.crash_after = crash_after
        self.approve = approve or set()
        self.reconciled = reconciled or {}
        self.accept_when = accept_when
        self.decided: list[list[str]] = []

    async def decide(self, lines: list[str]):
        self.decided.append(list(lines))
        done = {line.split(":", 1)[0] for line in lines}
        for action in self.plan:
            if action not in done:
                return Act(action)
        return Done()

    async def apply(self, action: str):
        if action == self.crash_before:
            self.crash_before = None
            raise Crash(action)
        self.effects.append(action)
        if action == self.crash_after:
            self.crash_after = None
            raise Crash(action)
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
        went = (outcome or {}).get("kind", "")
        return f"{action}: {kind} [{went}]"

    def needs_approval(self, action: str) -> bool:
        return action in self.approve

    def approval_summary(self, action: str) -> str:
        return f"do {action}"

    async def reconcile(self, action: str, prior: dict[str, Any]):
        return self.reconciled.get(action)

    async def verify(self, result: TurnResult, run: dict[str, Any]) -> Verification:
        wanted = self.accept_when if self.accept_when is not None else set(self.plan)
        done = set(self.effects) | {
            row for row in self.replayed
        }
        accepted = wanted <= done
        return Verification(accepted, {"effects": sorted(done)}, "all done" if accepted else "missing")

    replayed: set[str] = set()


async def _make_run(user_id: str, **overrides) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await AgentRunRepository(db).create(
            user_id,
            "agent:test",
            "scripted",
            "do a, b and c",
            ["a", "b", "c"],
            budget_seconds=overrides.get("budget_seconds", 30.0),
            max_steps=overrides.get("max_steps", 6),
            max_creates=overrides.get("max_creates", 6),
        )


async def _claim(worker_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as db:
        return await AgentRunRepository(db).claim_next(worker_id, 60.0)


async def _get(user_id: str, run_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        found = await AgentRunRepository(db).get_owned(user_id, run_id)
    assert found is not None
    return found


async def _clean(user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await AgentRunRepository(db).delete_for_user(user_id)


def _user() -> str:
    return f"runs_{uuid.uuid4().hex[:12]}"


# A world whose verification reads what the controller replayed too: the
# controller hands a replayed step's recorded outcome back to the loop, so
# the world learns of it through the lines it is shown.
def _world_with_replay(**kwargs) -> ScriptedWorld:
    world = ScriptedWorld(**kwargs)

    async def verify(result: TurnResult, run: dict[str, Any]) -> Verification:
        seen = {line.split(":", 1)[0] for line in result.steps and [s.line for s in result.steps] or []}
        done = set(world.effects) | seen | {
            line.split(":", 1)[0] for shown in world.decided for line in shown
        }
        wanted = set(world.plan)
        accepted = wanted <= done
        return Verification(accepted, {"effects": sorted(done)}, "all done" if accepted else "missing")

    world.verify = verify  # type: ignore[method-assign]
    return world


async def test_a_run_completes_with_evidence_and_records_every_step():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        assert claimed and claimed["id"] == run["id"]
        world = _world_with_replay(plan=["a", "b", "c"])
        outcome = await RunController(AsyncSessionLocal, "w1").execute(claimed, world)
        assert outcome.status == "completed", outcome
        assert world.effects == ["a", "b", "c"]
        found = await _get(user, run["id"])
        assert found["status"] == "completed"
        assert [row["tool"] for row in found["actions"]] == ["tool_a", "tool_b", "tool_c"]
        assert all(row["status"] == "succeeded" for row in found["actions"])
        assert found["result"]["evidence"]["effects"] == ["a", "b", "c"]
        kinds = [event["kind"] for event in found["events"]]
        assert kinds[0] == "created" and kinds[-1] == "finished"
    finally:
        await _clean(user)


# Killed after the effect landed and before the row closed: on resume the
# row says dispatched; the world says it happened; nothing is redone.
async def test_a_kill_after_the_effect_does_not_redo_it_on_resume():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        world = _world_with_replay(
            plan=["a", "b", "c"],
            crash_after="b",
            reconciled={"b": {"kind": "done", "did": "b"}},
        )
        with pytest.raises(Crash):
            await RunController(AsyncSessionLocal, "w1").execute(claimed, world)
        assert world.effects == ["a", "b"]
        mid = await _get(user, run["id"])
        statuses = {row["tool"]: row["status"] for row in mid["actions"]}
        assert statuses == {"tool_a": "succeeded", "tool_b": "dispatched"}

        # The lease lapses and another worker picks it up.
        async with AsyncSessionLocal() as db:
            resumed = await AgentRunRepository(db).claim_next(
                "w2", 60.0, now=datetime.now(UTC) + timedelta(seconds=120)
            )
        assert resumed and resumed["id"] == run["id"]
        outcome = await RunController(AsyncSessionLocal, "w2").execute(resumed, world)
        assert outcome.status == "completed", outcome
        # b was never applied a second time; only c was new.
        assert world.effects == ["a", "b", "c"]
        after = await _get(user, run["id"])
        statuses = [(row["tool"], row["status"]) for row in after["actions"]]
        assert statuses == [("tool_a", "succeeded"), ("tool_b", "succeeded"), ("tool_c", "succeeded")]
        assert "step_reconciled" in {event["kind"] for event in after["events"]}
    finally:
        await _clean(user)


# Killed after dispatching and before the effect, with a world that cannot
# say what happened: the run stops rather than risk doing it twice.
async def test_an_unreconcilable_step_stops_the_run_instead_of_repeating():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        world = _world_with_replay(plan=["a", "b"], crash_before="b")
        with pytest.raises(Crash):
            await RunController(AsyncSessionLocal, "w1").execute(claimed, world)
        async with AsyncSessionLocal() as db:
            resumed = await AgentRunRepository(db).claim_next(
                "w2", 60.0, now=datetime.now(UTC) + timedelta(seconds=120)
            )
        outcome = await RunController(AsyncSessionLocal, "w2").execute(resumed, world)
        assert outcome.status == "failed"
        assert outcome.error_code == "unknown_effect"
        assert world.effects == ["a"], "b must not be attempted blind"
        after = await _get(user, run["id"])
        assert {row["tool"]: row["status"] for row in after["actions"]}["tool_b"] == "unknown"
    finally:
        await _clean(user)


# The same kill, with a world that can say the effect did not happen: it is
# done now, once, as a fresh row.
async def test_a_step_the_world_says_never_happened_is_done_once():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        world = _world_with_replay(
            plan=["a", "b"], crash_before="b", reconciled={"b": {"kind": "failed"}}
        )
        with pytest.raises(Crash):
            await RunController(AsyncSessionLocal, "w1").execute(claimed, world)
        async with AsyncSessionLocal() as db:
            resumed = await AgentRunRepository(db).claim_next(
                "w2", 60.0, now=datetime.now(UTC) + timedelta(seconds=120)
            )
        outcome = await RunController(AsyncSessionLocal, "w2").execute(resumed, world)
        assert outcome.status == "completed", outcome
        assert world.effects == ["a", "b"]
        after = await _get(user, run["id"])
        b_rows = [row["status"] for row in after["actions"] if row["tool"] == "tool_b"]
        assert b_rows == ["failed", "succeeded"]
    finally:
        await _clean(user)


async def test_a_cancel_is_honoured_between_steps():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        world = _world_with_replay(plan=["a", "b", "c"])

        # The cancel arrives while step a is running - after its effect, before
        # the next decision - which is exactly where the controller reads it.
        original = world.apply

        async def apply_then_cancel(action):
            applied = await original(action)
            if action == "a":
                async with AsyncSessionLocal() as db:
                    await AgentRunRepository(db).request_cancel(user, run["id"])
            return applied

        world.apply = apply_then_cancel  # type: ignore[method-assign]
        outcome = await RunController(AsyncSessionLocal, "w1").execute(claimed, world)
        assert outcome.status == "cancelled"
        assert world.effects == ["a"]
        assert (await _get(user, run["id"]))["status"] == "cancelled"
    finally:
        await _clean(user)


async def test_a_queued_run_is_cancelled_outright():
    user = _user()
    try:
        run = await _make_run(user)
        async with AsyncSessionLocal() as db:
            assert await AgentRunRepository(db).request_cancel(user, run["id"]) == "cancelled"
            assert await AgentRunRepository(db).request_cancel("someone-else", run["id"]) == "missing"
        assert await _claim("w1") is None or (await _claim("w1"))["id"] != run["id"]
    finally:
        await _clean(user)


async def test_an_approval_parks_the_run_and_a_yes_is_spent_by_that_call():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        world = _world_with_replay(plan=["a", "b", "c"], approve={"b"})
        outcome = await RunController(AsyncSessionLocal, "w1").execute(claimed, world)
        assert outcome.status == "waiting_approval"
        assert world.effects == ["a"]
        parked = await _get(user, run["id"])
        assert parked["status"] == "waiting_approval"
        (pending,) = [row for row in parked["approvals"] if row["status"] == "pending"]
        assert pending["tool"] == "tool_b"
        assert await _claim("w2") is None or (await _claim("w2"))["id"] != run["id"]

        async with AsyncSessionLocal() as db:
            assert await AgentRunRepository(db).decide_approval(user, pending["id"], True) == "granted"
        resumed = await _claim("w2")
        assert resumed and resumed["id"] == run["id"]
        outcome = await RunController(AsyncSessionLocal, "w2").execute(resumed, world)
        assert outcome.status == "completed", outcome
        assert world.effects == ["a", "b", "c"]
        after = await _get(user, run["id"])
        assert [row["status"] for row in after["approvals"]] == ["consumed"]
    finally:
        await _clean(user)


async def test_a_no_ends_the_run():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        world = _world_with_replay(plan=["a", "b"], approve={"b"})
        assert (await RunController(AsyncSessionLocal, "w1").execute(claimed, world)).status == "waiting_approval"
        (pending,) = (await _get(user, run["id"]))["approvals"]
        async with AsyncSessionLocal() as db:
            assert await AgentRunRepository(db).decide_approval(user, pending["id"], False) == "denied"
        resumed = await _claim("w2")
        outcome = await RunController(AsyncSessionLocal, "w2").execute(resumed, world)
        assert outcome.status == "failed"
        assert outcome.error_code == "approval_denied"
        assert world.effects == ["a"]
    finally:
        await _clean(user)


async def test_an_expired_approval_cannot_be_granted_late():
    user = _user()
    try:
        run = await _make_run(user)
        claimed = await _claim("w1")
        world = _world_with_replay(plan=["a"], approve={"a"})
        await RunController(AsyncSessionLocal, "w1", approval_ttl_seconds=1.0).execute(claimed, world)
        (pending,) = (await _get(user, run["id"]))["approvals"]
        async with AsyncSessionLocal() as db:
            late = await AgentRunRepository(db).decide_approval(
                user, pending["id"], True, now=datetime.now(UTC) + timedelta(seconds=5)
            )
        assert late == "expired"
        async with AsyncSessionLocal() as db:
            assert await AgentRunRepository(db).decide_approval("stranger", pending["id"], True) == "missing"
    finally:
        await _clean(user)


# The router declining is not completion: a world whose verification finds
# the evidence missing fails the run however cleanly the loop stopped.
async def test_completion_is_the_worlds_evidence_not_the_stop():
    user = _user()
    try:
        await _make_run(user)
        claimed = await _claim("w1")
        world = ScriptedWorld(plan=["a"], accept_when={"a", "b"})
        outcome = await RunController(AsyncSessionLocal, "w1").execute(claimed, world)
        assert outcome.status == "failed"
        assert outcome.error_code == "unverified"
        assert world.effects == ["a"]
    finally:
        await _clean(user)


async def test_a_lapsed_lease_is_reclaimed_and_a_stale_worker_cannot_close():
    user = _user()
    try:
        run = await _make_run(user)
        first = await _claim("w1")
        assert first is not None
        assert first["attempt_count"] == 1
        assert await _claim("w2") is None or (await _claim("w2"))["id"] != run["id"]
        async with AsyncSessionLocal() as db:
            reclaimed = await AgentRunRepository(db).claim_next(
                "w2", 60.0, now=datetime.now(UTC) + timedelta(seconds=120)
            )
            assert reclaimed is not None
            assert reclaimed["id"] == run["id"]
            assert reclaimed["attempt_count"] == 2
            assert await AgentRunRepository(db).finish(run["id"], "completed", worker_id="w1") == "not_mine"
            assert await AgentRunRepository(db).renew_lease(run["id"], "w1", 60.0) is False
            assert await AgentRunRepository(db).renew_lease(run["id"], "w2", 60.0) is True
    finally:
        await _clean(user)
