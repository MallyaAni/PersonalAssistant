"""Drive one run: the turn loop over durable rows, with the guarantees.

The controller is what makes a run more than a long turn:

  * **Every step is recorded before it runs.** A worker killed mid-call
    leaves a `dispatched` row, never nothing, so the next attempt knows a
    call may have happened.
  * **A succeeded step is never redone.** On resume the world's key finds the
    earlier row and its recorded outcome stands in for the call.
  * **An unheard-from step is reconciled, never retried blind.** The world
    is asked what actually happened; if it cannot say, the run stops with
    `unknown_effect` for a person to look at rather than doubling an effect.
  * **An approval binds one exact call.** A step the world says needs a
    person parks the run with a pending approval for the tool and the hash
    of its arguments; a yes is consumed by that call and no other, a no ends
    the run, and an expired yes is no yes.
  * **A cancel is honoured between steps.** The flag is read before every
    decision.
  * **Completion is evidence.** The world verifies its acceptance criteria;
    the router declining is never, by itself, done.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from itertools import count
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.runs.repository import AgentRunRepository
from backend.runs.worlds import RunWorld, arguments_hash
from backend.services.turn_steps import (
    BUDGET,
    CEILING,
    DECLINED,
    FAILED,
    NEEDS_INPUT,
    REFUSED,
    REPEATED,
    SECOND_CREATE,
    SUCCEEDED,
    UNAVAILABLE,
    UNKNOWN,
    UNKNOWN_STATUS,
    Done,
    Resume,
    TurnResult,
    run_steps,
    status_of,
)

logger = logging.getLogger(__name__)

CANCELLED = "cancelled"


class NeedsApproval(Exception):
    """A step needs a person's yes; the run parks until one arrives."""

    def __init__(self, tool: str, target: str) -> None:
        super().__init__(f"{tool} needs approval")
        self.tool = tool
        self.target = target


class ApprovalDeniedError(Exception):
    """A person said no to this exact call; the run cannot go on."""


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """How one attempt at a run ended."""

    status: str
    stopped: str
    steps: int
    error_code: str | None = None
    evidence: dict[str, Any] | None = None
    summary: str = ""


# Why a bound stop is a failure, named for the row.
_STOP_ERRORS = {
    BUDGET: "budget",
    CEILING: "ceiling",
    REPEATED: "repeated",
    SECOND_CREATE: "creation_allowance",
    NEEDS_INPUT: "needs_input",
    UNAVAILABLE: "router_unavailable",
    UNKNOWN: "unknown_effect",
    REFUSED: "refused",
}


class RunController:
    """Run one claimed run to its next stop and record everything."""

    # `sessions` opens a database session; `worker_id` is the claim holder.
    def __init__(
        self,
        sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        worker_id: str,
        approval_ttl_seconds: float = 86_400.0,
    ) -> None:
        self.sessions = sessions
        self.worker_id = worker_id
        self.approval_ttl_seconds = approval_ttl_seconds

    # One attempt: resume from the recorded actions, loop, verify, close.
    async def execute(self, run: dict[str, Any], world: RunWorld) -> RunOutcome:
        run_id = str(run["id"])
        async with self.sessions() as db:
            repo = AgentRunRepository(db)
            prior = await repo.actions_for(run_id)
            await repo.record_event(run_id, "attempt_started", {"attempt": run["attempt_count"]})

        resume = Resume(
            lines=tuple(row["line"] for row in prior if row["line"]),
            keys=frozenset(
                row["idempotency_key"]
                for row in prior
                if row["idempotency_key"] and row["status"] == "succeeded"
            ),
            created=sum(1 for row in prior if row["creates"] and row["status"] in ("succeeded", "unknown")),
            steps=len(prior),
        )
        sequence = count(len(prior) + 1)

        async def decide(lines: list[str]):
            async with self.sessions() as db:
                if await AgentRunRepository(db).is_cancel_requested(run_id):
                    return Done(CANCELLED)
            return await world.decide(lines)

        async def apply(action: Any) -> tuple[str, dict[str, Any]] | None:
            return await self._apply(run, world, action, next(sequence))

        try:
            if await self._cancelled(run_id):
                return await self._close(run_id, CANCELLED, DECLINED, 0, "cancelled")
            opening = await world.decide(list(resume.lines))
            first = getattr(opening, "action", None)
            if first is None:
                # No action to start with: the world's own decision decides
                # the run - declined means verify, anything else is a stop.
                result = TurnResult((), _stop_for(opening), getattr(opening, "reason", "") or getattr(opening, "tool", ""))
            else:
                result = await run_steps(
                    first,
                    apply=apply,
                    decide=decide,
                    describe=world.describe,
                    creates=world.creates,
                    max_steps=int(run["max_steps"]),
                    budget_seconds=float(run["budget_seconds"]),
                    key=world.key,
                    max_creates=int(run["max_creates"]),
                    bound_first=True,
                    resume=resume,
                )
        except NeedsApproval:
            async with self.sessions() as db:
                await AgentRunRepository(db).park_for_approval(run_id, self.worker_id)
            return RunOutcome("waiting_approval", "waiting for approval", 0)
        except ApprovalDeniedError:
            return await self._close(run_id, "failed", "approval denied", 0, "approval_denied")

        if result.stopped == DECLINED and result.detail == CANCELLED:
            return await self._close(run_id, CANCELLED, result.stopped, len(result.steps), "cancelled")
        if result.unknown:
            return await self._close(
                run_id, "failed", result.stopped, len(result.steps), "unknown_effect"
            )

        verification = await world.verify(result, run)
        if verification.accepted:
            return await self._close(
                run_id,
                "completed",
                result.stopped,
                len(result.steps),
                None,
                evidence=verification.evidence,
                summary=verification.summary,
            )
        error = _STOP_ERRORS.get(result.stopped, "unverified")
        return await self._close(
            run_id,
            "failed",
            result.stopped,
            len(result.steps),
            error,
            evidence=verification.evidence,
            summary=verification.summary,
            retryable=result.stopped in (BUDGET, UNAVAILABLE),
        )

    # One step: reconcile or replay a prior row by key, gate on approval,
    # record, run, record.
    async def _apply(
        self, run: dict[str, Any], world: RunWorld, action: Any, sequence: int
    ) -> tuple[str, dict[str, Any]] | None:
        run_id = str(run["id"])
        tool = world.tool_name(action)
        arguments = world.arguments(action)
        key = world.key(action)
        async with self.sessions() as db:
            repo = AgentRunRepository(db)
            prior = await repo.find_action(run_id, key) if key else None
            if prior is not None and prior["status"] == "succeeded":
                await repo.record_event(run_id, "step_replayed", {"tool": tool, "sequence": prior["sequence"]})
                replayed = dict(prior["outcome"] or {"kind": "done"})
                _observe(world, action, prior["kind"], replayed)
                return prior["kind"], replayed
            if prior is not None and prior["status"] in ("dispatched", "unknown"):
                seen = await world.reconcile(action, prior)
                if seen is None:
                    await repo.finish_action(prior["id"], "unknown", {"kind": "unknown"}, prior["line"])
                    await repo.record_event(run_id, "step_unreconciled", {"tool": tool})
                    return prior["kind"], {"kind": "unknown"}
                status = _status_name(seen)
                await repo.finish_action(prior["id"], status, seen, world.describe(action, prior["kind"], seen))
                await repo.record_event(run_id, "step_reconciled", {"tool": tool, "status": status})
                if status == "succeeded":
                    _observe(world, action, prior["kind"], seen)
                    return prior["kind"], seen
                # It did not happen: fall through and do it now, as a new row.

            if world.needs_approval(action):
                digest = arguments_hash(tool, arguments)
                if await repo.denied_approval(run_id, digest):
                    raise ApprovalDeniedError(tool)
                granted = await repo.granted_approval(run_id, digest)
                if granted is None:
                    target = str(arguments.get("target") or arguments.get("to") or tool)
                    await repo.request_approval(
                        run_id,
                        run["user_id"],
                        tool,
                        digest,
                        target,
                        world.approval_summary(action),
                        self.approval_ttl_seconds,
                    )
                    raise NeedsApproval(tool, target)
                await repo.consume_approval(granted["id"])

            row = await repo.dispatch_action(
                run_id,
                sequence,
                tool,
                arguments,
                idempotency_key=key,
                creates=world.creates(action),
            )

        try:
            applied = await world.apply(action)
        except Exception as exc:
            outcome = {"kind": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            async with self.sessions() as db:
                await AgentRunRepository(db).finish_action(
                    row["id"], "failed", outcome, world.describe(action, "step", outcome)
                )
            logger.warning("Run %s step %d failed", run_id, sequence, exc_info=True)
            return "step", outcome

        async with self.sessions() as db:
            repo = AgentRunRepository(db)
            if applied is None:
                outcome = {"kind": "unavailable"}
                await repo.finish_action(row["id"], "refused", outcome, world.describe(action, "step", outcome))
                return None
            kind, outcome = applied
            await repo.finish_action(
                row["id"], _status_name(outcome), outcome, world.describe(action, kind, outcome), kind=kind
            )
        _observe(world, action, kind, outcome)
        return kind, outcome

    async def _cancelled(self, run_id: str) -> bool:
        async with self.sessions() as db:
            return await AgentRunRepository(db).is_cancel_requested(run_id)

    async def _close(
        self,
        run_id: str,
        status: str,
        stopped: str,
        steps: int,
        error_code: str | None,
        *,
        evidence: dict[str, Any] | None = None,
        summary: str = "",
        retryable: bool = False,
    ) -> RunOutcome:
        async with self.sessions() as db:
            closed = await AgentRunRepository(db).finish(
                run_id,
                status,
                result={"evidence": evidence or {}, "summary": summary, "stopped": stopped},
                error_code=error_code,
                worker_id=self.worker_id,
                retryable=retryable,
            )
        return RunOutcome(closed if closed in ("requeued", "not_mine") else status, stopped, steps, error_code, evidence, summary)


# Tell the world what a step came to, when it wants to know.
def _observe(world: Any, action: Any, kind: str, outcome: dict[str, Any]) -> None:
    observe = getattr(world, "observe", None)
    if callable(observe):
        observe(action, kind, outcome)


# The action row's status word for an outcome.
def _status_name(outcome: dict[str, Any] | None) -> str:
    status = status_of(outcome)
    if status == SUCCEEDED:
        return "succeeded"
    if status == UNKNOWN_STATUS:
        return "unknown"
    return "failed" if status == FAILED else status


# The stop a non-action opening decision amounts to.
def _stop_for(decision: Any) -> str:
    name = type(decision).__name__
    return {"NeedsInput": NEEDS_INPUT, "Unavailable": UNAVAILABLE, "Refused": REFUSED}.get(name, DECLINED)
