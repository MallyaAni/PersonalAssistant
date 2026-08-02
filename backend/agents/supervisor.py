"""Route bounded user intents to application-owned tools or subagents."""

from dataclasses import asdict, dataclass
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from backend.agents.delegation import DEFAULT_POLICIES, DelegationRegistry

SupervisorAction = Literal[
    "respond",
    "invoke_tool",
    "delegate_agent",
    "request_confirmation",
]


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    """A typed routing decision that carries no execution authority."""

    action: SupervisorAction
    capability_id: str | None = None
    reason: str = "direct_response"


class SupervisorState(TypedDict):
    """Bounded state for the main orchestration graph's routing node."""

    query: str
    decision: NotRequired[dict[str, Any]]


# Build the main routing graph without granting it service or storage access.
# The registry is a parameter so a caller can route against a different policy
# set without reaching into this module.
def build_supervisor_graph(registry: DelegationRegistry | None = None) -> Any:
    policies = registry or DelegationRegistry(DEFAULT_POLICIES)

    # Choose only application-registered capabilities using bounded policy. The
    # decision carries a capability name and no authority to run it; the caller
    # still resolves that name against what is actually registered.
    def route_node(state: SupervisorState) -> dict[str, dict[str, Any]]:
        matched = policies.select(state["query"])
        if matched is None:
            decision = SupervisorDecision(action="respond")
        else:
            decision = SupervisorDecision(
                action="delegate_agent",
                capability_id=matched.capability_id,
                reason=matched.reason,
            )
        return {"decision": asdict(decision)}

    workflow = StateGraph(SupervisorState)
    workflow.add_node("route_capability", route_node)
    workflow.set_entry_point("route_capability")
    workflow.add_edge("route_capability", END)
    return workflow.compile()


class MainSupervisorAgent:
    """Run the first typed routing step before tools or specialist agents."""

    # Compile the routing node once for reuse across conversation turns.
    def __init__(self, registry: DelegationRegistry | None = None) -> None:
        self.registry = registry or DelegationRegistry(DEFAULT_POLICIES)
        self.graph = build_supervisor_graph(self.registry)

    # Return one validated decision for the current user request.
    async def decide(self, query: str) -> SupervisorDecision:
        result = await self.graph.ainvoke({"query": query})
        decision = result.get("decision")
        if not isinstance(decision, dict):
            raise RuntimeError("Supervisor graph completed without a decision")
        return SupervisorDecision(
            action=decision.get("action", "respond"),
            capability_id=decision.get("capability_id"),
            reason=str(decision.get("reason") or "direct_response"),
        )
