"""An externally supplied stance, read point in time, graded beside the five.

The research studies that propose a new analyst (text surprise, the LLM
statement reader, insider trades) each measure their arm's rank IC on
their own and then need the book gate: the point-in-time scorecard run
with the arm's stance in the grade. They emit the same table for it, in
long form, one row per (session, name) on which the arm's own persisted
stance is not neutral:

    session     ticker  stance  [conviction | rank]
    2024-03-04  NVDA    1
    2024-03-04  CRM     -1

`load` reads such a table (parquet through pyarrow, or CSV), `align` lays
it onto a panel point in time, and `regrade` re-grades a desk report with
it under one of two modes:

* `sixth`: the table votes as a sixth analyst under the unchanged rule
  (`grading.grade_stances`' `extra`): a full vote, never a veto, no part
  in the release or strong-agreement clauses. A bullish sixth vote lowers
  by one the votes a name needs from the five for B, A and A+; a bearish
  one raises them by one without capping the grade.
* `replace:<analyst>`: the table takes that analyst's place entirely -
  its stance, its conviction in the ordering score, and that analyst's
  role in the rule (replacing `sentiment`, a bullish table row is the
  bullish release; replacing a core analyst, a bearish row vetoes).

The date rule: a row dated `d` applies to the first panel session on or
after `d` and to that session only. Nothing is carried forward, because
the tables are dense (the arm's stance is written on every session it
holds, and a session with no row is neutral); a row dated after a session
cannot touch it, and a row dated after the panel's last session is
unused. A name the panel does not hold is ignored and counted. The
conviction column, when present, is the table's conviction in the summed
score; a `rank` column in [0, 1] is turned into one as the analysts'
ranks are (`opinions.conviction_from_ranks`); with neither, the stance
itself is the conviction, so a bullish row orders above a neutral one.

The null test the scorecard runs before any table is read: the same rows
with every stance and conviction set to zero, in `sixth` mode, must
reproduce the incumbent's grades, votes, convictions and scores bit for
bit (`zeroed`).
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import grading, risk
from backend.agents.trading.desk.opinions import (
    BEARISH,
    BULLISH,
    NEUTRAL,
    SHARPNESS,
    conviction_from_ranks,
)

MODE_SIXTH = "sixth"
MODE_REPLACE = "replace"
MODES = (MODE_SIXTH, f"{MODE_REPLACE}:<analyst>")
# The names the five analysts carry in a Graded's stances.
ANALYSTS: tuple[str, ...] = tuple(grading.ANALYST_WEIGHTS)
# The prefix an extra analyst's name carries in the grade, so it can
# never collide with the five.
EXTRA_PREFIX = "table:"
# Accepted column names, first match wins.
DATE_COLUMNS = ("session", "date")
NAME_COLUMNS = ("ticker", "name", "symbol")
STANCE_COLUMN = "stance"
CONVICTION_COLUMN = "conviction"
RANK_COLUMN = "rank"


@dataclass(frozen=True)
class StanceTable:
    """The rows of one table, as read: dates, names, stances and convictions."""

    path: str
    sha256: str
    # The analyst name the table grades under in `sixth` mode.
    name: str
    dates: np.ndarray  # (R,) datetime64[D]
    tickers: tuple[str, ...]  # (R,)
    stances: np.ndarray  # (R,) int in {-1, 0, 1}
    # (R,) float conviction in [-1, 1]; NaN where the table gave none.
    convictions: np.ndarray
    columns: tuple[str, ...] = ()

    # How many rows the table holds.
    def __len__(self) -> int:
        """Return the row count."""
        return len(self.dates)


@dataclass(frozen=True)
class Aligned:
    """One table laid onto a panel: (T, N) stance and conviction, and the audit."""

    table: StanceTable
    stance: np.ndarray  # (T, N) int
    conviction: np.ndarray  # (T, N) float, NaN where no row
    record: dict[str, object] = field(default_factory=dict)


# The mode string parsed: ("sixth", None) or ("replace", analyst).
def parse_mode(mode: str) -> tuple[str, str | None]:
    """Return (kind, analyst) for `sixth` or `replace:<analyst>`; else ValueError."""
    text = (mode or "").strip()
    if text == MODE_SIXTH:
        return MODE_SIXTH, None
    kind, sep, analyst = text.partition(":")
    if kind == MODE_REPLACE and sep and analyst in ANALYSTS:
        return MODE_REPLACE, analyst
    raise ValueError(
        f"unknown stance mode {mode!r}: expected {MODE_SIXTH!r} or "
        f"replace:<one of {', '.join(ANALYSTS)}>"
    )


# The analyst name a table votes under in `sixth` mode: its file stem,
# prefixed so it cannot be one of the five.
def extra_name(path: Path | str) -> str:
    """Return the grade's name for the table at `path`."""
    return EXTRA_PREFIX + Path(path).stem


# The SHA-256 of a file's bytes, so a payload names exactly the table it read.
def sha256_of(path: Path | str) -> str:
    """Return the hex digest of the file at `path`."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Read a table's columns from parquet (pyarrow) or CSV, as lists.
def read_columns(path: Path | str) -> dict[str, list]:
    """Return {column: values} from the file at `path`."""
    path = Path(path)
    if path.suffix.lower() in (".parquet", ".pq"):
        import pyarrow.parquet as pq

        return pq.read_table(path).to_pydict()
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        with open(path, newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle), [])
        return {column: [] for column in header}
    return {column: [row[column] for row in rows] for column in rows[0]}


# The first of `wanted` present in `columns`, or None.
def _pick(columns: dict[str, list], wanted: tuple[str, ...]) -> str | None:
    for name in wanted:
        if name in columns:
            return name
    return None


# Build the table from its columns: dates parsed, stances checked to be
# in {-1, 0, 1}, the conviction from the conviction or rank column.
def from_columns(
    columns: dict[str, list], path: str = "", sha256: str = "", name: str = ""
) -> StanceTable:
    """Return the StanceTable the columns describe; a bad value is a ValueError."""
    date_column = _pick(columns, DATE_COLUMNS)
    name_column = _pick(columns, NAME_COLUMNS)
    if date_column is None or name_column is None or STANCE_COLUMN not in columns:
        raise ValueError(
            f"stance table {path or '<columns>'} needs columns "
            f"{'/'.join(DATE_COLUMNS)}, {'/'.join(NAME_COLUMNS)} and {STANCE_COLUMN}; "
            f"found {sorted(columns)}"
        )
    raw_dates = columns[date_column]
    try:
        dates = np.array([np.datetime64(str(d)[:10], "D") for d in raw_dates])
    except ValueError as exc:
        raise ValueError(f"stance table {path}: an unreadable date: {exc}") from exc
    tickers = tuple(str(t).strip().upper() for t in columns[name_column])
    stances = np.zeros(len(raw_dates), dtype=int)
    for i, value in enumerate(columns[STANCE_COLUMN]):
        number = float(value)
        if number not in (BEARISH, NEUTRAL, BULLISH):
            raise ValueError(
                f"stance table {path}: row {i} has stance {value!r}; "
                "a stance is -1, 0 or 1"
            )
        stances[i] = int(number)
    convictions = np.full(len(raw_dates), np.nan)
    if CONVICTION_COLUMN in columns:
        values = np.array(
            [
                np.nan if v in ("", None) else float(v)
                for v in columns[CONVICTION_COLUMN]
            ]
        )
        finite = values[np.isfinite(values)]
        if finite.size and np.abs(finite).max() > 1.0:
            raise ValueError(f"stance table {path}: a conviction outside [-1, 1]")
        convictions = values
    elif RANK_COLUMN in columns:
        ranks = np.array(
            [np.nan if v in ("", None) else float(v) for v in columns[RANK_COLUMN]]
        )
        finite = ranks[np.isfinite(ranks)]
        if finite.size and (finite.min() < 0.0 or finite.max() > 1.0):
            raise ValueError(f"stance table {path}: a rank outside [0, 1]")
        convictions = conviction_from_ranks(ranks, SHARPNESS)
    return StanceTable(
        path=str(path),
        sha256=sha256,
        name=name or extra_name(path or "table"),
        dates=dates if len(dates) else np.array([], dtype="datetime64[D]"),
        tickers=tickers,
        stances=stances,
        convictions=convictions,
        columns=tuple(columns),
    )


# Read one table from disk, hashed.
def load(path: Path | str) -> StanceTable:
    """Return the StanceTable at `path`, with its sha256 and grade name."""
    path = Path(path)
    columns = read_columns(path)
    return from_columns(columns, str(path), sha256_of(path), extra_name(path))


# Lay a table onto a panel point in time: a row dated d lands on the
# first session >= d and that session only; later duplicates win; rows
# after the panel, and names the panel lacks, are counted and dropped.
def align(table: StanceTable, panel) -> Aligned:
    """Return the (T, N) stance and conviction of `table` on `panel`."""
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    tickers = tuple(panel.tickers)
    column = {t: j for j, t in enumerate(tickers)}
    benchmark = getattr(panel, "benchmark", None)
    stance = np.zeros((len(days), len(tickers)), dtype=int)
    conviction = np.full(stance.shape, np.nan)
    counts = {
        "rows": int(len(table)),
        "rows_used": 0,
        "rows_after_panel": 0,
        "rows_before_panel": 0,
        "rows_unknown_name": 0,
        "rows_benchmark": 0,
        "rows_mapped_forward": 0,
        "rows_overridden": 0,
    }
    if len(table):
        order = np.argsort(table.dates, kind="stable")
        positions = np.searchsorted(days, table.dates, side="left")
        seen = np.zeros(stance.shape, dtype=bool)
        for i in order:
            name = table.tickers[i]
            if name == benchmark:
                counts["rows_benchmark"] += 1
                continue
            j = column.get(name)
            if j is None:
                counts["rows_unknown_name"] += 1
                continue
            t = int(positions[i])
            if t >= len(days):
                counts["rows_after_panel"] += 1
                continue
            if table.dates[i] < days[0]:
                # A row from before the panel's first session is not that
                # session's stance; a dense table says nothing about it.
                counts["rows_before_panel"] += 1
                continue
            if days[t] != table.dates[i]:
                counts["rows_mapped_forward"] += 1
            if seen[t, j]:
                counts["rows_overridden"] += 1
            seen[t, j] = True
            stance[t, j] = int(table.stances[i])
            given = table.convictions[i]
            conviction[t, j] = (
                float(given) if np.isfinite(given) else float(stance[t, j])
            )
            counts["rows_used"] += 1
    record: dict[str, object] = {
        "path": table.path,
        "sha256": table.sha256,
        "name": table.name,
        "columns": list(table.columns),
        **counts,
        "cells_bullish": int((stance == BULLISH).sum()),
        "cells_bearish": int((stance == BEARISH).sum()),
        "first_session": str(days[np.flatnonzero((stance != 0).any(axis=1))[0]])
        if (stance != 0).any()
        else None,
        "last_session": str(days[np.flatnonzero((stance != 0).any(axis=1))[-1]])
        if (stance != 0).any()
        else None,
    }
    return Aligned(table, stance, conviction, record)


# The same rows with every stance and conviction at zero: the null table.
def zeroed(aligned: Aligned) -> Aligned:
    """Return `aligned` with its stance and conviction all zero."""
    return Aligned(
        aligned.table,
        np.zeros_like(aligned.stance),
        np.zeros_like(aligned.conviction),
        {**aligned.record, "null": True},
    )


# The five analysts' convictions in the order `grading.grade` sums them,
# recomputed from the report's opinions and its regime view, so the
# re-grade's summed conviction is the desk's own to the bit.
def _convictions(report) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for name in ("fundamental", "technical", "sentiment"):
        out[name] = report.opinions[name].conviction()
    rotation = getattr(report.regime, "rotation", None)
    if "rotation" in report.graded.stances and rotation is not None:
        out["rotation"] = rotation.conviction()
    if "value" in report.graded.stances and "value" in report.opinions:
        out["value"] = report.opinions["value"].conviction()
    return out


# The grade's inputs with the tables in place: the five stances (one
# replaced in replace mode), the convictions in the desk's order with the
# tables' appended, and the extra stances for sixth mode.
def _inputs(report, aligned: list[Aligned], kind: str, analyst: str | None):
    """Return (stances, convictions, extra) for `grading.grade_stances`."""
    if kind == MODE_REPLACE and len(aligned) != 1:
        raise ValueError("replace mode takes exactly one stance table")
    stances = dict(report.graded.stances)
    for name in ("fundamental", "technical", "sentiment"):
        if name not in stances:
            raise ValueError(f"the report's grade carries no {name!r} stance")
    shape = np.shape(stances["fundamental"])
    for item in aligned:
        if np.shape(item.stance) != shape:
            raise ValueError("a stance table is not aligned to the report's panel")
    convictions = _convictions(report)
    if kind == MODE_REPLACE:
        if analyst not in stances:
            raise ValueError(f"the report's grade carries no {analyst!r} stance")
        stances[analyst] = aligned[0].stance
        convictions[analyst] = aligned[0].conviction
        return stances, convictions, None
    extra: dict[str, np.ndarray] = {}
    for item in aligned:
        if item.table.name in extra:
            raise ValueError(f"two stance tables are both named {item.table.name!r}")
        extra[item.table.name] = item.stance
        convictions[item.table.name] = item.conviction
    return stances, convictions, extra


# Re-grade a desk report with the aligned tables under `mode`, by the
# desk's own rule and weights (`desk.assemble`), and re-size its book.
def regrade(
    report,
    aligned: list[Aligned],
    mode: str,
    weights: dict[str, float] | None = grading.ANALYST_WEIGHTS,
):
    """Return a copy of `report` graded with the tables; `mode` as `parse_mode`."""
    from backend.agents.trading.desk import desk

    kind, analyst = parse_mode(mode)
    stances, convictions, extra = _inputs(report, aligned, kind, analyst)
    graded = grading.grade_stances(
        stances["fundamental"],
        stances["technical"],
        stances["sentiment"],
        stances.get("rotation"),
        stances.get("value"),
        convictions,
        weights,
        True,
        extra=extra,
    )
    tie_break = desk.blended(report.opinions) if report.opinions else None
    scores = graded.as_scores(tie_break)
    panel = report.panel
    last = len(panel.dates) - 1
    book = risk.size(scores[last], graded.grades[last], panel, report.regime.today())
    out = replace(report, graded=graded, scores=scores, book=book)
    alternate = getattr(report, "alternate", None)
    if alternate is not None:
        out = replace(out, alternate=regrade(alternate, aligned, mode, weights))
    return out


# What the tables did to the grade: per window, the eligible name-sessions
# at each grade before and after, and the cells whose grade moved.
def grade_record(before, after, mask: np.ndarray, windows: dict) -> dict[str, object]:
    """Return {window: {"before": {grade: n}, "after": {...}, "moved": n, ...}}."""
    from backend.agents.trading.desk import point_in_time

    dates = np.asarray(before.panel.dates, dtype="datetime64[D]")
    out: dict[str, object] = {}
    for name, (start, end) in windows.items():
        w = point_in_time.window(dates, start, end)
        cells = mask & w[:, None]
        counts = {}
        for label, graded in (("before", before.graded), ("after", after.graded)):
            counts[label] = {
                letter: int(((graded.grades == grading.ORDINAL[letter]) & cells).sum())
                for letter in grading.GRADES
            }
        moved = (before.graded.grades != after.graded.grades) & cells
        up = (after.graded.grades > before.graded.grades) & cells
        out[name] = {
            **counts,
            "eligible_name_sessions": int(cells.sum()),
            "moved": int(moved.sum()),
            "moved_up": int(up.sum()),
            "moved_down": int((moved & ~up).sum()),
        }
    return out
