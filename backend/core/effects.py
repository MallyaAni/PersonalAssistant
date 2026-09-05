"""What every tool does to the world, declared once and read by policy.

Until now the loop knew three things about a tool, each written in a
different place: which tools a later step may see (`AUTOMATION_TOOLS`, a set
of names in the registry), which ones "create" something (a lambda in
`ConversationService`), and whether an MCP call may be retried (a server's
trust classification, which is not the same question). Every one of those
was a real safety rule, and every one was a special case that another agent
would have had to rediscover.

An `EffectContract` says the whole thing on the tool's own row:

  * `effect`   - what the call does to the world. A `read` can be repeated
                 freely; a `write` changes this system's own records; `send`
                 puts words in front of another person; `spend` consumes a
                 budget that does not come back; `mutate_external` changes
                 something outside this system.
  * `cost`     - how long it takes. A later step in a bounded loop may start
                 a `fast` call, a `slow` one with time in hand, and never an
                 `expensive` one - a ninety-second image render is the turn's
                 own request or it is nothing.
  * `idempotency` - the natural key of a call, read off the action, so two
                 reminders with different words are two effects and the same
                 reminder twice is one. None means the tool has no such key
                 and a repeat is judged on the action's whole shape.
  * `creates`  - whether a successful call makes a new thing, so the loop can
                 hold a turn to its creation allowance.
  * `reversible` - the receipt kind a call writes, so "undo that" can find it.
  * `approval` - whether a person must say yes first: never, for anything
                 consequential (a trusted server's writes), or always.
  * `retry`    - whether a dropped call may be replayed. Derived from the
                 effect unless declared, and a declaration can only make it
                 safer: nothing but a read or a keyed call is ever replayed.

The contract replaces the automation allowlist as the rule for later steps,
the trust-equals-replay-safe rule for MCP retries, the creation lambda, and
the repr-based repeat guard. It does not replace the unattended rule: a
scheduled firing is still offered no tool that changes what is scheduled or
taught, because nobody is there to notice.

It lives in `core` rather than beside the tool rows because the MCP
invocation service reads it too, and `backend.tools` imports the services
layer through `actions.py`; `backend.tools.contracts` re-exports it for the
rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Effect = Literal["read", "write", "send", "spend", "mutate_external"]
Cost = Literal["fast", "slow", "expensive"]
Approval = Literal["never", "consequential", "always"]
Retry = Literal["replay_safe", "once", "never"]

EFFECTS: frozenset[str] = frozenset(
    {"read", "write", "send", "spend", "mutate_external"}
)
COSTS: frozenset[str] = frozenset({"fast", "slow", "expensive"})
APPROVALS: tuple[str, ...] = ("never", "consequential", "always")
RETRIES: frozenset[str] = frozenset({"replay_safe", "once", "never"})

# Effects a later step in a bounded loop may carry out on its own. A send, a
# spend or an external mutation is the turn's own request or nothing: a
# second decision, made on the model's reading of what is "still needed",
# must not be able to message somebody or spend a budget.
LATER_STEP_EFFECTS: frozenset[str] = frozenset({"read", "write"})

# How much of the budget a slow step needs left before it is offered.
SLOW_STEP_NEEDS_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class EffectContract:
    """What one tool does to the world, and so what may be done with it."""

    effect: str = "write"
    # Expensive by default: a tool that has not said how long it takes is
    # not offered to a later step. Fail closed, then declare.
    cost: str = "expensive"
    idempotency: Callable[[Any], str | None] | None = None
    # Whether a successful call makes a new thing. A bool for a tool that
    # always or never does; a judgement of the action for one whose
    # operations differ (arming a check-in creates, listing them does not).
    creates: bool | Callable[[Any], bool] = False
    reversible: str = ""
    approval: str = "never"
    retry: str | None = None

    # Reject a contract that names a value policy does not know, so a typo
    # fails at import rather than reading as "never" or "fast" somewhere.
    def __post_init__(self) -> None:
        if self.effect not in EFFECTS:
            raise ValueError(f"unknown effect {self.effect!r}")
        if self.cost not in COSTS:
            raise ValueError(f"unknown cost {self.cost!r}")
        if self.approval not in APPROVALS:
            raise ValueError(f"unknown approval {self.approval!r}")
        if self.retry is not None and self.retry not in RETRIES:
            raise ValueError(f"unknown retry {self.retry!r}")

    # Whether a dropped call may be replayed. A declaration is honoured only
    # when it is safe: a read can always be replayed, a keyed call can be
    # reconciled by its key, and nothing else is ever replayed however the
    # server describes itself. Undeclared, a read replays and the rest do not.
    @property
    def retry_policy(self) -> str:
        if self.retry == "replay_safe":
            if self.effect == "read" or self.idempotency is not None:
                return "replay_safe"
            return "never"
        if self.retry is not None:
            return self.retry
        return "replay_safe" if self.effect == "read" else "never"

    # Whether this particular call would make a new thing.
    def is_creation(self, action: Any) -> bool:
        if callable(self.creates):
            return bool(self.creates(action))
        return bool(self.creates)

    # The natural key of one call, or None when the tool declares none.
    def key(self, action: Any) -> str | None:
        if self.idempotency is None:
            return None
        found = self.idempotency(action)
        return str(found) if found else None

    # Whether a later step in a bounded loop may start this tool with the
    # time it has left. A tool needing approval is never a later step: the
    # person is asked about the turn's own request, not about what the
    # model decided it still needed.
    def allows_later_step(self, remaining_seconds: float) -> bool:
        if self.approval != "never":
            return False
        if self.effect not in LATER_STEP_EFFECTS:
            return False
        if self.cost == "expensive":
            return False
        if self.cost == "slow":
            return remaining_seconds >= SLOW_STEP_NEEDS_SECONDS
        return True


# The most conservative contract for a tool that declared nothing.
UNDECLARED = EffectContract()


# The contract an MCP server's classification implies for a tool that has
# no contract of its own. Trust is not idempotency: a trusted server's call
# changes something outside this system, a dropped response does not prove
# it did not happen, and a later step in a turn may not start one. It may be
# called without asking, which is what trust means here and all it means;
# the operator declares a tool a `read` (or a `write` to this system's own
# records) to make it more than that.
def contract_for_classification(risk_classification: str) -> EffectContract:
    if risk_classification == "read_only":
        return EffectContract(effect="read", cost="slow")
    if risk_classification == "trusted":
        return EffectContract(effect="mutate_external", cost="slow", retry="never")
    return EffectContract(
        effect="mutate_external", cost="slow", approval="consequential", retry="never"
    )


# A declared per-tool contract, held to what its server's classification
# permits: an effect may be stated, an approval may only be raised, and a
# replay is allowed only where the contract itself makes it safe.
def narrow(server_default: EffectContract, declared: EffectContract) -> EffectContract:
    approval = max(
        (server_default.approval, declared.approval), key=APPROVALS.index
    )
    return EffectContract(
        effect=declared.effect,
        cost=declared.cost,
        idempotency=declared.idempotency,
        creates=declared.creates,
        reversible=declared.reversible,
        approval=approval,
        retry=declared.retry,
    )
