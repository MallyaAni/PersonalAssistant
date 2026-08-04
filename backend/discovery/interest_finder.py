"""Propose interests from what the assistant already knows.

An empty form is a bad way to configure an agent whose whole premise is that it
already knows what you like. This reads the memory the user has already approved
and proposes labels from it.

Two rules make that safe rather than creepy:

- a proposal is never a fact. Nothing here writes to the profile; it returns
  candidates the user accepts one at a time, and acceptance is what records
  `user_explicit` provenance;
- only *approved* memory is read. The memory subsystem distinguishes what the
  user confirmed from what was inferred, and building a profile out of
  inferences would produce an agent acting on things they never said.
"""

from dataclasses import dataclass

from backend.discovery.projection import INTEREST_KEY_PREFIX, LOCALITY_KEY
from backend.discovery.types import (
    MAX_LABEL_CHARS,
    DiscoveryProfile,
    label_digest,
    normalize_label,
)

# Enough to pick from without turning setup into a review task.
MAX_PROPOSALS = 8

# Labels shorter than this are too generic to rank an event against. "art" will
# match everything; "ceramics" will not.
MIN_LABEL_CHARS = 3

# Words that are about the assistant or the conversation rather than a subject.
# A proposal built from these would rank events against the wrong thing.
_STOPWORDS = frozenset(
    {
        "user",
        "assistant",
        "prefers",
        "preference",
        "name",
        "called",
        "likes",
        "like",
        "wants",
        "asked",
        "said",
        "remember",
        "memory",
        "conversation",
        "response",
        "style",
    }
)


@dataclass(frozen=True, slots=True)
class InterestProposal:
    """One candidate interest, with where it came from."""

    label: str
    # Shown so the user can judge the suggestion instead of trusting it.
    evidence: str
    source: str


# Turn approved memory records into proposals the user can accept.
# `records` are the already-approved facts and semantic memories a caller read;
# this module does no querying of its own, so the read policy stays in one place.
def propose_interests(
    records: tuple[dict[str, object], ...],
    profile: DiscoveryProfile,
    limit: int = MAX_PROPOSALS,
) -> tuple[InterestProposal, ...]:
    existing = {label_digest(interest.label) for interest in profile.interests}
    proposals: list[InterestProposal] = []
    seen: set[str] = set()

    for record in records:
        if _is_structural(record):
            continue
        label = _label_from(record)
        if label is None:
            continue
        digest = label_digest(label)
        # Already on the profile, or already proposed in this batch.
        if digest in existing or digest in seen:
            continue
        seen.add(digest)
        proposals.append(
            InterestProposal(
                label=label,
                evidence=_evidence(record),
                source=str(record.get("source") or "memory"),
            )
        )
        if len(proposals) >= limit:
            break
    return tuple(proposals)


# Facts that describe the person rather than what they enjoy. A profile fact is
# still an approved fact, so without naming these the finder offered a home
# locality and a preferred name as interests — the two facts almost every
# account has, which is why the feature looked like it suggested "everything in
# memory".
_STRUCTURAL_FACT_KEYS = frozenset(
    {
        LOCALITY_KEY,
        "preferred_name",
        "response_style",
    }
)


# Whether this fact describes the user rather than something they like.
def _is_structural(record: dict[str, object]) -> bool:
    raw = record.get("fact_key")
    if not isinstance(raw, str) or not raw:
        return False
    # An interest already projected onto the profile is not a new suggestion;
    # it is the thing being suggested, already accepted.
    return raw in _STRUCTURAL_FACT_KEYS or raw.startswith(INTEREST_KEY_PREFIX)


def _label_from(record: dict[str, object]) -> str | None:
    # Only the stored *value* can become a label, and only if it is already
    # interest-shaped. There is deliberately no fallback to an internal key or
    # to the surrounding prose: a note reading "remember their dentist
    # appointment" is filed under a key like `dentist`, and falling back to that
    # key would propose "dentist" as something the user is interested in. The
    # record has to say what they like, not what it is filed as.
    raw = record.get("value")
    if isinstance(raw, str) and raw.strip():
        return _normalize(raw)
    return None


def _normalize(raw: str) -> str | None:
    # Normalizing decides whether this is interest-shaped; it does not decide
    # how it reads. Returning the folded form put "rock climbing" and "Rock
    # Climbing" on the profile as the former, so every suggestion arrived in
    # lower case while a typed one kept its capitals. Identity is normalized
    # separately by `label_digest`, so the two are still one interest.
    display = " ".join(raw.split())
    label = normalize_label(display)
    # A sentence is not an interest. Anything long enough to be prose is
    # rejected rather than truncated into a misleading label.
    if len(label) > MAX_LABEL_CHARS or len(label) < MIN_LABEL_CHARS:
        return None
    if len(display) > MAX_LABEL_CHARS:
        return None
    words = label.split()
    if not words or len(words) > 4:
        return None
    if any(word in _STOPWORDS for word in words):
        return None
    return display


def _evidence(record: dict[str, object]) -> str:
    for key in ("content", "value", "label"):
        raw = record.get(key)
        if isinstance(raw, str) and raw.strip():
            collapsed = " ".join(raw.split())
            return collapsed[:160]
    return ""
