"""Render a mermaid flowchart to PNG, for channels with no browser.

A diagram artifact stores mermaid *source*; the web UI renders it
client-side and no rendered bytes exist anywhere server-side - which made
diagrams the one artifact an iMessage bubble could not carry, defeating
their whole point of legible text. This translates mermaid's flowchart
grammar to DOT and lets Graphviz do the layout it has spent thirty years
being good at.

The parser is deliberately a subset: node declarations in the bracket
shapes the spec validator emits ([box], (round), {diamond}, ((circle))),
edges with optional labels, and direction. It is syntax plumbing - the
judgement about what the diagram says happened in the model that wrote
the source. Anything the subset cannot read raises, and the caller sends
the text reply without an image rather than a wrong picture.
"""

import re
import subprocess

_DIRECTION = re.compile(r"^\s*(?:flowchart|graph)\s+(TD|TB|LR|RL|BT)\s*$", re.I)
# A[Label], A(Label), A{Label}, A((Label)) - id then bracketed text.
_NODE = re.compile(
    r"([A-Za-z0-9_]+)\s*(\[\[|\(\(|\[|\(|\{)"
    r"\s*([^\]\)\}]*?)\s*(\]\]|\)\)|\]|\)|\})"
)
# A --> B, A -->|label| B, A --- B, A -.-> B
_EDGE = re.compile(
    r"([A-Za-z0-9_]+)\s*(?:\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\})?\s*"
    r"(-{1,3}\.?-*>?|={2,3}>?)\s*(?:\|([^|]*)\|)?\s*"
    r"([A-Za-z0-9_]+)"
)

_SHAPES = {
    "[": "box",
    "(": "box",  # rounded, styled below
    "{": "diamond",
    "((": "circle",
    "[[": "box",
}


class MermaidUnsupportedError(ValueError):
    """The source is outside the flowchart subset this renderer reads."""


# The body lines as (labels, shapes, edges). Split out so the grammar walk
# and the DOT emission each stay simple enough to read at a glance.
def _parse_body(
    lines: list[str],
) -> tuple[dict[str, str], dict[str, str], list[tuple[str, str, str]]]:
    labels: dict[str, str] = {}
    shapes: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    for line in lines:
        if line.startswith("%%"):
            continue
        for node_id, opener, text, _closer in _NODE.findall(line):
            if text:
                labels[node_id] = text
                shapes[node_id] = _SHAPES.get(opener, "box")
        edge = _EDGE.search(line)
        if edge:
            edges.append((edge.group(1), edge.group(4), (edge.group(3) or "").strip()))
        elif "-->" in line or "---" in line:
            raise MermaidUnsupportedError(f"unreadable edge line: {line[:60]}")
    return labels, shapes, edges


# Mermaid flowchart source to DOT. Raises MermaidUnsupportedError for anything
# outside the subset, so a wrong picture is never sent in place of a right
# one.
def flowchart_to_dot(source: str) -> str:
    lines = [line.strip() for line in source.strip().splitlines() if line.strip()]
    if not lines or not _DIRECTION.match(lines[0]):
        raise MermaidUnsupportedError("not a flowchart the subset reads")
    rankdir = {"TD": "TB", "TB": "TB", "LR": "LR", "RL": "RL", "BT": "BT"}[
        _DIRECTION.match(lines[0]).group(1).upper()
    ]

    labels, shapes, edges = _parse_body(lines[1:])
    if not edges and not labels:
        raise MermaidUnsupportedError("no nodes or edges found")

    def quote(value: str) -> str:
        return '"' + value.replace('"', r"\"") + '"'

    out = [
        f"digraph G {{ rankdir={rankdir};",
        # Readable at phone size: real fonts, filled boxes, breathing room.
        'node [fontname="Helvetica" fontsize=13 style="filled,rounded" '
        'fillcolor="#eef3fb" color="#3b5b92" shape=box margin="0.18,0.1"];',
        'edge [fontname="Helvetica" fontsize=11 color="#556" arrowsize=0.8];',
        "bgcolor=white; pad=0.3; nodesep=0.4; ranksep=0.5;",
    ]
    for node_id, label in labels.items():
        shape = shapes.get(node_id, "box")
        extra = f" shape={shape}" if shape != "box" else ""
        out.append(f"{quote(node_id)} [label={quote(label)}{extra}];")
    for left, right, label in edges:
        tail = f" [label={quote(label)}]" if label else ""
        out.append(f"{quote(left)} -> {quote(right)}{tail};")
    out.append("}")
    return "\n".join(out)


# DOT to PNG bytes via the graphviz binary. A missing binary or a layout
# failure raises; the caller degrades to a text-only reply.
def render_flowchart_png(source: str, timeout: int = 20) -> bytes:
    dot = flowchart_to_dot(source)
    completed = subprocess.run(
        ["dot", "-Tpng", "-Gdpi=144"],
        input=dot.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0 or not completed.stdout.startswith(b"\x89PNG"):
        raise MermaidUnsupportedError(
            f"graphviz refused the layout: {completed.stderr[:120]!r}"
        )
    return completed.stdout
