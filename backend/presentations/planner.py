import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.presentations.layout import (
    fit_font_size,
    fit_stack_font_size,
    required_height,
)
from backend.presentations.types import (
    DeckSpec,
    PresentationTheme,
    ShapeElement,
    SlideElement,
    SlideSpec,
    TextElement,
)

# Slide geometry, in inches on the 13.333x7.5 canvas. Heights are computed from
# the text rather than fixed, so a long title or a sixth bullet reflows instead
# of overflowing its box.
_TITLE_TOP = 0.45
_HEAD_WIDTH = 11.8
_TITLE_FONT = 30
_TITLE_FONT_MIN = 22
_TITLE_MAX_HEIGHT = 1.15
_PURPOSE_FONT = 14
_PURPOSE_MAX_HEIGHT = 0.62
_POINT_FONT = 18
_POINT_FONT_MIN = 12
_POINT_GAP = 0.14
_BODY_WIDTH = 10.55
# The generated image occupies x=8.45 onward, so a slide expecting one keeps its
# text clear of that column.
_BODY_WIDTH_WITH_IMAGE = 6.75
_KEY_MESSAGE_TOP = 6.55
_KEY_MESSAGE_HEIGHT = 0.5
_CONTENT_FLOOR = 7.05
_MIN_CONTENT_HEIGHT = 1.0


class DeckPlanModel(BaseModel):
    """Reject unknown compact-plan fields before deterministic compilation."""

    model_config = ConfigDict(extra="forbid")


class PlannedSlide(DeckPlanModel):
    """Concise semantic content for one slide without layout authority."""

    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=300)
    points: list[str] = Field(min_length=2, max_length=6)
    key_message: str | None = Field(default=None, max_length=240)
    visual_prompt: str | None = Field(default=None, max_length=500)
    visual_priority: int = Field(default=0, ge=0, le=3)
    notes: str = Field(default="", max_length=1_500)

    # Canonicalize an explicit null optional note to the same empty value as omission.
    @field_validator("notes", mode="before")
    @classmethod
    def normalize_optional_notes(cls, value: object) -> object:
        return "" if value is None else value


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
    # A slide whose imagery is worth generating gets a reserved right column, so
    # bullets never run underneath the picture that arrives later.
    reserves_image = planned.visual_priority >= 1 and bool(planned.visual_prompt)
    body_width = _BODY_WIDTH_WITH_IMAGE if reserves_image else _BODY_WIDTH

    title_size = fit_font_size(
        planned.title, _HEAD_WIDTH, _TITLE_MAX_HEIGHT, _TITLE_FONT, _TITLE_FONT_MIN
    )
    title_height = required_height(planned.title, _HEAD_WIDTH, title_size)
    purpose_y = _TITLE_TOP + title_height + 0.06
    purpose_height = min(
        _PURPOSE_MAX_HEIGHT,
        required_height(planned.purpose, _HEAD_WIDTH, _PURPOSE_FONT),
    )

    content_top = purpose_y + purpose_height + 0.18
    # The key message owns a fixed band at the foot of the slide, so the bullet
    # column is bounded by it rather than growing into it.
    content_bottom = _KEY_MESSAGE_TOP - 0.12 if planned.key_message else _CONTENT_FLOOR
    available = max(content_bottom - content_top, _MIN_CONTENT_HEIGHT)

    point_size = fit_stack_font_size(
        list(planned.points),
        body_width,
        available,
        _POINT_FONT,
        _POINT_FONT_MIN,
        _POINT_GAP,
    )
    point_heights = [
        required_height(point, body_width, point_size) for point in planned.points
    ]
    used = sum(point_heights) + _POINT_GAP * max(len(point_heights) - 1, 0)

    elements: list[SlideElement] = [
        TextElement(
            element_id=f"{slide_id}_title",
            text=planned.title,
            x=0.75,
            y=_TITLE_TOP,
            w=_HEAD_WIDTH,
            h=title_height,
            font_size=int(title_size),
            bold=True,
            color=theme.text_color,
        ),
        TextElement(
            element_id=f"{slide_id}_purpose",
            text=planned.purpose,
            x=0.8,
            y=purpose_y,
            w=_HEAD_WIDTH,
            h=purpose_height,
            font_size=_PURPOSE_FONT,
            color=theme.muted_color,
        ),
        ShapeElement(
            element_id=f"{slide_id}_accent",
            shape="roundRect",
            x=0.75,
            y=content_top,
            w=0.12,
            h=max(used, 1.0),
            fill_color=theme.primary_color,
            line_color=theme.primary_color,
            line_width=0,
        ),
    ]
    point_y = content_top
    for point_index, point in enumerate(planned.points, start=1):
        height = point_heights[point_index - 1]
        elements.extend(
            [
                ShapeElement(
                    element_id=f"{slide_id}_marker_{point_index:02d}",
                    shape="ellipse",
                    x=1.08,
                    y=point_y + (height / 2) - 0.08,
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
                    w=body_width,
                    h=height,
                    font_size=int(point_size),
                    color=theme.text_color,
                    valign="mid",
                ),
            ]
        )
        point_y += height + _POINT_GAP
    if planned.key_message:
        elements.append(
            TextElement(
                element_id=f"{slide_id}_key_message",
                text=planned.key_message,
                x=0.95,
                y=_KEY_MESSAGE_TOP,
                w=11.35,
                h=_KEY_MESSAGE_HEIGHT,
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
        visual_prompt=planned.visual_prompt,
        visual_priority=planned.visual_priority,
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
