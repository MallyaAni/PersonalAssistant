import asyncio
import json
import re
from typing import Any

from backend.agents.diagram.prompts import DIAGRAM_SYSTEM
from backend.artifacts.types import DiagramSpecification
from backend.core.interfaces import DiagramProvider
from backend.core.llm import LLMClient

MAX_DIAGRAM_SOURCE_CHARS = 8_000
MAX_DIAGRAM_LINES = 120
MAX_DIAGRAM_TITLE_CHARS = 160
UNSAFE_MERMAID_PATTERN = re.compile(
    r"(?im)(?:^\s*(?:click|href)\b|%%\{|javascript\s*:|https?://|"
    r"<\s*/?\s*[a-z][^>]*>)"
)
DIAGRAM_PREFIXES = {
    "flowchart": "flowchart",
    "graph": "flowchart",
    "sequencediagram": "sequence",
    "statediagram-v2": "state",
    "classdiagram": "class",
    "erdiagram": "entity_relationship",
    "mindmap": "mindmap",
    "timeline": "timeline",
    "architecture-beta": "architecture",
}
DIAGRAM_DECLARATIONS = {
    "flowchart": "flowchart TD",
    "flowchart td": "flowchart TD",
    "flowchart lr": "flowchart LR",
    "graph": "graph TD",
    "graph td": "graph TD",
    "graph lr": "graph LR",
    "sequence": "sequenceDiagram",
    "sequence diagram": "sequenceDiagram",
    "state": "stateDiagram-v2",
    "state diagram": "stateDiagram-v2",
    "class": "classDiagram",
    "class diagram": "classDiagram",
    "entity relationship": "erDiagram",
    "er diagram": "erDiagram",
    "erd": "erDiagram",
    "mindmap": "mindmap",
    "timeline": "timeline",
    "architecture": "architecture-beta",
}


# Extract the first JSON object from a model response without evaluating code.
def _extract_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Diagram provider did not return a JSON object")
    parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Diagram provider JSON must be an object")
    return parsed


# Resolve an optional model-declared diagram type to a safe Mermaid header.
def _declared_mermaid_header(payload: dict[str, Any]) -> str | None:
    declared_type = payload.get("diagram_type")
    if not isinstance(declared_type, str):
        return None
    normalized_type = re.sub(r"\s+", " ", declared_type.strip().lower())
    return DIAGRAM_DECLARATIONS.get(normalized_type)


# Return one bounded non-empty artifact title from provider output.
def _validated_title(payload: dict[str, Any]) -> str:
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Diagram title is required")
    title = title.strip()
    if len(title) > MAX_DIAGRAM_TITLE_CHARS:
        raise ValueError("Diagram title is too long")
    return title


# Decoding grammar for the reply envelope. It cannot judge Mermaid validity, but
# it does guarantee a well-formed JSON object with correctly escaped newlines in
# `source` -- the specific failure the correction retry below was written for.
_DIAGRAM_REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_DIAGRAM_TITLE_CHARS,
        },
        # One array element per Mermaid statement, rather than one string with
        # escaped newlines in it.
        #
        # Asking for the newlines was the whole failure. Measured 2026-08-29 on
        # the request a live group chat had just failed on: with the string
        # field the model returned everything on one line - "flowchart TD
        # A[Source] --> B[Basin] B --> C[Channel]" - four times in five, and
        # rewording the instruction only traded that for a bare "flowchart TD"
        # with no body at all. It reliably drew the right graph and reliably
        # would not put an escape sequence inside a JSON string. An array needs
        # no escape, and the engine's grammar enforces the shape, so the
        # failure cannot happen rather than being asked not to.
        "lines": {
            "type": "array",
            "minItems": 2,
            "maxItems": MAX_DIAGRAM_LINES,
            "items": {"type": "string", "minLength": 1, "maxLength": 400},
        },
        "diagram_type": {"type": "string", "enum": sorted(DIAGRAM_DECLARATIONS)},
    },
    "required": ["title", "lines"],
    "additionalProperties": False,
}


# `<br>`, `<br/>`, `<br />` — any spelling of an HTML line break, used by the
# model as a line separator.
_HTML_LINE_BREAK = re.compile(r"\s*<\s*br\s*/?\s*>\s*", re.IGNORECASE)


# Validate and normalize a provider-produced Mermaid specification.
def validate_diagram_specification(payload: dict[str, Any]) -> DiagramSpecification:
    title = _validated_title(payload)
    # `lines` is what the model is asked for now, because an array needs no
    # escape sequence. `source` is still accepted: it is what a stored artifact
    # from before 2026-08-29 holds, and what a caller assembling a diagram in
    # code naturally writes.
    listed = payload.get("lines")
    if isinstance(listed, list) and listed:
        source = "\n".join(
            str(line).strip() for line in listed if str(line).strip()
        )
    else:
        source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Mermaid source is required")

    source = source.strip().replace("\r\n", "\n")
    # A line break written as HTML. Inside a JSON string the model reaches for
    # <br/> instead of an escaped newline, and the result is rejected whole —
    # measured across eight varied requests, the graph itself was correct every
    # time it did this: right nodes, right branches, right labels. Repaired
    # here rather than answered with a larger model, because nothing about the
    # reasoning was wrong.
    source = _HTML_LINE_BREAK.sub("\n", source)
    # A whole flowchart on one line, statements divided by semicolons. Mermaid
    # accepts that form; this validator's "must contain a body" check counts
    # lines and does not, so a correct diagram was refused. A live group chat
    # got "I couldn't create that diagram" twice on 2026-08-29, and the request
    # reproduced it four times out of four.
    #
    # Repaired here for the same reason `<br/>` above is: the graph was right
    # every time - right nodes, right edges, right labels - and only the
    # separator differed. Split rather than rejected, and only when there is
    # nothing else to go on, so a source that already has lines is untouched.
    if "\n" not in source and ";" in source:
        source = "\n".join(
            piece.strip() for piece in source.split(";") if piece.strip()
        )
    if source.startswith("```"):
        source = re.sub(r"^```(?:mermaid)?\s*", "", source, flags=re.IGNORECASE)
        source = re.sub(r"\s*```$", "", source).strip()
    if UNSAFE_MERMAID_PATTERN.search(source):
        raise ValueError("Mermaid source contains unsupported active content")

    first_line = source.splitlines()[0].strip().lower()
    prefix = first_line.split(maxsplit=1)[0]
    diagram_type = DIAGRAM_PREFIXES.get(prefix)
    if diagram_type is None:
        declaration = _declared_mermaid_header(payload)
        if declaration is None:
            raise ValueError("Mermaid diagram type is not supported")
        source = f"{declaration}\n{source}"
        diagram_type = DIAGRAM_PREFIXES[declaration.lower().split(maxsplit=1)[0]]
    if len(source) > MAX_DIAGRAM_SOURCE_CHARS:
        raise ValueError("Mermaid source is too large")
    if len(source.splitlines()) > MAX_DIAGRAM_LINES:
        raise ValueError("Mermaid source has too many lines")
    if len(source.splitlines()) < 2:
        raise ValueError("Mermaid diagram must contain a body")
    return DiagramSpecification(
        title=title,
        diagram_type=diagram_type,
        source=source,
    )


class LLMDiagramProvider(DiagramProvider):
    # Keep diagram generation replaceable while reusing the configured local LLM.
    def __init__(self, llm: LLMClient, model_name: str):
        self.llm = llm
        self.model_name = model_name

    # Ask the local model for bounded JSON and retry one invalid format once.
    async def generate(self, query: str) -> DiagramSpecification:
        messages = [
            {
                "role": "system",
                "content": (DIAGRAM_SYSTEM),
            },
            {"role": "user", "content": query},
        ]
        for attempt in range(2):
            result = await asyncio.to_thread(
                self.llm.chat,
                messages,
                2_048,
                response_schema=_DIAGRAM_REPLY_SCHEMA,
                # Greedy, as every other call here is. This one ran at the
                # provider default, so the same request drew a different
                # diagram each time and a failure could not be reproduced long
                # enough to diagnose — eight requests scored 0/8 and then 3/8
                # with nothing changed in between.
                temperature=0.0,
            )
            content = result.get("content")
            try:
                if not isinstance(content, str):
                    raise ValueError("Diagram provider did not return text")
                return validate_diagram_specification(_extract_json_object(content))
            except ValueError as error:
                if attempt == 1:
                    raise ValueError(
                        "Diagram provider did not return a valid specification"
                    ) from error
                messages[0]["content"] += (
                    " Your previous output was invalid. Correct it and return only "
                    "valid JSON. Escape every source newline as \\n and do not use "
                    "any other backslash escape."
                )
        raise AssertionError("Diagram validation retry did not terminate")
