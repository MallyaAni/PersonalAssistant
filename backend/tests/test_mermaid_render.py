"""The flowchart subset renders, and everything outside it refuses loudly.

A diagram artifact stores mermaid source and no rendered bytes - the
browser renders client-side, and an iMessage bubble has no browser, which
made diagrams the one artifact whose whole point (legible text) a phone
could not see. The translator is syntax plumbing: node shapes, edges,
edge labels, direction. A wrong picture is worse than no picture, so
anything unreadable raises rather than guessing.
"""

import shutil

import pytest

from backend.workers.mermaid_render import (
    MermaidUnsupportedError,
    flowchart_to_dot,
    render_flowchart_png,
)

_AGILE = """flowchart TD
  A[Product Backlog] --> B[Sprint Planning]
  B --> C[Sprint Execution]
  C --> D{Daily Standup}
  D --> C
  C --> E[Review]
  E -->|feedback| A
"""


def test_the_real_agile_source_translates_completely():
    dot = flowchart_to_dot(_AGILE)

    assert "rankdir=TB" in dot
    assert '"A" [label="Product Backlog"];' in dot
    assert '"D" [label="Daily Standup" shape=diamond];' in dot
    assert '"E" -> "A" [label="feedback"];' in dot
    assert dot.count("->") == 6


def test_direction_and_round_nodes_survive():
    dot = flowchart_to_dot("graph LR\n  S(Start) --> T((End))")

    assert "rankdir=LR" in dot
    assert '"T" [label="End" shape=circle];' in dot


@pytest.mark.parametrize(
    "source",
    [
        "sequenceDiagram\n  A->>B: hi",
        'pie\n  "a": 1',
        "",
    ],
)
def test_everything_outside_the_subset_refuses(source: str):
    with pytest.raises(MermaidUnsupportedError):
        flowchart_to_dot(source)


@pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz not installed")
def test_graphviz_produces_a_real_png():
    png = render_flowchart_png(_AGILE)

    assert png[:4] == b"\x89PNG"
    assert len(png) > 5_000
