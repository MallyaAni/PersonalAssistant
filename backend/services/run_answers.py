"""The person's answer to a run, from a chat turn.

A run that is about to send, spend or change something outside this system
parks with a pending approval and waits. Until now the only way to answer
was the runs API. This carries the answer from conversation: the router
decides the person answered a waiting run (`manage_runs`), and this module
finds which approval they mean and decides it through the same repository
method the API uses, so a yes from chat is bound to the same exact call.

Which run they mean is decided plainly: one pending approval is the one;
several and a number from the list they were shown picks that one; several
and no number is a question back to them, never a guess from their words.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.runs.repository import AgentRunRepository
from backend.tools.actions import ManageRunsAction

Sessions = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# How many runs a status answer lists.
MAX_LISTED = 6


# One pending approval as the reply and the person see it.
def _waiting_view(index: int, approval: dict[str, Any], run: dict[str, Any] | None) -> dict[str, Any]:
    expires = approval.get("expires_at")
    return {
        "number": index,
        "approval_id": approval["id"],
        "run_id": approval["run_id"],
        "kind": str((run or {}).get("kind") or "run").replace("_", " "),
        "objective": str((run or {}).get("objective") or "")[:160],
        "summary": str(approval.get("summary") or approval.get("tool") or ""),
        "expires_at": expires.isoformat() if isinstance(expires, datetime) else None,
    }


# The runs waiting on this person's yes, oldest first, numbered as shown.
async def waiting_for(repo: AgentRunRepository, user_id: str) -> list[dict[str, Any]]:
    pending = await repo.pending_approvals_for_user(user_id)
    views = []
    for index, (approval, run) in enumerate(pending, start=1):
        views.append(_waiting_view(index, approval, run))
    return views


# The one they mean among several, by the number they were shown; None
# when the words do not settle it.
def _chosen(which: str, waiting: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(waiting) == 1:
        return waiting[0]
    words = str(which or "").strip()
    for token in words.replace("#", " ").split():
        if token.isdigit() and 1 <= int(token) <= len(waiting):
            return waiting[int(token) - 1]
    for view in waiting:
        if words and view["approval_id"].startswith(words):
            return view
    return None


# Carry out the person's answer and say what happened, in the outcome
# vocabulary the reply renders from.
async def answer(sessions: Sessions, user_id: str, action: ManageRunsAction) -> dict[str, Any]:
    async with sessions() as db:
        repo = AgentRunRepository(db)
        waiting = await waiting_for(repo, user_id)
        if action.mode == "status":
            runs = await repo.list_for_user(user_id, limit=MAX_LISTED)
            return {
                "kind": "runs_status",
                "waiting": waiting,
                "runs": [
                    {
                        "kind": str(run.get("kind") or "").replace("_", " "),
                        "status": run.get("status"),
                        "objective": str(run.get("objective") or "")[:160],
                        "summary": str(((run.get("result") or {}) if isinstance(run.get("result"), dict) else {}).get("summary") or "")[:200],
                    }
                    for run in runs
                ],
            }
        if not waiting:
            return {"kind": "runs_nothing_pending", "mode": action.mode}
        chosen = _chosen(action.which, waiting)
        if chosen is None:
            return {"kind": "runs_which", "mode": action.mode, "waiting": waiting}
        granted = action.mode == "approve"
        decided = await repo.decide_approval(user_id, chosen["approval_id"], granted, now=datetime.now(UTC))
        if decided not in ("granted", "denied"):
            return {"kind": "runs_not_pending", "mode": action.mode, "state": decided, "chosen": chosen}
        return {"kind": "run_approved" if granted else "run_denied", "chosen": chosen}
