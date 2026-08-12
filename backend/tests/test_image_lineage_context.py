"""Turning a resolved lineage into the words the model is given.

The resolver is measured against a real database elsewhere, and what the model
does with the result is measured against a real model in the functional suite.
This is the seam between them: that a lineage reaches the prompt at all, in
terms a reader can act on, and that failing to resolve one costs provenance
rather than the turn.
"""

from typing import Any

import pytest

from backend.artifacts.lineage import Lineage
from backend.services.conversation_service import ConversationService, _image_lineage


class StubLineage:
    """Answer with a fixed lineage, or fail, without a database."""

    def __init__(
        self,
        answers: dict[str, Lineage] | None = None,
        fail: bool = False,
    ) -> None:
        self.answers = answers or {}
        self.fail = fail
        self.calls: list[list[str]] = []

    async def resolve_lineage(self, user_id, artifact_ids, max_depth=12):
        self.calls.append(list(artifact_ids))
        if self.fail:
            raise RuntimeError("database unavailable")
        return {k: v for k, v in self.answers.items() if k in set(artifact_ids)}


def _service(lineage: StubLineage | None) -> ConversationService:
    # Only the lineage collaborator matters here; the rest of the workflow is
    # never entered, so it is left unbuilt rather than elaborately faked.
    service = ConversationService.__new__(ConversationService)
    service.lineage = lineage
    return service


_PHOTO = Lineage(
    origin={
        "id": "a",
        "kind": "uploaded_image",
        "title": "Uploaded image",
        "description": "A man in a wide-brimmed black cowboy hat.",
    },
    edits=("give me a straw hat",),
)

# One call for the whole page of matches, not one per match.
@pytest.mark.asyncio
async def test_every_match_is_resolved_in_a_single_call() -> None:
    lineage = StubLineage({"b": _PHOTO})
    matches: list[dict[str, Any]] = [{"id": "b"}, {"id": "c"}, {"id": "d"}]

    result = await _service(lineage)._with_lineage("u", matches)

    assert lineage.calls == [["b", "c", "d"]]
    assert result[0]["lineage"] is _PHOTO
    # An artifact with no lineage is passed through untouched rather than
    # carrying an empty one, which would read as "origin unknown".
    assert "lineage" not in result[1]


# Provenance is an enrichment. Losing it must not lose the images themselves.
@pytest.mark.asyncio
async def test_a_resolver_failure_leaves_the_matches_intact() -> None:
    matches: list[dict[str, Any]] = [{"id": "b"}, {"id": "c"}]

    result = await _service(StubLineage(fail=True))._with_lineage("u", matches)

    assert result == matches


@pytest.mark.asyncio
async def test_no_resolver_configured_changes_nothing() -> None:
    matches: list[dict[str, Any]] = [{"id": "b"}]
    assert await _service(None)._with_lineage("u", matches) == matches


# The terms the model is given. `supplied_by_user` is the distinction it got
# wrong, and the edits are ordered so the origin reads as history.
def test_a_photograph_is_rendered_as_the_users_own() -> None:
    rendered = _image_lineage({"id": "b", "lineage": _PHOTO})

    assert rendered["edited_from"]["supplied_by_user"] is True
    assert "black cowboy hat" in rendered["edited_from"]["description"]
    assert rendered["edits_applied"] == ["give me a straw hat"]


def test_an_edited_generation_is_not_rendered_as_the_users_own() -> None:
    generated = Lineage(
        origin={
            "id": "a",
            "kind": "generated_image",
            "title": "Generated image",
            "description": "a cobalt sports car",
        },
        edits=("make it red",),
    )

    assert _image_lineage({"lineage": generated})["edited_from"][
        "supplied_by_user"
    ] is False


def test_a_match_with_no_lineage_renders_nothing() -> None:
    assert _image_lineage({"id": "b"}) == {}
    assert _image_lineage({"id": "b", "lineage": None}) == {}
