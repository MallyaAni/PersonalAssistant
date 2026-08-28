"""Whose memory a fact said in a group belongs to.

The memory agent, given the roster, says who each fact is about; this turns
that into owners. The rule that matters most is the one about other people:
nothing is ever written to a member's own memory on somebody else's word.
"Jen hates cilantro", said by Ani, is the group's knowledge with Ani as its
source - not a fact in Jen's profile.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# What the memory agent says when a fact is about everyone in the room.
GROUP_WORDS = frozenset({"the group", "group", "us", "we", "everyone", "all of us", "both of us"})
SELF_WORDS = frozenset({"me", "i", "myself", "the speaker"})


@dataclass(frozen=True, slots=True)
class Owner:
    """One store a fact goes to, and how it is attributed there."""

    user_id: str
    # A source note for the group's copy ("said by Jen"); None when the fact
    # is written to the speaker's own memory as their own statement.
    provenance: str | None


# The owners of one fact from the memory agent's `about` list. `roster`
# maps display names to user ids; the speaker's name is in it.
def owners_for(
    about: Sequence[str],
    roster: Mapping[str, str],
    speaker_user_id: str,
    speaker_name: str,
    group_user_id: str,
) -> tuple[Owner, ...]:
    by_name = {name.casefold(): user_id for name, user_id in roster.items()}
    mentions_group = False
    mentions_speaker = False
    others: list[str] = []
    for raw in about:
        word = " ".join(str(raw or "").split()).casefold()
        if not word:
            continue
        if word in GROUP_WORDS:
            mentions_group = True
        elif word in SELF_WORDS or word == speaker_name.casefold():
            mentions_speaker = True
        elif word in by_name and by_name[word] == speaker_user_id:
            mentions_speaker = True
        else:
            others.append(word)
    said_by = f"said by {speaker_name}" if speaker_name else "said in the group"
    if not about or (not mentions_speaker and not others and not mentions_group):
        # Nothing named: the safest reading is the speaker talking about
        # themself, exactly as a one-to-one turn is read.
        mentions_speaker = True
    if mentions_speaker:
        # The speaker's own statement - alone, or their share of "Jen and I"
        # - is theirs, and the room's with the source. Jen's share is the
        # room's only: her memory is never written on Ani's word.
        return (Owner(speaker_user_id, None), Owner(group_user_id, said_by))
    # About the group, another member, or an outsider: the group's
    # knowledge with its source, and never a write into somebody else's memory.
    return (Owner(group_user_id, said_by),)


# The fact's content as the group's copy stores it: the source rides in the
# words, because the group's memory is read without the roster.
def with_provenance(content: str, provenance: str | None) -> str:
    text = " ".join(str(content or "").split())
    if not provenance or not text:
        return text
    return f"{text} ({provenance})"
