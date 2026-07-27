from collections.abc import AsyncIterator
from typing import Any, NotRequired

from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from backend.presentations.planner import DeckDraft
from backend.presentations.provider import PresentationProvider
from backend.presentations.types import DeckSpec, SlideSpec


class PresentationState(TypedDict):
    """Typed state for one focused presentation planning operation."""

    operation: str
    prompt: NotRequired[str]
    deck: NotRequired[DeckSpec]
    slide_id: NotRequired[str]
    feedback: NotRequired[str]
    specification: NotRequired[DeckSpec]
    slide: NotRequired[SlideSpec]


class PresentationAgent:
    """Focused LangGraph subagent with planning authority but no persistence."""

    # Compile one small graph around a replaceable presentation provider.
    def __init__(self, provider: PresentationProvider) -> None:
        self.provider = provider
        self.graph = build_presentation_graph(provider)

    # Plan one complete typed deck from a bounded user brief.
    async def create(self, prompt: str) -> DeckSpec:
        result = await self.graph.ainvoke({"operation": "create", "prompt": prompt})
        specification = result.get("specification")
        if not isinstance(specification, DeckSpec):
            raise RuntimeError("Presentation graph completed without a deck")
        return specification

    # Stream compiled drafts from the presentation graph's planning node.
    async def create_progress(self, prompt: str) -> AsyncIterator[DeckDraft]:
        async for draft in self.graph.astream(
            {"operation": "create_progress", "prompt": prompt},
            stream_mode="custom",
        ):
            if not isinstance(draft, DeckDraft):
                raise RuntimeError("Presentation graph emitted an invalid draft")
            yield draft

    # Plan one slide replacement without receiving storage or file access.
    async def revise_slide(
        self,
        deck: DeckSpec,
        slide_id: str,
        feedback: str,
    ) -> SlideSpec:
        result = await self.graph.ainvoke(
            {
                "operation": "revise_slide",
                "deck": deck,
                "slide_id": slide_id,
                "feedback": feedback,
            }
        )
        slide = result.get("slide")
        if not isinstance(slide, SlideSpec):
            raise RuntimeError("Presentation graph completed without a slide")
        return slide


# Build a specialized create-or-revise graph around the injected provider.
def build_presentation_graph(provider: PresentationProvider) -> Any:
    # Produce the typed result for the requested presentation operation.
    async def plan_node(state: PresentationState) -> dict[str, DeckSpec | SlideSpec]:
        if state["operation"] == "create":
            return {"specification": await provider.create(state["prompt"])}
        if state["operation"] == "create_progress":
            writer = get_stream_writer()
            specification: DeckSpec | None = None
            async for draft in provider.create_progress(state["prompt"]):
                specification = draft.specification
                writer(draft)
            if specification is None:
                raise ValueError("Presentation provider returned no slides")
            return {"specification": specification}
        if state["operation"] == "revise_slide":
            return {
                "slide": await provider.revise_slide(
                    state["deck"],
                    state["slide_id"],
                    state["feedback"],
                )
            }
        raise ValueError("Unsupported presentation operation")

    workflow = StateGraph(PresentationState)
    workflow.add_node("plan_presentation", plan_node)
    workflow.set_entry_point("plan_presentation")
    workflow.add_edge("plan_presentation", END)
    return workflow.compile()
