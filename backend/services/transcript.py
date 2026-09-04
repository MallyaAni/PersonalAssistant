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
        answered = _answer_line(turn)
        note = _attempt_note(turn)
        stamp = said_at(turn, zone)
        prefix = f"[{stamp}] " if stamp else ""
        if said:
            lines.append(f"{prefix}{speaker_label(turn)}: {said}")
        if answered or note:
            spoken = " ".join(part for part in (answered, note) if part)
            lines.append(f"{prefix}{assistant_label}: {spoken}")
    return lines


# Whether this turn's tool ran and delivered, said in the history so that a
# retry is visibly a retry.
#
# A turn whose search failed, was refused by a limit, came back empty, or came
# back about a different subject reads exactly like one that worked: the
# assistant's prose is there either way, and the failure lives only in the
# trace nobody shows the model. So "try again" reaches a router that cannot
# see there was anything to try again, and it decides the same way a second
# time for the same reasons - which is what a person means when they say the
# assistant keeps doing the wrong thing.
#
# Read off the trace the turn already writes rather than from the reply's
# words, so it holds whatever language the reply happens to be in, and kept to
# the outcome with no subject of its own: a note naming what was searched for
# is the receipt that became the conversation's apparent subject on
# 2026-08-30. The reply's own text still carries the subject.
_SEARCH_OUTCOMES = {
    "failed": "[the web search did not run]",
    "limit": "[the web search was not allowed to run]",
}


def _attempt_note(turn: dict[str, Any] | None) -> str:
    trace = ((turn or {}).get("metadata") or {}).get("trace")
    if not isinstance(trace, dict):
        return ""
    search = str(trace.get("search") or "")
    if search in _SEARCH_OUTCOMES:
        return _SEARCH_OUTCOMES[search]
    if not search.startswith("ran:"):
        return ""
    # "ran:0", or "ran:7 off-subject" when the ranker judged the results to be
    # about something other than what was asked. Both are attempts that did
    # not answer the question, and only the second has any results at all.
    if "off-subject" in search:
        return "[the web search came back about a different subject]"
    ran, _, _ = search[len("ran:") :].partition(" ")
    return "[the web search found nothing]" if ran == "0" else ""


# What the assistant said, unless what it said was bookkeeping about something
# it made.
#
# "Created an editable diagram: Try Again Flow." is a receipt, not subject
# matter, and it reads like subject matter. Measured on a real thread 2026-08-30:
# after three failed diagram attempts the follow-up resolver answered
# `subject="Try Again Flow"` - the title of the last failure - for every
# referential message put to it, including "draw the stacked arches". The
# assistant's record of what it had done had become what the conversation
# appeared to be about.
#
# Detected from the turn's own metadata rather than from its words: a turn that
# produced an artifact carries `artifact_ids`, whatever language the sentence
# happens to be in. The outcome is kept - a person asking "try again" means the
# failure, and the reply needs to know one happened - and only the title goes.
def _answer_line(turn: dict[str, Any] | None) -> str:
    answered = str((turn or {}).get("response") or "").strip()
    metadata = (turn or {}).get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("artifact_ids"):
        return answered
    route = (metadata.get("trace") or {}).get("route") or {}
    made = str(route.get("label") or "artifact").strip().casefold()
    kind = {"diagrams": "diagram", "new images": "picture", "presentations": "deck"}.get(
        made, "attachment"
    )
    # What it was asked to make, as the router resolved it at the time. This is
    # the part that makes "try again" answerable: a retry refers to the last
    # request that was not satisfied, so the record has to say what each
    # attempt was *for* as well as whether it worked. Dropping the subject and
    # keeping only "[a diagram was created]" left a reader able to see that
    # something happened and not what it was about.
    about = " ".join(str(route.get("detail") or "").split())[:120]
    the_ask = f' for "{about}"' if about else ""
    status = str(metadata.get("artifact_status") or "").strip().casefold()
    if status and status not in {"ready", "complete", "completed"}:
        return f"[a {kind} was attempted{the_ask} and did not succeed]"
    return f"[a {kind} was created{the_ask}]"
