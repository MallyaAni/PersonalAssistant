from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5


class PresentationModel(BaseModel):
    """Reject unknown model output instead of silently dropping it."""

    model_config = ConfigDict(extra="forbid")


class PresentationTheme(PresentationModel):
    """Reusable visual defaults applied to every slide in one deck."""

    font_face: str = Field(default="Aptos", min_length=1, max_length=80)
    background_color: str = Field(default="F5F5F7", pattern=r"^[0-9A-Fa-f]{6}$")
    primary_color: str = Field(default="0071E3", pattern=r"^[0-9A-Fa-f]{6}$")
    text_color: str = Field(default="1D1D1F", pattern=r"^[0-9A-Fa-f]{6}$")
    muted_color: str = Field(default="6E6E73", pattern=r"^[0-9A-Fa-f]{6}$")


class ElementBase(PresentationModel):
    """Shared identity and position for one editable slide object."""

    element_id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        max_length=80,
    )
    x: float = Field(ge=0, le=SLIDE_WIDTH)
    y: float = Field(ge=0, le=SLIDE_HEIGHT)
    w: float = Field(gt=0, le=SLIDE_WIDTH)
    h: float = Field(gt=0, le=SLIDE_HEIGHT)

    # Refuse objects whose lower-right corner leaves the fixed widescreen canvas.
    @model_validator(mode="after")
    def fits_slide(self) -> "ElementBase":
        if self.x + self.w > SLIDE_WIDTH + 0.001:
            raise ValueError("Element extends past the slide width")
        if self.y + self.h > SLIDE_HEIGHT + 0.001:
            raise ValueError("Element extends past the slide height")
        return self


class TextElement(ElementBase):
    """Native PowerPoint text that remains directly editable."""

    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=8_000)
    font_size: float = Field(default=24, ge=8, le=96)
    bold: bool = False
    color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "mid", "bottom"] = "top"
    bullet: bool = False


class ShapeElement(ElementBase):
    """Native PowerPoint shape with editable fill and outline."""

    type: Literal["shape"] = "shape"
    shape: Literal["rect", "roundRect", "ellipse", "line"] = "rect"
    fill_color: str = Field(default="FFFFFF", pattern=r"^[0-9A-Fa-f]{6}$")
    line_color: str = Field(default="D2D2D7", pattern=r"^[0-9A-Fa-f]{6}$")
    line_width: float = Field(default=1, ge=0, le=10)


class ChartSeries(PresentationModel):
    """One named numeric series rendered as a native PowerPoint chart."""

    name: str = Field(min_length=1, max_length=100)
    values: list[float] = Field(min_length=1, max_length=50)


class ChartElement(ElementBase):
    """Native PowerPoint chart whose data remains editable."""

    type: Literal["chart"] = "chart"
    chart_type: Literal["bar", "column", "line", "pie"] = "column"
    categories: list[str] = Field(min_length=1, max_length=50)
    series: list[ChartSeries] = Field(min_length=1, max_length=12)
    show_legend: bool = True
    show_title: bool = False
    title: str | None = Field(default=None, max_length=160)

    # Require each series to align exactly with the category axis.
    @model_validator(mode="after")
    def aligned_series(self) -> "ChartElement":
        category_count = len(self.categories)
        if any(len(series.values) != category_count for series in self.series):
            raise ValueError("Every chart series must match the category count")
        if self.chart_type == "pie" and len(self.series) != 1:
            raise ValueError("Pie charts require exactly one series")
        return self


class TableElement(ElementBase):
    """Native PowerPoint table whose cells remain editable."""

    type: Literal["table"] = "table"
    headers: list[str] = Field(min_length=1, max_length=12)
    rows: list[list[str]] = Field(min_length=1, max_length=40)
    font_size: float = Field(default=16, ge=8, le=36)

    # Require every data row to have the same number of cells as the header.
    @model_validator(mode="after")
    def rectangular_rows(self) -> "TableElement":
        width = len(self.headers)
        if any(len(row) != width for row in self.rows):
            raise ValueError("Every table row must match the header width")
        return self


class ImageElement(ElementBase):
    """Owned image reference embedded as a replaceable PowerPoint picture."""

    type: Literal["image"] = "image"
    artifact_id: UUID
    alt_text: str = Field(min_length=1, max_length=500)


SlideElement = Annotated[
    TextElement | ShapeElement | ChartElement | TableElement | ImageElement,
    Field(discriminator="type"),
]


class SlideSpec(PresentationModel):
    """One stable slide that can be revised without replacing its siblings."""

    slide_id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        max_length=80,
    )
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=500)
    background_color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    notes: str = Field(default="", max_length=8_000)
    elements: list[SlideElement] = Field(min_length=1, max_length=80)

    # Keep element identifiers unique so slide-level patches have unambiguous targets.
    @model_validator(mode="after")
    def unique_element_ids(self) -> "SlideSpec":
        identifiers = [element.element_id for element in self.elements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Element identifiers must be unique within a slide")
        return self


class DeckSpec(PresentationModel):
    """Canonical editable source used to render and revise one presentation."""

    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    theme: PresentationTheme = Field(default_factory=PresentationTheme)
    slides: list[SlideSpec] = Field(min_length=1, max_length=30)

    # Keep slide identifiers stable and unique across the entire deck.
    @model_validator(mode="after")
    def unique_slide_ids(self) -> "DeckSpec":
        identifiers = [slide.slide_id for slide in self.slides]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Slide identifiers must be unique within a deck")
        return self


class RenderedPresentation(PresentationModel):
    """Binary renderer result plus structural evidence returned by the worker."""

    content: bytes
    slide_count: int = Field(ge=1, le=30)
    renderer: str
    renderer_version: str

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
