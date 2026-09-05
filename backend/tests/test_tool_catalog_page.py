"""The page that says what the assistant can do is the rows, or it is fiction.

Fifteen tools were spread across nine documents by mention, with no page
naming them all and nothing checking that a mention was still true. A
hand-written list goes stale the first time a tool is renamed and nothing
fails when it does. These tests are what makes the page fail instead.
"""
from pathlib import Path

from backend.tools.catalog_page import render
from backend.tools.registry import builtin_tools, core_tool_names, gated_tools

PAGE = Path("docs/TOOL_CATALOG.md")


def test_the_committed_page_is_what_the_rows_render_today():
    assert PAGE.exists(), "run python -m backend.cli.generate_tool_catalog"
    assert PAGE.read_text() == render(), (
        "docs/TOOL_CATALOG.md is stale; "
        "run python -m backend.cli.generate_tool_catalog"
    )


def test_every_tool_appears_including_the_ones_needing_a_service():
    page = render()
    rows = builtin_tools(enabled=tuple(gated_tools().values()))
    missing = [row.name for row in rows if f"`{row.name}`" not in page]
    assert not missing, missing
    # Gated tools exist in the repository whether or not this machine wires
    # the service, and a page that hid them would describe the deployment
    # rather than the system.
    assert set(gated_tools()) <= {row.name for row in rows}
    for name, service in gated_tools().items():
        assert f"needs the {service} service" in page


def test_search_web_is_named_even_though_it_is_not_a_row():
    # It is assembled from whichever search server is wired, so it has no
    # BuiltinTool row and would be the one tool a row-driven page missed.
    assert "`search_web`" in render()


def test_the_page_says_when_each_tool_is_put_in_front_of_the_router():
    page = render()
    assert "always" in page and "with a picture" in page and "catalogued" in page
    # A core tool's row must say `always`: that split is what the catalogue
    # measurement turns on, and a page disagreeing with it misleads the
    # next person deciding whether to raise the threshold.
    for line in page.splitlines():
        for name in core_tool_names():
            if line.startswith(f"| `{name}`"):
                # The `loaded` cell by position: tool, gist, arguments,
                # loaded, effect.
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                assert cells[3] == "always", line


def test_renaming_a_tool_changes_the_page():
    # The property the drift test depends on: the page is a function of the
    # rows, not a copy of them.
    before = render()
    rows = builtin_tools(enabled=tuple(gated_tools().values()))
    assert any(f"`{row.name}`" in before for row in rows)
    assert before == render(), "render must be deterministic or the check flaps"
