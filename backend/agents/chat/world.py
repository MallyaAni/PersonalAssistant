"""A chat turn's unfinished work as a durable run.

A turn that stops on its budget or its step ceiling with the router still
naming steps hands the rest here: the person's words, the steps the turn
took, and the conversation. The world asks the same router for the next
step, shown everything already done, and carries it out through the same
executor - over the API, with the person's short-lived token, because the
worker is another process. The controller records each step before it runs,
replays by key on resume, and a step outside the run's grant is refused.

Completion is the router declining after the steps it named were carried
out: that is the same stop a turn has, with the difference that here the
steps were done. A router that needs something the message did not say ends
the run with `needs_input`, for the person to answer; the run's delivery
tells them.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from backend.runs.worlds import Verification
from backend.services.turn_steps import Act, Decision, Done, NeedsInput, Refused, TurnResult, Unavailable

KIND = "chat_continuation"

# Effects a continuation may carry out for a person who is not watching. A
# read is what the turn would have done next; anything that sends, spends
# or changes something outside this system needs the person's yes.
UNATTENDED_EFFECTS = frozenset({"read", "write"})
# How many times the router may fail before the run gives up on it.
MAX_ROUTER_FAILURES = 3


class StepClient(Protocol):
    """How the world reaches the assistant."""

    async def decide(self, user_id: str, query: str, lines: list[str], remaining_seconds: float) -> dict[str, Any]: ...

    async def apply(self, user_id: str, query: str, conversation_id: str | None, call: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class StepCall:
    """One step the router named, as the boundary carries it."""

    tool: str
    call_json: str
    label: str
    detail: str
    key: str | None
    creates: bool
    effect: str
    approval: str

    @property
    def call(self) -> dict[str, Any]:
        return json.loads(self.call_json)


# The step lines a turn recorded before handing off, from the run's
# acceptance list, where the turn wrote them.
def lines_of(run: dict[str, Any]) -> list[str]:
    return [str(line) for line in (run.get("acceptance") or []) if str(line).strip()]


class ChatContinuationWorld:
    """Continue a chat turn's steps until the router declines."""

    def __init__(self, run: dict[str, Any], client: StepClient) -> None:
        self.run = run
        self.client = client
        self.user_id = str(run["user_id"])
        self.query = str(run.get("objective") or "")
        self.conversation_id = str(run["conversation_id"]) if run.get("conversation_id") else None
        self.before = lines_of(run)
        self.budget = float(run.get("budget_seconds") or 60.0)
        self.started = time.monotonic()
        self.taken: list[str] = []
        self.router_failures = 0
        self.stopped_by: str = ""

    # The router's next step, shown the turn's steps and the run's.
    async def decide(self, lines: list[str]) -> Decision:
        remaining = max(0.0, self.budget - (time.monotonic() - self.started))
        try:
            view = await self.client.decide(self.user_id, self.query, [*self.before, *lines], remaining)
        except Exception as exc:
            self.router_failures += 1
            if self.router_failures >= MAX_ROUTER_FAILURES:
                return Unavailable(f"the router could not be reached: {type(exc).__name__}")
            return Unavailable(f"the router could not be reached: {type(exc).__name__}")
        kind = str(view.get("kind") or "")
        if kind == "act":
            call = view.get("call")
            if not isinstance(call, dict):
                return Unavailable("the router named a step with no call")
            step = StepCall(
                tool=str(view.get("tool") or ""),
                call_json=json.dumps(call, sort_keys=True, default=str),
                label=str(view.get("label") or view.get("tool") or "step"),
                detail=str(view.get("detail") or ""),
                key=view.get("key") if view.get("key") else None,
                creates=bool(view.get("creates")),
                effect=str(view.get("effect") or "undeclared"),
                approval=str(view.get("approval") or "never"),
            )
            return Act(step)
        if kind == "done":
            self.stopped_by = "done"
            return Done(str(view.get("reason") or "nothing further"))
        if kind == "needs_input":
            self.stopped_by = "needs_input"
            return NeedsInput(str(view.get("tool") or ""), str(view.get("missing") or ""))
        if kind == "refused":
            return Refused(str(view.get("reason") or "refused"))
        return Unavailable(str(view.get("reason") or "the router could not decide"))

    async def apply(self, action: Any) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(action, StepCall):
            return None
        applied = await self.client.apply(self.user_id, self.query, self.conversation_id, action.call)
        kind = str(applied.get("kind") or "")
        outcome = applied.get("outcome")
        if not kind or not isinstance(outcome, dict):
            return None
        return kind, outcome

    def tool_name(self, action: Any) -> str:
        if isinstance(action, StepCall):
            # A toolbox step is named by what it does at the grant, not by
            # the server's tool: a continuation may read through any server,
            # and nothing else.
            if action.tool and str(action.call.get("type")) == "ToolboxAction":
                return f"mcp:{action.effect}"
            return action.tool
        return "unknown"

    def arguments(self, action: Any) -> dict[str, Any]:
        if isinstance(action, StepCall):
            return {"tool": action.tool, "call": action.call}
        return {}

    def key(self, action: Any) -> str | None:
        return action.key if isinstance(action, StepCall) else None

    def creates(self, action: Any) -> bool:
        return action.creates if isinstance(action, StepCall) else False

    def describe(self, action: Any, kind: str, outcome: dict[str, Any] | None) -> str:
        if not isinstance(action, StepCall):
            return kind
        line = f"{action.label}: {action.detail}" if action.detail else action.label
        went = str((outcome or {}).get("kind") or "")
        if went and went != "done" and went != "found":
            line = f"{line} [{went}]"
        return line

    # A person who is not watching is asked before anything leaves or spends.
    def needs_approval(self, action: Any) -> bool:
        if not isinstance(action, StepCall):
            return False
        return action.approval == "always" or action.effect not in UNATTENDED_EFFECTS

    def approval_summary(self, action: Any) -> str:
        if not isinstance(action, StepCall):
            return ""
        return f"{action.label}: {action.detail}".strip(": ")

    # A read that was never heard from is simply done again; a write is not
    # guessed at, and the run stops for a person to look.
    async def reconcile(self, action: Any, prior: dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(action, StepCall) and action.effect == "read":
            return {"kind": "failed", "error": "redone after an interrupted read"}
        return None

    def observe(self, action: Any, kind: str, outcome: dict[str, Any]) -> None:
        if isinstance(action, StepCall):
            self.taken.append(self.describe(action, kind, outcome))

    async def verify(self, result: TurnResult, run: dict[str, Any]) -> Verification:
        steps = [step.line for step in result.steps]
        # Done when the router declined after the steps it named were carried
        # out and none of them was cut short; anything else names its stop.
        clean = result.clean and self.stopped_by == "done"
        evidence = {
            "query": self.query,
            "steps_before": self.before,
            "steps": steps,
            "stopped": result.stopped,
            "conversation_id": self.conversation_id,
        }
        if clean:
            summary = (
                f"Finished the rest of what you asked: {'; '.join(steps)}."
                if steps else "Nothing further was needed after what the turn already did."
            )
        elif self.stopped_by == "needs_input":
            summary = "Stopped because the next step needs something you did not say; ask again with it."
        else:
            summary = f"Stopped before finishing: {result.stopped}."
        return Verification(clean, evidence, summary)
