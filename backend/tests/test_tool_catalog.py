"""The tool catalog: a one-line index, a search that finds by meaning rather
than by name, and a split that keeps the most-used tools loaded.

The router is handed more tools every time someone teaches a skill or an MCP
server is connected, and selection accuracy falls away as that list grows.
This is the mechanism that keeps the list short: the shape Anthropic's tool
search uses, implemented on our side because we route on our own model.
"""
from backend.tools.catalog import (
    ALWAYS_LOADED,
    FIND_TOOLS,
    build_catalog,
    catalog_block,
    defer_tools,
    loaded_block,
)


def _definition(name: str, description: str, arguments: tuple[str, ...] = ()) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {argument: {"type": "string"} for argument in arguments},
            },
        },
    }


DEFINITIONS = [
    _definition("search_web", "Search the internet for current information.", ("query",)),
    _definition("search_history", "Search past conversations for something said before.", ("query",)),
    _definition("manage_tasks", "List, cancel, pause or reschedule tasks already scheduled.", ("operation",)),
    _definition("schedule_task", "Set something up to happen later or on a schedule.", ("instruction", "cadence")),
    _definition("generate_image", "Make a picture from a description.", ("prompt",)),
    _definition("edit_image", "Change a picture the person sent or the assistant made.", ("instruction",)),
    _definition("create_document", "Write a PDF or Word document from what was just discussed.", ("title", "format")),
    _definition("manage_check_ins", "Check-ins: coming back later to ask how something went.", ("mode",)),
    _definition("create_diagram", "Draw a diagram of a system or a process.", ("subject",)),
    _definition("skill__morning-brief", "The person's skill 'Morning brief': the weather, their tasks, one thing to look forward to."),
    _definition("get_weather", "The forecast for a place.", ("location",)),
]


def test_the_index_is_one_line_per_tool_and_names_every_one():
    catalog = build_catalog(DEFINITIONS)
    lines = catalog.index().splitlines()
    assert len(lines) == len(DEFINITIONS)
    assert all(line.startswith("- ") and len(line) < 180 for line in lines)
    assert {line.split(":")[0][2:] for line in lines} == set(catalog.names())


def test_search_finds_the_tool_by_what_the_person_asked_for():
    catalog = build_catalog(DEFINITIONS)
    for asked, expected in [
        ("make a picture of a fox", "generate_image"),
        ("draw a diagram of the deploy pipeline", "create_diagram"),
        ("put that in a PDF", "create_document"),
        ("brief me on my morning", "skill__morning-brief"),
        ("what did we say about the trip before", "search_history"),
        ("check in with me on Friday", "manage_check_ins"),
        ("what is the forecast", "get_weather"),
    ]:
        found = catalog.search(asked)
        assert found, asked
        assert found[0].name == expected, (asked, [entry.name for entry in found])


def test_search_reads_argument_names_and_returns_nothing_for_nothing():
    catalog = build_catalog(DEFINITIONS)
    # "cadence" appears only as an argument name of schedule_task.
    assert catalog.search("cadence")[0].name == "schedule_task"
    assert catalog.search("") == ()
    assert catalog.search("xylophone porcupine") == ()


def test_the_split_keeps_the_most_used_loaded_and_defers_the_rest():
    loaded, catalog = defer_tools(DEFINITIONS, picture_in_view=False)
    names = {tool["function"]["name"] for tool in loaded}
    assert ALWAYS_LOADED <= names, names
    assert FIND_TOOLS in names
    assert "generate_image" not in names and "generate_image" in catalog.names()
    # Everything is either loaded or catalogued; nothing is lost.
    assert names - {FIND_TOOLS} | set(catalog.names()) == {
        definition["function"]["name"] for definition in DEFINITIONS
    }


def test_the_picture_tools_load_only_when_a_picture_is_in_view():
    without, _ = defer_tools(DEFINITIONS, picture_in_view=False)
    with_picture, _ = defer_tools(DEFINITIONS, picture_in_view=True)
    assert "edit_image" not in {tool["function"]["name"] for tool in without}
    assert "edit_image" in {tool["function"]["name"] for tool in with_picture}


def test_nothing_to_defer_leaves_the_tools_exactly_as_they_were():
    core = [definition for definition in DEFINITIONS if definition["function"]["name"] in ALWAYS_LOADED]
    loaded, catalog = defer_tools(core, picture_in_view=False)
    assert loaded == core and len(catalog) == 0
    assert FIND_TOOLS not in {tool["function"]["name"] for tool in loaded}


def test_the_blocks_say_what_the_model_can_do_next():
    catalog = build_catalog(DEFINITIONS)
    block = catalog_block(catalog)
    assert FIND_TOOLS in block and "generate_image" in block
    assert catalog_block(build_catalog([])) == ""
    assert "generate_image" in loaded_block(("generate_image",))
    assert "no catalogued tool" in loaded_block(()).lower()
