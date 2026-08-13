from typing import Any


# The parent this artifact was derived from, whichever way it was recorded.
#
# It is a column now, and the column is what the migration backfilled and what
# every new derivative writes. The metadata key is still read because it is
# still written, and because a row whose parent was deleted keeps the key while
# the column is null — for deduplication that distinction does not matter, and
# treating such a row as a revision is correct: it is one.
def parent_of(candidate: dict[str, Any]) -> str:
    column = candidate.get("parent_artifact_id")
    if column:
        return str(column)
    return str((candidate.get("metadata") or {}).get("parent_artifact_id") or "")


# Keep only the latest revision when several from one refinement chain match.
#
# Refining an image creates a new artifact linked to its parent, so an original
# and its revisions are near-identical and can all match a recall query. Any
# candidate that is the parent of another candidate in the set is superseded, so
# it is dropped, leaving the newest revision of each lineage. Candidates whose
# parent is not among the results are untouched.
#
# This decides what is *shown*, and nothing more. What a dropped original knew
# is not this function's problem to preserve — it was, briefly, and that was the
# wrong place for it: an answer assembled from whatever else happened to match
# is only ever as complete as the query was lucky. Provenance is resolved from
# the parent edge instead, by `ArtifactLineageStore`, for every survivor
# regardless of what else was retrieved.
def collapse_revision_chains(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    superseded = {
        parent for candidate in candidates if (parent := parent_of(candidate))
    }
    if not superseded:
        return candidates
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("id")) not in superseded
    ]


# Keep only the newest copy when the exact same file was uploaded more than
# once.
#
# Nothing links these rows the way a revision links to its parent - each
# upload is its own independent artifact - but an identical sha256 means
# identical bytes, so a recall that returns three of them is the same
# picture three times, not three pictures. Observed directly: the same file
# uploaded across three separate conversations while testing all matched one
# style question and were all shown. `created_at` here is already the
# ISO-8601 string `to_dict()` produces, which sorts correctly as text.
def collapse_duplicate_content(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    newest_by_digest: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        digest = candidate.get("sha256")
        if not digest:
            continue
        current = newest_by_digest.get(digest)
        if current is None or candidate.get("created_at", "") > current.get(
            "created_at", ""
        ):
            newest_by_digest[digest] = candidate
    return [
        candidate
        for candidate in candidates
        if not candidate.get("sha256")
        or candidate is newest_by_digest[candidate["sha256"]]
    ]
