from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.presentations.types import (
    ChartElement,
    ChartSeries,
    DeckSpec,
    ShapeElement,
    SlideElement,
    SlideSpec,
    TableElement,
    TextElement,
)


class SlideEditModel(BaseModel):
    """Reject unknown compact-edit fields before application-owned mutation."""

    model_config = ConfigDict(extra="forbid")


class TextUpdate(SlideEditModel):
    """Change content or styling on one existing native text object."""

    element_id: str = Field(min_length=1, max_length=80)
    text: str | None = Field(default=None, min_length=1, max_length=8_000)
    font_size: float | None = Field(default=None, ge=8, le=96)
    bold: bool | None = None
    color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    align: Literal["left", "center", "right"] | None = None
    valign: Literal["top", "mid", "bottom"] | None = None


class ShapeUpdate(SlideEditModel):
    """Change styling on one existing native shape without moving it."""

    element_id: str = Field(min_length=1, max_length=80)
    fill_color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    line_color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    line_width: float | None = Field(default=None, ge=0, le=10)


class ChartUpdate(SlideEditModel):
    """Change data or display settings on one existing native chart."""

    element_id: str = Field(min_length=1, max_length=80)
    chart_type: Literal["bar", "column", "line", "pie"] | None = None
    categories: list[str] | None = Field(default=None, min_length=1, max_length=50)
    series: list[ChartSeries] | None = Field(default=None, min_length=1, max_length=12)
    show_legend: bool | None = None
    show_title: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)


class TableUpdate(SlideEditModel):
    """Change cells or typography on one existing native table."""

    element_id: str = Field(min_length=1, max_length=80)
    headers: list[str] | None = Field(default=None, min_length=1, max_length=12)
    rows: list[list[str]] | None = Field(default=None, min_length=1, max_length=40)
    font_size: float | None = Field(default=None, ge=8, le=36)


class TextAddition(SlideEditModel):
    """Add bounded text at an application-owned footer or callout position."""

    text: str = Field(min_length=1, max_length=1_000)
    role: Literal["footer", "callout"] = "footer"
    bold: bool = False
    color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")


class SlideEdit(SlideEditModel):
    """Compact selected-slide changes that never reproduce the whole layout."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=8_000)
    background_color: str | None = Field(
        default=None,
        pattern=r"^[0-9A-Fa-f]{6}$",
    )
    text_updates: list[TextUpdate] = Field(default_factory=list, max_length=30)
    shape_updates: list[ShapeUpdate] = Field(default_factory=list, max_length=30)
    chart_updates: list[ChartUpdate] = Field(default_factory=list, max_length=12)
    table_updates: list[TableUpdate] = Field(default_factory=list, max_length=12)
    add_text: list[TextAddition] = Field(default_factory=list, max_length=6)
    remove_element_ids: list[str] = Field(default_factory=list, max_length=30)


ElementUpdate = TextUpdate | ShapeUpdate | ChartUpdate | TableUpdate


# Return only explicitly supplied update fields so unchanged values remain exact.
def _changes(update: SlideEditModel) -> dict[str, object]:
    return update.model_dump(
        mode="python",
        exclude={"element_id"},
        exclude_none=True,
    )


# Reject missing, duplicated, or wrong-type element references before mutation.
def _validated_updates(
    updates: Sequence[ElementUpdate],
    elements_by_id: dict[str, SlideElement],
    expected_type: (
        type[TextElement] | type[ShapeElement] | type[ChartElement] | type[TableElement]
    ),
) -> dict[str, ElementUpdate]:
    validated: dict[str, ElementUpdate] = {}
    for update in updates:
        element_id = update.element_id
        if element_id in validated:
            raise ValueError(f"Element {element_id} was updated more than once")
        element = elements_by_id.get(element_id)
        if not isinstance(element, expected_type):
            raise ValueError(f"Element {element_id} has the wrong editable type")
        validated[element_id] = update
    return validated


# Validate every compact element reference and combine the typed updates by ID.
def _element_updates(
    edit: SlideEdit,
    elements_by_id: dict[str, SlideElement],
) -> dict[str, ElementUpdate]:
    groups = [
        _validated_updates(edit.text_updates, elements_by_id, TextElement),
        _validated_updates(edit.shape_updates, elements_by_id, ShapeElement),
        _validated_updates(edit.chart_updates, elements_by_id, ChartElement),
        _validated_updates(edit.table_updates, elements_by_id, TableElement),
    ]
    combined = {
        element_id: update for group in groups for element_id, update in group.items()
    }
    if len(combined) != sum(len(group) for group in groups):
        raise ValueError("An element cannot receive multiple update types")
    return combined


# Apply root-title and purpose changes to their matching native text objects.
def _edit_existing_element(
    element: SlideElement,
    selected: SlideSpec,
    edit: SlideEdit,
    updates: dict[str, ElementUpdate],
) -> SlideElement:
    update = updates.get(element.element_id)
    changes = _changes(update) if update is not None else {}
    if (
        edit.title is not None
        and isinstance(element, TextElement)
        and (element.element_id.endswith("_title") or element.text == selected.title)
        and element.element_id not in updates
    ):
        changes["text"] = edit.title
    if (
        edit.purpose is not None
        and isinstance(element, TextElement)
        and (
            element.element_id.endswith("_purpose") or element.text == selected.purpose
        )
        and element.element_id not in updates
    ):
        changes["text"] = edit.purpose
    return element.model_copy(update=changes)


# Compile new text into bounded application-owned positions and stable identifiers.
def _added_text_elements(
    deck: DeckSpec,
    slide_id: str,
    additions: Sequence[TextAddition],
    existing_ids: set[str],
) -> list[TextElement]:
    elements: list[TextElement] = []
    next_addition = 1
    for addition in additions:
        while f"{slide_id}_edit_{next_addition:02d}" in existing_ids:
            next_addition += 1
        element_id = f"{slide_id}_edit_{next_addition:02d}"
        existing_ids.add(element_id)
        if addition.role == "footer":
            x, y, w, h, font_size = 0.85, 7.08, 11.63, 0.22, 10
        else:
            x, y, w, h, font_size = 0.95, 5.85, 11.35, 0.52, 15
        elements.append(
            TextElement(
                element_id=element_id,
                text=addition.text,
                x=x,
                y=y,
                w=w,
                h=h,
                font_size=font_size,
                bold=addition.bold,
                color=addition.color or deck.theme.muted_color,
                align="center",
                valign="mid",
            )
        )
        next_addition += 1
    return elements


# Apply one compact edit while preserving every unspecified native slide object.
def apply_slide_edit(deck: DeckSpec, slide_id: str, edit: SlideEdit) -> SlideSpec:
    selected = next(
        (slide for slide in deck.slides if slide.slide_id == slide_id),
        None,
    )
    if selected is None:
        raise ValueError("Selected slide was not found")

    elements_by_id = {element.element_id: element for element in selected.elements}
    updates = _element_updates(edit, elements_by_id)
    remove_ids = set(edit.remove_element_ids)
    if len(remove_ids) != len(edit.remove_element_ids):
        raise ValueError("An element cannot be removed more than once")
    if missing := remove_ids - elements_by_id.keys():
        raise ValueError(f"Unknown element removal: {sorted(missing)[0]}")

    elements = [
        _edit_existing_element(element, selected, edit, updates)
        for element in selected.elements
        if element.element_id not in remove_ids
    ]
    elements.extend(
        _added_text_elements(
            deck,
            slide_id,
            edit.add_text,
            {element.element_id for element in elements},
        )
    )

    if not elements:
        raise ValueError("A slide edit cannot remove every element")
    slide_changes: dict[str, object] = {"elements": elements}
    for field_name in ("title", "purpose", "notes", "background_color"):
        value = getattr(edit, field_name)
        if value is not None:
            slide_changes[field_name] = value
    if not edit.model_dump(exclude_none=True, exclude_defaults=True):
        raise ValueError("Presentation edit did not request any changes")
    return selected.model_copy(update=slide_changes)
