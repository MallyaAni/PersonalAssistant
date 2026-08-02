"""Typed discovery-profile records and the normalization their identity uses."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

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

    # Use a temporary travel destination when set, otherwise use the user's home.
    @property
    def active_locality(self) -> Locality | None:
        for locality in self.localities:
            if locality.is_travel_active:
                return locality
        return self.primary_locality


# Fold case, width, and whitespace so "Live  Music" and "live music" are one
# interest. Accents are preserved because they distinguish real place names.
def normalize_label(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", " ", folded)


# Identify a label without storing a searchable copy of it. The sealed column
# cannot be compared or constrained, so uniqueness rides on this digest.
def label_digest(value: str) -> str:
    return hashlib.sha256(normalize_label(value).encode("utf-8")).hexdigest()
