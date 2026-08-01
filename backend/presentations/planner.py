import re
from dataclasses import dataclass
from typing import Literal

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

# The shapes a slide may take. Grammar-constrained decoding restricts the model
# to exactly these, so an unknown layout is unrepresentable rather than caught.
SlideLayout = Literal["bullets", "section", "statistic", "quote", "comparison"]
SLIDE_LAYOUTS: tuple[str, ...] = (
    "bullets",
    "section",
    "statistic",
    "quote",
    "comparison",
)


class DeckPlanModel(BaseModel):
    """Reject unknown compact-plan fields before deterministic compilation."""

    model_config = ConfigDict(extra="forbid")


class PlannedSlide(DeckPlanModel):
    """Concise semantic content for one slide without layout authority."""

    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=300)
    # Always supplied. A layout that does not show a bulleted list simply does
    # not render these, which keeps one contract for every slide kind.
    points: list[str] = Field(min_length=2, max_length=6)
    # The model picks the shape of the slide; the compiler still owns geometry.
    # A deck of identically shaped slides is the single biggest reason generated
    # decks read as generated.
    layout: SlideLayout = "bullets"
    # Only the layout that needs them reads these. A layout missing what it
    # needs degrades to bullets rather than failing the deck.
    statistic_value: str | None = Field(default=None, max_length=12)
    statistic_label: str | None = Field(default=None, max_length=120)
    quote: str | None = Field(default=None, max_length=400)
    quote_attribution: str | None = Field(default=None, max_length=120)
    comparison_left_heading: str | None = Field(default=None, max_length=60)
    comparison_right_heading: str | None = Field(default=None, max_length=60)
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
    """Bounded title, purpose, and shape used to schedule one slide microtask."""

    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=300)
    # Chosen while the whole deck is in view. A slide planned in isolation only
    # sees its own title and purpose, which carry no signal about what shape the
    # deck needs next, so every slide came back as bullets.
    layout: SlideLayout = "bullets"


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
    # A layout that lacks the content it needs falls back rather than rendering
    # an empty panel, so a partial plan still produces a usable slide.
    layout = _effective_layout(planned)
    if layout == "section":
        elements = _section_elements(planned, slide_id, theme)
    elif layout == "statistic":
        elements = _statistic_elements(planned, slide_id, theme)
    elif layout == "quote":
        elements = _quote_elements(planned, slide_id, theme)
    elif layout == "comparison":
        elements = _comparison_elements(planned, slide_id, theme)
    else:
        elements = _bullet_elements(planned, slide_id, theme)
    return SlideSpec(
        slide_id=slide_id,
        title=planned.title,
        purpose=planned.purpose,
        visual_prompt=planned.visual_prompt,
        visual_priority=planned.visual_priority,
        notes=planned.notes,
        elements=elements,
    )


# Resolve the layout the slide can actually render with the content it carries.
def _effective_layout(planned: PlannedSlide) -> str:
    if planned.layout == "statistic" and not (planned.statistic_value or "").strip():
        return "bullets"
    if planned.layout == "quote" and not (planned.quote or "").strip():
        return "bullets"
    if planned.layout == "comparison" and len(planned.points) < 2:
        return "bullets"
    return planned.layout


def _bullet_elements(
    planned: PlannedSlide, slide_id: str, theme: PresentationTheme
) -> list[SlideElement]:
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
    return elements


# A divider. Large centred title over a rule, used to open a section so a deck
# has visible structure instead of running as one undifferentiated sequence.
def _section_elements(
    planned: PlannedSlide, slide_id: str, theme: PresentationTheme
) -> list[SlideElement]:
    title_size = fit_font_size(planned.title, 10.5, 1.9, 44, 28)
    title_height = required_height(planned.title, 10.5, title_size)
    title_y = 2.55 - (title_height / 2)
    purpose_height = required_height(planned.purpose, 9.0, 16)
    return [
        ShapeElement(
            element_id=f"{slide_id}_rule",
            shape="roundRect",
            x=5.87,
            y=title_y - 0.45,
            w=1.6,
            h=0.09,
            fill_color=theme.primary_color,
            line_color=theme.primary_color,
            line_width=0,
        ),
        TextElement(
            element_id=f"{slide_id}_title",
            text=planned.title,
            x=1.4,
            y=title_y,
            w=10.5,
            h=title_height,
            font_size=int(title_size),
            bold=True,
            color=theme.text_color,
            align="center",
        ),
        TextElement(
            element_id=f"{slide_id}_purpose",
            text=planned.purpose,
            x=2.15,
            y=title_y + title_height + 0.24,
            w=9.0,
            h=purpose_height,
            font_size=16,
            color=theme.muted_color,
            align="center",
        ),
    ]


# One number carried large enough to be the point of the slide, with its
# supporting detail beside it rather than competing with it.
def _statistic_elements(
    planned: PlannedSlide, slide_id: str, theme: PresentationTheme
) -> list[SlideElement]:
    value = (planned.statistic_value or "").strip()
    label = (planned.statistic_label or planned.purpose).strip()
    elements = _heading_elements(planned, slide_id, theme)
    value_size = fit_font_size(value, 5.1, 2.1, 96, 40)
    elements.extend(
        [
            TextElement(
                element_id=f"{slide_id}_stat_value",
                text=value,
                x=0.95,
                y=2.35,
                w=5.1,
                h=required_height(value, 5.1, value_size),
                font_size=int(value_size),
                bold=True,
                color=theme.primary_color,
                align="center",
            ),
            TextElement(
                element_id=f"{slide_id}_stat_label",
                text=label,
                x=0.95,
                y=4.6,
                w=5.1,
                h=min(1.0, required_height(label, 5.1, 15)),
                font_size=15,
                color=theme.muted_color,
                align="center",
            ),
        ]
    )
    support = list(planned.points)[:4]
    point_size = fit_stack_font_size(support, 5.6, 3.4, 16, 12, _POINT_GAP)
    point_y = 2.4
    for index, point in enumerate(support, start=1):
        height = required_height(point, 5.6, point_size)
        elements.append(
            TextElement(
                element_id=f"{slide_id}_point_{index:02d}",
                text=point,
                x=6.75,
                y=point_y,
                w=5.6,
                h=height,
                font_size=int(point_size),
                color=theme.text_color,
                bullet=True,
                valign="mid",
            )
        )
        point_y += height + _POINT_GAP
    return elements


# A pull quote. Rendered large and centred with its attribution beneath, so a
# cited voice reads as evidence rather than as another bullet.
def _quote_elements(
    planned: PlannedSlide, slide_id: str, theme: PresentationTheme
) -> list[SlideElement]:
    quote = (planned.quote or "").strip()
    quote_size = fit_font_size(quote, 9.6, 3.0, 30, 18)
    quote_height = required_height(quote, 9.6, quote_size)
    quote_y = max(2.35, 3.35 - (quote_height / 2))
    elements: list[SlideElement] = [
        ShapeElement(
            element_id=f"{slide_id}_quote_rule",
            shape="roundRect",
            x=1.5,
            y=quote_y,
            w=0.1,
            h=quote_height,
            fill_color=theme.primary_color,
            line_color=theme.primary_color,
            line_width=0,
        ),
        TextElement(
            element_id=f"{slide_id}_title",
            text=planned.title,
            x=1.85,
            y=1.05,
            w=10.0,
            h=required_height(planned.title, 10.0, 20),
            font_size=20,
            bold=True,
            color=theme.muted_color,
        ),
        TextElement(
            element_id=f"{slide_id}_quote",
            text=quote,
            x=1.85,
            y=quote_y,
            w=9.6,
            h=quote_height,
            font_size=int(quote_size),
            color=theme.text_color,
        ),
    ]
    attribution = (planned.quote_attribution or "").strip()
    if attribution:
        elements.append(
            TextElement(
                element_id=f"{slide_id}_quote_attribution",
                text=f"— {attribution}",
                x=1.85,
                y=quote_y + quote_height + 0.3,
                w=9.6,
                h=0.45,
                font_size=15,
                color=theme.primary_color,
            )
        )
    return elements


# Two columns for a genuine contrast. Points are split in order, so the model
# supplies one list and the compiler decides where the boundary falls.
def _comparison_elements(
    planned: PlannedSlide, slide_id: str, theme: PresentationTheme
) -> list[SlideElement]:
    elements = _heading_elements(planned, slide_id, theme)
    points = list(planned.points)
    midpoint = (len(points) + 1) // 2
    columns = (
        (planned.comparison_left_heading, points[:midpoint], 0.95),
        (planned.comparison_right_heading, points[midpoint:], 6.95),
    )
    column_width = 5.4
    text_width = column_width - 0.5
    largest = max((column[1] for column in columns), key=len, default=[])
    point_size = fit_stack_font_size(largest, text_width, 3.3, 16, 12, _POINT_GAP)
    for column_index, (heading, column_points, x) in enumerate(columns, start=1):
        elements.append(
            ShapeElement(
                element_id=f"{slide_id}_column_{column_index:02d}",
                shape="roundRect",
                x=x,
                y=2.2,
                w=column_width,
                h=4.1,
                fill_color=theme.background_color,
                line_color=theme.primary_color,
                line_width=1,
            )
        )
        if heading and heading.strip():
            elements.append(
                TextElement(
                    element_id=f"{slide_id}_column_{column_index:02d}_heading",
                    text=heading.strip(),
                    x=x + 0.25,
                    y=2.42,
                    w=text_width,
                    h=0.42,
                    font_size=17,
                    bold=True,
                    color=theme.primary_color,
                )
            )
        point_y = 3.0
        for point_index, point in enumerate(column_points, start=1):
            height = required_height(point, text_width, point_size)
            elements.append(
                TextElement(
                    element_id=(
                        f"{slide_id}_point_{column_index:02d}{point_index:02d}"
                    ),
                    text=point,
                    x=x + 0.25,
                    y=point_y,
                    w=text_width,
                    h=height,
                    font_size=int(point_size),
                    color=theme.text_color,
                    bullet=True,
                )
            )
            point_y += height + _POINT_GAP
    return elements


# The shared title and purpose band used by every content layout.
def _heading_elements(
    planned: PlannedSlide, slide_id: str, theme: PresentationTheme
) -> list[SlideElement]:
    title_size = fit_font_size(
        planned.title, _HEAD_WIDTH, _TITLE_MAX_HEIGHT, _TITLE_FONT, _TITLE_FONT_MIN
    )
    title_height = required_height(planned.title, _HEAD_WIDTH, title_size)
    return [
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
            y=_TITLE_TOP + title_height + 0.06,
            w=_HEAD_WIDTH,
            h=min(
                _PURPOSE_MAX_HEIGHT,
                required_height(planned.purpose, _HEAD_WIDTH, _PURPOSE_FONT),
            ),
            font_size=_PURPOSE_FONT,
            color=theme.muted_color,
        ),
    ]


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
