"""Tone expiry (study A5): whether a stale release-tone reading should stop counting.

`docs/research/tone-expiry-plan-2026-10-01.md` registers everything here.

The sentiment analyst grades a name from its newest scored earnings release,
and `language.tone_features` carries that reading forward until the next one
is read, with no expiry. The nightly coverage check
(`backend/market/release_coverage.py`) calls a reading *overdue* when the days
since it exceed `TOLERANCE` (1.5) times the name's usual gap between
releases: its own median gap with four or more releases, else the median gap
across the book. This module ages the reading by that same rule - it calls
the check's `own_cadence`, `book_cadence` and `TOLERANCE` rather than
re-deriving them, so the board's coverage note and the study cannot define
"overdue" differently - and offers the plan's two arms:

* `HARD`: a reading older than 1.5 x its usual gap is treated as missing:
  its ten tone fields are set to 0 and `has_tone` to 0, the path a name with
  no scored release already takes (the analyst then has no view of it);
* `DECAY`: the ten tone fields are multiplied by w = 1 up to 1.0 x the usual
  gap, 2 - age/gap between 1.0 x and 2.0 x, and 0 from 2.0 x, where the
  reading is treated as missing exactly as under `HARD`.

Everything is point in time. At a session only the releases whose reaction
date is on or before it count - for the reading's age, the name's own gap
and the book's gap alike - which is how the check counts them and how
`tone_features` admits them on the desk's (legacy) path. The age is in
calendar days, as the check's.

**The flag.** `TONE_EXPIRY` is None (off: the default and the live desk),
`HARD` or `DECAY`. `model.load_tone_features`, the desk's loader of the
sentiment analyst's only input, applies it through `on_load`. Nothing that
reads tone through `language.tone_features` directly - the expectations-gap
learner's strict path, which feeds the value analyst - is touched.
`TONE_EXPIRY_NULL` runs the same path with an infinite horizon, every weight
1, which the point-in-time scorecard's `--tone-expiry <arm> --null-test`
asserts reproduces the incumbent to the bit.

`expired_words` and `weighted_words` are the board's grade-detail lines the
plan drafted for an expired and for a weighted-down reading. Nothing on the
board calls them: they exist so the words are fixed and tested before any
arm could be adopted.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.market import language, release_coverage

HARD = "hard"
DECAY = "decay"
MODES: tuple[str, ...] = (HARD, DECAY)
# A5-hard's horizon is the coverage check's own tolerance, so a reading
# expires exactly when the board's coverage note calls it overdue.
HORIZON = release_coverage.TOLERANCE
# A5-decay's band, in multiples of the usual gap: full weight up to the
# usual gap, none from about one missed release.
DECAY_START = 1.0
DECAY_END = 2.0

# The study's flag: None (off), HARD or DECAY. Off by default and in the
# live desk; set only inside a scorecard run that asks for it.
TONE_EXPIRY: str | None = None
# The null test: the expiry path with an infinite horizon (every weight 1).
TONE_EXPIRY_NULL = False

# The indicator an expiry clears and the ten tone fields it scales.
HAS_TONE = language.FEATURE_NAMES.index("has_tone")
FIELDS: tuple[int, ...] = tuple(
    k for k, name in enumerate(language.FEATURE_NAMES) if name != "has_tone"
)

# Words the grade detail never uses: the coverage note's list and the
# grade actions' verbs.
ADVICE: tuple[str, ...] = (
    "trade",
    "buy",
    "sell",
    "should",
    "avoid",
    "safe",
    "consider",
    "recommend",
    "own",
    "wait",
)


@dataclass(frozen=True)
class Ages:
    """Every (session, name) reading's age and the usual gap it is judged by."""

    # (T, N) calendar days since the reading in use; NaN where there is none.
    age: np.ndarray
    # (T, N) the usual gap in days the age is judged by; NaN where unknown.
    cadence: np.ndarray
    # (T, N) True where the usual gap is the name's own, False for the book's.
    own: np.ndarray
    # (T, N) the reading's reaction date; NaT where there is none.
    last_read: np.ndarray


# The distinct reaction dates of each name's scored releases, oldest first,
# read with the coverage check's own date coercion.
def histories(
    records: Mapping[str, Sequence[language.ToneRecord]],
) -> dict[str, tuple[date, ...]]:
    """Return {ticker: sorted distinct reaction dates} from tone records."""
    return {
        ticker: tuple(sorted({release_coverage._day(r.reaction_date) for r in rows}))
        for ticker, rows in records.items()
    }


# A cadence from the coverage check (None when unknown) as a float or NaN.
def _or_nan(value: float | None) -> float:
    """Return `value` as a float, NaN for None."""
    return math.nan if value is None else float(value)


# The book's usual gap at every session: `release_coverage.book_cadence` of
# every name's releases counted by then. It moves only when some release
# starts to count, so it is computed once per such step.
def _book_cadences(
    calendar: np.ndarray, known: Mapping[str, tuple[date, ...]]
) -> np.ndarray:
    """Return the (T,) book cadence in days at each session, NaN where unknown."""
    every = sorted({d for dates in known.values() for d in dates})
    stamps = np.asarray(every, dtype="datetime64[D]")
    steps = np.searchsorted(stamps, calendar, side="right")
    out = np.full(len(calendar), np.nan)
    for step in np.unique(steps):
        if step == 0:
            continue
        cutoff = every[int(step) - 1]
        value = release_coverage.book_cadence(
            dates[: bisect_right(dates, cutoff)] for dates in known.values()
        )
        out[steps == step] = _or_nan(value)
    return out


# Each (session, name) reading's age and the usual gap it is judged by, from
# the releases counted at that session only: the name's own median gap with
# OWN_HISTORY or more of them (`release_coverage.own_cadence`), else the
# median gap pooled over every name but `benchmark`
# (`release_coverage.book_cadence`). The benchmark column is never aged.
def ages(
    sessions,
    tickers: Sequence[str],
    days: Mapping[str, Sequence[date]],
    benchmark: str | None = None,
) -> Ages:
    """Return the Ages of every (session, name) on the calendar `sessions`."""
    calendar = np.asarray(sessions, dtype="datetime64[D]")
    size, width = len(calendar), len(tickers)
    known = {
        ticker: tuple(sorted(set(days.get(ticker, ()))))
        for ticker in tickers
        if ticker != benchmark
    }
    book = _book_cadences(calendar, known)
    age = np.full((size, width), np.nan)
    cadence = np.full((size, width), np.nan)
    own = np.zeros((size, width), dtype=bool)
    last_read = np.full((size, width), np.datetime64("NaT", "D"), dtype="datetime64[D]")
    for column, ticker in enumerate(tickers):
        dates = known.get(ticker, ())
        if not dates:
            continue
        stamps = np.asarray(dates, dtype="datetime64[D]")
        counted = np.searchsorted(stamps, calendar, side="right")
        # The name's own cadence once n of its releases count, n = 0..all.
        lookup = np.array(
            [
                _or_nan(release_coverage.own_cadence(dates[:n]))
                for n in range(len(dates) + 1)
            ]
        )
        reading = counted > 0
        latest = stamps[np.maximum(counted - 1, 0)]
        mine = lookup[counted]
        has_own = np.isfinite(mine)
        age[reading, column] = (calendar - latest)[reading].astype(np.int64)
        cadence[reading, column] = np.where(has_own, mine, book)[reading]
        own[reading, column] = has_own[reading]
        last_read[reading, column] = latest[reading]
    return Ages(age, cadence, own, last_read)


# Each reading's weight under `mode`: 1 keeps it, 0 treats it as missing,
# and between them (DECAY only) its tone fields are scaled. A cell with no
# reading, or whose usual gap is unknown, keeps weight 1, as the check
# flags nothing without a cadence. `null` puts every horizon at infinity,
# so every weight is 1 by the same arithmetic. HARD compares the age with
# 1.5 x the gap exactly as `release_coverage.assess` does.
def weights(found: Ages, mode: str, null: bool = False) -> np.ndarray:
    """Return the (T, N) weights in [0, 1] of `mode` for the readings in `found`."""
    if mode not in MODES:
        raise ValueError(f"unknown tone expiry {mode!r}; expected one of {MODES}")
    judged = np.isfinite(found.age) & np.isfinite(found.cadence)
    age = np.where(judged, found.age, 0.0)
    gap = np.where(judged, found.cadence, 1.0)
    out = np.ones(found.age.shape)
    if mode == HARD:
        limit = math.inf if null else HORIZON
        out[judged & (age > limit * gap)] = 0.0
        return out
    start, end = (math.inf, math.inf) if null else (DECAY_START, DECAY_END)
    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        low, high = start * gap, end * gap
        slope = np.where(
            age <= low, 1.0, np.where(age >= high, 0.0, (high - age) / (high - low))
        )
    return np.where(judged, slope, out)


# The tone block with each reading's ten fields scaled by its weight. A
# weight of 0 is the missing-reading path (fields 0, `has_tone` 0); a weight
# of 1 leaves the cell's bytes exactly as they were.
def apply(tone: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Return a copy of the (T, N, F) tone block with `weight` applied."""
    out = np.array(tone, copy=True)
    raw = np.asarray(weight, dtype=float)
    gone = raw == 0
    scale = raw.astype(out.dtype)
    for k in FIELDS:
        out[:, :, k] = np.where(gone, 0.0, out[:, :, k] * scale)
    out[:, :, HAS_TONE] = np.where(gone, 0.0, out[:, :, HAS_TONE])
    return out


# The desk's tone block with the study's flag applied: the block itself when
# the flag is off (the live desk), else a copy aged under TONE_EXPIRY, read
# point in time from the same records the block was built from.
def on_load(tone: np.ndarray, panel, records) -> np.ndarray:
    """Return `tone`, or its expired copy when TONE_EXPIRY is set."""
    if TONE_EXPIRY is None:
        return tone
    found = ages(panel.dates, panel.tickers, histories(records), panel.benchmark)
    return apply(tone, weights(found, TONE_EXPIRY, null=TONE_EXPIRY_NULL))


# "usually every 91 days", with "across the book" when the gap is the book's;
# whole days rounded as the coverage note rounds them.
def _usual(cadence_days: float, own: bool) -> str:
    """Return the usual-gap phrase of the grade-detail words."""
    book = "" if own else " across the book"
    return f"usually every {release_coverage._whole(cadence_days)} days{book}"


# The plan's grade-detail line for an expired reading (A5-hard; A5-decay at
# weight 0), led by the recorded stance's mark like every grade-detail line.
def expired_words(
    mark: str, last_read: date, age_days: int, cadence_days: float, own: bool
) -> str:
    """Return the line the board would show for an expired reading."""
    return (
        f"{mark} Sentiment: no current earnings reading (last release read "
        f"{last_read.isoformat()}, {int(age_days)} days ago; "
        f"{_usual(cadence_days, own)})"
    )


# The plan's grade-detail line for a weighted-down reading (A5-decay, a
# weight strictly between 0 and 1): the release's own words as the board
# writes them (`clause`, never from the shrunk numbers), then its date, age,
# usual gap and weight. The weight is shown between 1% and 99%, so a reading
# that is weighted down never reads as unweighted or as gone.
def weighted_words(
    clause: str,
    last_read: date,
    age_days: int,
    cadence_days: float,
    own: bool,
    weight: float,
) -> str:
    """Return the line the board would show for a weighted-down reading."""
    percent = min(99, max(1, int(100.0 * float(weight) + 0.5)))
    return (
        f"{clause} (release read {last_read.isoformat()}, {int(age_days)} days ago, "
        f"{_usual(cadence_days, own)}; weighted {percent}% for its age)"
    )


__all__ = [
    "ADVICE",
    "Ages",
    "DECAY",
    "DECAY_END",
    "DECAY_START",
    "FIELDS",
    "HARD",
    "HAS_TONE",
    "HORIZON",
    "MODES",
    "TONE_EXPIRY",
    "TONE_EXPIRY_NULL",
    "ages",
    "apply",
    "expired_words",
    "histories",
    "on_load",
    "weighted_words",
    "weights",
]
