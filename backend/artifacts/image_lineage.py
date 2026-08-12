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
