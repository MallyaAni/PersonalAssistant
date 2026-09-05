"""One step of a chat turn, decided and carried out on request.

A chat turn that runs out of budget with work left hands the rest to a
durable run (`chat_continuation`). The run's worker lives in another
process and reaches the assistant the way every worker does - over the API
with a short-lived token - so the turn's loop is exposed here as two calls:
*decide*, which asks the router for the next step given the steps already
taken, and *apply*, which carries one step out. Between them the action
travels as a plain call - its type and fields - and is rebuilt through the
same dataclasses the router produced, so what the run applies is exactly
what the router decided.

Nothing here decides anything itself. The router decides the step, the
turn's executor carries it out, the effect contracts say what a later step
may be; this module only carries their answers across the boundary.
"""

from __future__ import annotations

import dataclasses
import typing
from typing import Any

from backend.services.mcp_tool_orchestration_service import MCPToolPlan
from backend.services.turn_steps import Act, Decision, Done, NeedsInput, Refused, Unavailable
from backend.tools import actions as action_types
from backend.tools.actions import MainAction, ToolboxAction
from backend.tools.registry import (
    action_creates,
    action_key,
    contract_for_action,
    describe_action,
    tool_name_of,
)

# Every action class the router can produce, by name, so a call names its
# type and is rebuilt as that type and nothing else.
_ACTION_TYPES: dict[str, type] = {
    cls.__name__: cls
    for cls in (*typing.get_args(MainAction), action_types.ManageCheckInsAction)
    if dataclasses.is_dataclass(cls)
}


# An action as a plain call: its type and its fields.
def call_of(action: MainAction) -> dict[str, Any]:
    return {"type": type(action).__name__, "fields": dataclasses.asdict(action)}


# The action a call names, rebuilt as the type the router produced; None
# for a call naming no action type this system has.
def action_of(call: dict[str, Any] | None) -> MainAction | None:
    if not isinstance(call, dict):
        return None
    cls = _ACTION_TYPES.get(str(call.get("type") or ""))
    fields = call.get("fields")
    if cls is None or not isinstance(fields, dict):
        return None
    if cls is ToolboxAction:
        plan = fields.get("plan")
        if not isinstance(plan, dict):
            return None
        try:
            return ToolboxAction(plan=MCPToolPlan(**plan))
        except TypeError:
            return None
    try:
        return cls(**fields)
    except TypeError:
        return None


# A decision as the boundary carries it: what kind, and for a step, the
# call plus what its contract says about it, so the run's world can key,
# grant and record the step without the action types themselves.
def decision_view(
    decision: Decision, toolbox_contract: Any | None = None
) -> dict[str, Any]:
    if isinstance(decision, Act):
        action = decision.action
        contract = contract_for_action(action, toolbox_contract)
        described = describe_action(action) or (tool_name_of(action), "")
        return {
            "kind": "act",
            "call": call_of(action),
            "tool": tool_name_of(action),
            "label": described[0],
            "detail": described[1],
            "key": action_key(action, toolbox_contract),
            "creates": action_creates(action, toolbox_contract),
            "effect": contract.effect,
            "approval": contract.approval,
        }
    if isinstance(decision, Done):
        return {"kind": "done", "reason": decision.reason}
    if isinstance(decision, NeedsInput):
        return {"kind": "needs_input", "tool": decision.tool, "missing": decision.missing}
    if isinstance(decision, Refused):
        return {"kind": "refused", "reason": decision.reason}
    if isinstance(decision, Unavailable):
        return {"kind": "unavailable", "reason": decision.reason}
    return {"kind": "unavailable", "reason": "an unreadable decision"}
