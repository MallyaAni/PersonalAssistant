"""Which specialist an intent belongs to, as data rather than a chain of ifs.

The supervisor previously had one hardcoded check. Every new specialist would
have added another branch, and the routing rules would have lived inside the
graph node that uses them — where they cannot be listed, tested in isolation, or
reasoned about as a set.

Three properties this exists to hold:

- **deterministic.** Routing runs on every turn, so a sampled judgement would
  make the same sentence reach different agents on different days. Matching is
  pattern-based and the decision is reproducible;
- **ordered and explicit.** When two policies match, the more specific one wins
  by declared priority rather than by which `if` was written first;
- **listable.** A registry can be enumerated, which is what lets the Agents tab
  and the tests describe the system instead of guessing at it.

A policy names a capability. It grants nothing: the caller still resolves that
capability against what is actually registered and permitted.
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DelegationPolicy:
    """One rule mapping an explicit intent to one specialist capability."""

    # Stable identifier, used in traces and tests rather than the display name.
    id: str
    capability_id: str
    reason: str
    # Every pattern must match. Splitting "what" from "do what with it" is what
    # keeps "show me the deck" from being read as "build me a deck".
    required: tuple[re.Pattern[str], ...]
    # Any match here blocks the policy, however well the rest fits.
    excluded: tuple[re.Pattern[str], ...] = field(default=())
    # Higher wins when several policies match one query.
    priority: int = 0

    def matches(self, query: str) -> bool:
        if any(pattern.search(query) for pattern in self.excluded):
            return False
        return all(pattern.search(query) for pattern in self.required)


def _pattern(source: str) -> re.Pattern[str]:
    return re.compile(source, re.IGNORECASE)


_CREATE_VERB = _pattern(
    r"\b(create|make|build|generate|prepare|produce|draft|design|put\s+together)\b"
)

PRESENTATION_POLICY = DelegationPolicy(
    id="presentation_creation",
    capability_id="presentation_agent",
    reason="explicit_presentation_creation",
    required=(
        _pattern(r"\b(presentation|slide\s*deck|deck|slides?|powerpoint|pptx)\b"),
        _CREATE_VERB,
    ),
    priority=10,
)

# Discovery is configured rather than invoked, so this routes the setup
# conversation to the agent that owns it instead of answering from chat. It
# deliberately does not match "what's on this weekend": that is a question, and
# answering it is the assistant's job, not a delegation.
DISCOVERY_POLICY = DelegationPolicy(
    id="discovery_configuration",
    capability_id="discovery_agent",
    reason="explicit_discovery_configuration",
    required=(
        _pattern(
            r"\b(discovery|ambient|scout|weekly\s+digest|events?\s+feed|"
            r"calendar\s+feed)\b"
        ),
        _pattern(
            r"\b(set\s*up|setup|configure|schedule|subscribe|enable|turn\s+on|"
            r"add\s+a?\s*feed|watch)\b"
        ),
    ),
    priority=10,
)

# Ordered most specific first for readability; selection uses priority, so the
# order here is presentation rather than policy.
DEFAULT_POLICIES: tuple[DelegationPolicy, ...] = (
    PRESENTATION_POLICY,
    DISCOVERY_POLICY,
)


class DelegationRegistry:
    """Hold the delegation policies and choose at most one."""

    def __init__(
        self, policies: tuple[DelegationPolicy, ...] = DEFAULT_POLICIES
    ) -> None:
        duplicates = {policy.id for policy in policies}
        if len(duplicates) != len(policies):
            raise ValueError("Delegation policy identifiers must be unique.")
        self.policies = policies

    # The single best match, or None to let the ordinary assistant answer.
    # Ties break on declared priority and then on identifier, so the outcome is
    # stable rather than dependent on registration order.
    def select(self, query: str) -> DelegationPolicy | None:
        matched = [policy for policy in self.policies if policy.matches(query)]
        if not matched:
            return None
        matched.sort(key=lambda policy: (-policy.priority, policy.id))
        return matched[0]

    def describe(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "id": policy.id,
                "capability_id": policy.capability_id,
                "priority": policy.priority,
            }
            for policy in self.policies
        )
