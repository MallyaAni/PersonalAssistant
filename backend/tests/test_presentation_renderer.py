import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

from backend.presentations.renderer import PptxGenJSRenderer, PresentationRenderError
from backend.presentations.types import (
    ChartElement,
    ChartSeries,
    DeckSpec,
    ShapeElement,
    SlideSpec,
    TableElement,
    TextElement,
)
from backend.presentations.validation import validate_presentation_structure


# Build one deck that exercises every native editable object category.
def _native_deck() -> DeckSpec:
    return DeckSpec(
        title="Editable acceptance",
        slides=[
            SlideSpec(
                slide_id="slide-1",
                title="Native objects",
                purpose="Verify editability",
                notes="Speaker note",
                elements=[
                    TextElement(
                        element_id="title",
                        text="Editable title",
                        x=0.7,
                        y=0.5,
                        w=5,
                        h=0.7,
                        bold=True,
                    ),
                    ShapeElement(
                        element_id="shape",
                        shape="roundRect",
                        x=0.7,
                        y=1.5,
                        w=2,
                        h=1,
                    ),
                    ChartElement(
                        element_id="chart",
                        chart_type="column",
                        categories=["Q1", "Q2"],
                        series=[ChartSeries(name="Revenue", values=[10, 14])],
                        x=3,
                        y=1.4,
                        w=4,
                        h=2.5,
                    ),
                    TableElement(
                        element_id="table",
                        headers=["Metric", "Value"],
                        rows=[["Growth", "40%"]],
                        x=0.7,
                        y=4.2,
                        w=6.3,
                        h=1.4,
                    ),
                ],
            )
        ],
    )


# Verify the Python adapter accepts a bounded OOXML renderer response.
@pytest.mark.asyncio
async def test_renderer_accepts_ooxml_response() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("ppt/presentation.xml", "<p:presentation/>")
        package.writestr("ppt/slides/slide1.xml", "<p:sld/>")

    # Return a deterministic worker response without contacting a process.
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/render"
        return httpx.Response(
            200,
            content=buffer.getvalue(),
            headers={
                "x-presentation-slide-count": "1",
                "x-presentation-renderer-version": "4.0.1",
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://renderer",
    )
    renderer = PptxGenJSRenderer("http://renderer", client=client)
    result = await renderer.render(_native_deck())
    await client.aclose()

    assert result.slide_count == 1
    assert result.renderer == "pptxgenjs"


# Verify a worker error is converted to one sanitized application exception.
@pytest.mark.asyncio
async def test_renderer_sanitizes_worker_failure() -> None:
    # Simulate a renderer rejecting an invalid or unsupported compile request.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "private renderer details"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://renderer",
    )
    renderer = PptxGenJSRenderer("http://renderer", client=client)
    with pytest.raises(PresentationRenderError, match="Unable to compile"):
        await renderer.render(_native_deck())
    await client.aclose()


# Recognize native PowerPoint text bodies under the presentation namespace.
def test_structure_inspector_recognizes_native_text_objects() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("ppt/presentation.xml", "<p:presentation/>")
        package.writestr(
            "ppt/slides/slide1.xml",
            "<p:sld><p:sp><p:txBody><a:p><a:r><a:t>Editable</a:t>"
            "</a:r></a:p></p:txBody></p:sp></p:sld>",
        )

    structure = validate_presentation_structure(
        buffer.getvalue(),
        DeckSpec(
            title="Native text",
            slides=[
                SlideSpec(
                    slide_id="slide-1",
                    title="Native text",
                    purpose="Verify the OOXML namespace",
                    elements=[
                        TextElement(
                            element_id="text",
                            text="Editable",
                            x=1,
                            y=1,
                            w=4,
                            h=1,
                        )
                    ],
                )
            ],
        ),
    )

    assert structure.text_objects == 1


# Compile through the real Node worker code and inspect its native OOXML objects.
def test_real_renderer_output_preserves_native_objects(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node belongs to the separate presentation renderer image")
    specification = _native_deck()
    input_path = tmp_path / "acceptance.json"
    output_path = tmp_path / "acceptance.pptx"
    input_path.write_text(
        json.dumps(specification.model_dump(mode="json")),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "node",
            "src/cli.mjs",
            str(input_path),
            str(output_path),
        ],
        cwd=Path(__file__).parents[2] / "presentation-renderer",
        check=True,
        capture_output=True,
        text=True,
    )
    structure = validate_presentation_structure(
        output_path.read_bytes(),
        specification,
    )
    assert structure.slides == 1
    assert structure.text_objects >= 1
    assert structure.shape_objects >= 1
    assert structure.chart_objects >= 1
    assert structure.table_objects >= 1
