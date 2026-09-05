"""Runs: what an agent is doing for a person, and their say over it.

A run is created by an agent or a turn, never here. Here a person sees
their runs with every recorded step and event, stops one, and answers the
approvals a step is waiting on. Every route checks the session identity owns
`user_id` and holds the scope for the verb: `runs:read` to look, `runs:act`
to cancel or decide.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.auth import (
    SCOPE_RUNS_ACT,
    SCOPE_RUNS_READ,
    IdentityDependency,
    authorize_scope,
    authorize_user,
)
from backend.core.dependencies import DependencyAgentRuns

router = APIRouter(prefix="/runs/{user_id}", tags=["runs"])


class ApprovalDecision(BaseModel):
    granted: bool


# A run as the workspace shows it: the columns a person can act on, with
# datetimes as ISO strings.
def _run_view(run: dict[str, Any]) -> dict[str, Any]:
    view = {
        key: run.get(key)
        for key in (
            "id",
            "actor",
            "kind",
            "objective",
            "acceptance",
            "status",
            "attempt_count",
            "cancel_requested",
            "error_code",
            "result",
            "channel",
            "conversation_id",
        )
    }
    for key in ("created_at", "started_at", "completed_at"):
        value = run.get(key)
        view[key] = value.isoformat() if value else None
    return view


def _stamped(items: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    stamped = []
    for item in items:
        copy = dict(item)
        for key in keys:
            if copy.get(key) is not None:
                copy[key] = copy[key].isoformat()
        stamped.append(copy)
    return stamped


@router.get("")
async def list_runs(
    user_id: str, identity: IdentityDependency, runs: DependencyAgentRuns
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_RUNS_READ)
    return {"runs": [_run_view(run) for run in await runs.list_for_user(user_id)]}


@router.get("/{run_id}")
async def get_run(
    user_id: str, run_id: str, identity: IdentityDependency, runs: DependencyAgentRuns
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_RUNS_READ)
    run = await runs.get_owned(user_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    view = _run_view(run)
    view["actions"] = _stamped(run["actions"], "dispatched_at", "finished_at")
    view["approvals"] = _stamped(run["approvals"], "requested_at", "expires_at", "decided_at")
    view["events"] = _stamped(run["events"], "at")
    return view


# Ask the run to stop. Between steps, so a step already dispatched finishes
# and is recorded before the run is closed.
@router.post("/{run_id}/cancel")
async def cancel_run(
    user_id: str, run_id: str, identity: IdentityDependency, runs: DependencyAgentRuns
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_RUNS_ACT)
    outcome = await runs.request_cancel(user_id, run_id)
    if outcome == "missing":
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": outcome}


# Yes or no to one exact call. A yes is spent by that call and no other; a
# no ends the run; an approval past its expiry cannot be granted late.
@router.post("/{run_id}/approvals/{approval_id}")
async def decide_approval(
    user_id: str,
    run_id: str,
    approval_id: str,
    body: ApprovalDecision,
    identity: IdentityDependency,
    runs: DependencyAgentRuns,
) -> dict[str, Any]:
    authorize_user(user_id, identity)
    authorize_scope(identity, SCOPE_RUNS_ACT)
    if await runs.get_owned(user_id, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    outcome = await runs.decide_approval(user_id, approval_id, body.granted)
    if outcome == "missing":
        raise HTTPException(status_code=404, detail="Approval not found")
    if outcome in ("not_pending", "expired"):
        raise HTTPException(status_code=409, detail=f"Approval is {outcome}")
    return {"status": outcome}
