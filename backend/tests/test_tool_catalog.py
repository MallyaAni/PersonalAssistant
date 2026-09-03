"""The tool catalog: a one-line index, a search that finds by meaning rather
than by name, and a split that keeps the most-used tools loaded.

The router is handed more tools every time someone teaches a skill or an MCP
server is connected, and selection accuracy falls away as that list grows.
This is the mechanism that keeps the list short: the shape Anthropic's tool
search uses, implemented on our side because we route on our own model.
"""
import pytest

from backend.tools.catalog import (
    FIND_TOOLS,
    clear_vector_cache,
    build_catalog,
    catalog_block,
    defer_tools,
    loaded_block,
)
from backend.tools.registry import core_tool_names, picture_tool_names, tool_families

CATALOGUED = [
    "search_web",
    "search_history",
    "manage_tasks",
    "schedule_task",
    "generate_image",
    "edit_image",
    "create_document",
    "manage_check_ins",
    "create_diagram",
    "skill__morning-brief",
    "get_weather",
]

# The vector cache is keyed on a tool's text and lives for the process, so
# two tests with different stand-in embedders would read each other's.
@pytest.fixture(autouse=True)
def _fresh_vectors():
    clear_vector_cache()
    yield
    clear_vector_cache()


CORE = core_tool_names()
PICTURES = picture_tool_names()
FAMILIES = tool_families()


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
    catalog = build_catalog(DEFINITIONS, FAMILIES)
    lines = catalog.index().splitlines()
    # Grouped by family: a heading, then indented one-line entries.
    entries = [line for line in lines if line.strip().startswith("- ")]
    assert len(entries) == len(DEFINITIONS)
    assert all(len(line) < 190 for line in lines)
    assert {line.strip()[2:].split(":")[0] for line in entries} == set(catalog.names())
    assert "documents:" in lines and "pictures:" in lines


def test_the_model_names_the_tools_it_read_in_the_index():
    catalog = build_catalog(DEFINITIONS, FAMILIES)
    found = catalog.named(["generate_image", "create_document"])
    assert [entry.name for entry in found] == ["generate_image", "create_document"]
    assert catalog.named(["no_such_tool"]) == () and catalog.named([]) == ()


# The words path is the fallback for a turn that described the need.
def test_search_finds_the_tool_by_what_the_person_asked_for():
    catalog = build_catalog(DEFINITIONS, FAMILIES)
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
    catalog = build_catalog(DEFINITIONS, FAMILIES)
    # "cadence" appears only as an argument name of schedule_task.
    assert catalog.search("cadence")[0].name == "schedule_task"
    assert catalog.search("") == ()
    assert catalog.search("xylophone porcupine") == ()


def test_the_split_keeps_the_most_used_loaded_and_defers_the_rest():
    loaded, catalog = defer_tools(DEFINITIONS, CORE, PICTURES, False, FAMILIES)
    names = {tool["function"]["name"] for tool in loaded}
    # The core comes from the rows themselves, so this cannot drift when a
    # tool is renamed: every core tool present in the fixture is loaded.
    assert (CORE & {d["function"]["name"] for d in DEFINITIONS}) <= names, names
    assert "search_web" in names and "search_history" in names
    assert FIND_TOOLS in names
    assert "generate_image" not in names and "generate_image" in catalog.names()
    # Everything is either loaded or catalogued; nothing is lost.
    assert names - {FIND_TOOLS} | set(catalog.names()) == {
        definition["function"]["name"] for definition in DEFINITIONS
    }


def test_the_picture_tools_load_only_when_a_picture_is_in_view():
    without, _ = defer_tools(DEFINITIONS, CORE, PICTURES, False, FAMILIES)
    with_picture, _ = defer_tools(DEFINITIONS, CORE, PICTURES, True, FAMILIES)
    assert "edit_image" not in {tool["function"]["name"] for tool in without}
    assert "edit_image" in {tool["function"]["name"] for tool in with_picture}


def test_nothing_to_defer_leaves_the_tools_exactly_as_they_were():
    core = [definition for definition in DEFINITIONS if definition["function"]["name"] in CORE]
    loaded, catalog = defer_tools(core, CORE, PICTURES, False, FAMILIES)
    assert loaded == core and len(catalog) == 0
    assert FIND_TOOLS not in {tool["function"]["name"] for tool in loaded}


def test_the_blocks_say_what_the_model_can_do_next():
    catalog = build_catalog(DEFINITIONS, FAMILIES)
    block = catalog_block(catalog)
    assert FIND_TOOLS in block and "generate_image" in block
    assert catalog_block(build_catalog([])) == ""
    assert "generate_image" in loaded_block(("generate_image",))
    assert "no catalogued tool" in loaded_block(()).lower()


# The embedding ranking runs beside the lexical one and neither is trusted
# alone: a request that shares no word with the tool's description is what
# the vectors are for, and a missing or broken embedder must not cost the
# turn its answer.
class _Embedder:
    """Stands in for the deployed model. Every tool gets a vector; the one
    the caller says the query means gets the vector closest to the query's."""

    def __init__(self, means: str) -> None:
        self.means = means

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            named = next(
                (name for name in CATALOGUED if text.startswith(name.replace("_", " ").replace("-", " "))),
                "",
            )
            if not named:
                vectors.append([1.0, 0.0])  # the query
            elif named == self.means:
                vectors.append([1.0, 0.05])
            else:
                vectors.append([0.05, 1.0])
        return vectors


class _BrokenEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding service is down")


def test_meaning_can_win_where_no_word_matches():
    catalog = build_catalog(DEFINITIONS, FAMILIES)
    asked = "get this over to Jen by Friday"
    # Lexically this names no tool; on meaning it is a document.
    lexical = catalog.search(asked)
    assert not lexical or lexical[0].name != "create_document", [entry.name for entry in lexical]
    # The shortlist carries the head of both rankings, and the model picks:
    # a ranking is not allowed to decide what the model may see.
    found = catalog.search(asked, embedder=_Embedder("create_document"))
    names = [entry.name for entry in found]
    assert "create_document" in names, names
    assert names[:2] == [lexical[0].name, "create_document"], names


def test_the_shortlist_keeps_the_head_of_both_rankings():
    catalog = build_catalog(DEFINITIONS, FAMILIES)
    found = catalog.search("make a picture of a fox", limit=4, embedder=_Embedder("create_diagram"))
    names = [entry.name for entry in found]
    assert names[0] == "generate_image" and "create_diagram" in names, names
    assert len(names) == len(set(names)) == 4


def test_a_broken_embedder_still_answers_on_words():
    catalog = build_catalog(DEFINITIONS, FAMILIES)
    found = catalog.search("make a picture of a fox", embedder=_BrokenEmbedder())
    assert found and found[0].name == "generate_image"
