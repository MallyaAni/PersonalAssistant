import io
import re
import zipfile
from dataclasses import dataclass

from backend.presentations.types import DeckSpec

_SLIDE_PATH = re.compile(r"^ppt/slides/slide\d+\.xml$")


@dataclass(frozen=True, slots=True)
class PresentationStructure:
    """Structural evidence found inside one generated OOXML package."""

    slides: int
    text_objects: int
    shape_objects: int
    chart_objects: int
    table_objects: int
    notes_slides: int


# Inspect native OOXML objects without relying on PowerPoint being installed.
def inspect_presentation(content: bytes) -> PresentationStructure:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            names = set(package.namelist())
            if (
                "[Content_Types].xml" not in names
                or "ppt/presentation.xml" not in names
            ):
                raise ValueError("PowerPoint package is missing required OOXML parts")
            slide_names = sorted(name for name in names if _SLIDE_PATH.match(name))
            slide_xml = b"".join(package.read(name) for name in slide_names)
            return PresentationStructure(
                slides=len(slide_names),
                text_objects=slide_xml.count(b"<p:txBody>"),
                shape_objects=slide_xml.count(b"<p:sp>"),
                chart_objects=sum(
                    name.startswith("ppt/charts/chart") for name in names
                ),
                table_objects=slide_xml.count(b"<a:tbl>"),
                notes_slides=sum(
                    name.startswith("ppt/notesSlides/notesSlide")
                    and name.endswith(".xml")
                    for name in names
                ),
            )
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("PowerPoint output is not a readable OOXML package") from exc


# Confirm the package preserved every requested native object category.
def validate_presentation_structure(
    content: bytes,
    specification: DeckSpec,
) -> PresentationStructure:
    structure = inspect_presentation(content)
    if structure.slides != len(specification.slides):
        raise ValueError("PowerPoint output has the wrong slide count")
    requested_types = {
        element.type for slide in specification.slides for element in slide.elements
    }
    if "text" in requested_types and structure.text_objects == 0:
        raise ValueError("PowerPoint output flattened or omitted native text")
    if "shape" in requested_types and structure.shape_objects == 0:
        raise ValueError("PowerPoint output flattened or omitted native shapes")
    if "chart" in requested_types and structure.chart_objects == 0:
        raise ValueError("PowerPoint output flattened or omitted native charts")
    if "table" in requested_types and structure.table_objects == 0:
        raise ValueError("PowerPoint output flattened or omitted native tables")
    return structure
