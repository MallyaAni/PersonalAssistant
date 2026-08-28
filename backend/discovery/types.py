"""Typed discovery-profile records and the normalization their identity uses."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

# Bound how much profile can exist. Every interest is eligible to enter a chat
# prompt, so an unbounded list would silently grow the context of every turn.
MAX_INTERESTS_PER_USER = 50
MAX_LOCALITIES_PER_USER = 5
MAX_LABEL_CHARS = 80
MAX_REGION_CHARS = 80
MIN_RADIUS_KM = 1
MAX_RADIUS_KM = 200

# `shared_by_members`: an interest a group holds because two or more of its
# members hold it (backend/groups/shared_interests.py); never written by a
# person and refreshed whenever the membership changes.
INTEREST_PROVENANCE = ("user_explicit", "approved_proposal", "shared_by_members")


@dataclass(frozen=True, slots=True)
class Interest:
    """One approved interest, independent of how it is stored."""

    id: str
    label: str
    strength: int
    provenance: str


@dataclass(frozen=True, slots=True)
class Locality:
    """One place the user wants discoveries near."""

    id: str
    label: str
    region: str | None
    radius_km: int
    timezone: str
    is_primary: bool
    is_travel_active: bool = False
    # When the trip ends on its own. None means open-ended, which is what a
    # destination set before expiry existed still carries.
    travel_expires_at: datetime | None = None

    # Report whether this is where the user currently is. A lapsed trip is not,
    # which is what stops a forgotten one from redirecting Scout forever.
    def is_away_at(self, moment: datetime) -> bool:
        if not self.is_travel_active:
            return False
        return self.travel_expires_at is None or self.travel_expires_at > moment


@dataclass(frozen=True, slots=True)
class DiscoveryProfile:
    """The complete scored profile one discovery run reads."""

    interests: tuple[Interest, ...]
    localities: tuple[Locality, ...]

    # Expose the place a run defaults to without making callers re-derive it.
    @property
    def primary_locality(self) -> Locality | None:
        for locality in self.localities:
            if locality.is_primary:
                return locality
        return self.localities[0] if self.localities else None

    # Use where the user currently is, otherwise where they live. An expired
    # trip falls back to home on its own, so forgetting to say you came back
    # costs nothing.
    @property
    def active_locality(self) -> Locality | None:
        return self.locality_at(datetime.now(UTC))

    # Resolve the active place as of a given moment, so the expiry rule is
    # testable without waiting for real time to pass.
    def locality_at(self, moment: datetime) -> Locality | None:
        for locality in self.localities:
            if locality.is_away_at(moment):
                return locality
        return self.primary_locality

    # True when the user is somewhere other than home right now. The interface
    # states this as a fact rather than offering it as a mode to switch.
    @property
    def is_away(self) -> bool:
        current = self.active_locality
        home = self.primary_locality
        return current is not None and home is not None and current.id != home.id


# Fold case, width, and whitespace so "Live  Music" and "live music" are one
# interest. Accents are preserved because they distinguish real place names.
def normalize_label(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", " ", folded)


# Identify a label without storing a searchable copy of it. The sealed column
# cannot be compared or constrained, so uniqueness rides on this digest.
def label_digest(value: str) -> str:
    return hashlib.sha256(normalize_label(value).encode("utf-8")).hexdigest()


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
