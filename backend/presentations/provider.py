import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel

from backend.agents.deck.prompts import (
    NEW_SLIDE_PREAMBLE,
    PLANNING_PREAMBLE,
    REVISION_PREAMBLE,
    _deck_outline_contract,
    _deck_plan_contract,
    _slide_content_contract,
    slide_content_preamble,
)
from backend.core.llm import LLMClient
from backend.core.model_gate import ModelExecutionGate
from backend.presentations.editing import SlideEdit
from backend.presentations.planner import (
    DeckDraft,
    DeckOutline,
    DeckPlan,
    PlannedSlide,
    compile_deck_plan,
    compile_slide,
    requested_slide_count,
)
from backend.presentations.research import DeckResearch, DeckSource, render_sources
from backend.presentations.types import (
    ChartElement,
    DeckSpec,
    ImageElement,
    SlideSpec,
    TableElement,
    TextElement,
)


class PresentationProvider(ABC):
    """Planning boundary implemented by the configured presentation model."""

    # Produce one complete bounded deck specification from a user brief.
    @abstractmethod
    async def create(self, prompt: str) -> DeckSpec: ...

    # Yield at least one compiled draft while retaining a buffered-provider fallback.
    async def create_progress(self, prompt: str) -> AsyncIterator[DeckDraft]:
        specification = await self.create(prompt)
        yield DeckDraft(specification, len(specification.slides))

    # Replace only the selected slide in response to focused user feedback.
    @abstractmethod
    async def revise_slide(
        self,
        deck: DeckSpec,
        slide_id: str,
        feedback: str,
    ) -> SlideSpec: ...

    # Plan one additional slide without rewriting the slides already accepted.
    @abstractmethod
    async def add_slide(
        self,
        deck: DeckSpec,
        brief: str,
        slide_id: str,
        after_slide_id: str | None = None,
    ) -> SlideSpec: ...


# Extract the first complete JSON object without evaluating model output.
def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Presentation provider did not return a JSON object")
    parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Presentation provider JSON must be an object")
    return parsed


# Describe the compact content grammar compiled by deterministic application code.
# Derive the decoding grammar from the same model that validates the reply, so a
# contract change cannot drift from what the runtime is allowed to emit.
def _response_schema(
    response_type: type[BaseModel],
    expected_slide_count: int | None = None,
    required_layout: str | None = None,
) -> dict[str, Any]:
    schema = response_type.model_json_schema()
    slides = schema.get("properties", {}).get("slides")
    # An exact requested count is a bound the grammar can enforce directly
    # instead of validating and re-prompting after generation.
    if expected_slide_count is not None and isinstance(slides, dict):
        slides["minItems"] = expected_slide_count
        slides["maxItems"] = expected_slide_count
    if required_layout is not None:
        _require_layout_fields(schema, required_layout)
    return schema


# Fields each layout cannot render without.
_LAYOUT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "statistic": ("statistic_value", "statistic_label"),
    "quote": ("quote", "quote_attribution"),
    "comparison": ("comparison_left_heading", "comparison_right_heading"),
    "chart": ("chart_kind", "chart_categories", "chart_series"),
    "table": ("table_headers", "table_rows"),
}


# Pin the slide to one layout and make that layout's fields mandatory in the
# grammar. Naming the fields in prose was not enough: asked for a chart slide,
# the model returned layout "chart" with no categories and no series, and the
# compiler correctly degraded it to bullets. Requiring them in the schema means
# a chart slide without chart data is not a decodable reply.
def _require_layout_fields(schema: dict[str, Any], layout: str) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    if isinstance(properties.get("layout"), dict):
        properties["layout"] = {"const": layout}
    required = list(schema.get("required", []))
    for field in _LAYOUT_REQUIREMENTS.get(layout, ()):
        target = properties.get(field)
        # These fields are optional and therefore nullable. A required-but-
        # nullable field is still satisfied by null, so the null branch goes.
        if isinstance(target, dict) and "anyOf" in target:
            concrete = [
                option for option in target["anyOf"] if option.get("type") != "null"
            ]
            if concrete:
                target.pop("anyOf")
                target.pop("default", None)
                target.update(concrete[0])
        if field not in required:
            required.append(field)
    schema["required"] = required


def _slide_content_view(slide: SlideSpec, layout: str | None = None) -> dict[str, Any]:
    points = [
        element.text
        for element in slide.elements
        if isinstance(element, TextElement) and "_point_" in element.element_id
    ]
    key_message = next(
        (
            element.text
            for element in slide.elements
            if isinstance(element, TextElement)
            and element.element_id.endswith("_key_message")
        ),
        None,
    )
    return {
        "title": slide.title,
        "purpose": slide.purpose,
        "points": points,
        "key_message": key_message,
        # A revision recompiles the slide from this view, so it has to say what
        # shape the slide currently is. Without it the model defaulted to
        # bullets and an edit to a chart silently deleted the chart.
        "layout": layout or _detect_layout(slide),
        **_data_view(slide),
        "visual_prompt": slide.visual_prompt,
        "visual_priority": slide.visual_priority,
        "notes": slide.notes,
    }


# Recover the layout from what the compiler produced. The compiled slide stores
# native objects rather than the plan that made them, so the shape is read back
# from the elements instead of being carried alongside them.
def _detect_layout(slide: SlideSpec) -> str:
    ids = {element.element_id.split("_", 2)[-1] for element in slide.elements}
    if any(isinstance(element, ChartElement) for element in slide.elements):
        return "chart"
    if any(isinstance(element, TableElement) for element in slide.elements):
        return "table"
    if "stat_value" in ids:
        return "statistic"
    if "quote" in ids:
        return "quote"
    if any(name.startswith("column_") for name in ids):
        return "comparison"
    if "rule" in ids:
        return "section"
    return "bullets"


# Return the chart or table already on the slide so a revision can edit its data
# rather than having to invent it again from the title alone.
def _data_view(slide: SlideSpec) -> dict[str, Any]:
    for element in slide.elements:
        if isinstance(element, ChartElement):
            return {
                "chart_kind": element.chart_type,
                "chart_categories": list(element.categories),
                "chart_series": [
                    {"name": series.name, "values": list(series.values)}
                    for series in element.series
                ],
            }
        if isinstance(element, TableElement):
            return {
                "table_headers": list(element.headers),
                "table_rows": [list(row) for row in element.rows],
            }
    return {}


# Decide which shape a revision must produce. Telling the model in prose to keep
# the slide's layout did not work: asked to change a chart's data it returned a
# layout with no chart data, which the compiler degraded to bullets, silently
# deleting the chart. So the layout is pinned in the grammar instead. The
# feedback may still ask for a different shape by naming one, which is what lets
# "remove the chart and use bullets" actually remove it.
_LAYOUT_WORDS: tuple[tuple[str, str], ...] = (
    ("bullet", "bullets"),
    ("chart", "chart"),
    ("graph", "chart"),
    ("table", "table"),
    ("quote", "quote"),
    ("comparison", "comparison"),
    ("compare", "comparison"),
    ("section", "section"),
    ("statistic", "statistic"),
)


def _requested_layout(feedback: str) -> str | None:
    lowered = feedback.lower()
    matches = {layout for word, layout in _LAYOUT_WORDS if word in lowered}
    # Only act on an unambiguous request; "turn the chart into a table" names
    # two shapes and is left to the model with the current one pinned.
    return matches.pop() if len(matches) == 1 else None


class LLMPresentationProvider(PresentationProvider):
    """Ask the configured local model for typed plans without file authority."""

    # Keep the configured model and output budget replaceable at assembly time.
    def __init__(
        self,
        llm: LLMClient,
        max_tokens: int,
        plan_max_tokens: int = 2_048,
        revision_max_tokens: int = 1_024,
        model_gate: ModelExecutionGate | None = None,
        background: bool = False,
        research: DeckResearch | None = None,
    ) -> None:
        self.llm = llm
        self.max_tokens = max_tokens
        self.plan_max_tokens = plan_max_tokens
        self.revision_max_tokens = revision_max_tokens
        self.model_gate = model_gate
        self.background = background
        # Absent, the deck is planned from the model's recollection alone, which
        # is what produced invented statistics. The contract still forbids
        # unsupported figures, so an ungrounded deck degrades to plainer slides
        # rather than to confident wrong ones.
        self.research = research

    # Gather bounded public sources once per deck, before any layout is chosen.
    async def _sources(self, prompt: str) -> tuple[DeckSource, ...]:
        if self.research is None:
            return ()
        return await self.research.gather(prompt)

    # Generate and validate a complete deck, retrying one invalid format once.
    async def create(self, prompt: str) -> DeckSpec:
        expected_slides = requested_slide_count(prompt)
        count_instruction = (
            f" Produce exactly {expected_slides} slides."
            if expected_slides is not None
            else ""
        )
        sources = await self._sources(prompt)
        messages = [
            {
                "role": "system",
                "content": (
                    PLANNING_PREAMBLE
                    + _deck_plan_contract()
                    + count_instruction
                    + "\n\n"
                    + render_sources(sources)
                ),
            },
            {"role": "user", "content": prompt},
        ]
        plan = await self._validated_reply(
            messages,
            DeckPlan,
            max_tokens=self.plan_max_tokens,
            expected_slide_count=expected_slides,
        )
        if not isinstance(plan, DeckPlan):
            raise TypeError("Presentation provider returned the wrong plan")
        return compile_deck_plan(plan)

    # Plan an outline, then yield after each independently scheduled slide call.
    async def create_progress(self, prompt: str) -> AsyncIterator[DeckDraft]:
        expected_slides = requested_slide_count(prompt)
        # One search per deck, before the outline, because the outline is where
        # layouts are chosen: a slide is told to carry a statistic there, and by
        # the time the slide pass runs the only way to satisfy that is to invent
        # one. The same sources are then repeated into every slide call.
        sources = await self._sources(prompt)
        rendered_sources = render_sources(sources)
        outline_messages = [
            {
                "role": "system",
                "content": (
                    PLANNING_PREAMBLE
                    + _deck_outline_contract(expected_slides)
                    + "\n\n"
                    + rendered_sources
                ),
            },
            {"role": "user", "content": prompt},
        ]
        outline = await self._validated_reply(
            outline_messages,
            DeckOutline,
            max_tokens=min(self.plan_max_tokens, 1_024),
            expected_slide_count=expected_slides,
        )
        if not isinstance(outline, DeckOutline):
            raise TypeError("Presentation provider returned the wrong outline")
        planned_slides: list[PlannedSlide] = []
        for index, outlined_slide in enumerate(outline.slides, start=1):
            slide_messages = [
                {
                    "role": "system",
                    "content": (
                        slide_content_preamble(
                            index, len(outline.slides), outline.title
                        )
                        + rendered_sources
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "brief": prompt,
                            "narrative": outline.narrative,
                            "through_line": outline.through_line,
                            # What came before, so this slide follows rather
                            # than restates. Titles and beats only: sending the
                            # earlier content would grow every later request.
                            "already_covered": [
                                {"title": earlier.title, "beat": earlier.beat}
                                for earlier in outline.slides[: index - 1]
                            ],
                            "slide": outlined_slide.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            planned = await self._validated_reply(
                slide_messages,
                PlannedSlide,
                max_tokens=self.revision_max_tokens,
                required_layout=outlined_slide.layout,
            )
            if not isinstance(planned, PlannedSlide):
                raise TypeError("Presentation provider returned the wrong slide")
            planned_slides.append(
                planned.model_copy(
                    update={
                        "title": outlined_slide.title,
                        "purpose": outlined_slide.purpose,
                        # The outline owns the deck's shape because it chose
                        # with every slide in view. If the slide pass did not
                        # supply what that layout needs, compilation degrades it
                        # to bullets rather than rendering an empty panel.
                        "layout": outlined_slide.layout,
                    }
                )
            )
            specification = compile_deck_plan(
                DeckPlan(
                    title=outline.title,
                    subtitle=outline.subtitle,
                    slides=planned_slides,
                )
            )
            yield DeckDraft(specification, len(outline.slides))

    # Ask for one replacement slide while preserving its stable slide identifier.
    # Plan one additional slide that fits an existing deck.
    async def add_slide(
        self,
        deck: DeckSpec,
        brief: str,
        slide_id: str,
        after_slide_id: str | None = None,
    ) -> SlideSpec:
        # The model sees the deck's shape but writes only the new slide, so an
        # addition can never rewrite the slides the user already accepted.
        messages = [
            {
                "role": "system",
                "content": (NEW_SLIDE_PREAMBLE + _slide_content_contract()),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "deck_title": deck.title,
                        "existing_slides": [
                            {"title": slide.title, "purpose": slide.purpose}
                            for slide in deck.slides
                        ],
                        "insert_after": after_slide_id or "end",
                        "request": brief,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        planned = await self._validated_reply(
            messages,
            PlannedSlide,
            max_tokens=self.revision_max_tokens,
        )
        if not isinstance(planned, PlannedSlide):
            raise TypeError("Presentation provider returned the wrong slide content")
        return compile_slide(planned, slide_id, deck.theme)

    async def revise_slide(
        self,
        deck: DeckSpec,
        slide_id: str,
        feedback: str,
    ) -> SlideSpec:
        selected = next(
            (slide for slide in deck.slides if slide.slide_id == slide_id),
            None,
        )
        if selected is None:
            raise ValueError("Selected slide was not found")
        # Regenerate the slide's semantic content and recompile it, rather than
        # asking the model for an element-id diff. A local model reliably rewrites
        # concise content but struggles to reference internal ids, which was making
        # the revision fail; layout stays deterministic and application-owned.
        layout = _requested_layout(feedback) or _detect_layout(selected)
        messages = [
            {
                "role": "system",
                "content": (REVISION_PREAMBLE + _slide_content_contract()),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "deck_title": deck.title,
                        "current_slide": _slide_content_view(selected, layout),
                        "feedback": feedback,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        planned = await self._validated_reply(
            messages,
            PlannedSlide,
            max_tokens=self.revision_max_tokens,
            required_layout=layout,
        )
        if not isinstance(planned, PlannedSlide):
            raise TypeError("Presentation provider returned the wrong slide content")
        revised = compile_slide(planned, slide_id, deck.theme)
        # Charts and tables are compiled from the plan, so the new plan owns
        # them: carrying the old one over would both duplicate a regenerated
        # chart and make "remove the table" impossible to honour. Only the
        # attached image survives a revision, because nothing regenerates it.
        preserved = [
            element
            for element in selected.elements
            if isinstance(element, ImageElement)
        ]
        if preserved:
            revised = revised.model_copy(
                update={"elements": [*revised.elements, *preserved]}
            )
        return revised

    # Validate model JSON and give one bounded correction opportunity.
    async def _validated_reply(
        self,
        messages: list[dict[str, str]],
        response_type: (
            type[DeckOutline] | type[DeckPlan] | type[SlideEdit] | type[PlannedSlide]
        ),
        max_tokens: int | None = None,
        expected_slide_count: int | None = None,
        response_validator: (
            Callable[
                [DeckOutline | DeckPlan | SlideEdit | PlannedSlide],
                object,
            ]
            | None
        ) = None,
        required_layout: str | None = None,
    ) -> DeckOutline | DeckPlan | SlideEdit | PlannedSlide:
        schema = _response_schema(response_type, expected_slide_count, required_layout)
        for attempt in range(2):
            if self.model_gate is not None and self.background:
                async with self.model_gate.background():
                    result = await asyncio.to_thread(
                        self.llm.chat,
                        messages,
                        max_tokens or self.max_tokens,
                        schema,
                    )
            else:
                result = await asyncio.to_thread(
                    self.llm.chat,
                    messages,
                    max_tokens or self.max_tokens,
                    schema,
                )
            content = result.get("content")
            try:
                if not isinstance(content, str):
                    raise ValueError("Presentation provider did not return text")
                specification = response_type.model_validate(
                    _extract_json_object(content)
                )
                if (
                    isinstance(specification, (DeckOutline, DeckPlan))
                    and expected_slide_count is not None
                    and len(specification.slides) != expected_slide_count
                ):
                    raise ValueError(
                        f"Expected exactly {expected_slide_count} slides, received "
                        f"{len(specification.slides)}"
                    )
                if response_validator is not None:
                    response_validator(specification)
                return specification
            except (ValueError, json.JSONDecodeError) as exc:
                if attempt == 1:
                    raise ValueError(
                        "Presentation provider did not return a valid specification"
                    ) from exc
                messages[0]["content"] += (
                    " Your prior JSON failed validation for this reason: "
                    f"{str(exc)[:2_000]}. Return one corrected JSON object only, "
                    "with every required field and no Markdown. Use only the exact "
                    "field names in the contract and never prefix one with optional_."
                )
        raise AssertionError("Presentation validation retry did not terminate")
