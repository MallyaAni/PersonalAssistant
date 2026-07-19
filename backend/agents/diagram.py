from typing import Any, NotRequired

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from backend.artifacts.types import DiagramSpecification
from backend.core.interfaces import DiagramProvider


class DiagramState(TypedDict):
    """Typed state passed through the focused diagram-generation graph."""

    query: str
    specification: NotRequired[DiagramSpecification]


class DiagramAgent:
    # Compile one focused graph around a replaceable diagram provider.
    def __init__(self, provider: DiagramProvider) -> None:
        self.graph = build_diagram_graph(provider)

    # Generate one validated specification through the diagram graph.
    async def generate(self, query: str) -> DiagramSpecification:
        result = await self.graph.ainvoke({"query": query})
        specification = result.get("specification")
        if not isinstance(specification, DiagramSpecification):
            raise RuntimeError("Diagram graph completed without a specification")
        return specification


# Construct the specialized diagram graph without granting it persistence authority.
def build_diagram_graph(provider: DiagramProvider) -> Any:
    # Delegate bounded source generation to the injected provider.
    async def generate_node(state: DiagramState) -> dict[str, DiagramSpecification]:
        return {"specification": await provider.generate(state["query"])}

    workflow = StateGraph(DiagramState)
    workflow.add_node("generate_diagram", generate_node)
    workflow.set_entry_point("generate_diagram")
    workflow.add_edge("generate_diagram", END)
    return workflow.compile()
