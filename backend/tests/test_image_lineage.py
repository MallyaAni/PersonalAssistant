from typing import Any

from backend.artifacts.image_lineage import collapse_revision_chains


def _hit(
    artifact_id: str,
    parent: str | None = None,
    kind: str = "generated_image",
    analysis: str = "",
    feedback: str = "",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if parent:
        metadata["parent_artifact_id"] = parent
    if analysis:
        metadata["analysis"] = analysis
    if feedback:
        metadata["refinement_feedback"] = feedback
    return {"id": artifact_id, "kind": kind, "title": artifact_id, "metadata": metadata}


def test_original_is_dropped_when_its_revision_also_matches() -> None:
    candidates = [_hit("A"), _hit("B", parent="A")]
    assert [c["id"] for c in collapse_revision_chains(candidates)] == ["B"]


def test_a_full_chain_collapses_to_the_latest_revision() -> None:
    candidates = [_hit("A"), _hit("B", parent="A"), _hit("C", parent="B")]
    assert [c["id"] for c in collapse_revision_chains(candidates)] == ["C"]


def test_unrelated_images_are_all_kept() -> None:
    candidates = [_hit("A"), _hit("B"), _hit("C")]
    assert [c["id"] for c in collapse_revision_chains(candidates)] == ["A", "B", "C"]


def test_a_revision_whose_parent_is_absent_is_kept() -> None:
    candidates = [_hit("B", parent="A"), _hit("C")]
    assert [c["id"] for c in collapse_revision_chains(candidates)] == ["B", "C"]


# The reported defect. A photograph was uploaded, edited, and the upload was
# collapsed away — taking with it the only record of what the user actually
# owned, while the surviving revision read as something the assistant invented.
def test_the_collapsed_original_travels_with_the_revision() -> None:
    upload = _hit(
        "A",
        kind="uploaded_image",
        analysis="A man in a wide-brimmed black cowboy hat by a lake.",
    )
    revision = _hit("B", parent="A", feedback="edit this to give me a straw hat")
    [survivor] = collapse_revision_chains([upload, revision])

    assert survivor["id"] == "B"
    assert survivor["origin"]["kind"] == "uploaded_image"
    assert "black cowboy hat" in survivor["origin"]["description"]
    assert survivor["edits"] == ["edit this to give me a straw hat"]


# An edit of an edit still names the picture the user supplied, not the
# intermediate one, and the edits read oldest first.
def test_a_chain_reports_its_root_and_every_edit_in_order() -> None:
    candidates = [
        _hit("A", kind="uploaded_image", analysis="A red bicycle."),
        _hit("B", parent="A", feedback="make it blue"),
        _hit("C", parent="B", feedback="add a basket"),
    ]
    [survivor] = collapse_revision_chains(candidates)

    assert survivor["origin"]["description"] == "A red bicycle."
    assert survivor["edits"] == ["make it blue", "add a basket"]


# Nothing is invented for an image that is nobody's revision: an ordinary match
# keeps exactly the shape it had before any of this.
def test_an_image_with_no_lineage_gains_no_lineage_keys() -> None:
    candidates = [_hit("A"), _hit("B", parent="A"), _hit("Z")]
    survivors = {c["id"]: c for c in collapse_revision_chains(candidates)}
    assert "origin" not in survivors["Z"]
    assert "edits" not in survivors["Z"]


# A parent link pointing back into its own chain must not spin.
def test_a_cycle_in_stored_lineage_terminates() -> None:
    candidates = [_hit("A", parent="B"), _hit("B", parent="A"), _hit("C", parent="A")]
    survivors = collapse_revision_chains(candidates)
    assert [c["id"] for c in survivors] == ["C"]
