"""The forward shadow of the sequence model's A/A+ laggard: ledger, scoring, verdict.

`docs/research/laggard-shadow-plan-2026-09-29.md` registers every rule here.
Nothing in this module trades, reaches the board or touches the live path.

A **ledger entry** is one decision date d after the frozen model's
training export:
- the model id and the export's sha256;
- the book: the export's rows at d graded A or A+ with a finite forecast,
  in the export's row order (ticker order), each with its grade and
  forecast;
- the laggard (the lowest forecast; ties go to the first row) and the top
  name;
- the book names whose own session d had no complete cube (an unclean
  date).

The first entry for a date is final: `append` refuses a second.

A date is **scored** once a later export has a finite 20-session relative
return r (`extra["r"]`) for every book name:
- the spread, 1e4 × (r of the laggard − the book's mean r);
- the frictionless gain, −spread / (n − 1) / `S1_HORIZON` bp per session;
- the top name's spread;
- the IC inside the book (three names or more).

The **primary statistic** is the mean spread over scored clean dates whose
book has at least `PRIMARY_MIN` names, in date order, with
`candidate_stats.hac_t` at `HAC_LAG`. The verdict is read at `LOOKS`
primary dates:
- CONFIRMED at the first look whose t is at most `THRESHOLD`;
- NOT CONFIRMED at the last look otherwise;
- PENDING before that.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk import grading
from backend.market import candidate_stats
from backend.market import stage3_io as io

PLAN = "docs/research/laggard-shadow-plan-2026-09-29.md"
BOOK_GRADE = grading.ORDINAL[grading.A]
PRIMARY_MIN = 3
SECONDARY_MINIMUMS = (3, 4, 5)
LOOKS = (250, 500)
THRESHOLD = -2.24
HAC_LAG = io.HAC_LAG
# The training export's last session: forward dates come after it.
TRAINED_THROUGH = "2026-09-28"


# The rows of one date in a date-sorted export, as a slice.
def date_rows(dates: np.ndarray, day: np.datetime64) -> np.ndarray:
    """Return the row positions dated `day`."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    lo = int(np.searchsorted(dates, day, side="left"))
    hi = int(np.searchsorted(dates, day, side="right"))
    return np.arange(lo, hi)


# The export's sessions strictly after `after`, in order.
def forward_dates(dates: np.ndarray, after: str = TRAINED_THROUGH) -> list[np.datetime64]:
    """Return the unique dates later than `after`."""
    unique = np.unique(np.asarray(dates, dtype="datetime64[D]"))
    return [d for d in unique if d > np.datetime64(after)]


# One ledger entry for date `day`: the book (A/A+ rows with a finite
# forecast, in row order), the laggard and top name, and which book names
# had no complete cube for their own session.
def entry(
    data: io.Stage3Data,
    yhat: np.ndarray,
    day: np.datetime64,
    *,
    model_id: str,
    export_sha256: str,
    made_at: str,
    own_invalid: Iterable[str] = (),
    book_grade: int = BOOK_GRADE,
) -> dict[str, Any]:
    """Return the ledger entry of `day`."""
    if data.kind != io.S1:
        raise ValueError(f"the shadow reads a T-S1 export, not {data.kind!r}")
    grades = np.asarray(data.extra["grade"])
    rows = date_rows(data.dates, day)
    yhat = np.asarray(yhat, dtype=float)
    book_rows = [int(r) for r in rows if grades[r] >= book_grade and math.isfinite(yhat[r])]
    book = [
        {"ticker": str(data.tickers[r]), "grade": int(grades[r]), "forecast": float(yhat[r])}
        for r in book_rows
    ]
    invalid = sorted(set(own_invalid) & {b["ticker"] for b in book})
    laggard = top = None
    if book:
        values = np.array([b["forecast"] for b in book])
        laggard = book[int(np.argmin(values))]["ticker"]
        top = book[int(np.argmax(values))]["ticker"]
    return {
        "date": str(np.datetime64(day, "D")),
        "model_id": model_id,
        "export_sha256": export_sha256,
        "made_at": made_at,
        "rows": int(len(rows)),
        "book": book,
        "n": len(book),
        "laggard": laggard,
        "top": top,
        "unclean": invalid,
        "plan": PLAN,
    }


# Every entry of a ledger file, in file order (empty when the file is absent).
def read_ledger(path: Path) -> list[dict[str, Any]]:
    """Return the ledger's entries."""
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# Append entries to the ledger. A date already in the ledger, or twice in
# `entries`, is refused: the first forecast for a date is final.
def append(path: Path, entries: Sequence[Mapping[str, Any]]) -> int:
    """Append `entries` and return how many were written."""
    path = Path(path)
    seen = {e["date"] for e in read_ledger(path)}
    new: list[str] = []
    for e in entries:
        if e["date"] in seen:
            raise ValueError(f"{e['date']} is already in the ledger; its first forecast is final")
        seen.add(e["date"])
        new.append(json.dumps(io.clean_json(dict(e)), sort_keys=True))
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write("\n".join(new) + "\n")
    return len(new)


# {(date, ticker): r} over an export's rows with a finite r.
def r_lookup(data: io.Stage3Data) -> dict[tuple[str, str], float]:
    """Return every finite relative return of the export by (date, ticker)."""
    r = np.asarray(data.extra["r"], dtype=float)
    keep = np.flatnonzero(np.isfinite(r))
    dates = np.asarray(data.dates, dtype="datetime64[D]").astype(str)
    return {(dates[i], str(data.tickers[i])): float(r[i]) for i in keep}


# Score one entry against the relative returns known now: None while any
# book name lacks one (or the book is empty), else the spread, the gain,
# the top name's spread and the book IC.
def score(e: Mapping[str, Any], returns: Mapping[tuple[str, str], float]) -> dict[str, Any] | None:
    """Return the entry's score, or None while it is not mature."""
    book = e["book"]
    if len(book) < 2:
        return None
    values = [returns.get((e["date"], b["ticker"])) for b in book]
    if any(v is None or not math.isfinite(v) for v in values):
        return None
    r = dict(zip((b["ticker"] for b in book), values, strict=True))
    centre = float(np.mean(values))
    spread = 1e4 * (r[e["laggard"]] - centre)
    forecasts = np.array([b["forecast"] for b in book])
    return {
        "date": e["date"],
        "model_id": e["model_id"],
        "n": len(book),
        "clean": not e["unclean"],
        "spread": spread,
        "gain": -spread / (len(book) - 1) / io.S1_HORIZON,
        "top_spread": 1e4 * (r[e["top"]] - centre),
        "ic_book": io.spearman(forecasts, np.array(values)) if len(book) >= 3 else math.nan,
    }


# Mean, HAC t and count of a series in order.
def _stats(values: Sequence[float]) -> dict[str, Any]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if not len(v):
        return {"mean": math.nan, "t": math.nan, "n": 0}
    return {"mean": float(v.mean()), "t": candidate_stats.hac_t(v, HAC_LAG), "n": int(len(v))}


# The registered verdict on the primary series (scored clean dates with a
# book of PRIMARY_MIN or more, in date order): CONFIRMED at the first look
# whose first-`look` t is at most THRESHOLD, NOT CONFIRMED after the last
# look, else PENDING.
def verdict(primary: Sequence[float]) -> dict[str, Any]:
    """Return the verdict record of the primary spreads."""
    looks = []
    for look in LOOKS:
        if len(primary) < look:
            break
        stats = _stats(primary[:look])
        looks.append({"look": look, **stats})
        if stats["t"] <= THRESHOLD:
            return {"label": "CONFIRMED", "at": look, "looks": looks}
    if len(primary) >= LOOKS[-1]:
        return {"label": "NOT CONFIRMED", "at": LOOKS[-1], "looks": looks}
    return {"label": "PENDING", "at": None, "looks": looks, "next_look": next(n for n in LOOKS if n > len(primary))}


# The summary of the ledger's scores: the primary statistic and verdict,
# and the secondary readings per book minimum and per model id.
def summarize(scores: Sequence[Mapping[str, Any]], entries: int) -> dict[str, Any]:
    """Return the summary record."""
    ordered = sorted(scores, key=lambda s: s["date"])
    primary = [s["spread"] for s in ordered if s["clean"] and s["n"] >= PRIMARY_MIN]
    out: dict[str, Any] = {
        "plan": PLAN,
        "entries": entries,
        "scored": len(ordered),
        "unclean_scored": sum(not s["clean"] for s in ordered),
        "primary": {"min_names": PRIMARY_MIN, **_stats(primary)},
        "verdict": verdict(primary),
        "secondary": {},
        "by_model": {},
    }
    for minimum in SECONDARY_MINIMUMS:
        chosen = [s for s in ordered if s["clean"] and s["n"] >= minimum]
        out["secondary"][str(minimum)] = {
            "spread": _stats([s["spread"] for s in chosen]),
            "gain": _stats([s["gain"] for s in chosen]),
            "top_spread": _stats([s["top_spread"] for s in chosen]),
            "ic_book": _stats([s["ic_book"] for s in chosen]),
        }
    for model_id in sorted({s["model_id"] for s in ordered}):
        chosen = [s["spread"] for s in ordered if s["model_id"] == model_id and s["clean"] and s["n"] >= PRIMARY_MIN]
        out["by_model"][model_id] = _stats(chosen)
    return out
