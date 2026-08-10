"""Aim a sweep at one person rather than at a topic.

Two things in the loop were built from the same two-word string. A search query
was `{label} {place} {month year}` — "Run Clubs Arlington, Virginia August 2026"
— and the vector a candidate was scored against was the embedding of `label`
alone. So the entire representation of a person, at both the finding step and
the sorting step, was "Run Clubs". That is why a man was offered a women-only
running event: nothing in the query was about him, and ranking was then asked to
sort candidates that were never chosen with him in mind.

This module asks the local model, once per sweep, to turn each approved interest
plus whatever memory knows about the person into two short pieces of text:

- a **search subject** — "casual weekend group runs" rather than "Run Clubs" —
  which is substituted into the existing query skeleton;
- a **ranking profile** — a fuller sentence, embedded in place of the bare label
  so a candidate is scored against something with more than two words in it.

Three rules keep this from undoing what has already been measured:

- **the skeleton is not the model's to write.** It still produces
  `{subject} {place} {month year}`. The phrasing was measured, and the comment in
  `sources/web.py::_queries` records it: `"events near X upcoming"` kept 0 of 5
  results while naming the month kept 6 of 9. Free-form queries would throw that
  away;
- **the budget does not move.** Same number of queries, better aimed;
- **failure is exactly today's behaviour.** Anything the model returns that
  cannot be validated — too long, carrying a date, naming the place the skeleton
  is about to name, or blocked by the egress screen — falls back to the bare
  label. A sweep with no model, or a model having a bad day, searches and ranks
  precisely as it did before this module existed.

The ranking profile never leaves the machine: it is embedded locally and
compared locally. Only the subject reaches a search provider, which is why the
two are validated to different standards.

**It runs even when memory is empty**, which was not the original design and is
where most of the measured benefit turned out to be. A real digest attributed
"COLLECTIVE at The Light Horse" to the interest "Horses" — a concert matched to
an equestrian interest by the name of the pub it was in. Scored against the bare
label the cross-encoder agreed, and confidently: Horses by a margin of 5.40.
Scored against "horse riding, equestrian shows and stables" the same find went
to Music by 4.44, and Horses fell from -0.9 to -8.1. Nothing about that needed
to know anything about the person; it needed the interest to be more than two
words.
"""

import asyncio
import json
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from backend.core.egress import OutboundPrivacyPolicy
from backend.core.interfaces import TextWriter
from backend.discovery.personal_context import PersonalContext
from backend.discovery.sources.web import MONTH_STEMS
from backend.discovery.types import normalize_label

# Short enough that the place and the month still dominate the query. A subject
# longer than this stops being a kind of happening and starts being a sentence,
# and a search engine reads a sentence as a phrase to match rather than a thing
# to find.
MAX_SUBJECT_CHARS = 60

# The vector text never leaves the machine, so it is bounded by what an
# embedding call should carry rather than by what is safe to disclose.
MAX_PROFILE_CHARS = 220

# How many interests one planning call covers. Beyond this the remaining
# interests keep their bare labels, which is the behaviour they had anyway.
MAX_AIMS = 10

# A date in the subject would collide with the month and year the skeleton
# appends, producing "run clubs September 2026 Arlington, Virginia August 2026".
# The stems come from the skeleton's own module so the two cannot disagree about
# what a month looks like.
_MONTH_WORDS = re.compile(rf"\b({MONTH_STEMS})[a-z]*\b", re.IGNORECASE)
_ANY_DIGIT = re.compile(r"\d")

# Search operators and punctuation that would change how a provider parses the
# query rather than what it is about.
_QUERY_SYNTAX = re.compile(r'["\'()\[\]{}<>|&+~^:;/\\]')


class _Aim(BaseModel):
    """One interest, restated for searching and for scoring."""

    model_config = ConfigDict(extra="forbid")

    interest: str = Field(max_length=80)
    subject: str = Field(max_length=MAX_SUBJECT_CHARS)
    profile: str = Field(max_length=MAX_PROFILE_CHARS)


class _AimPlan(BaseModel):
    """The grammar-constrained plan returned by the local model."""

    model_config = ConfigDict(extra="forbid")

    aims: list[_Aim] = Field(default_factory=list, max_length=MAX_AIMS)


@dataclass(frozen=True, slots=True)
class InterestAim:
    """What one interest becomes when it is aimed at a particular person."""

    label: str
    # What the query skeleton searches for. Never more disclosing than the
    # interest label itself.
    subject: str
    # What ranking embeds instead of the bare label. Stays on this machine.
    profile: str


@dataclass(frozen=True, slots=True)
class SweepAim:
    """Every interest of one sweep, aimed."""

    aims: tuple[InterestAim, ...] = ()

    # What the web source searches for, in the order the interests were given.
    def subjects(self) -> tuple[str, ...]:
        return tuple(aim.subject for aim in self.aims)

    # What ranking embeds, keyed by the label a matched interest is reported as.
    # The key stays the user's own label so a digest still names the interest
    # they stated rather than a phrasing the model invented.
    def vector_texts(self) -> dict[str, str]:
        return {aim.label: aim.profile for aim in self.aims}

    # The unaimed sweep: every interest as its own bare label. This is what runs
    # when there is no model or nothing usable came back — not when memory is
    # empty, which is the common case and still benefits: a two-word label
    # cannot be matched against an event description at all.
    @staticmethod
    def from_labels(labels: tuple[str, ...]) -> "SweepAim":
        return SweepAim(
            tuple(
                InterestAim(label=label, subject=label, profile=label)
                for label in labels
            )
        )


_SYSTEM = """You aim a weekly local-events search at one particular person.

For each of their interests, return two things.

subject: what to search the web for. It is placed into a fixed query as
"<subject> <place> <month year>", so write only the kind of happening — no place,
no date, no month, no year, no quotes or search operators. Make it the kind of
that interest this person would actually go to, using only the facts listed
below. "Run Clubs" for someone whose facts say they run casually at weekends
becomes "casual weekend group runs". With no fact bearing on an interest, return
that interest's own words unchanged. Never write a person's name, an address, an
age, a contact detail, or anything about health, money, or legal matters.

profile: one plain sentence saying what kind of happening this interest names,
for matching against event descriptions. Write one for every interest, whether
or not any fact bears on it. "Horses" on its own becomes "horse riding,
equestrian shows and stables"; a fact saying they ride at weekends makes it
"weekend horse riding and equestrian shows". Two words cannot be matched against
an event description — this sentence is what gets compared, so it has to say
what the interest actually means. Still no names and no contact details.

Use only the facts given for anything about the person. Do not invent a
preference, an ability, a companion, or a constraint that no fact states. An
interest with nothing relevant in the facts keeps its own words as the subject
and still gets a described profile. Return one entry per interest, with the
interest copied exactly as given."""


class AimPlanner:
    """Turn interests plus approved memory into search subjects and vectors."""

    # The writer is the same narrow inference contract the describer uses, so a
    # sweep can be exercised end to end without a model by passing None.
    def __init__(
        self,
        writer: TextWriter | None,
        privacy: OutboundPrivacyPolicy | None = None,
        max_aims: int = MAX_AIMS,
        max_tokens: int = 1024,
    ) -> None:
        self.writer = writer
        self.privacy = privacy or OutboundPrivacyPolicy()
        self.max_aims = max_aims
        self.max_tokens = max_tokens

    # Plan one sweep. `place` is what the skeleton will append, and is passed so
    # a subject that repeats it can be rejected rather than doubled.
    async def plan(
        self,
        labels: tuple[str, ...],
        context: PersonalContext,
        place: str = "",
    ) -> SweepAim:
        fallback = SweepAim.from_labels(labels)
        if self.writer is None or not labels:
            return fallback
        planned = await self._ask(labels[: self.max_aims], context)
        if not planned:
            return fallback
        aimed: list[InterestAim] = []
        for label in labels:
            proposal = planned.get(normalize_label(label))
            if proposal is None:
                aimed.append(InterestAim(label=label, subject=label, profile=label))
                continue
            subject, profile = proposal
            aimed.append(
                InterestAim(
                    label=label,
                    subject=self._safe_subject(subject, place) or label,
                    profile=_safe_profile(profile) or label,
                )
            )
        return SweepAim(tuple(aimed))

    # One constrained call, or nothing. Every failure mode — an unreachable
    # runtime, an unparseable body, a schema violation — degrades to the bare
    # labels rather than failing the sweep.
    async def _ask(
        self, labels: tuple[str, ...], context: PersonalContext
    ) -> dict[str, tuple[str, str]] | None:
        # Said explicitly rather than left blank. An empty heading reads as an
        # omission, and a model fills an omission in.
        facts = (
            f"Facts this person has approved about themselves:\n{context.render()}"
            if not context.is_empty
            else (
                "This person has approved no facts about themselves yet, so "
                "describe each interest on its own terms and infer nothing "
                "about them."
            )
        )
        prompt = f"{facts}\n\nTheir interests:\n" + "\n".join(
            f"- {label}" for label in labels
        )
        try:
            result = await asyncio.to_thread(
                self.writer.chat,  # type: ignore[union-attr]
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                self.max_tokens,
                _AimPlan.model_json_schema(),
                # Greedy. A sweep runs while nobody is watching, so the same
                # profile must aim the same way every week; a query that changes
                # by sampling also spends metered search on the variation.
                0.0,
            )
            plan = _AimPlan.model_validate(json.loads(result["content"]))
        except Exception:
            return None
        return {
            normalize_label(aim.interest): (aim.subject, aim.profile)
            for aim in plan.aims
            if aim.interest.strip()
        }

    # Accept a subject only when it is still a kind of happening and still safe
    # to send. Rejection is not a failure: the caller falls back to the interest
    # label, which is what a query carried before this existed.
    def _safe_subject(self, value: str, place: str) -> str | None:
        text = " ".join(_QUERY_SYNTAX.sub(" ", value or "").split())
        if not text or len(text) > MAX_SUBJECT_CHARS:
            return None
        # The skeleton supplies the place and the date. A subject that names
        # either produces a query that says it twice, which is the phrasing
        # measured to return directory pages.
        if _ANY_DIGIT.search(text) or _MONTH_WORDS.search(text):
            return None
        lowered = text.casefold()
        for part in re.split(r"[,/]", place or ""):
            fragment = part.strip().casefold()
            if fragment and fragment in lowered:
                return None
        screened = self.privacy.sanitize(text)
        if not screened.allowed or screened.was_rewritten:
            # A minimized subject is a subject that carried personal framing.
            # It is not repaired here: the label is a better query than a
            # half-edited sentence.
            return None
        return text


# Bound the text ranking embeds. It never leaves the machine, so it is checked
# for shape rather than screened for disclosure.
def _safe_profile(value: str) -> str | None:
    text = " ".join((value or "").split())[:MAX_PROFILE_CHARS]
    return text or None
