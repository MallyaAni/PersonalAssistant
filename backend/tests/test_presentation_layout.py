import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.presentations.layout import (
    fit_font_size,
    fit_stack_font_size,
    line_count,
    required_height,
)
from backend.presentations.planner import PlannedSlide, compile_slide, default_theme
from backend.presentations.types import (
    SLIDE_HEIGHT,
    SLIDE_WIDTH,
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
    "The shift marks a transition from predetermined paths to dynamic, "
    "software-defined behavior.",
    "Today, machines possess the computational capacity to execute complex "
    "decision-making autonomously.",
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

    assert len(points) == 6
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
    assert "rule" in ids["section"]
    # A section divider is a divider: it carries no bulleted list.
    assert not any("point_" in name for name in ids["section"])
    assert ids["bullets"] != ids["statistic"] != ids["quote"]


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
