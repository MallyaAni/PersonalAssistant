import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from backend.presentations.types import (
    DeckSpec,
    PresentationTheme,
    ShapeElement,
    SlideElement,
    SlideSpec,
    TextElement,
)


class DeckPlanModel(BaseModel):
    """Reject unknown compact-plan fields before deterministic compilation."""

    model_config = ConfigDict(extra="forbid")


class PlannedSlide(DeckPlanModel):
    """Concise semantic content for one slide without layout authority."""

    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=300)
    points: list[str] = Field(min_length=2, max_length=6)
    key_message: str | None = Field(default=None, max_length=240)
    notes: str = Field(default="", max_length=1_500)


class DeckPlan(DeckPlanModel):
    """Compact model output compiled into a fully editable canonical deck."""

    title: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    slides: list[PlannedSlide] = Field(min_length=1, max_length=30)


class DeckOutlineSlide(DeckPlanModel):
    """Bounded title and purpose used to schedule one slide microtask."""

    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=300)


class DeckOutline(DeckPlanModel):
    """Compact deck structure produced before individual slide content."""

    title: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    slides: list[DeckOutlineSlide] = Field(min_length=1, max_length=30)


@dataclass(frozen=True, slots=True)
class DeckDraft:
    """Progressive compiled deck snapshot plus its expected final slide count."""

    specification: DeckSpec
    expected_slide_count: int


# Read an explicitly requested numeric slide count without interpreting other numbers.
def requested_slide_count(prompt: str) -> int | None:
    match = re.search(r"\b([1-9]|[12]\d|30)\s*[- ]*slides?\b", prompt, re.IGNORECASE)
    return int(match.group(1)) if match else None


# The default deck theme, applied to a whole deck and to any single rerendered slide.
def default_theme() -> PresentationTheme:
    return PresentationTheme(
        font_face="Aptos",
        background_color="F5F5F7",
        primary_color="0071E3",
        text_color="1D1D1F",
        muted_color="6E6E73",
    )


# Compile one concise model slide into deterministic native editable objects. Used
# both for a full deck and to rerender a single slide during a revision, so the two
# paths always produce identical layout and element ids.
def compile_slide(
    planned: PlannedSlide, slide_id: str, theme: PresentationTheme
) -> SlideSpec:
    elements: list[SlideElement] = [
        TextElement(
            element_id=f"{slide_id}_title",
            text=planned.title,
            x=0.75,
            y=0.45,
            w=11.8,
            h=0.65,
            font_size=30,
            bold=True,
            color=theme.text_color,
        ),
        TextElement(
            element_id=f"{slide_id}_purpose",
            text=planned.purpose,
            x=0.8,
            y=1.15,
            w=11.4,
            h=0.4,
            font_size=14,
            color=theme.muted_color,
        ),
        ShapeElement(
            element_id=f"{slide_id}_accent",
            shape="roundRect",
            x=0.75,
            y=1.67,
            w=0.12,
            h=min(4.85, max(1.0, len(planned.points) * 0.82)),
            fill_color=theme.primary_color,
            line_color=theme.primary_color,
            line_width=0,
        ),
    ]
    for point_index, point in enumerate(planned.points, start=1):
        point_y = 1.68 + ((point_index - 1) * 0.82)
        elements.extend(
            [
                ShapeElement(
                    element_id=f"{slide_id}_marker_{point_index:02d}",
                    shape="ellipse",
                    x=1.08,
                    y=point_y + 0.18,
                    w=0.16,
                    h=0.16,
                    fill_color=theme.primary_color,
                    line_color=theme.primary_color,
                    line_width=0,
                ),
                TextElement(
                    element_id=f"{slide_id}_point_{point_index:02d}",
                    text=point,
                    x=1.42,
                    y=point_y,
                    w=10.55,
                    h=0.62,
                    font_size=18,
                    color=theme.text_color,
                    valign="mid",
                ),
            ]
        )
    if planned.key_message:
        elements.append(
            TextElement(
                element_id=f"{slide_id}_key_message",
                text=planned.key_message,
                x=0.95,
                y=6.55,
                w=11.35,
                h=0.45,
                font_size=15,
                bold=True,
                color=theme.primary_color,
                align="center",
                valign="mid",
            )
        )
    return SlideSpec(
        slide_id=slide_id,
        title=planned.title,
        purpose=planned.purpose,
        notes=planned.notes,
        elements=elements,
    )


# Compile concise model-owned content into deterministic native editable slides.
def compile_deck_plan(plan: DeckPlan) -> DeckSpec:
    theme = default_theme()
    slides = [
        compile_slide(planned, f"slide_{slide_index:03d}", theme)
        for slide_index, planned in enumerate(plan.slides, start=1)
    ]
    return DeckSpec(
        title=plan.title,
        subtitle=plan.subtitle,
        theme=theme,
        slides=slides,
    )
