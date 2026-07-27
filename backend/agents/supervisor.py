"""Route bounded user intents to application-owned tools or subagents."""

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, StateGraph

SupervisorAction = Literal[
    "respond",
    "invoke_tool",
    "delegate_agent",
    "request_confirmation",
]

_PRESENTATION_NOUN = re.compile(
    r"\b(presentation|slide\s*deck|deck|slides?|powerpoint|pptx)\b",
    re.IGNORECASE,
)
_PRESENTATION_CREATE = re.compile(
    r"\b(create|make|build|generate|prepare|produce|draft|design|put\s+together)\b",
    re.IGNORECASE,
)


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


# Recognize an explicit request for a new editable slide presentation.
def _is_presentation_creation(query: str) -> bool:
    return bool(_PRESENTATION_NOUN.search(query) and _PRESENTATION_CREATE.search(query))


# Build the main routing graph without granting it service or storage access.
def build_supervisor_graph() -> Any:
    # Choose only application-registered capabilities using bounded policy.
    def route_node(state: SupervisorState) -> dict[str, dict[str, Any]]:
        if _is_presentation_creation(state["query"]):
            decision = SupervisorDecision(
                action="delegate_agent",
                capability_id="presentation_agent",
                reason="explicit_presentation_creation",
            )
        else:
            decision = SupervisorDecision(action="respond")
        return {"decision": asdict(decision)}

    workflow = StateGraph(SupervisorState)
    workflow.add_node("route_capability", route_node)
    workflow.set_entry_point("route_capability")
    workflow.add_edge("route_capability", END)
    return workflow.compile()


class MainSupervisorAgent:
    """Run the first typed routing step before tools or specialist agents."""

    # Compile the routing node once for reuse across conversation turns.
    def __init__(self) -> None:
        self.graph = build_supervisor_graph()

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
