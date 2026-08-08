"""The provider-neutral contract every discovery source implements.

Local listings are already structured, so discovery reads feeds rather than
searching. That keeps the loop inside the free tiers the project commits to and
yields parseable records instead of prose a model has to interpret.

Feeds are untrusted third-party input. Every field arriving from one is bounded
and stripped of control characters here, at the boundary, so no later stage has
to remember to do it.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

# Bound what one source may contribute. A feed is someone else's data and can
# change size without notice, so a run's cost cannot depend on their restraint.
MAX_EVENTS_PER_SOURCE = 200
MAX_TITLE_CHARS = 300
MAX_PLACE_CHARS = 300
MAX_SUMMARY_CHARS = 2_000
MAX_URL_CHARS = 2_048

# Control characters would corrupt a calendar file and can hide text from a
# reviewer while remaining present in the data.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Up to the first sentence end followed by a space. Requiring the space is what
# keeps "Sept. 12" and "www.example.com" from reading as an ending.
_FIRST_SENTENCE = re.compile(r"(.+?[.!?])\s+\S")

# Below this a leading "sentence" is far more likely an abbreviation than a
# name, so the original title is kept whole.
MIN_SENTENCE_TITLE_CHARS = 25


class FeedError(RuntimeError):
    """Raised when a source cannot be read or its payload is unusable."""


@dataclass(frozen=True, slots=True)
class DiscoveredEvent:
    """One candidate happening, normalized away from its source format."""

    source_id: str
    # Identity as the source states it. Stage 4 deduplicates on this before
    # falling back to similarity, so a re-listed event is announced once.
    external_id: str
    title: str
    starts_at: datetime | None
    ends_at: datetime | None
    place: str | None
    url: str | None
    summary: str | None

    # A calendar entry needs a start; a listing without one can still be shown
    # but cannot become a VEVENT, so the distinction is explicit rather than
    # discovered in stage 5.
    @property
    def is_schedulable(self) -> bool:
        return self.starts_at is not None


class EventSource(ABC):
    """Read one feed of local happenings."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Stable identifier recorded with every event this source yields."""

    @abstractmethod
    async def fetch(self) -> tuple[DiscoveredEvent, ...]:
        """Return the current listing, or raise FeedError."""


# Collapse whitespace, drop control characters, and bound length. Returns None
# for anything that normalizes to nothing so callers get one empty value.
def clean_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    stripped = _CONTROL_CHARACTERS.sub("", value)
    collapsed = " ".join(stripped.split())
    return collapsed[:limit] or None


# A name, not the paragraph a page opened with.
#
# Some sites put a whole description in the title, and truncating that to fit a
# message cuts mid-word: "Country Dance at Faith Lutheran Church in Arlington.
# Lessons: Love, JoAnn (LD), East Coas…" is what reached a delivered digest.
# Everything after the first sentence there is detail the summary already
# carries, so the sentence is the name and the rest is not.
#
# Only applied when the first sentence is itself substantial. "Dr. Dog at the
# Anthem" must not become "Dr." — an abbreviation is not the end of a sentence,
# and the length floor is what tells the two apart without a list of titles.
def clean_title(value: str | None, limit: int = MAX_TITLE_CHARS) -> str | None:
    cleaned = clean_text(value, limit)
    if cleaned is None:
        return None
    sentence = _FIRST_SENTENCE.match(cleaned)
    if sentence is not None:
        candidate = sentence.group(1).strip()
        if len(candidate) >= MIN_SENTENCE_TITLE_CHARS:
            return candidate
    return cleaned


# Accept only web URLs. A feed may carry javascript:, data:, or file: targets,
# and those must never reach a notification or a calendar entry.
def clean_url(value: str | None) -> str | None:
    cleaned = clean_text(value, MAX_URL_CHARS)
    if cleaned is None:
        return None
    lowered = cleaned.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return None
    return cleaned
