"""Enforce the module boundaries the architecture depends on.

A layering that is only documented erodes. These tests fail when an import
crosses a boundary that the design relies on, so the structure is checked the
same way behaviour is.
"""

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


# Collect every backend module a package imports, ignoring test code.
def imported_modules(package: str) -> dict[pathlib.Path, set[str]]:
    root = BACKEND / package
    found: dict[pathlib.Path, set[str]] = {}
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        found[path] = {m for m in modules if m.startswith("backend.")}
    return found


@pytest.mark.parametrize("forbidden", ["backend.services", "backend.api"])
def test_protocol_layer_does_not_depend_on_orchestration(forbidden):
    # backend.mcp speaks the protocol. If it reaches into services or the API,
    # the transport can no longer be replaced or tested independently.
    for path, modules in imported_modules("mcp").items():
        offending = {m for m in modules if m.startswith(forbidden)}
        assert not offending, f"{path.name} imports {offending}"


@pytest.mark.parametrize("layer", ["mcp", "search", "artifacts", "embeddings"])
def test_lower_layers_do_not_depend_on_the_api(layer):
    for path, modules in imported_modules(layer).items():
        offending = {m for m in modules if m.startswith("backend.api")}
        assert not offending, f"{path.name} imports {offending}"


def test_search_package_holds_only_web_search():
    # Image retrieval and outbound screening previously lived here, which made
    # "search" mean three unrelated things. The list is exact on purpose: every
    # new module under search/ should be a deliberate decision, so an addition
    # fails here first and is admitted only after review.
    names = {p.stem for p in (BACKEND / "search").glob("*.py") if p.stem != "__init__"}

    assert names == {
        # Admitted deliberately: per-account metering of web search. It wraps a
        # provider and returns results, so it is web search, not a fourth
        # meaning of the word.
        "budgeted",
        # Admitted 2026-08-25: Brave Search as the first rung of the provider
        # chain, a web-search provider like tavily and google_adk beside it.
        "brave",
        "google_adk",
        "hybrid",
        "mcp",
        "quota",
        "query",
        # Kept after the pattern cascade and the bounded classifier that were
        # scored on it were deleted: the labelled set is the measurement, not
        # the thing measured, and it now holds the turn's action selection to
        # the same recall and specificity floor.
        "routing_cases",
        "tavily",
        "types",
    }


def test_the_outbound_gate_is_shared_rather_than_search_specific():
    # Tool arguments carry the same disclosure risk as a search query, so the
    # policy lives in core and must not be reintroduced under search.
    assert (BACKEND / "core" / "egress.py").is_file()
    assert not (BACKEND / "search" / "privacy.py").exists()


def test_every_outbound_caller_uses_the_shared_gate():
    # A second implementation of screening is how the first one gets bypassed.
    duplicates = [
        path.name
        for path in BACKEND.rglob("*.py")
        if "__pycache__" not in str(path)
        and "tests" not in str(path)
        and path.name != "egress.py"
        and "class OutboundPrivacyPolicy" in path.read_text(encoding="utf-8")
    ]

    assert duplicates == []


def test_scout_does_not_season_ordinary_conversation():
    # Scout's profile — interests with strengths, and a home locality — was
    # added to every chat turn on the reasoning that the assistant may as well
    # know what someone likes. In practice a standing list of interests in
    # every prompt is a thumb on the scale for all of them, and unrelated
    # questions came back bent toward whatever was in it.
    #
    # What the assistant should know about a person belongs in memory, which is
    # retrieved per question and only when relevant.
    source = (BACKEND / "services" / "conversation_service.py").read_text(
        encoding="utf-8"
    )
    assert "render_profile_context(" not in source
