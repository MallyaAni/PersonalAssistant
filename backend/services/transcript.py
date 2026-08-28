"""Who said what, for every place a conversation is shown to a model.

A one-to-one conversation has two voices, and every renderer labelled them
"User" and "Assistant". A group turn has a third dimension - which member
spoke - and it is carried on the turn's metadata (`group.speaker_name`),
never in the words themselves, so memory and search see what was said and
the renderers see who said it. One function per label, shared by all of
them, so the routing model, the follow-up resolver, the reply model, and the
image thread cannot disagree about who a line belongs to.
"""

from __future__ import annotations

from typing import Any

USER_LABEL = "User"


# The speaker's name for a group turn, or None for a one-to-one turn.
def speaker_name(turn_or_metadata: dict[str, Any] | None) -> str | None:
    if not turn_or_metadata:
        return None
    metadata = turn_or_metadata.get("metadata") if "metadata" in turn_or_metadata else turn_or_metadata
    group = (metadata or {}).get("group") if isinstance(metadata, dict) else None
    name = str((group or {}).get("speaker_name") or "").strip()
    return name or None


# The label for the user side of a stored turn: the member's name in a
# group, "User" otherwise.
def speaker_label(turn: dict[str, Any]) -> str:
    return speaker_name(turn) or USER_LABEL


# The user side of a turn as a chat message's content: a group member's
# words carry their name so the model can tell members apart in one thread.
def user_content(turn: dict[str, Any]) -> str:
    query = str(turn.get("query") or "")
    name = speaker_name(turn)
    return f"{name}: {query}" if name else query
