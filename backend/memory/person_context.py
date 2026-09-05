"""One view of the person for a turn, with provenance and an egress flag.

The search path used to assemble what it knew about the person three times
over: up to eight interests for the query composer, up to forty for the
interest judgement, and eight mixed lines for the result ranker, each
fetched and capped in its own place. Three views of one person drift, and
none of them could say where a line came from or whether it was allowed to
leave the machine.

`PersonContext` is built once per turn and every consumer reads it. Each
entry carries what it is (an interest, a stated preference, a disposition),
where it came from (which store, which memory id), and whether it may leave
the machine. The rule for that last flag is the one the search path already
lived by in code: an interest is a search term and may be put in a query; a
preference is a fact about the person and is applied locally to what comes
back, never sent. A consumer that composes an outbound query asks for
`search_terms()`; one that orders results asks for `ranking_lines()`; the
object refuses to hand a non-leaving entry to the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from backend.memory.purposes import CONSTRAINT_PURPOSE
from typing import Any

# How many interests the query composer is shown as advice - only so the
# list stays a list - and how many the interest judgement may choose from.
# Two caps, one object: the judgement sees the wider list because a weaker
# chooser must not stand in front of a better one (2026-09-04).
COMPOSER_INTERESTS = 8
JUDGEMENT_INTERESTS = 40
RANKING_LINES = 8


@dataclass(frozen=True, slots=True)
class Known:
    """One thing known about the person, with where it came from."""

    text: str
    # "interest" (Scout's profile), "preference" (a stated fact),
    # "constraint" (a hard limit a result must not cross), or
    # "disposition" (how they choose, decided this turn).
    kind: str
    # "stated" by the person, or "inferred" by a classifier.
    source: str = "stated"
    store: str = ""
    memory_id: str | None = None
    noted_at: datetime | None = None
    # Whether this may appear in anything that leaves the machine.
    may_leave: bool = False


@dataclass(frozen=True, slots=True)
class PersonContext:
    """What this turn knows about the person, built once."""

    user_id: str
    interests: tuple[Known, ...] = ()
    preferences: tuple[Known, ...] = ()
    dispositions: tuple[str, ...] = ()
    # One-line characterisation of the interests, when the persona pass
    # produced one; empty otherwise.
    described: str = ""
    place: str = ""
    timezone: str = ""
    local_now: datetime | None = None

    # The interest labels, widest first, for the judgement that chooses.
    def interest_labels(self, limit: int = JUDGEMENT_INTERESTS) -> tuple[str, ...]:
        return tuple(item.text for item in self.interests[:limit])

    # The hard constraints: preferences filed as limits. A result that
    # violates one is filtered, not ranked down; none of them ever leaves.
    @property
    def constraints(self) -> tuple[Known, ...]:
        return tuple(item for item in self.preferences if item.kind == "constraint")

    # The constraints as short lines for a local judge.
    def constraint_lines(self, limit: int = RANKING_LINES) -> tuple[str, ...]:
        return tuple(item.text for item in self.constraints)[:limit]

    # What may be put into an outbound query: only entries allowed to leave.
    # A preference never comes back from here, whatever a caller asks.
    def search_terms(self, limit: int = JUDGEMENT_INTERESTS) -> tuple[str, ...]:
        return tuple(
            item.text
            for item in (*self.interests, *self.preferences)
            if item.may_leave
        )[:limit]

    # Short lines for a ranker that runs on this machine: who they are, their
    # interests, their stated preferences. Local only; this is the view that
    # may hold what must not leave.
    def ranking_lines(self, question: str = "", limit: int = RANKING_LINES) -> tuple[str, ...]:
        lines: list[str] = []
        if self.described:
            lines.append(f"who they are: {self.described}")
        labels = self.interest_labels()
        if labels:
            lines.append("interests: " + ", ".join(_interests_for(question, labels)))
        lines.extend(
            (f"must: {item.text}" if item.kind == "constraint" else item.text)
            for item in self.preferences
        )
        return tuple(lines[:limit])

    # The same view with a disposition the turn decided added to it.
    def with_dispositions(self, dispositions: tuple[str, ...]) -> PersonContext:
        return PersonContext(
            user_id=self.user_id,
            interests=self.interests,
            preferences=self.preferences,
            dispositions=tuple(dispositions),
            described=self.described,
            place=self.place,
            timezone=self.timezone,
            local_now=self.local_now,
        )

    # Everything, for the turn trace: what was known and whether it may leave.
    def as_trace(self) -> dict[str, Any]:
        return {
            "interests": len(self.interests),
            "preferences": len(self.preferences),
            "constraints": len(self.constraints),
            "dispositions": list(self.dispositions),
            "may_leave": [item.text for item in (*self.interests, *self.preferences) if item.may_leave][:12],
            "local_only": [item.kind for item in (*self.interests, *self.preferences) if not item.may_leave],
        }


# Interests most likely to bear on the question first, by word overlap - an
# ordering for a bounded list, never a decision about meaning (that is the
# personalize judgement's). Kept identical to the search path's own rule so
# the two views cannot disagree.
def _interests_for(question: str, interests: tuple[str, ...], limit: int = COMPOSER_INTERESTS) -> list[str]:
    words = {word for word in str(question or "").casefold().split() if len(word) > 3}
    scored = sorted(
        interests,
        key=lambda label: -sum(1 for word in words if word in label.casefold()),
    )
    return list(scored[:limit])


@dataclass
class PersonSources:
    """Where a person context is read from; every source optional."""

    # `get_profile(user_id)` -> object with `.interests`, each with `.label`.
    discovery_profile: Any = None
    # `get_preferences(user_id, limit)` -> list of memory dicts.
    memory: Any = None
    # `characterize(llm, interests)` needs the model; None skips the line.
    llm: Any = None
    preference_limit: int = 3
    extra: dict[str, Any] = field(default_factory=dict)


# When a record was noted, from a datetime or the ISO string a store's
# `to_dict` writes; None for anything else. Dropping a string here lost the
# provenance the object exists to carry (the reviewer's pilot, 2026-09-05).
def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


# The text of one memory record, as the ranker has always read it.
def _memory_text(item: dict[str, Any]) -> str:
    for key in ("content", "value", "text"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:160]
    return ""


# Build the person's context for this turn from the stores that hold it. A
# store that fails costs its part, never the turn.
async def build_person_context(
    user_id: str,
    sources: PersonSources,
    *,
    place: str = "",
    timezone: str = "",
    local_now: datetime | None = None,
) -> PersonContext:
    interests: list[Known] = []
    if sources.discovery_profile is not None:
        try:
            profile = await sources.discovery_profile.get_profile(user_id)
            for interest in getattr(profile, "interests", ()) or ():
                label = str(getattr(interest, "label", "") or "").strip()
                if label:
                    interests.append(
                        Known(label, "interest", "stated", "discovery_profile", may_leave=True)
                    )
        except Exception:
            interests = []

    preferences: list[Known] = []
    reader = getattr(sources.memory, "get_preferences", None) if sources.memory is not None else None
    if reader is not None:
        try:
            for item in (await reader(user_id, limit=sources.preference_limit)) or []:
                text = _memory_text(item)
                if text:
                    preferences.append(
                        Known(
                            text,
                            "constraint" if str(item.get("purpose") or "") == CONSTRAINT_PURPOSE else "preference",
                            "stated" if not item.get("inferred") else "inferred",
                            "memory_facts",
                            memory_id=str(item.get("id")) if item.get("id") else None,
                            noted_at=_when(item.get("created_at")),
                            may_leave=False,
                        )
                    )
        except Exception:
            preferences = []

    described = ""
    if interests and sources.llm is not None:
        try:
            from backend.core.persona import characterize

            described = await characterize(sources.llm, tuple(item.text for item in interests))
        except Exception:
            described = ""

    return PersonContext(
        user_id=user_id,
        interests=tuple(interests),
        preferences=tuple(preferences),
        described=described,
        place=place,
        timezone=timezone,
        local_now=local_now,
    )
