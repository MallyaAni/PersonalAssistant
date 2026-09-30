"""Which names the desk grades, and against whom: the universe arms' cohort.

`desk.run` grades the 94-name AI-and-software book, ranking every analyst's
score across the whole book. The universe-expansion registration
(`docs/research/universe-expansion-plan-2026-09-30.md`, "Arms") asks the
same desk to grade every stock member of `build_universe()` (the S&P 500
constituents plus the overlay) with the cross-section chosen per arm. A
`Cohort` says which names and which cross-section; `desk.run(cohort=...)`
reads it, and with `cohort=None` runs the book exactly as before.

Choices (where the registration left a detail open, the simplest faithful
option, written down before any universe number is read):

1. **The regime analyst reads the book, whatever the cohort.** Its AI and
   software baskets, participation, novelty and the rotation gate come
   from `book_sides` and the book's themes; names outside the book carry
   no theme in the cohort panel. So the regime states, the exposure and
   the rotation stance are those of the book-94 run, and the rotation
   stance is 0 outside the book (its scores are NaN there), as the plan
   registers. This is also what makes the null test exact.
2. **An analyst's score is built as today; its rank is taken within the
   group.** Each analyst's own leg blend (the sentiment analyst's rank
   blend of tone legs, the fundamental analyst's of growth legs) still
   runs over the whole panel; the percentile rank that makes the stance
   and the conviction (`Opinion.ranks`) is taken within the name's group.
   "Top 30% of its sector" is the registered meaning, and this is the
   smallest change that gives it.
3. **The value analyst's peer group is the cohort's group map**, so in the
   sector arm a name is cheap against its GICS sector, in the flat arm
   against the whole universe (one group), and on the book against its
   side. The expectations gap blended into it (`challenger.with_gap`)
   ranks within the same groups. The size-neutral leg keeps its
   universe-wide size thirds: size is not a sector.
4. **Overlay names without a GICS sector count in Information
   Technology** (the plan's words); an overlay name that is also a
   constituent keeps the constituent file's sector.
5. **The tone arm's names are those with a stored `release_tone` frame**
   at the run's `asof`, read from the store, not a list in code, so the
   arm follows coverage as the plan describes it.
6. **The blended tie-break** (`desk.blended`) is unchanged: it only
   orders names when no conviction was recorded, which never happens on
   this path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.market import universe as universe_module
from backend.market.panel import Panel

# The sector overlay-only names count in, per the registration.
OVERLAY_SECTOR = "Information Technology"
# The one group of the flat arm.
FLAT_GROUP = "universe"

SECTOR = "sector"
FLAT = "flat"
TONE = "tone"
BOOK = "book"
ARMS: tuple[str, ...] = (SECTOR, FLAT, TONE)


@dataclass(frozen=True)
class Cohort:
    """The names the desk grades and the cross-section each rank is taken in."""

    # What the run is called in payloads and file names.
    label: str
    # The stock names of the panel (the benchmark is added by the desk).
    names: tuple[str, ...]
    # {ticker: group} for every name: the value analyst's peer map, and
    # the rank group when `rank_within_peers` is set.
    peers: dict[str, str]
    # Whether every analyst's rank, stance and conviction is taken within
    # the name's `peers` group rather than across the whole panel.
    rank_within_peers: bool

    # The (N,) group id per panel column, -1 for the benchmark or a name
    # outside the map; None when the cohort ranks across the whole panel.
    def groups_for(self, panel: Panel) -> np.ndarray | None:
        """Return the column group ids for `Opinion.groups`, or None."""
        if not self.rank_within_peers:
            return None
        labels = sorted(set(self.peers.values()))
        ids = np.full(len(panel.tickers), -1, dtype=int)
        for column, ticker in enumerate(panel.tickers):
            if ticker == panel.benchmark:
                continue
            group = self.peers.get(ticker)
            if group is not None:
                ids[column] = labels.index(group)
        return ids


# {ticker: GICS sector} for every stock member of the universe: the
# constituent file's sector, and OVERLAY_SECTOR for an overlay-only name.
def sector_map(universe=None) -> dict[str, str]:
    """Return the sector of every FOCUS/MEMBER name."""
    universe = universe_module.build_universe() if universe is None else universe
    return {
        m.ticker: m.sector or OVERLAY_SECTOR
        for m in universe
        if m.role in (universe_module.FOCUS, universe_module.MEMBER)
    }


# The book as a cohort: the same names and the same side peer map the desk
# uses, ranked across the whole panel. Running the desk on it must give the
# book run bit for bit; the scorecard's `--null-test` asserts that.
def book_cohort(universe=None) -> Cohort:
    """Return the 94-name book as a Cohort (the control)."""
    universe = universe_module.build_universe() if universe is None else universe
    sides = universe_module.book_sides(universe)
    return Cohort(BOOK, tuple(sorted(sides)), dict(sides), rank_within_peers=False)


# One of the registered universe arms as a cohort. `store` and `asof` are
# read only by the tone arm, to find which names carry a tone frame.
def universe_cohort(
    arm: str, store=None, asof: date | None = None, universe=None
) -> Cohort:
    """Return the Cohort for `arm` in ARMS."""
    if arm not in ARMS:
        raise ValueError(f"unknown universe arm {arm!r}; expected one of {ARMS}")
    universe = universe_module.build_universe() if universe is None else universe
    sectors = sector_map(universe)
    names = tuple(sorted(sectors))
    if arm == FLAT:
        return Cohort(
            FLAT, names, {t: FLAT_GROUP for t in names}, rank_within_peers=False
        )
    if arm == TONE:
        if store is None:
            raise ValueError("the tone arm needs the store to read tone coverage")
        names = tuple(t for t in names if has_tone(store, t, asof))
        sectors = {t: sectors[t] for t in names}
    return Cohort(arm, names, sectors, rank_within_peers=True)


# Whether the store holds a release-tone frame for the name on or before asof.
def has_tone(store, ticker: str, asof: date | None = None) -> bool:
    """Return True when a `release_tone` frame is stored for `ticker`."""
    from backend.market import language

    return store.read_frame(language.TONE_KIND, ticker, asof) is not None
