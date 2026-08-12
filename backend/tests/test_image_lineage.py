from typing import Any

from backend.artifacts.image_lineage import collapse_revision_chains, parent_of


# Built the way retrieval returns them: the parent as a column, which is what
# the migration backfilled and what every new derivative writes.
def _hit(artifact_id: str, parent: str | None = None) -> dict[str, Any]:
    return {"id": artifact_id, "parent_artifact_id": parent, "metadata": {}}


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


# Deduplication decides what is shown and nothing else. What the dropped
# original knew is resolved from the parent edge, for every survivor, whether or
# not the original was retrieved — so nothing is carried here.
def test_collapsing_does_not_annotate_the_survivor() -> None:
    [survivor] = collapse_revision_chains([_hit("A"), _hit("B", parent="A")])
    assert set(survivor) == {"id", "parent_artifact_id", "metadata"}


# A row written before the column existed, whose parent has since been deleted,
# keeps only the metadata key. It is still a revision and still deduplicates.
def test_a_parent_recorded_only_in_metadata_is_still_read() -> None:
    legacy = {"id": "B", "metadata": {"parent_artifact_id": "A"}}
    assert parent_of(legacy) == "A"
    assert [c["id"] for c in collapse_revision_chains([_hit("A"), legacy])] == ["B"]


# The column wins when both are present, because the foreign key is the one that
# is null after the parent is deleted — the metadata key never notices.
def test_the_column_is_preferred_over_the_metadata_copy() -> None:
    both = {
        "id": "C",
        "parent_artifact_id": "B",
        "metadata": {"parent_artifact_id": "A"},
    }
    assert parent_of(both) == "B"


def test_an_artifact_with_no_parent_reports_none() -> None:
    assert parent_of(_hit("A")) == ""
    assert parent_of({"id": "A"}) == ""
