"""Post-hoc diagnostics of stage 3's selection forecasts inside the A/A+ book.

Not a registered test, and nothing here decides anything. It was written
after the eight registered verdicts of
`docs/research/stage3-results-2026-09-29.md`, and after their 2024-2026
readings had been seen, to ask why the T-S1 overlay turned the sequence
model's forecast - the most informative of the four - into almost nothing.
Its numbers are evidence a later registration may start from. Every drop
rule it scores counts as a trial in that registration's tally; its ICs
and correlations are descriptive.

It reads the T-S1 export (`stage3_io.Stage3Data`, kind ``s1``): one row per
graded member at each decision date t, with `extra["r"]`, the 20-session
open-to-open log return ln(O(t+21) / O(t+1)) minus its mean over the
date's rows, and `extra["grade"]`, the desk's grade at t (the ordinals of
`grading.ORDINAL`). The *book* of a date is its rows graded A or A+, the
policy's `MIN_GRADE`. Per date, over the rows with a finite score and a
finite r, and only when at least `min_names` such rows are there:

* the Spearman IC between a score and r across every graded name, and
  inside the book;
* `lowest` (`highest`): the r of the book's lowest-scored (highest-scored)
  name minus the book's mean r, in bp over the 20 sessions. Dropping that
  name and spreading its weight equally over the rest buys
  -lowest / (n - 1) before costs, caps and the executor, which is why the
  number is the diagnostic's centre: the registered overlay acted on
  exactly this name;
* `gain`: that frictionless drop, -lowest / (n - 1) / 20 in bp per session,
  and zero on sessions whose book is too small to act on - the average over
  every scored session is what a drop-the-lowest overlay could earn at
  best, at any reset phase, before costs, the cap and the executor.

A score is a forecast (`Stage3Forecast.yhat`) or one daily feature column,
which makes the rule "drop the book's name with the lowest (highest) value
of that feature". Rule books are restricted to the rows the reference
forecast scores, so a rule and the forecast are read on the same names and
dates. Ties go to the first row (the export's ticker order).

`summarize` reports each daily series per window (2016-2023, 2024-2026)
and per calendar year: mean, the Newey-West t at `stage3_io.HAC_LAG`
(`candidate_stats.hac_t`; the 20-session labels of neighbouring dates share
19 sessions), median, the share below zero and the count.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.agents.trading.desk import grading
from backend.market import candidate_stats
from backend.market import stage3_io as io

BOOK_GRADE = grading.ORDINAL[grading.A]
WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("2016-2023", "2016-01-01", "2024-01-01"),
    ("2024-2026", "2024-01-01", "2027-01-01"),
)
NOTE = (
    "post-hoc diagnostic, not a registered test: written after the stage-3 "
    "verdicts and after their 2024-2026 readings were seen; it decides nothing"
)


@dataclass(frozen=True)
class BookSeries:
    """One score's daily diagnostics, one entry per session of the export.

    Entries are NaN on sessions without `min_names` usable rows (for the
    book statistics: usable book rows); `graded_size` and `book_size` count
    the usable rows whatever their number.
    """

    dates: np.ndarray  # (S,) datetime64[D], the export's sessions in order
    graded_size: np.ndarray  # (S,) int, usable graded rows
    book_size: np.ndarray  # (S,) int, usable book rows
    ic_all: np.ndarray  # (S,) Spearman IC across every usable graded row
    ic_book: np.ndarray  # (S,) the same inside the book
    lowest: np.ndarray  # (S,) bp: r of the lowest-scored book name - book mean
    highest: np.ndarray  # (S,) bp: the same for the highest-scored name
    gain: np.ndarray  # (S,) bp/session of the frictionless drop; 0 when too few


# The [start, end) row ranges of each session of an export sorted by date.
def session_bounds(dates: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (session dates, starts, ends) of the date-sorted rows."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    if len(dates) and np.any(dates[1:] < dates[:-1]):
        raise ValueError("rows must be sorted by date")
    if not len(dates):
        empty = np.zeros(0, dtype=np.int64)
        return dates, empty, empty
    starts = np.r_[0, np.flatnonzero(dates[1:] != dates[:-1]) + 1].astype(np.int64)
    ends = np.r_[starts[1:], len(dates)].astype(np.int64)
    return dates[starts], starts, ends


# The export's r and grades, checked: the diagnostics read only T-S1 rows.
def _labels(data: io.Stage3Data) -> tuple[np.ndarray, np.ndarray]:
    if data.kind != io.S1:
        raise ValueError(f"the diagnostics read a T-S1 export, not {data.kind!r}")
    for key in ("r", "grade"):
        if key not in data.extra:
            raise ValueError(f"the export has no extra[{key!r}]")
    return np.asarray(data.extra["r"], dtype=float), np.asarray(data.extra["grade"])


# The daily diagnostics of one score over the export's rows. `usable`
# further restricts the rows (a rule's book is the reference forecast's).
def book_series(
    data: io.Stage3Data,
    scores: np.ndarray,
    *,
    usable: np.ndarray | None = None,
    min_names: int = io.S1_MIN_NAMES,
    book_grade: int = BOOK_GRADE,
) -> BookSeries:
    """Return the per-session ICs and book spreads of `scores`."""
    r, grade = _labels(data)
    if min_names < 2:
        raise ValueError("a book needs at least two names to drop one")
    scores = np.asarray(scores, dtype=float)
    if scores.shape != (len(data),):
        raise ValueError(f"scores have shape {scores.shape}; the export has {len(data)} rows")
    ok = np.isfinite(scores) & np.isfinite(r)
    if usable is not None:
        usable = np.asarray(usable, dtype=bool)
        if usable.shape != ok.shape:
            raise ValueError("usable must have one entry per row")
        ok &= usable
    in_book = ok & (grade >= book_grade)
    days, starts, ends = session_bounds(data.dates)
    count = len(days)
    graded_size = np.zeros(count, dtype=np.int64)
    size = np.zeros(count, dtype=np.int64)
    ic_all, ic_book, lowest, highest, gain = (np.full(count, np.nan) for _ in range(5))
    for g, (s, e) in enumerate(zip(starts, ends)):
        rows = np.arange(s, e)
        graded = rows[ok[rows]]
        book = rows[in_book[rows]]
        graded_size[g] = len(graded)
        size[g] = len(book)
        if len(graded) >= min_names:
            ic_all[g] = io.spearman(scores[graded], r[graded])
        if len(graded):
            gain[g] = 0.0
        if len(book) >= min_names:
            ic_book[g] = io.spearman(scores[book], r[book])
            centre = float(r[book].mean())
            lowest[g] = 1e4 * (r[book[int(np.argmin(scores[book]))]] - centre)
            highest[g] = 1e4 * (r[book[int(np.argmax(scores[book]))]] - centre)
            gain[g] = -lowest[g] / (len(book) - 1) / io.S1_HORIZON
    return BookSeries(days, graded_size, size, ic_all, ic_book, lowest, highest, gain)


# Per session, the Spearman correlation of two scores inside the book (how
# much a forecast is one feature), on dates with `min_names` rows where
# both are finite.
def book_correlation(
    data: io.Stage3Data,
    first: np.ndarray,
    second: np.ndarray,
    *,
    min_names: int = io.S1_MIN_NAMES,
    book_grade: int = BOOK_GRADE,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (session dates, per-session book correlation, NaN where too few)."""
    _, grade = _labels(data)
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    ok = np.isfinite(first) & np.isfinite(second) & (grade >= book_grade)
    days, starts, ends = session_bounds(data.dates)
    out = np.full(len(days), np.nan)
    for g, (s, e) in enumerate(zip(starts, ends)):
        rows = np.arange(s, e)
        book = rows[ok[rows]]
        if len(book) >= min_names:
            out[g] = io.spearman(first[book], second[book])
    return days, out


# Mean, HAC t, median, share below zero and count of the finite values in
# [start, end).
def _stats(values: np.ndarray) -> dict[str, float | int]:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {"mean": math.nan, "t": math.nan, "median": math.nan, "below_zero": math.nan, "n": 0}
    return {
        "mean": float(finite.mean()),
        "t": candidate_stats.hac_t(finite, io.HAC_LAG),
        "median": float(np.median(finite)),
        "below_zero": float((finite < 0).mean()),
        "n": int(len(finite)),
    }


# A daily series read per window and per calendar year.
def summarize(
    dates: np.ndarray,
    values: np.ndarray,
    windows: Sequence[tuple[str, str, str]] = WINDOWS,
) -> dict[str, Any]:
    """Return {window: stats, "years": {year: mean}} of the finite values."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    values = np.asarray(values, dtype=float)
    out: dict[str, Any] = {}
    for name, start, end in windows:
        inside = (dates >= np.datetime64(start)) & (dates < np.datetime64(end))
        out[name] = _stats(values[inside])
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    by_year: dict[str, float] = {}
    for year in np.unique(years):
        chosen = values[(years == year) & np.isfinite(values)]
        if len(chosen):
            by_year[str(int(year))] = float(chosen.mean())
    out["years"] = by_year
    return out


# The share of sessions with each usable book size, per window, over the
# sessions with at least one usable graded row.
def size_shares(
    series: BookSeries, windows: Sequence[tuple[str, str, str]] = WINDOWS
) -> dict[str, dict[str, float]]:
    """Return {window: {book size: share of the window's scored sessions}}."""
    out: dict[str, dict[str, float]] = {}
    scored = series.graded_size > 0
    for name, start, end in windows:
        inside = scored & (series.dates >= np.datetime64(start)) & (series.dates < np.datetime64(end))
        sizes = series.book_size[inside]
        out[name] = (
            {str(int(k)): float((sizes == k).mean()) for k in np.unique(sizes)} if len(sizes) else {}
        )
    return out


# A forecast whose keys are the export's rows, or an error: every
# diagnostic reads forecast and label row by row.
def check_forecast(data: io.Stage3Data, forecast: io.Stage3Forecast) -> np.ndarray:
    """Return the forecast's yhat as float, after checking it matches the export."""
    if forecast.kind != io.S1:
        raise ValueError(f"{forecast.family}: a {forecast.kind!r} forecast, not T-S1")
    same = (
        len(forecast.dates) == len(data)
        and np.array_equal(np.asarray(forecast.dates, dtype="datetime64[D]"), np.asarray(data.dates, dtype="datetime64[D]"))
        and np.array_equal(np.asarray(forecast.tickers).astype(str), np.asarray(data.tickers).astype(str))
    )
    if not same:
        raise ValueError(f"{forecast.family}: the forecast's keys are not the export's rows")
    return np.asarray(forecast.yhat, dtype=float)


# Every diagnostic for the given forecasts, and for the one-feature rules
# read on the reference forecast's book.
def diagnose(
    data: io.Stage3Data,
    forecasts: Mapping[str, io.Stage3Forecast],
    *,
    features: Sequence[str] = (),
    reference: str | None = None,
    min_names: int = io.S1_MIN_NAMES,
    book_grade: int = BOOK_GRADE,
) -> dict[str, Any]:
    """Return the JSON-ready diagnostics record."""
    out: dict[str, Any] = {
        "plan": io.PLAN,
        "note": NOTE,
        "min_names": int(min_names),
        "book_grade": int(book_grade),
        "hac_lag": io.HAC_LAG,
        "units": (
            "ic: Spearman; lowest/highest: bp of 20-session log return against the book mean; "
            "gain: bp per session of the frictionless drop of the lowest name"
        ),
        "forecasts": {},
        "rules": {},
    }
    scores: dict[str, np.ndarray] = {}
    for family, forecast in forecasts.items():
        yhat = check_forecast(data, forecast)
        scores[family] = yhat
        series = book_series(data, yhat, min_names=min_names, book_grade=book_grade)
        out["forecasts"][family] = {
            "ic_all": summarize(series.dates, series.ic_all),
            "ic_book": summarize(series.dates, series.ic_book),
            "lowest": summarize(series.dates, series.lowest),
            "highest": summarize(series.dates, series.highest),
            "gain": summarize(series.dates, series.gain),
            "book_sizes": size_shares(series),
        }
    if features:
        if reference not in scores:
            raise ValueError(f"the rules need a reference forecast among {sorted(scores)}, not {reference!r}")
        out["rules"]["reference"] = reference
        names = list(data.feature_names)
        base = np.isfinite(scores[reference])
        for feature in features:
            if feature not in names:
                raise ValueError(f"unknown feature {feature!r}")
            column = np.asarray(data.x[:, names.index(feature)], dtype=float)
            series = book_series(data, column, usable=base, min_names=min_names, book_grade=book_grade)
            days, corr = book_correlation(
                data, scores[reference], column, min_names=min_names, book_grade=book_grade
            )
            out["rules"][feature] = {
                "drop_lowest": summarize(series.dates, series.lowest),
                "drop_highest": summarize(series.dates, series.highest),
                "correlation_with_reference": summarize(days, corr),
            }
    return out
