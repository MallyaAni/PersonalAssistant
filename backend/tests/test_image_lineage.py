from typing import Any

from backend.artifacts.image_lineage import (
    collapse_duplicate_content,
    collapse_revision_chains,
    parent_of,
)


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


# Built the way retrieval returns them: sha256 and created_at as the plain
# ISO-8601 string `to_dict()` produces, with no parent/revision relationship
# between rows - each upload is independent, unlike a refinement chain.
def _upload(artifact_id: str, digest: str, created_at: str) -> dict[str, Any]:
    return {"id": artifact_id, "sha256": digest, "created_at": created_at}


# The exact scenario observed live: the same file uploaded across three
# separate conversations all matched one recall and were all shown.
def test_the_same_file_uploaded_more_than_once_collapses_to_the_newest() -> None:
    candidates = [
        _upload("A", "hash1", "2026-08-13T17:53:26"),
        _upload("B", "hash1", "2026-08-13T18:03:19"),
        _upload("C", "hash1", "2026-08-13T18:07:13"),
    ]
    assert [c["id"] for c in collapse_duplicate_content(candidates)] == ["C"]


def test_genuinely_different_images_are_all_kept() -> None:
    candidates = [
        _upload("A", "hash1", "2026-08-13T17:00:00"),
        _upload("B", "hash2", "2026-08-13T17:00:00"),
        _upload("C", "hash3", "2026-08-13T17:00:00"),
    ]
    assert [c["id"] for c in collapse_duplicate_content(candidates)] == [
        "A",
        "B",
        "C",
    ]


# A missing digest (an older row, or a source retrieval that never set one)
# must not be treated as matching every other missing digest and collapsed
# away together - only a real, shared hash proves two rows are the same file.
def test_a_missing_digest_is_never_collapsed() -> None:
    candidates = [
        {"id": "A", "sha256": None, "created_at": "2026-08-13T17:00:00"},
        {"id": "B", "created_at": "2026-08-13T17:00:01"},
    ]
    assert [c["id"] for c in collapse_duplicate_content(candidates)] == ["A", "B"]


# Order among the survivors is the caller's retrieval order (relevance-ranked
# or selector-chosen), not creation time - only which copy survives uses date.
def test_survivor_order_follows_the_original_list_not_creation_time() -> None:
    candidates = [
        _upload("A", "hash1", "2026-08-13T18:07:13"),
        _upload("B", "hash2", "2026-08-13T17:00:00"),
    ]
    assert [c["id"] for c in collapse_duplicate_content(candidates)] == ["A", "B"]
