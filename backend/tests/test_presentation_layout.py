import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.presentations.layout import (
    fit_font_size,
    fit_stack_font_size,
    line_count,
    required_height,
)
from backend.presentations.planner import (
    PlannedSeries,
    PlannedSlide,
    compile_slide,
    default_theme,
)
from backend.presentations.types import (
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
    ChartElement,
    TableElement,
    TextElement,
)

# The slide from the reported bug: a title that wraps, a long purpose, and the
# maximum six bullets, each long enough to wrap.
_LONG_TITLE = "Origins: From Industrial Replication to Autonomous Systems"
_LONG_PURPOSE = (
    "Define the historical trajectory from hard-coded industrial automation to "
    "the software-driven flexibility of modern machines"
)
_LONG_POINTS = [
    "Early automation relied on mechanical linkages and physical toll tables "
    "for rigid task replication.",
    "Programming introduced fixed logic, but remained static due to lack of "
    "adaptive feedback loops.",
    "The mid-20th century saw the integration of sensors and basic processors "
    "in manufacturing environments.",
    "Modern systems utilize real-time learning algorithms to adapt routines "
    "based on environmental data.",
]
_KEY_MESSAGE = (
    "Autonomous evolution is defined by the replacement of static mechanical "
    "logic with adaptive software intelligence."
)


def _slide(**overrides: object) -> PlannedSlide:
    fields: dict[str, object] = {
        "title": _LONG_TITLE,
        "purpose": _LONG_PURPOSE,
        "points": _LONG_POINTS,
        "key_message": _KEY_MESSAGE,
        "visual_priority": 0,
        "notes": "",
    }
    fields.update(overrides)
    return PlannedSlide(**fields)  # type: ignore[arg-type]


def _texts(spec: object) -> list[TextElement]:
    return [e for e in spec.elements if isinstance(e, TextElement)]  # type: ignore[attr-defined]


def test_a_wrapping_title_is_measured_as_more_than_one_line():
    # 11.8 inches at 30pt fits roughly 54 characters, so this title wraps.
    assert line_count(_LONG_TITLE, 11.8, 30) >= 2
    assert required_height(_LONG_TITLE, 11.8, 30) > 0.65


# The bug: the title box was a fixed 0.65in, so a two-line title was clipped.
def test_title_box_is_tall_enough_for_the_text_it_holds():
    spec = compile_slide(_slide(), "slide_001", default_theme())
    title = next(e for e in _texts(spec) if e.element_id.endswith("_title"))

    assert title.h >= required_height(_LONG_TITLE, title.w, title.font_size) - 0.01


# The bug: six bullets at a fixed 0.82in pitch ended at 6.60in while the key
# message was pinned at 6.55in, so they always collided.
def test_bullets_never_reach_the_key_message_band():
    spec = compile_slide(_slide(), "slide_001", default_theme())
    points = [e for e in _texts(spec) if "_point_" in e.element_id]
    key = next(e for e in _texts(spec) if e.element_id.endswith("_key_message"))

    assert len(points) == 4
    assert max(point.y + point.h for point in points) <= key.y


def test_no_element_extends_past_the_slide():
    spec = compile_slide(_slide(), "slide_001", default_theme())

    for element in spec.elements:
        assert element.x + element.w <= SLIDE_WIDTH + 0.01
        assert element.y + element.h <= SLIDE_HEIGHT + 0.01


def test_stacked_bullets_do_not_overlap_each_other():
    spec = compile_slide(_slide(), "slide_001", default_theme())
    points = sorted(
        (e for e in _texts(spec) if "_point_" in e.element_id), key=lambda e: e.y
    )

    for earlier, later in zip(points, points[1:], strict=False):
        assert earlier.y + earlier.h <= later.y + 0.01


# A slide expecting generated imagery must keep its text out of the column the
# image occupies, which starts at x=8.45.
def test_text_avoids_the_image_column_when_a_visual_is_expected():
    spec = compile_slide(
        _slide(visual_priority=3, visual_prompt="a factory floor"),
        "slide_001",
        default_theme(),
    )
    points = [e for e in _texts(spec) if "_point_" in e.element_id]

    assert points
    for point in points:
        assert point.x + point.w <= 8.45


def test_full_width_is_used_when_no_visual_is_expected():
    spec = compile_slide(_slide(visual_priority=0), "slide_001", default_theme())
    points = [e for e in _texts(spec) if "_point_" in e.element_id]

    assert max(point.w for point in points) > 8.0


# Dense content shrinks rather than overflows, but never below the floor that
# keeps a slide readable.
def test_dense_content_shrinks_the_body_font_within_bounds():
    spec = compile_slide(_slide(), "slide_001", default_theme())
    sparse = compile_slide(
        _slide(points=["Short one.", "Short two."], key_message=None),
        "slide_002",
        default_theme(),
    )

    dense_size = min(e.font_size for e in _texts(spec) if "_point_" in e.element_id)
    sparse_size = min(e.font_size for e in _texts(sparse) if "_point_" in e.element_id)

    assert 12 <= dense_size <= 18
    assert sparse_size >= dense_size


def test_fit_helpers_return_the_floor_rather_than_failing():
    # Even an absurd string resolves to the minimum instead of raising.
    assert fit_font_size("x" * 5_000, 4.0, 0.5, 30, 22) == 22
    assert fit_stack_font_size(["y" * 2_000] * 6, 4.0, 1.0, 18, 12, 0.14) == 12


# A deck of identically shaped slides is what makes generated decks read as
# generated, so each layout must produce visibly different geometry.
def test_each_layout_produces_its_own_elements():
    theme = default_theme()
    ids = {}
    for layout, extra in (
        ("bullets", {}),
        ("section", {}),
        ("statistic", {"statistic_value": "35%", "statistic_label": "of forage"}),
        ("quote", {"quote": "Cities need bees.", "quote_attribution": "A beekeeper"}),
        (
            "comparison",
            {
                "comparison_left_heading": "Rooftop",
                "comparison_right_heading": "Ground level",
            },
        ),
    ):
        spec = compile_slide(_slide(layout=layout, **extra), f"slide_{layout}", theme)
        ids[layout] = {e.element_id.split("_", 2)[-1] for e in spec.elements}

    assert "stat_value" in ids["statistic"]
    assert "quote" in ids["quote"]
    assert any(name.startswith("column_") for name in ids["comparison"])
    # The rule is what makes a divider read as a divider; it keeps that while
    # still carrying its points, which it used to discard.
    assert "rule" in ids["section"]
    assert ids["bullets"] != ids["statistic"] != ids["quote"]


# Every slide is planned with two to four points and this layout rendered none
# of them, so a section slide came back holding a title and a purpose and
# nothing else - three of five slides in one real deck. No layout may silently
# discard planned content.
def test_section_slide_renders_its_points_instead_of_dropping_them():
    theme = default_theme()
    planned = _slide(
        layout="section",
        points=["Kennedy set the goal in 1961", "NASA grew to 400,000 people"],
    )

    spec = compile_slide(planned, "slide_section", theme)

    rendered = [e.text for e in spec.elements if isinstance(e, TextElement)]
    for point in planned.points:
        assert point in rendered
    # It is still a divider, not a bullets slide: no markers, and centred.
    assert not any("marker" in e.element_id for e in spec.elements)
    assert all(e.align == "center" for e in spec.elements if isinstance(e, TextElement))


# A layout missing the content it needs degrades rather than rendering an empty
# panel, so a partial plan still produces a usable slide.
def test_incomplete_layouts_fall_back_to_bullets():
    theme = default_theme()

    no_value = compile_slide(_slide(layout="statistic"), "slide_a", theme)
    no_quote = compile_slide(_slide(layout="quote"), "slide_b", theme)

    assert any("_point_" in e.element_id for e in no_value.elements)
    assert not any("stat_value" in e.element_id for e in no_value.elements)
    assert any("_point_" in e.element_id for e in no_quote.elements)
    assert not any(e.element_id.endswith("_quote") for e in no_quote.elements)


# Every layout is subject to the same containment rule the bullets layout is.
def test_no_layout_places_anything_off_the_slide():
    theme = default_theme()
    cases = [
        _slide(layout="section"),
        _slide(layout="statistic", statistic_value="1,250", statistic_label="hives"),
        _slide(
            layout="quote",
            quote="A long quotation that runs on for a while to force wrapping "
            "across several rendered lines in the preview and the deck.",
            quote_attribution="Someone Notable, Author of Something",
        ),
        _slide(
            layout="comparison",
            comparison_left_heading="Before",
            comparison_right_heading="After",
        ),
    ]
    for index, planned in enumerate(cases):
        spec = compile_slide(planned, f"slide_{index:03d}", theme)
        for element in spec.elements:
            assert element.x + element.w <= SLIDE_WIDTH + 0.01, planned.layout
            assert element.y + element.h <= SLIDE_HEIGHT + 0.01, planned.layout


def test_comparison_splits_points_across_both_columns():
    spec = compile_slide(
        _slide(
            layout="comparison",
            comparison_left_heading="Rooftop",
            comparison_right_heading="Ground",
        ),
        "slide_001",
        default_theme(),
    )
    left = [e for e in spec.elements if "_point_01" in e.element_id]
    right = [e for e in spec.elements if "_point_02" in e.element_id]

    assert left
    assert right
    # Columns do not overlap horizontally.
    assert max(e.x + e.w for e in left) <= min(e.x for e in right) + 0.01


# Charts and tables existed in the type system and the renderer but the planner
# could never emit them, so a deck asking for a comparison table got prose.
def test_chart_layout_emits_a_native_editable_chart():
    spec = compile_slide(
        _slide(
            layout="chart",
            chart_kind="column",
            chart_categories=["2024", "2025", "2026"],
            chart_series=[PlannedSeries(name="Hives", values=[120.0, 180.0, 265.0])],
            chart_axis_label="Registered hives",
        ),
        "slide_001",
        default_theme(),
    )
    charts = [e for e in spec.elements if isinstance(e, ChartElement)]

    assert len(charts) == 1
    assert charts[0].categories == ["2024", "2025", "2026"]
    assert charts[0].series[0].values == [120.0, 180.0, 265.0]
    # One series needs no legend; the data is the label.
    assert charts[0].show_legend is False


def test_table_layout_emits_a_native_editable_table():
    spec = compile_slide(
        _slide(
            layout="table",
            table_headers=["Site", "Yield"],
            table_rows=[["Rooftop", "24 kg"], ["Ground", "19 kg"]],
        ),
        "slide_001",
        default_theme(),
    )
    tables = [e for e in spec.elements if isinstance(e, TableElement)]

    assert len(tables) == 1
    assert tables[0].headers == ["Site", "Yield"]
    assert len(tables[0].rows) == 2


# Misaligned data would raise inside the element type and lose the whole slide,
# so the compiler decides the fallback before building it.
def test_misaligned_chart_and_table_data_fall_back_to_bullets():
    theme = default_theme()
    ragged_chart = compile_slide(
        _slide(
            layout="chart",
            chart_kind="column",
            chart_categories=["A", "B", "C"],
            chart_series=[PlannedSeries(name="S", values=[1.0, 2.0])],
        ),
        "slide_a",
        theme,
    )
    ragged_table = compile_slide(
        _slide(
            layout="table",
            table_headers=["One", "Two"],
            table_rows=[["only one cell"]],
        ),
        "slide_b",
        theme,
    )

    assert not [e for e in ragged_chart.elements if isinstance(e, ChartElement)]
    assert any("_point_" in e.element_id for e in ragged_chart.elements)
    assert not [e for e in ragged_table.elements if isinstance(e, TableElement)]
    assert any("_point_" in e.element_id for e in ragged_table.elements)


def test_a_pie_chart_with_several_series_falls_back():
    spec = compile_slide(
        _slide(
            layout="chart",
            chart_kind="pie",
            chart_categories=["A", "B"],
            chart_series=[
                PlannedSeries(name="One", values=[1.0, 2.0]),
                PlannedSeries(name="Two", values=[3.0, 4.0]),
            ],
        ),
        "slide_001",
        default_theme(),
    )

    assert not [e for e in spec.elements if isinstance(e, ChartElement)]


def test_data_layouts_stay_on_the_slide():
    theme = default_theme()
    cases = [
        _slide(
            layout="chart",
            chart_kind="line",
            chart_categories=[str(year) for year in range(2019, 2027)],
            chart_series=[
                PlannedSeries(name=f"Series {index}", values=[float(index)] * 8)
                for index in range(1, 4)
            ],
        ),
        _slide(
            layout="table",
            table_headers=["A", "B", "C", "D", "E"],
            table_rows=[[f"r{row}c{col}" for col in range(5)] for row in range(8)],
        ),
    ]
    for index, planned in enumerate(cases):
        spec = compile_slide(planned, f"slide_{index:03d}", theme)
        for element in spec.elements:
            assert element.x + element.w <= SLIDE_WIDTH + 0.01, planned.layout
            assert element.y + element.h <= SLIDE_HEIGHT + 0.01, planned.layout


# An image is attached later at x=8.45, so every content layout must yield that
# column. Only the bullets layout used to, so a chart, table, comparison, or
# statistic slide had its content run underneath the picture.
def test_every_layout_clears_the_image_column_when_a_visual_is_expected():
    theme = default_theme()
    cases = [
        _slide(layout="bullets"),
        _slide(layout="statistic", statistic_value="35%", statistic_label="forage"),
        _slide(layout="quote", quote="Cities need bees.", quote_attribution="A keeper"),
        _slide(
            layout="comparison",
            comparison_left_heading="Rooftop",
            comparison_right_heading="Ground",
        ),
        _slide(
            layout="chart",
            chart_kind="column",
            chart_categories=["2024", "2025"],
            chart_series=[PlannedSeries(name="Hives", values=[1.0, 2.0])],
        ),
        _slide(
            layout="table",
            table_headers=["Site", "Yield"],
            table_rows=[["Rooftop", "24 kg"]],
        ),
    ]
    for planned in cases:
        expecting = planned.model_copy(
            update={"visual_priority": 3, "visual_prompt": "a rooftop apiary"}
        )
        spec = compile_slide(expecting, "slide_001", theme)
        for element in spec.elements:
            # The picture occupies this rectangle; see attach_image. The title
            # band legitimately spans the full width because it sits above it.
            overlaps = (
                element.x < 12.85
                and element.x + element.w > 8.45
                and element.y < 6.35
                and element.y + element.h > 1.95
            )
            assert not overlaps, (
                f"{planned.layout}: {element.element_id} overlaps the image"
            )


def test_layouts_use_the_full_width_without_an_expected_visual():
    spec = compile_slide(
        _slide(
            layout="table",
            table_headers=["Site", "Yield"],
            table_rows=[["Rooftop", "24 kg"]],
        ),
        "slide_001",
        default_theme(),
    )
    table = next(e for e in spec.elements if isinstance(e, TableElement))

    assert table.w > 8.0
