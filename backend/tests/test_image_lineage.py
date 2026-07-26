from typing import Any

from backend.artifacts.image_lineage import collapse_revision_chains


def _hit(artifact_id: str, parent: str | None = None) -> dict[str, Any]:
    metadata = {"parent_artifact_id": parent} if parent else {}
    return {"id": artifact_id, "metadata": metadata}


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
