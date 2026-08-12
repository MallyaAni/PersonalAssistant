"""What an artifact was made from, resolved rather than reconstructed.

Retrieval returns what matched a query. Provenance is a property of the thing
itself, and the two were confused: an edited photograph could only say where it
came from when its original happened to match the same query, which is exactly
when it did not need to — the original was right there. When the original did
not match, the edit was all anyone saw, and the assistant described a picture
the user had taken as one it had invented.

So this asks the database instead of the result set. One recursive query walks
every requested artifact to the root of its chain, gathering the edits applied
along the way, bounded so a cycle in stored data cannot spin. It is keyed on the
`parent_artifact_id` edge and nothing about images, so a trimmed recording or a
revised document inherits it the day those exist.

Ownership is enforced at every hop, not only at the entry point: a chain must
never walk out of the requesting user's own history.
"""

import json
from dataclasses import dataclass, field
from typing import Any

# How far back a chain is followed. Beyond this someone has edited one picture
# a dozen times; the root is still the interesting end, and the bound is what
# stops a cycle in stored data from running forever.
MAX_LINEAGE_DEPTH = 12


@dataclass(frozen=True, slots=True)
class Lineage:
    """The picture at the start of a chain, and how it got to this one."""

    # The oldest ancestor still on record, as the reader needs to recognise it.
    origin: dict[str, Any]
    # The edits applied from the origin to this artifact, oldest first.
    edits: tuple[str, ...] = field(default=())

    # True when a person supplied the original rather than a model producing it.
    #
    # The distinction the assistant got wrong: calling someone's own photograph
    # something it had generated. Kept here so no caller has to know which kinds
    # mean "uploaded".
    @property
    def supplied_by_user(self) -> bool:
        return str(self.origin.get("kind", "")).startswith("uploaded_")


# Read a JSON column that a raw query may hand back either way.
#
# The ORM deserializes `extra_data`; a `text()` query does not, and the driver
# returns the column as a string. Both reach this module, and a lineage that
# silently returned no description because the metadata arrived as text would be
# indistinguishable from an artifact that genuinely has none.
def as_metadata(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str | bytes | bytearray):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# The description a person would recognise this artifact by.
#
# An analysis when one was made, the prompt it was generated from otherwise.
# Both are plain untrusted text and neither is guaranteed, so an artifact with
# neither simply has no description rather than a placeholder standing in.
def describe(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") or {}
    text = metadata.get("analysis") or metadata.get("generation_prompt") or ""
    return " ".join(str(text).split())
