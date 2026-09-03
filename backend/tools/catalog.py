"""The tool catalog: a cheap index in every decision, definitions on demand.

Every tool the router could choose used to be sent in full on every turn -
fifteen to twenty schemas, and growing with each skill a person teaches and
each MCP server that is connected. Two things go wrong as that list grows,
and Anthropic measured both for its own tool-search feature: the definitions
crowd the context (a five-server setup costs about 55k tokens before any
work is done), and selection accuracy falls away once a model is choosing
among more than thirty to fifty tools.

The answer there is the one used here: keep a handful of the most-used tools
loaded, put a one-line index of everything else in front of the model, and
let it fetch the full definitions of the few tools a turn actually needs
through a search tool. Anthropic runs that search server-side; the same
docs describe the client-side form, which is what this is - AniOS routes on
its own model, so the catalog, the search and the expansion all live here.

The ranking is BM25 over each tool's name, description and argument names,
written out rather than pulled in as a dependency: the corpus is twenty
short documents, and the whole of it fits in the function below.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# How many tools a search hands back by default. Anthropic's tool search
# returns five; the same number is enough here, where the whole catalog is
# an order of magnitude smaller than the thousands that feature is built for.
DEFAULT_LIMIT = 5

# Words that carry no signal in a corpus of tool descriptions: every one of
# them appears in most entries, so BM25's own IDF would discount them anyway.
# Listed to keep short queries ("what is on tonight") from scoring on them.
_STOP = frozenset(
    """a an the this that these those and or but if then than for to of in on at by with
    from into about as is are was were be been being it its their they them you your i me
    my we us our do does did doing done can could should would will shall may might must
    have has had not no nor so such only own same too very just now here there when where
    what which who whom how why all any both each few more most other some own""".split()
)

_WORD = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> list[str]:
    return [word for word in _WORD.findall((text or "").lower()) if word not in _STOP]


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One tool as the catalog knows it: how it is named, what it is for."""

    name: str
    description: str
    arguments: tuple[str, ...] = ()
    # The whole definition, handed back when the tool is discovered.
    definition: dict[str, Any] = field(default_factory=dict, compare=False)

    # The words a search matches on: the name (split on separators), the
    # description, and the argument names. Anthropic's tool search reads the
    # same four fields, which is why namespaced names ("document_", "image_")
    # let one search pull a whole family.
    def searchable(self) -> list[str]:
        parts = [self.name.replace("_", " "), self.description, " ".join(self.arguments)]
        return _terms(" ".join(parts))

    # The one line the model sees for a tool it has not loaded. The first
    # sentence of the description is what a tool's author wrote to tell the
    # model when to choose it, so it is the sentence worth spending.
    def index_line(self, width: int = 150) -> str:
        first = self.description.strip().split(". ")[0].strip().rstrip(".")
        return f"- {self.name}: {first[:width]}"


# The catalog for one turn, built from the definitions the router would
# otherwise have sent in full.
@dataclass(frozen=True, slots=True)
class Catalog:
    entries: tuple[CatalogEntry, ...] = ()

    def __len__(self) -> int:
        return len(self.entries)

    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.entries)

    def by_name(self, name: str) -> CatalogEntry | None:
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    # The index, as the model sees it. Cheap by construction: one line each.
    def index(self) -> str:
        return "\n".join(entry.index_line() for entry in self.entries)

    # The tools whose words best answer a query, best first.
    #
    # BM25 with the usual k1 and b. A tool scores on the terms it shares with
    # the query, weighted by how rare each term is across the catalog, so
    # "brief me on my morning" finds a "morning brief" skill without either
    # side having to use the other's exact wording.
    def search(self, query: str, limit: int = DEFAULT_LIMIT, k1: float = 1.5, b: float = 0.75) -> tuple[CatalogEntry, ...]:
        wanted = _terms(query)
        if not wanted or not self.entries:
            return ()
        documents = [entry.searchable() for entry in self.entries]
        lengths = [len(document) for document in documents]
        average = (sum(lengths) / len(lengths)) or 1.0
        appears: Counter[str] = Counter()
        for document in documents:
            appears.update(set(document))
        scored: list[tuple[float, int, CatalogEntry]] = []
        for position, (entry, document, length) in enumerate(zip(self.entries, documents, lengths, strict=True)):
            counts = Counter(document)
            score = 0.0
            for term in wanted:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                # +1 inside the log keeps a term that every tool carries from
                # scoring negatively, which the textbook form allows.
                idf = math.log(1 + (len(documents) - appears[term] + 0.5) / (appears[term] + 0.5))
                score += idf * (frequency * (k1 + 1)) / (frequency + k1 * (1 - b + b * length / average))
            if score > 0:
                # Position breaks ties in the catalog's own order, so a search
                # is reproducible rather than dependent on sort stability.
                scored.append((score, -position, entry))
        scored.sort(reverse=True)
        return tuple(entry for _, _, entry in scored[: max(1, limit)])


# The catalog for a set of tool definitions, in the order they were offered.
def build_catalog(definitions: list[dict[str, Any]]) -> Catalog:
    entries: list[CatalogEntry] = []
    for definition in definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "")
        if not name:
            continue
        parameters = function.get("parameters")
        properties = parameters.get("properties") if isinstance(parameters, dict) else None
        arguments = tuple(str(key) for key in properties) if isinstance(properties, dict) else ()
        entries.append(
            CatalogEntry(
                name=name,
                description=str(function.get("description") or ""),
                arguments=arguments,
                definition=definition,
            )
        )
    return Catalog(tuple(entries))


# The one tool that is never deferred: how the model asks for the rest.
#
# Named for what it does to the catalog rather than for what it finds, so it
# cannot be confused with `search_web` (which searches the internet) or
# `search_history` (which searches past conversations) - three tools whose
# names would otherwise all begin with the same word.
FIND_TOOLS = "find_tools"

FIND_TOOLS_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": FIND_TOOLS,
        "description": (
            "Look up tools that are listed in the catalog but not yet loaded, "
            "and load them so they can be called. Use it when the message asks "
            "for something one of the catalogued tools does and that tool is "
            "not already available on this turn. Describe what is needed in "
            "plain words - 'make a picture', 'the person's morning brief', "
            "'add this to their calendar' - rather than guessing a tool name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "needed": {
                    "type": "string",
                    "description": "What the turn needs a tool for, in a few words.",
                }
            },
            "required": ["needed"],
            "additionalProperties": False,
        },
    },
}


# What the model is told about the tools it has not been handed. Kept to one
# line each: the index is paid for on every turn, the definitions are not.
def catalog_block(catalog: Catalog) -> str:
    if not len(catalog):
        return ""
    return (
        "Tools not loaded on this turn, one line each. To use one, call "
        f"{FIND_TOOLS} with what you need in plain words; its full definition "
        "is then available to call.\n" + catalog.index()
    )


# The tools that stay loaded whatever else is deferred, chosen by what this
# system actually routes to. Seven days of live turns (2026-09-03): past
# conversations 46, web search 36, manage scheduled tasks 25, then a long
# tail of nine or fewer. Anthropic's guidance is the same shape - keep the
# three to five most frequently used non-deferred so the common turn needs
# no search at all.
ALWAYS_LOADED = frozenset({"search_web", "search_history", "manage_tasks", "schedule_task"})

# Tools that only make sense with a picture in view. Loaded when there is
# one, deferred when there is not: the interface state already decides
# whether they can be used, so it may as well decide whether they are shown.
WITH_A_PICTURE = frozenset({"edit_image", "show_image", "discuss_image"})


# The turn's tools, split into what is handed to the model and what is left
# in the catalog for it to find.
def defer_tools(
    definitions: list[dict[str, Any]], picture_in_view: bool
) -> tuple[list[dict[str, Any]], Catalog]:
    loaded: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    keep = ALWAYS_LOADED | (WITH_A_PICTURE if picture_in_view else frozenset())
    for definition in definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        name = str((function or {}).get("name") or "")
        (loaded if name in keep else deferred).append(definition)
    # Nothing to search for is not worth a search tool; hand back what came in.
    if not deferred:
        return definitions, Catalog()
    loaded.append(FIND_TOOLS_DEFINITION)
    return loaded, build_catalog(deferred)


# What the model is told once the tools it asked for have been loaded.
def loaded_block(names: tuple[str, ...]) -> str:
    if not names:
        return (
            "No catalogued tool matches what you described. Choose from the "
            "tools you already have, or take no tool."
        )
    return (
        "These tools are now loaded and can be called: "
        + ", ".join(names)
        + ". Call the one this message needs, or take no tool."
    )
