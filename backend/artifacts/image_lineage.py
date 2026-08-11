from typing import Any

# How far back a lineage is walked. A chain longer than this is a user editing
# the same picture over and over; the root is still the interesting end, and the
# bound stops a cycle in stored metadata from spinning here.
MAX_LINEAGE_DEPTH = 12


# What the picture this one was made from actually was.
#
# Only the parts a reader needs to recognise it: whether the user supplied it,
# what it was called, and what it showed.
def _origin(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") or {}
    return {
        "id": str(record.get("id")),
        "kind": record.get("kind"),
        "title": record.get("title"),
        "description": metadata.get("analysis")
        or metadata.get("generation_prompt")
        or "",
    }


# Keep only the latest revision when several from one refinement chain match,
# and carry what was collapsed onto the revision that replaces it.
#
# Refining an image creates a new artifact linked to its parent, so an original
# and its revisions are near-identical and can all match a recall query. Any
# candidate that is the parent of another candidate in the set is superseded, so
# it is dropped, leaving the newest revision of each lineage. Candidates whose
# parent is not among the results are untouched.
#
# Dropping the parent used to drop everything the parent knew. Editing a
# photograph produced a `generated_image` titled "Edited image" whose analysis
# described the edited picture, the upload it came from was collapsed away, and
# the assistant then told the owner of the photograph that the only image on
# record was one it had generated from a creative request. The original was
# still in the database; nothing carried it into the turn. So the survivor now
# leaves with its lineage: the root it descends from, and the edits applied
# along the way, oldest first.
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

    by_id = {str(candidate.get("id")): candidate for candidate in candidates}
    survivors: list[dict[str, Any]] = []
    for candidate in candidates:
        if str(candidate.get("id")) in superseded:
            continue
        root, edits = _walk_to_root(candidate, by_id)
        if root is None:
            survivors.append(candidate)
            continue
        survivors.append({**candidate, "origin": _origin(root), "edits": edits})
    return survivors


# Follow parent links as far as the matched set goes, gathering the edits.
#
# The walk stops at the last ancestor actually present: an artifact not among
# the candidates cannot be described here, and inventing a link to one would put
# a picture in front of the model that nothing had retrieved.
def _walk_to_root(
    candidate: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    edits: list[str] = []
    seen = {str(candidate.get("id"))}
    current = candidate
    root: dict[str, Any] | None = None
    for _ in range(MAX_LINEAGE_DEPTH):
        metadata = current.get("metadata") or {}
        feedback = metadata.get("refinement_feedback")
        if isinstance(feedback, str) and feedback.strip():
            edits.append(feedback.strip())
        parent_id = str(metadata.get("parent_artifact_id") or "")
        if not parent_id or parent_id in seen or parent_id not in by_id:
            break
        seen.add(parent_id)
        current = by_id[parent_id]
        root = current
    edits.reverse()
    return root, edits
