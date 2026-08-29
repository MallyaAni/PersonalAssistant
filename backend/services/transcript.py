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

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

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


# When a stored turn was said, in the reader's zone, or "" if unknown.
#
# Absolute rather than relative ("Thu 28 Aug 9:17pm", not "yesterday") for two
# reasons. It does not change between turns, so the history stays byte-stable
# and the server keeps reusing its KV blocks - measured at 16.5x on a 34k
# conversation, and a stamp that re-rendered every turn would throw that away.
# And the current time is already in front of the model, after the history, so
# it can do the subtraction itself and does not need us to have done it at a
# moment that has since passed.
def said_at(turn: dict[str, Any], zone: str = "") -> str:
    raw = str((turn or {}).get("created_at") or "")
    if not raw:
        return ""
    try:
        moment = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return ""
    if moment.tzinfo is None:
        # A stored time with no offset is UTC here; saying so explicitly is
        # what keeps `astimezone` from quietly reading it as the container's
        # clock, which is UTC today and something else the day someone runs
        # this anywhere but a container.
        moment = moment.replace(tzinfo=UTC)
    marker = ""
    if zone:
        try:
            moment = moment.astimezone(ZoneInfo(zone))
        except Exception:
            marker = " UTC"
    else:
        # No zone known. Still stamped - a UTC stamp beats no stamp - but said
        # out loud, so a reader does not take an 11pm UTC turn for a late night
        # in a place that was actually mid-evening.
        marker = " UTC"
    hour = moment.hour % 12 or 12
    meridiem = "am" if moment.hour < 12 else "pm"
    # Built from parts rather than one strftime: %-d is a GNU extension, and
    # this string is assembled on whatever host happens to run the tests.
    return (
        f"{moment:%a} {moment.day} {moment:%b} "
        f"{hour}:{moment.minute:02d}{meridiem}{marker}"
    )


# The user side of a turn as a chat message's content: when it was said, and -
# in a group - who said it, so the model can tell members apart in one thread
# and tell last night from tonight.
#
# The timestamp is what was missing on 2026-08-29, when a reminder set the
# evening before was described to the room as happening "tonight". Everything
# the model needed was in the history; none of it was dated.
def user_content(turn: dict[str, Any], zone: str = "") -> str:
    query = str(turn.get("query") or "")
    name = speaker_name(turn)
    said = f"{name}: {query}" if name else query
    stamp = said_at(turn, zone)
    return f"[{stamp}] {said}" if stamp else said


# The conversation as dated lines, for every renderer that shows a model what
# was said rather than replaying it as chat messages - the router and the
# follow-up resolver. One function, so the router cannot end up reasoning
# about a differently-shaped transcript than the reply does.
def transcript_lines(
    history: list[dict[str, Any]],
    zone: str = "",
    assistant_label: str = "Assistant",
) -> list[str]:
    lines: list[str] = []
    for turn in history or []:
        said = str((turn or {}).get("query") or "").strip()
        answered = str((turn or {}).get("response") or "").strip()
        stamp = said_at(turn, zone)
        prefix = f"[{stamp}] " if stamp else ""
        if said:
            lines.append(f"{prefix}{speaker_label(turn)}: {said}")
        if answered:
            lines.append(f"{prefix}{assistant_label}: {answered}")
    return lines
