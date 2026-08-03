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

INTEREST_PROVENANCE = ("user_explicit", "approved_proposal")


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
