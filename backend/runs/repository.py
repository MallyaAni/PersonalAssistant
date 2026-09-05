"""Storage for runs, their actions, approvals and events.

A copy of the shape the scheduled-task queue proved: a worker claims the
oldest claimable run with a lease, a crashed worker's lease lapses and the
run is reclaimed, and `finish` is the only thing that closes one. Every
method returns plain data, never a live ORM object.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_run import (
    AgentRun,
    AgentRunAction,
    AgentRunApproval,
    AgentRunEvent,
)

OPEN_STATUSES = frozenset({"queued", "running", "waiting_approval"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


# JSON, or the fallback when the column is empty or unreadable.
def _loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except ValueError:
        return fallback


def _run_dict(run: AgentRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "tenant_id": run.tenant_id,
        "user_id": run.user_id,
        "actor": run.actor,
        "kind": run.kind,
        "objective": run.objective,
        "acceptance": _loads(run.acceptance, []),
        "status": run.status,
        "budget_seconds": run.budget_seconds,
        "max_steps": run.max_steps,
        "max_creates": run.max_creates,
        "policy_version": run.policy_version,
        "prompt_versions": _loads(run.prompt_versions, {}),
        "cancel_requested": run.cancel_requested,
        "attempt_count": run.attempt_count,
        "worker_id": run.worker_id,
        "lease_expires_at": run.lease_expires_at,
        "conversation_id": str(run.conversation_id) if run.conversation_id else None,
        "channel": run.channel,
        "result": _loads(run.result, None),
        "error_code": run.error_code,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
    }


def _action_dict(action: AgentRunAction) -> dict[str, Any]:
    return {
        "id": str(action.id),
        "run_id": str(action.run_id),
        "sequence": action.sequence,
        "tool": action.tool,
        "kind": action.kind,
        "arguments": _loads(action.arguments, {}),
        "idempotency_key": action.idempotency_key,
        "creates": action.creates,
        "status": action.status,
        "outcome": _loads(action.outcome, None),
        "line": action.line,
        "dispatched_at": action.dispatched_at,
        "finished_at": action.finished_at,
    }


def _approval_dict(approval: AgentRunApproval) -> dict[str, Any]:
    return {
        "id": str(approval.id),
        "run_id": str(approval.run_id),
        "user_id": approval.user_id,
        "tool": approval.tool,
        "arguments_hash": approval.arguments_hash,
        "target": approval.target,
        "summary": approval.summary,
        "status": approval.status,
        "requested_at": approval.requested_at,
        "expires_at": approval.expires_at,
        "decided_at": approval.decided_at,
        "decided_by": approval.decided_by,
    }


def _event_dict(event: AgentRunEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "at": event.at,
        "kind": event.kind,
        "detail": _loads(event.detail, None),
    }


class AgentRunRepository:
    """Runs and everything recorded about them, on the caller's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # A new run, queued. The principal is the person; the actor is who acts.
    async def create(
        self,
        user_id: str,
        actor: str,
        kind: str,
        objective: str,
        acceptance: list[str],
        *,
        budget_seconds: float,
        max_steps: int,
        max_creates: int,
        tenant_id: str = "default",
        policy_version: str = "",
        prompt_versions: dict[str, str] | None = None,
        conversation_id: str | None = None,
        channel: str = "web",
    ) -> dict[str, Any]:
        run = AgentRun(
            tenant_id=tenant_id,
            user_id=user_id,
            actor=actor,
            kind=kind,
            objective=objective,
            acceptance=json.dumps(list(acceptance)),
            status="queued",
            budget_seconds=float(budget_seconds),
            max_steps=int(max_steps),
            max_creates=int(max_creates),
            policy_version=policy_version,
            prompt_versions=json.dumps(prompt_versions or {}, sort_keys=True),
            conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
            channel=channel,
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        await self.record_event(str(run.id), "created", {"kind": kind, "actor": actor})
        return _run_dict(run)

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(AgentRun)
                .where(AgentRun.user_id == user_id)
                .order_by(AgentRun.created_at.desc())
                .limit(limit)
            )
        ).scalars()
        return [_run_dict(run) for run in rows]

    # One run with everything recorded about it, only if this person owns it.
    async def get_owned(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        run = await self._owned(user_id, run_id)
        if run is None:
            return None
        found = _run_dict(run)
        found["actions"] = await self.actions_for(run_id)
        found["approvals"] = await self.approvals_for(run_id)
        found["events"] = await self.events_for(run_id)
        return found

    async def get(self, run_id: str) -> dict[str, Any] | None:
        run = await self.session.get(AgentRun, uuid.UUID(str(run_id)))
        return _run_dict(run) if run else None

    async def _owned(self, user_id: str, run_id: str) -> AgentRun | None:
        try:
            key = uuid.UUID(str(run_id))
        except ValueError:
            return None
        run = await self.session.get(AgentRun, key)
        if run is None or run.user_id != user_id:
            return None
        return run

    # Take the oldest claimable run: queued, or running with a lapsed lease. A
    # run waiting for approval is not claimable until a decision wakes it.
    #
    # `kinds` is what this worker can run; a worker never claims a run it
    # would only fail with `no_world`, and two workers hosting different
    # agents share the table without taking each other's work. `user_id`
    # narrows further, for a caller driving one person's run by hand.
    async def claim_next(
        self,
        worker_id: str,
        lease_seconds: float,
        now: datetime | None = None,
        kinds: Iterable[str] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        moment = now or datetime.now(UTC)
        conditions = [
            or_(
                AgentRun.status == "queued",
                (AgentRun.status == "running") & (AgentRun.lease_expires_at < moment),
            )
        ]
        if kinds is not None:
            conditions.append(AgentRun.kind.in_(tuple(kinds)))
        if user_id is not None:
            conditions.append(AgentRun.user_id == user_id)
        run = cast(
            AgentRun | None,
            await self.session.scalar(
                select(AgentRun)
                .where(*conditions)
                .order_by(AgentRun.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            ),
        )
        if run is None:
            await self.session.rollback()
            return None
        run.status = "running"
        run.worker_id = worker_id
        run.lease_expires_at = moment + timedelta(seconds=lease_seconds)
        run.attempt_count += 1
        run.started_at = run.started_at or moment
        await self.session.commit()
        await self.session.refresh(run)
        return _run_dict(run)

    async def renew_lease(self, run_id: str, worker_id: str, lease_seconds: float) -> bool:
        run = await self.session.get(AgentRun, uuid.UUID(str(run_id)))
        if run is None or run.worker_id != worker_id or run.status != "running":
            return False
        run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        await self.session.commit()
        return True

    # Ask an open run to stop between steps. The worker honours it at its
    # next decision; a run that is queued is cancelled outright.
    async def request_cancel(self, user_id: str, run_id: str) -> str:
        run = await self._owned(user_id, run_id)
        if run is None:
            return "missing"
        if run.status in TERMINAL_STATUSES:
            return "finished"
        run.cancel_requested = True
        if run.status in ("queued", "waiting_approval"):
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            run.error_code = "cancelled"
        await self.session.commit()
        await self.record_event(run_id, "cancel_requested", {"by": user_id})
        return "cancelled" if run.status == "cancelled" else "requested"

    async def is_cancel_requested(self, run_id: str) -> bool:
        run = await self.session.get(AgentRun, uuid.UUID(str(run_id)))
        if run is None:
            return True
        await self.session.refresh(run)
        return bool(run.cancel_requested)

    # ---------------------------------------------------------------- actions

    async def actions_for(self, run_id: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(AgentRunAction)
                .where(AgentRunAction.run_id == uuid.UUID(str(run_id)))
                .order_by(AgentRunAction.sequence.asc())
            )
        ).scalars()
        return [_action_dict(action) for action in rows]

    # The latest action with this key, so a resume can tell a step already
    # done from one dispatched and never heard from.
    async def find_action(self, run_id: str, idempotency_key: str) -> dict[str, Any] | None:
        action = await self.session.scalar(
            select(AgentRunAction)
            .where(
                (AgentRunAction.run_id == uuid.UUID(str(run_id)))
                & (AgentRunAction.idempotency_key == idempotency_key)
            )
            .order_by(AgentRunAction.sequence.desc())
            .limit(1)
        )
        return _action_dict(action) if action else None

    # Record a step before it runs, so a worker killed mid-call leaves a
    # `dispatched` row rather than nothing.
    async def dispatch_action(
        self,
        run_id: str,
        sequence: int,
        tool: str,
        arguments: dict[str, Any],
        *,
        idempotency_key: str | None,
        creates: bool,
        kind: str = "step",
    ) -> dict[str, Any]:
        action = AgentRunAction(
            run_id=uuid.UUID(str(run_id)),
            sequence=sequence,
            tool=tool,
            kind=kind,
            arguments=json.dumps(arguments, sort_keys=True, default=str),
            idempotency_key=idempotency_key,
            creates=creates,
            status="dispatched",
        )
        self.session.add(action)
        await self.session.commit()
        await self.session.refresh(action)
        return _action_dict(action)

    async def finish_action(
        self,
        action_id: str,
        status: str,
        outcome: dict[str, Any] | None,
        line: str,
        kind: str | None = None,
    ) -> None:
        action = await self.session.get(AgentRunAction, uuid.UUID(str(action_id)))
        if action is None:
            return
        action.status = status
        action.outcome = json.dumps(outcome or {}, sort_keys=True, default=str)
        action.line = line
        if kind:
            action.kind = kind
        action.finished_at = datetime.now(UTC)
        await self.session.commit()

    # -------------------------------------------------------------- approvals

    async def approvals_for(self, run_id: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(AgentRunApproval)
                .where(AgentRunApproval.run_id == uuid.UUID(str(run_id)))
                .order_by(AgentRunApproval.requested_at.asc())
            )
        ).scalars()
        return [_approval_dict(approval) for approval in rows]

    async def request_approval(
        self,
        run_id: str,
        user_id: str,
        tool: str,
        arguments_hash: str,
        target: str,
        summary: str,
        ttl_seconds: float,
    ) -> dict[str, Any]:
        approval = AgentRunApproval(
            run_id=uuid.UUID(str(run_id)),
            user_id=user_id,
            tool=tool,
            arguments_hash=arguments_hash,
            target=target[:300],
            summary=summary,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        self.session.add(approval)
        await self.session.commit()
        await self.session.refresh(approval)
        await self.record_event(run_id, "approval_requested", {"tool": tool, "target": target[:120]})
        return _approval_dict(approval)

    # A granted, unexpired, unconsumed approval for exactly this call.
    async def granted_approval(
        self, run_id: str, arguments_hash: str, now: datetime | None = None
    ) -> dict[str, Any] | None:
        moment = now or datetime.now(UTC)
        approval = await self.session.scalar(
            select(AgentRunApproval)
            .where(
                (AgentRunApproval.run_id == uuid.UUID(str(run_id)))
                & (AgentRunApproval.arguments_hash == arguments_hash)
                & (AgentRunApproval.status == "granted")
                & (AgentRunApproval.expires_at > moment)
            )
            .order_by(AgentRunApproval.decided_at.desc())
            .limit(1)
        )
        return _approval_dict(approval) if approval else None

    # Whether a person already said no to exactly this call.
    async def denied_approval(self, run_id: str, arguments_hash: str) -> bool:
        approval = await self.session.scalar(
            select(AgentRunApproval)
            .where(
                (AgentRunApproval.run_id == uuid.UUID(str(run_id)))
                & (AgentRunApproval.arguments_hash == arguments_hash)
                & (AgentRunApproval.status == "denied")
            )
            .limit(1)
        )
        return approval is not None

    async def consume_approval(self, approval_id: str) -> None:
        approval = await self.session.get(AgentRunApproval, uuid.UUID(str(approval_id)))
        if approval is None:
            return
        approval.status = "consumed"
        await self.session.commit()

    # A person's decision on one pending approval, only if they own the run.
    # An expired approval cannot be granted late; the run asks again.
    async def decide_approval(
        self, user_id: str, approval_id: str, granted: bool, now: datetime | None = None
    ) -> str:
        try:
            key = uuid.UUID(str(approval_id))
        except ValueError:
            return "missing"
        approval = await self.session.get(AgentRunApproval, key)
        if approval is None or approval.user_id != user_id:
            return "missing"
        if approval.status != "pending":
            return "not_pending"
        moment = now or datetime.now(UTC)
        if approval.expires_at <= moment:
            approval.status = "expired"
            await self.session.commit()
            return "expired"
        approval.status = "granted" if granted else "denied"
        approval.decided_at = moment
        approval.decided_by = user_id
        run = await self.session.get(AgentRun, approval.run_id)
        # Either answer wakes the run: a yes to carry on, a no to record it.
        if run is not None and run.status == "waiting_approval":
            run.status = "queued"
            run.worker_id = None
            run.lease_expires_at = None
        await self.session.commit()
        await self.record_event(
            str(approval.run_id), "approval_decided", {"granted": granted, "by": user_id}
        )
        return approval.status

    # Release the lease and wait for a person.
    async def park_for_approval(self, run_id: str, worker_id: str) -> bool:
        run = await self.session.get(AgentRun, uuid.UUID(str(run_id)))
        if run is None or run.worker_id not in (None, worker_id):
            return False
        run.status = "waiting_approval"
        run.worker_id = None
        run.lease_expires_at = None
        await self.session.commit()
        return True

    # ----------------------------------------------------------------- events

    async def record_event(self, run_id: str, kind: str, detail: dict[str, Any] | None) -> None:
        self.session.add(
            AgentRunEvent(
                run_id=uuid.UUID(str(run_id)),
                kind=kind,
                detail=json.dumps(detail or {}, sort_keys=True, default=str),
            )
        )
        await self.session.commit()

    async def events_for(self, run_id: str) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == uuid.UUID(str(run_id)))
                .order_by(AgentRunEvent.at.asc())
            )
        ).scalars()
        return [_event_dict(event) for event in rows]

    # ----------------------------------------------------------------- finish

    # Close a run. A failure with attempts left goes back on the queue; a
    # worker whose lease lapsed cannot close a run another worker has taken.
    async def finish(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        worker_id: str | None = None,
        max_attempts: int = 3,
        retryable: bool = False,
    ) -> str:
        run = await self.session.get(AgentRun, uuid.UUID(str(run_id)))
        if run is None:
            return "missing"
        if worker_id is not None and run.worker_id not in (None, worker_id):
            return "not_mine"
        if status == "failed" and retryable and run.attempt_count < max_attempts:
            run.status = "queued"
            run.error_code = error_code
            run.worker_id = None
            run.lease_expires_at = None
            await self.session.commit()
            await self.record_event(run_id, "requeued", {"error": error_code})
            return "requeued"
        run.status = status
        run.result = json.dumps(result or {}, sort_keys=True, default=str) if result is not None else run.result
        run.error_code = error_code
        run.completed_at = datetime.now(UTC)
        run.worker_id = None
        run.lease_expires_at = None
        await self.session.commit()
        await self.record_event(run_id, "finished", {"status": status, "error": error_code})
        return status

    # Remove one person's runs and everything under them; for tests.
    async def delete_for_user(self, user_id: str) -> int:
        rows = list(
            (
                await self.session.execute(select(AgentRun).where(AgentRun.user_id == user_id))
            ).scalars()
        )
        for run in rows:
            await self.session.delete(run)
        await self.session.commit()
        return len(rows)
