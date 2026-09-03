"""The tool catalog: a cheap index in every decision, definitions on demand.

Every tool the router could choose used to be sent in full on every turn -
fourteen built-ins, web search, each MCP alias, and one per skill a person
has taught. Two things go wrong as that list grows, and Anthropic measured
both when building tool search for its own API: the definitions crowd the
context (about 55k tokens for a five-server setup, cut by over 85%), and
selection accuracy falls away once a model is choosing among more than
thirty to fifty tools. OpenAI's deferred tool surfaces work the same way and
add one instruction worth keeping: the namespace tells the model what to
load, the description tells it how to use what it loaded.

So: a one-line index grouped by family, a core that stays loaded, and a
search that hands back the few definitions a turn needs. Anthropic runs that
search server-side; their docs describe the client-side form, which is what
this is, because AniOS routes on its own model.

Two things this module deliberately does not do. It does not decide which
tools are core or which need a picture - the rows say that themselves
(`BuiltinTool.core`, `.needs_picture`, `.family`), because a set of tool
names written out here would go stale the day a tool is renamed and nothing
would fail loudly. And it does not rank on words alone: lexical matching
misses the paraphrase people actually type ("get this to Jen by Friday"
shares no word with "write a PDF"), so an embedding ranking runs beside BM25
and the two are fused. The embedder is the one already deployed for memory;
where it is missing or fails, BM25 alone still answers.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# How many tools a search hands back. Anthropic's returns five by default;
# the same number suits a catalog an order of magnitude smaller than the
# thousands that feature is built for.
DEFAULT_LIMIT = 5

# Embeddings for tool text, kept between turns: the catalog is nearly the
# same list every time, so the steady state is one query embedding per
# search. Bounded because a person's skills come and go.
_VECTORS: OrderedDict[str, list[float]] = OrderedDict()
_VECTOR_CACHE_MAX = 512

# Words that carry no signal in a corpus of tool descriptions: every entry
# has them, so they only add noise to a short query.
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


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One tool as the catalog knows it: how it is named, what it is for."""

    name: str
    description: str
    arguments: tuple[str, ...] = ()
    family: str = ""
    definition: dict[str, Any] = field(default_factory=dict, compare=False)

    # The text a search matches on: the name (split at its separators), the
    # family, the description and the argument names. Anthropic's tool search
    # reads the same fields, which is why a family prefix lets one search
    # pull a whole group.
    def searchable(self) -> str:
        return " ".join(
            (
                self.name.replace("_", " ").replace("-", " "),
                self.family,
                self.description,
                " ".join(self.arguments),
            )
        )

    # The one line the model sees for a tool it has not been handed. The
    # first sentence is what the tool's author wrote to say when it applies,
    # so it is the sentence worth spending.
    def index_line(self, width: int = 150) -> str:
        first = self.description.strip().split(". ")[0].strip().rstrip(".")
        return f"- {self.name}: {first[:width]}"


@dataclass(frozen=True, slots=True)
class Catalog:
    entries: tuple[CatalogEntry, ...] = ()

    def __len__(self) -> int:
        return len(self.entries)

    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.entries)

    def by_name(self, name: str) -> CatalogEntry | None:
        return next((entry for entry in self.entries if entry.name == name), None)

    # The index, grouped by family so the model reads a short list of
    # neighbourhoods rather than a flat wall - OpenAI's namespace guidance,
    # and it is how a person thinks about them anyway.
    def index(self) -> str:
        grouped: OrderedDict[str, list[CatalogEntry]] = OrderedDict()
        for entry in self.entries:
            grouped.setdefault(entry.family or "other", []).append(entry)
        lines: list[str] = []
        for family, entries in grouped.items():
            lines.append(f"{family}:")
            lines.extend(f"  {entry.index_line()}" for entry in entries)
        return "\n".join(lines)

    # The tools the model asked for by name, in the catalogue's own order.
    # This is the path that should carry most turns: the whole index is in
    # front of the model, so which tool it needs is a judgement it can make
    # itself - the repository's rule is that meaning is decided by a model,
    # never by a pattern, and a lexical ranking deciding which tools the
    # model may even see would be exactly that.
    def named(self, names: list[str] | tuple[str, ...]) -> tuple[CatalogEntry, ...]:
        wanted = {str(name).strip() for name in names if str(name).strip()}
        if not wanted:
            return ()
        return tuple(entry for entry in self.entries if entry.name in wanted)

    # The fallback, for a turn where the model described what it needed
    # instead of naming it.
    #
    # Two rankings, interleaved rather than fused into one score. BM25
    # catches the exact word a person used; the embedding catches a request
    # that shares no word with the tool's description at all. Fusing them
    # would let a spurious word match ("get this to Jen" scoring on
    # get_weather) outrank the true meaning, and that is the ranking
    # deciding what the model may see - which is the thing this repository
    # does not do. Interleaving keeps the head of both rankings, and the
    # model chooses from the shortlist. With no embedder, words answer alone.
    def search(
        self, query: str, limit: int = DEFAULT_LIMIT, embedder: Embedder | None = None
    ) -> tuple[CatalogEntry, ...]:
        if not query.strip() or not self.entries:
            return ()
        rankings = [self._lexical(query)]
        if embedder is not None:
            rankings.append(self._semantic(query, embedder))
        shortlist: list[CatalogEntry] = []
        seen: set[str] = set()
        for position in range(max((len(ranking) for ranking in rankings), default=0)):
            for ranking in rankings:
                if position >= len(ranking):
                    continue
                entry = ranking[position]
                if entry.name in seen:
                    continue
                seen.add(entry.name)
                shortlist.append(entry)
                if len(shortlist) >= max(1, limit):
                    return tuple(shortlist)
        return tuple(shortlist)

    # BM25 over the catalog, written out rather than added as a dependency:
    # twenty short documents, and the whole of it is the loop below.
    def _lexical(self, query: str, k1: float = 1.5, b: float = 0.75) -> list[CatalogEntry]:
        wanted = _terms(query)
        if not wanted:
            return []
        documents = [_terms(entry.searchable()) for entry in self.entries]
        lengths = [len(document) for document in documents]
        average = (sum(lengths) / len(lengths)) or 1.0
        appears: Counter[str] = Counter()
        for document in documents:
            appears.update(set(document))
        scored: list[tuple[float, int, CatalogEntry]] = []
        for position, (entry, document, length) in enumerate(
            zip(self.entries, documents, lengths, strict=True)
        ):
            counts = Counter(document)
            score = 0.0
            for term in wanted:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                # +1 inside the log keeps a term every tool carries from
                # scoring negatively, which the textbook form allows.
                idf = math.log(1 + (len(documents) - appears[term] + 0.5) / (appears[term] + 0.5))
                score += idf * (frequency * (k1 + 1)) / (frequency + k1 * (1 - b + b * length / average))
            if score > 0:
                scored.append((score, -position, entry))
        scored.sort(reverse=True)
        return [entry for _, _, entry in scored]

    # The same catalog ordered by meaning. Failure is not an error here: the
    # lexical ranking already answered, and a search that waits on a slow
    # embedder to say the same thing is worse than one that does not.
    def _semantic(self, query: str, embedder: Embedder) -> list[CatalogEntry]:
        texts = [entry.searchable() for entry in self.entries]
        try:
            missing = [text for text in texts if text not in _VECTORS]
            if missing:
                for text, vector in zip(missing, embedder.embed_texts(missing), strict=True):
                    _VECTORS[text] = vector
                while len(_VECTORS) > _VECTOR_CACHE_MAX:
                    _VECTORS.popitem(last=False)
            asked = embedder.embed_texts([query])[0]
        except Exception:
            logger.warning("Catalogue embedding unavailable; ranking on words alone", exc_info=True)
            return []
        scored = [
            (_cosine(asked, _VECTORS[text]), -position, entry)
            for position, (entry, text) in enumerate(zip(self.entries, texts, strict=True))
        ]
        scored.sort(reverse=True)
        return [entry for _, _, entry in scored]


# Drop the cached tool vectors. The cache is keyed on a tool's text, which
# is right while one embedder answers for the life of a process; swap the
# embedding model and the old vectors would be read as the new model's.
def clear_vector_cache() -> None:
    _VECTORS.clear()


def _cosine(one: list[float], other: list[float]) -> float:
    if not one or not other or len(one) != len(other):
        return 0.0
    dot = sum(a * b for a, b in zip(one, other, strict=True))
    left = math.sqrt(sum(a * a for a in one))
    right = math.sqrt(sum(b * b for b in other))
    return dot / (left * right) if left and right else 0.0


# The catalog for a set of tool definitions, in the order they were offered.
# `families` names the family of any tool that has one; a skill or an MCP
# alias has none of its own and is grouped by what it is.
def build_catalog(
    definitions: list[dict[str, Any]], families: dict[str, str] | None = None
) -> Catalog:
    known = families or {}
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
                family=known.get(name) or ("skills" if name.startswith("skill__") else "other"),
                definition=definition,
            )
        )
    return Catalog(tuple(entries))


# The one tool that is never deferred: how the model asks for the rest.
#
# Named for what it does to the catalog rather than for what it finds, so it
# cannot be confused with `search_web` (the internet) or `search_history`
# (past conversations).
FIND_TOOLS = "find_tools"

FIND_TOOLS_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": FIND_TOOLS,
        "description": (
            "Look up tools that are listed in the catalogue but not yet loaded, "
            "and load them so they can be called. Use it when the message asks "
            "for something one of the catalogued tools does and that tool is "
            "not already available on this turn. Name the tools you want from "
            "the catalogue above; describe what you need in plain words only "
            "when none of the names is obviously right."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "The tools to load, named exactly as the catalogue lists them. "
                        "Prefer this: you can read the catalogue."
                    ),
                },
                "needed": {
                    "type": "string",
                    "description": (
                        "What the turn needs a tool for, in a few words - used only "
                        "when no name is given."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
}


# The turn's tools, split into what is handed to the model and what is left
# in the catalog for it to find. Which names are core and which need a
# picture is the caller's to say, read from the rows themselves.
def defer_tools(
    definitions: list[dict[str, Any]],
    core: frozenset[str],
    picture_tools: frozenset[str],
    picture_in_view: bool,
    families: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], Catalog]:
    keep = core | (picture_tools if picture_in_view else frozenset())
    loaded: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for definition in definitions:
        function = definition.get("function") if isinstance(definition, dict) else None
        name = str((function or {}).get("name") or "")
        (loaded if name in keep else deferred).append(definition)
    # Nothing to search for is not worth a search tool.
    if not deferred:
        return definitions, Catalog()
    loaded.append(FIND_TOOLS_DEFINITION)
    return loaded, build_catalog(deferred, families)


# What the model is told about the tools it has not been handed.
def catalog_block(catalog: Catalog) -> str:
    if not len(catalog):
        return ""
    return (
        "Tools not loaded on this turn, by family, one line each. To use one, "
        f"call {FIND_TOOLS} with what you need in plain words; its full "
        "definition is then available to call.\n" + catalog.index()
    )


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
