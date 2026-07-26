from typing import Any


# Keep only the latest revision when several from one refinement chain match.
#
# Refining an image creates a new artifact linked to its parent, so an original
# and its revisions are near-identical and can all match a recall query. Any
# candidate that is the parent of another candidate in the set is superseded, so
# it is dropped, leaving the newest revision of each lineage. Candidates whose
# parent is not among the results are untouched.
def collapse_revision_chains(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    superseded = {
        str((candidate.get("metadata") or {}).get("parent_artifact_id"))
        for candidate in candidates
        if (candidate.get("metadata") or {}).get("parent_artifact_id")
    }
    if not superseded:
        return candidates
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("id")) not in superseded
    ]
