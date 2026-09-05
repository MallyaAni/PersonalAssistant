"""What a run is allowed to call, decided beside the registry and enforced
by the controller - never taken from the world's own word.

A world names the tool for each action it decides. The world is the
agent's code, and the agent is the thing under test: a prompt injection
that talked a world into asking for a write, or a defect that made it ask
for a tool it was never meant to have, must meet a wall that is not the
world. The wall is the grant: the set of tool names the run may ever call,
fixed per run kind by the operator's registry, checked by the controller
before any step is dispatched. A step outside the grant is recorded as
refused, and the run fails with `unauthorized_tool`, not retried.

This is D8 of the platform plan in its first shape: a scope per run,
derived from what the kind's contracts need, checked at execution. It is
not yet a token, because nothing outside this process reads it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Grant:
    """The tool names one run may call."""

    tools: frozenset[str]

    # Whether a tool name is within the grant.
    def allows(self, tool: str) -> bool:
        return str(tool) in self.tools


class GrantViolation(Exception):
    """A step named a tool the run was never granted."""

    def __init__(self, tool: str) -> None:
        super().__init__(tool)
        self.tool = tool


# A grant from any iterable of names, for the registry to write plainly.
def grant_of(*tools: str) -> Grant:
    return Grant(frozenset(str(tool) for tool in tools))
