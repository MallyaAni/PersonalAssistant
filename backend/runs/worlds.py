"""What an agent supplies to be run durably: its judgement and its effects.

The controller owns the guarantees - a step is recorded before it runs,
a succeeded step is never redone, an approval binds one exact call, a cancel
is honoured between steps, completion is evidence. The agent owns everything
here: what to do next, how to do it, how to tell a repeat from a new call,
which calls need a person, and what counts as done.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from backend.services.turn_steps import Decision, TurnResult


@dataclass(frozen=True, slots=True)
class Verification:
    """Whether the run's acceptance criteria are met, and the evidence."""

    accepted: bool
    evidence: dict[str, Any]
    summary: str = ""


class RunWorld(Protocol):
    """One agent's side of a durable run."""

    # The next decision, given the lines of everything already done.
    async def decide(self, lines: list[str]) -> Decision: ...

    # Carry out one action; None for an action this world does not run.
    async def apply(self, action: Any) -> tuple[str, dict[str, Any]] | None: ...

    # The tool an action calls, for the record.
    def tool_name(self, action: Any) -> str: ...

    # The action's arguments as JSON-able data, for the record and the approval.
    def arguments(self, action: Any) -> dict[str, Any]: ...

    # The natural key of an action, or None when its tool declares none.
    def key(self, action: Any) -> str | None: ...

    # Whether carrying out this action makes a new thing.
    def creates(self, action: Any) -> bool: ...

    # The line the next decision reads about a step.
    def describe(self, action: Any, kind: str, outcome: dict[str, Any] | None) -> str: ...

    # Whether a person must approve this exact call first.
    def needs_approval(self, action: Any) -> bool: ...

    # What the approval is about, in words a person can read.
    def approval_summary(self, action: Any) -> str: ...

    # An earlier attempt dispatched this call and never saw it finish. What
    # actually happened, or None when the world cannot tell.
    async def reconcile(self, action: Any, prior: dict[str, Any]) -> dict[str, Any] | None: ...

    # Whether the run's acceptance criteria are met, with the evidence.
    async def verify(self, result: TurnResult, run: dict[str, Any]) -> Verification: ...

    # Every step's outcome, fresh or replayed from an earlier attempt, so a
    # resumed world remembers what it learned without redoing the reads.
    def observe(self, action: Any, kind: str, outcome: dict[str, Any]) -> None: ...


# The hash an approval is bound to: the tool and its exact arguments.
def arguments_hash(tool: str, arguments: dict[str, Any]) -> str:
    material = json.dumps({"tool": tool, "arguments": arguments}, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


WorldFactory = Callable[[dict[str, Any]], RunWorld]
