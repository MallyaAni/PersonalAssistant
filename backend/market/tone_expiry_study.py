"""Tone expiry (A5): what an arm did, measured on the scorecard run, and the verdict.

`docs/research/tone-expiry-plan-2026-10-01.md` registers everything here;
the rule itself is `backend/market/tone_expiry.py`. The point-in-time
scorecard (`market_pit_scorecard --tone-expiry {hard,decay}`) runs the desk
with the flag on and attaches `record(...)` as the payload's `tone_expiry`
block; the control run (`--sentiment-ic`) attaches the incumbent analyst's
own IC series (`own_ic`) and the desk's fingerprint. `verdict` reads the
control and the two arms' payloads.

**The sentiment analyst's rank IC** is measured as the analysts are:
`harness.evaluate_scores` on `sentiment.opine`'s score, beta-adjusted
residual forward return, 20 names minimum, the benchmark excluded, at 20
and 60 sessions on the desk's panel. The incumbent's rebalance dates are the
grid; the arm is measured on the same dates (`ics_at`, the harness's own
eligibility and correlation, no minimum count), so every period pairs. A
period belongs to the window holding its rebalance date.

* All cells: per period IC(arm) - IC(incumbent), each on its own
  cross-section; the mean and the plain t over the window's periods
  (`paired_t`: the periods do not overlap; every difference exactly zero is
  t = 0, an arm that changed nothing).
* The affected cells (`affected_at`): the incumbent's eligible names the arm
  changed on a rebalance date (A5-hard an expired reading, A5-decay a weight
  below 1). Each has q, the centred percentile of its residual forward
  return in the incumbent's cross-section, and p, the centred percentile of
  each side's score in that side's own cross-section (0, the middle, where
  the arm has no view). Each side's IC on the cells is 12 x mean(p x q); the
  paired difference per date and its plain t over the dates with a changed
  cell. Reported, deciding nothing.

**The book** is read from the payloads: `rule / point-in-time` at 25 bp,
the paired daily difference arm - control at the median offset (the
`curves` block) with its Newey-West t at lag 20, and the median CAGR across
the offsets (the row's `median_cagr`), per window.

**Verdict (`judge`, non-inferiority).** An arm REPLACES if on both
2016-2023 and 2024-2026 (1) the paired IC difference (all cells) has
t >= -1 at 20 and at 60 sessions, (2) the book's paired daily difference has
Newey-West t >= -1, and (3) its median CAGR is no more than 0.5 point below
the control's; RECORD otherwise. A difference that is zero on every session
is read as t = 0 for the book too. If both arms REPLACE, A5-hard is the one
proposed (`verdict`). `verdict` refuses payloads that do not describe the
same desk: a different session or membership file, an incumbent IC series
or a desk fingerprint that differs from the control's, or an arm block
whose rule does not reproduce its own report.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any

import numpy as np

from backend.market import candidate_stats, tone_expiry
from backend.market.baselines import average_rank
from backend.market.harness import evaluate_scores, rank_correlation

PLAN = "docs/research/tone-expiry-plan-2026-10-01.md"
STUDY = "tone_expiry"
# The plan's two trials, by arm name, and the cumulative count.
ARMS: dict[str, str] = {"A5-hard": tone_expiry.HARD, "A5-decay": tone_expiry.DECAY}
TRIALS = {"registered": 2, "cumulative": 482}
HORIZONS: tuple[int, ...] = (20, 60)
DECIDING: tuple[str, ...] = ("2016-2023", "2024-2026")
COST_BPS = 25.0
RULE_LINE = "rule / point-in-time"
HAC_LAG = 20
# The non-inferiority floors.
IC_T_FLOOR = -1.0
BOOK_T_FLOOR = -1.0
CAGR_FLOOR = -0.005
# Reported only: the plan's "better" for scoring its prior.
BETTER_T = 2.0
REPLACES = "REPLACES"
RECORD = "RECORD"
# The names listed from this date on (the plan: the names in 2026).
RECENT = "2026-01-01"
# How close two IC series must be to count as the same desk's.
SAME = 1e-12

assert TRIALS["registered"] == len(ARMS)


# --- the sentiment analyst's IC ---------------------------------------------


# The rows the harness measures `scores` on at `horizon`, and its report:
# the incumbent's grid, which the arm is measured on too.
def grid(scores: np.ndarray, panel, horizon: int):
    """Return (rows, HarnessReport) of evaluate_scores on `scores`."""
    report = evaluate_scores(scores, panel, horizon)
    calendar = np.asarray(panel.dates, dtype="datetime64[D]")
    stamps = np.asarray([p.date for p in report.periods], dtype="datetime64[D]")
    return np.searchsorted(calendar, stamps).astype(int), report


# The names the harness would rank at row t: a finite score and residual,
# never the benchmark.
def _eligible(
    scores_row: np.ndarray, residual_row: np.ndarray, bench: int
) -> np.ndarray:
    """Return the (N,) Boolean eligibility of one row."""
    ok = np.isfinite(scores_row) & np.isfinite(residual_row)
    ok[bench] = False
    return ok


# The rank IC of `scores` on each of `rows`, as the harness measures it
# (its eligibility and its correlation) with no minimum count: NaN where
# fewer than three names qualify.
def ics_at(scores: np.ndarray, panel, horizon: int, rows: Sequence[int]) -> np.ndarray:
    """Return the (len(rows),) rank ICs of `scores` against the residual."""
    residual = panel.forward_residual(horizon)
    bench = panel.index(panel.benchmark)
    out = []
    for t in rows:
        columns = np.flatnonzero(_eligible(scores[t], residual[t], bench))
        out.append(rank_correlation(scores[t, columns], residual[t, columns]))
    return np.asarray(out, dtype=float)


# The mean, plain t and count of a series of paired differences (finite
# entries). Every difference exactly zero is t = 0: an arm that changed
# nothing cannot be inferior. A constant non-zero difference is +-inf.
def paired_t(diff) -> dict[str, float]:
    """Return {"n", "mean", "t"} of `diff`."""
    d = np.asarray(diff, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n == 0:
        return {"n": 0, "mean": math.nan, "t": math.nan}
    mean = float(d.mean())
    if n < 2:
        return {"n": n, "mean": mean, "t": 0.0 if mean == 0 else math.nan}
    sd = float(d.std(ddof=1))
    if sd == 0:
        t = 0.0 if mean == 0 else math.copysign(math.inf, mean)
    else:
        t = mean / (sd / math.sqrt(n))
    return {"n": n, "mean": mean, "t": float(t)}


# The mean IC and its t over a window's defined ICs, as the harness reads them.
def _ic_summary(ics: np.ndarray) -> dict[str, float]:
    """Return {"periods", "mean_ic", "t"} of the finite entries of `ics`."""
    v = np.asarray(ics, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 2 or v.std(ddof=1) == 0:
        t = math.nan
    else:
        t = float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v))))
    return {
        "periods": int(len(v)),
        "mean_ic": float(v.mean()) if len(v) else math.nan,
        "t": t,
    }


# Sessions on or after `start` and before `end` (ISO dates or None).
def _inside(stamps: np.ndarray, start, end) -> np.ndarray:
    """Return the Boolean mask of `stamps` inside [start, end)."""
    days = np.asarray(stamps, dtype="datetime64[D]")
    out = np.ones(len(days), dtype=bool)
    if start is not None:
        out &= days >= np.datetime64(str(start), "D")
    if end is not None:
        out &= days < np.datetime64(str(end), "D")
    return out


# Centred percentile ranks (average rank / (n - 1) - 0.5) of `values` over
# `mask`, 0 elsewhere: the middle of the cross-section for a name not in it.
def _centred(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return (N,) centred percentiles of `values` within `mask`."""
    out = np.zeros(len(values))
    columns = np.flatnonzero(mask)
    if len(columns) >= 2:
        out[columns] = average_rank(values[columns]) / (len(columns) - 1) - 0.5
    return out


# On each of `rows`, the cells the arm changed among the incumbent's
# eligible names, each with p (the centred percentile of each side's score
# in that side's cross-section; 0 where the arm has no view) and q (that of
# the residual forward return in the incumbent's cross-section), and per
# date each side's IC on those cells, 12 x mean(p x q).
def affected_at(
    plain: np.ndarray,
    arm: np.ndarray,
    changed: np.ndarray,
    panel,
    horizon: int,
    rows: Sequence[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (per-date rows, per-cell rows) of the affected-cell IC."""
    residual = panel.forward_residual(horizon)
    bench = panel.index(panel.benchmark)
    calendar = np.asarray(panel.dates, dtype="datetime64[D]")
    dates: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for t in rows:
        before = _eligible(plain[t], residual[t], bench)
        hit = changed[t] & before
        if not hit.any():
            continue
        after = _eligible(arm[t], residual[t], bench)
        q = _centred(residual[t], before)
        p0 = _centred(plain[t], before)
        p1 = _centred(arm[t], after)
        columns = np.flatnonzero(hit)
        s0 = float(12.0 * np.mean(p0[columns] * q[columns]))
        s1 = float(12.0 * np.mean(p1[columns] * q[columns]))
        day = str(calendar[t])
        dates.append(
            {
                "date": day,
                "cells": int(len(columns)),
                "incumbent": s0,
                "arm": s1,
                "difference": s1 - s0,
            }
        )
        for j in columns:
            cells.append(
                {
                    "date": day,
                    "ticker": str(panel.tickers[j]),
                    "p_incumbent": float(p0[j]),
                    "p_arm": float(p1[j]),
                    "q": float(q[j]),
                }
            )
    return dates, cells


# The incumbent and the arm's sentiment IC at 20 and 60 sessions on the
# incumbent's grid, paired per window on all cells and on the affected
# cells, with every period's and every affected cell's numbers so the
# check can recompute them.
def sentiment_ic(
    plain: np.ndarray,
    arm: np.ndarray,
    changed: np.ndarray,
    panel,
    windows: Mapping[str, tuple[Any, Any]],
) -> dict[str, Any]:
    """Return the block's "sentiment_ic" entry."""
    out: dict[str, Any] = {}
    calendar = np.asarray(panel.dates, dtype="datetime64[D]")
    for horizon in HORIZONS:
        rows, report = grid(plain, panel, horizon)
        incumbent = np.asarray([p.rank_ic for p in report.periods], dtype=float)
        theirs = ics_at(arm, panel, horizon, rows)
        stamps = calendar[rows]
        by_date, by_cell = affected_at(plain, arm, changed, panel, horizon, rows)
        affected_days = np.asarray([d["date"] for d in by_date], dtype="datetime64[D]")
        per_window: dict[str, Any] = {}
        for name, (start, end) in windows.items():
            keep = _inside(stamps, start, end)
            hit = _inside(affected_days, start, end)
            chosen = [d for d, k in zip(by_date, hit, strict=True) if k]
            per_window[name] = {
                "incumbent": _ic_summary(incumbent[keep]),
                "arm": _ic_summary(theirs[keep]),
                "paired": paired_t(theirs[keep] - incumbent[keep]),
                "affected": {
                    "dates": len(chosen),
                    "cells": int(sum(d["cells"] for d in chosen)),
                    "incumbent_mean": _mean([d["incumbent"] for d in chosen]),
                    "arm_mean": _mean([d["arm"] for d in chosen]),
                    "paired": paired_t([d["difference"] for d in chosen]),
                },
            }
        out[f"h{horizon}"] = {
            "horizon": horizon,
            "periods": {
                "dates": [str(d) for d in stamps],
                "incumbent": incumbent.tolist(),
                "arm": theirs.tolist(),
            },
            "windows": per_window,
            "affected_dates": by_date,
            "affected_cells": by_cell,
        }
    return out


# The mean of a list, NaN when it is empty.
def _mean(values: Sequence[float]) -> float:
    """Return the mean of `values`, NaN for none."""
    return float(np.mean(values)) if len(values) else math.nan


# A run's own sentiment IC at 20 and 60 sessions (the control's, for the
# verdict to compare with the arm's incumbent series): every period's date
# and IC, and the summary per window.
def own_ic(
    scores: np.ndarray, panel, windows: Mapping[str, tuple[Any, Any]]
) -> dict[str, Any]:
    """Return the payload's "sentiment_ic" block for one desk."""
    out: dict[str, Any] = {}
    calendar = np.asarray(panel.dates, dtype="datetime64[D]")
    for horizon in HORIZONS:
        rows, report = grid(scores, panel, horizon)
        ics = np.asarray([p.rank_ic for p in report.periods], dtype=float)
        stamps = calendar[rows]
        out[f"h{horizon}"] = {
            "horizon": horizon,
            "mean_ic": float(report.mean_ic),
            "ic_t": float(report.ic_tstat),
            "net_sharpe": float(report.net_sharpe),
            "periods": {"dates": [str(d) for d in stamps], "ic": ics.tolist()},
            "windows": {
                name: _ic_summary(ics[_inside(stamps, start, end)])
                for name, (start, end) in windows.items()
            },
        }
    return out


# --- what the arm changed ------------------------------------------------------


# The cells the arm changes: a reading in use whose weight is below 1
# (A5-hard: an expired reading; A5-decay: one weighted down or expired).
def changed_cells(plain_tone: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """Return the (T, N) Boolean mask of changed readings."""
    reading = np.asarray(plain_tone)[:, :, tone_expiry.HAS_TONE] > 0
    return reading & (np.asarray(weight, dtype=float) < 1.0)


# Cells, names and the share of reading cells in one block of rows.
def _count(changed: np.ndarray, reading: np.ndarray) -> dict[str, Any]:
    """Return {"cells", "names", "reading_cells", "share"} of a block."""
    cells = int(changed.sum())
    total = int(reading.sum())
    return {
        "cells": cells,
        "names": int(changed.any(axis=0).sum()) if changed.size else 0,
        "reading_cells": total,
        "share": float(cells / total) if total else math.nan,
    }


# How many cells (name-sessions) and names the arm changes, per calendar
# year and per window, on the whole panel and within the point-in-time
# book (`mask`), with the cells that carry a reading as the base.
def affected_counts(
    changed: np.ndarray,
    reading: np.ndarray,
    mask: np.ndarray,
    panel,
    windows: Mapping[str, tuple[Any, Any]],
) -> dict[str, Any]:
    """Return the block's "affected" entry."""
    calendar = np.asarray(panel.dates, dtype="datetime64[D]")
    years = calendar.astype("datetime64[Y]").astype(int) + 1970
    out: dict[str, Any] = {"years": {}, "windows": {}}
    for year in np.unique(years):
        rows = years == year
        out["years"][str(int(year))] = {
            "panel": _count(changed[rows], reading[rows]),
            "book": _count((changed & mask)[rows], (reading & mask)[rows]),
        }
    for name, (start, end) in windows.items():
        rows = _inside(calendar, start, end)
        out["windows"][name] = {
            "panel": _count(changed[rows], reading[rows]),
            "book": _count((changed & mask)[rows], (reading & mask)[rows]),
        }
    return out


# Every (name, reading) the arm changed from `since` on: the reading's
# date, its first and last changed session, the sessions changed, the usual
# gap on the last of them and whether it is the name's own, the largest age
# and age / gap, and the smallest weight.
def affected_names(
    changed: np.ndarray,
    found: tone_expiry.Ages,
    weight: np.ndarray,
    panel,
    since: str = RECENT,
) -> list[dict[str, Any]]:
    """Return one entry per (name, reading) changed on or after `since`."""
    calendar = np.asarray(panel.dates, dtype="datetime64[D]")
    recent = calendar >= np.datetime64(since, "D")
    out: list[dict[str, Any]] = []
    for j, ticker in enumerate(panel.tickers):
        hit = changed[:, j] & recent
        if not hit.any():
            continue
        for read in np.unique(found.last_read[hit, j]):
            rows = np.flatnonzero(hit & (found.last_read[:, j] == read))
            ratio = found.age[rows, j] / found.cadence[rows, j]
            out.append(
                {
                    "ticker": str(ticker),
                    "last_read": str(read),
                    "first": str(calendar[rows[0]]),
                    "last": str(calendar[rows[-1]]),
                    "sessions": int(len(rows)),
                    "cadence_days": float(found.cadence[rows[-1], j]),
                    "cadence_from": "own" if found.own[rows[-1], j] else "book",
                    "max_age_days": int(np.nanmax(found.age[rows, j])),
                    "max_ratio": float(np.nanmax(ratio)),
                    "min_weight": float(np.min(weight[rows, j])),
                }
            )
    return out


# What the arm did to the grades, per window, among the point-in-time
# book's name-sessions: how many letters moved, up and down, the A+ counts
# before and after, and how many of the changed cells moved.
def grade_moves(
    plain: np.ndarray,
    arm: np.ndarray,
    changed: np.ndarray,
    mask: np.ndarray,
    panel,
    windows: Mapping[str, tuple[Any, Any]],
    a_plus: int = 3,
) -> dict[str, Any]:
    """Return the block's "grades" entry."""
    calendar = np.asarray(panel.dates, dtype="datetime64[D]")
    out: dict[str, Any] = {}
    for name, (start, end) in windows.items():
        rows = _inside(calendar, start, end)[:, None] & mask
        moved = rows & (plain != arm)
        out[name] = {
            "eligible_name_sessions": int(rows.sum()),
            "moved": int(moved.sum()),
            "moved_up": int((moved & (arm > plain)).sum()),
            "moved_down": int((moved & (arm < plain)).sum()),
            "a_plus_before": int((rows & (plain == a_plus)).sum()),
            "a_plus_after": int((rows & (arm == a_plus)).sum()),
            "changed_cells": int((rows & changed).sum()),
            "changed_cells_moved": int((moved & changed).sum()),
        }
    return out


# The plan's grade-detail words for every name the arm changes on the
# panel's last session: the expired line, or the release's own words (from
# the incumbent's evidence and the board's own phrasing) with its age and
# weight. The mark is the arm's recorded sentiment stance.
def board_lines(
    changed: np.ndarray,
    found: tone_expiry.Ages,
    weight: np.ndarray,
    stances: np.ndarray,
    plain_opinion,
    panel,
    sides: Mapping[str, str],
) -> list[dict[str, str]]:
    """Return [{"ticker", "words"}] for the last session's changed names."""
    from backend.agents.trading.desk import plainly

    t = len(panel.dates) - 1
    columns = np.flatnonzero(changed[t])
    if not len(columns):
        return []
    scale = plainly.spreads(
        SimpleNamespace(panel=panel, sides=sides, opinions={"sentiment": plain_opinion})
    )
    out = []
    for j in columns:
        stance = int(stances[t, j])
        read = _as_date(found.last_read[t, j])
        age = int(found.age[t, j])
        own = bool(found.own[t, j])
        gap = float(found.cadence[t, j])
        if weight[t, j] == 0:
            words = tone_expiry.expired_words(plainly.MARK[stance], read, age, gap, own)
        else:
            clause = plainly.reason(
                {
                    "stances": {"sentiment": stance},
                    "evidence": {"sentiment": plain_opinion.cite(t, int(j))},
                },
                scale,
            )
            words = tone_expiry.weighted_words(
                clause, read, age, gap, own, float(weight[t, j])
            )
        out.append({"ticker": str(panel.tickers[j]), "words": words})
    return out


# A datetime64 day as a date.
def _as_date(value) -> date:
    """Return `value` (datetime64[D]) as a datetime.date."""
    return np.datetime64(value, "D").astype(object)


# A short fingerprint of a desk: the sha256 of its grades and of its scores,
# so two runs can be shown to be the same desk without storing either.
def fingerprint(grades: np.ndarray, scores: np.ndarray) -> dict[str, str]:
    """Return {"grades_sha256", "scores_sha256"}."""
    return {
        "grades_sha256": hashlib.sha256(
            np.ascontiguousarray(grades, dtype=np.int64).tobytes()
        ).hexdigest(),
        "scores_sha256": hashlib.sha256(
            np.ascontiguousarray(scores, dtype=np.float64).tobytes()
        ).hexdigest(),
    }


# The arm run's payload block: the rule and its constants, whether the
# report was built by it, what it changed (cells and names per year and
# window, the 2026 names, the grades), the paired sentiment IC, the
# incumbent desk's fingerprint and the last session's board words.
def record(
    mode: str,
    report,
    plain_report,
    plain_tone: np.ndarray,
    found: tone_expiry.Ages,
    weight: np.ndarray,
    rebuilt_scores: np.ndarray,
    mask: np.ndarray,
    windows: Mapping[str, tuple[Any, Any]],
) -> dict[str, Any]:
    """Return the payload's "tone_expiry" block for an arm run."""
    panel = report.panel
    plain_opinion = plain_report.opinions["sentiment"]
    arm_opinion = report.opinions["sentiment"]
    changed = changed_cells(plain_tone, weight)
    reading = np.asarray(plain_tone)[:, :, tone_expiry.HAS_TONE] > 0
    matches = bool(np.array_equal(rebuilt_scores, arm_opinion.scores, equal_nan=True))
    return {
        "plan": PLAN,
        "mode": mode,
        "arm": next(name for name, m in ARMS.items() if m == mode),
        "flag": mode,
        "rule": {
            "horizon": tone_expiry.HORIZON,
            "decay_start": tone_expiry.DECAY_START,
            "decay_end": tone_expiry.DECAY_END,
            "tolerance_source": "release_coverage.TOLERANCE",
            "cadence_source": "release_coverage.own_cadence / book_cadence",
        },
        "report_matches_rule": matches,
        "affected": affected_counts(changed, reading, mask, panel, windows),
        "affected_2026": affected_names(changed, found, weight, panel),
        "grades": grade_moves(
            plain_report.graded.grades,
            report.graded.grades,
            changed,
            mask,
            panel,
            windows,
        ),
        "sentiment_ic": sentiment_ic(
            plain_opinion.scores, arm_opinion.scores, changed, panel, windows
        ),
        "incumbent_fingerprint": fingerprint(
            plain_report.graded.grades, plain_report.scores
        ),
        "board_words": board_lines(
            changed,
            found,
            weight,
            report.graded.stances["sentiment"],
            plain_opinion,
            panel,
            report.sides,
        ),
    }


# --- the verdict ------------------------------------------------------------------


# A payload number (None or NaN) as a float.
def _f(value) -> float:
    """Return `value` as a float, NaN for None."""
    return math.nan if value is None else float(value)


# The rule / point-in-time row of a payload on a window at the plan's cost.
def _row(payload: Mapping[str, Any], window: str, cost: float = COST_BPS) -> dict:
    """Return the row, or raise when the payload lacks it."""
    for row in payload["rows"]:
        if (
            row["line"] == RULE_LINE
            and row["window"] == window
            and float(row["cost_bps"]) == cost
        ):
            return row
    raise KeyError(f"no {RULE_LINE!r} row for {window!r} at {cost:g} bp")


# The rule line's median-offset daily returns on a window, paired session
# by session between two payloads (dates matched, both finite).
def _paired_daily(
    arm: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> tuple[np.ndarray, np.ndarray]:
    """Return (arm daily, control daily) on the sessions both price."""
    start, end = control["windows"][window]
    key = f"{COST_BPS:g}"
    a, b = arm["curves"][key], control["curves"][key]
    theirs = dict(zip(b["dates"], b["lines"][RULE_LINE], strict=True))
    xs, ys = [], []
    for day, value in zip(a["dates"], a["lines"][RULE_LINE], strict=True):
        if (start is not None and day < start) or (end is not None and day >= end):
            continue
        other = theirs.get(day)
        if value is None or other is None:
            continue
        if not (math.isfinite(value) and math.isfinite(other)):
            continue
        xs.append(value)
        ys.append(other)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


# The book's paired daily difference (arm minus control) on a window: its
# length, mean in bp a session and Newey-West t at lag 20; zero on every
# session is t = 0.
def book_paired(
    arm: Mapping[str, Any], control: Mapping[str, Any], window: str
) -> dict[str, Any]:
    """Return {"sessions", "mean_daily_bp", "hac_t"} of the paired difference."""
    a, b = _paired_daily(arm, control, window)
    diff = a - b
    if len(diff) and not np.any(diff):
        t = 0.0
    else:
        t = candidate_stats.hac_t(diff, HAC_LAG) if len(diff) > 2 else math.nan
    return {
        "sessions": int(len(diff)),
        "mean_daily_bp": float(diff.mean() * 1e4) if len(diff) else math.nan,
        "hac_t": float(t),
    }


# Why two payloads cannot be judged together, or an empty list: a different
# session, membership file, cost or offset count; a control without its own
# IC series or fingerprint; an arm block that does not reproduce its report,
# names another rule, or whose incumbent IC series or desk differ from the
# control's.
def problems(
    control: Mapping[str, Any], arm: Mapping[str, Any], mode: str
) -> list[str]:
    """Return the reasons the pair is refused (empty: judge it)."""
    out: list[str] = []
    for key in ("asof", "membership", "offsets"):
        if control.get(key) != arm.get(key):
            out.append(f"{key} differs: {control.get(key)!r} vs {arm.get(key)!r}")
    if COST_BPS not in [float(c) for c in arm.get("costs_bps", [])]:
        out.append(f"the arm has no {COST_BPS:g} bp lines")
    block = arm.get("tone_expiry")
    if not block:
        return [*out, "the arm payload has no tone_expiry block"]
    if block.get("mode") != mode:
        out.append(f"the arm block's mode is {block.get('mode')!r}, not {mode!r}")
    if not block.get("report_matches_rule"):
        out.append("the arm's report was not built by its rule")
    own = control.get("sentiment_ic")
    if not own:
        return [*out, "the control payload has no sentiment_ic block (--sentiment-ic)"]
    if block.get("incumbent_fingerprint") != control.get("desk_fingerprint"):
        out.append("the arm's incumbent desk differs from the control's")
    return out + _series_problems(block["sentiment_ic"], own)


# Where an arm's incumbent IC series is not the control's own: other
# rebalance dates, or an IC that differs by more than SAME on any of them.
def _series_problems(mine: Mapping[str, Any], own: Mapping[str, Any]) -> list[str]:
    """Return the per-horizon reasons the two series differ (empty: same)."""
    out: list[str] = []
    for horizon in HORIZONS:
        key = f"h{horizon}"
        arm_side, control_side = mine[key]["periods"], own[key]["periods"]
        if arm_side["dates"] != control_side["dates"]:
            out.append(f"{key}: the rebalance dates differ from the control's")
            continue
        a = np.asarray([_f(x) for x in arm_side["incumbent"]])
        b = np.asarray([_f(x) for x in control_side["ic"]])
        if not bool(np.all(np.isclose(a, b, rtol=0.0, atol=SAME, equal_nan=True))):
            out.append(f"{key}: the incumbent IC series differs from the control's")
    return out


# One arm judged against the control on the plan's non-inferiority
# criteria, with every number the criteria read and the reported ones.
def judge(control: Mapping[str, Any], arm: Mapping[str, Any], name: str) -> dict:
    """Return one arm's verdict record."""
    block = arm["tone_expiry"]
    windows: dict[str, Any] = {}
    passed = True
    for window in DECIDING:
        ic = {
            f"h{h}": block["sentiment_ic"][f"h{h}"]["windows"][window]["paired"]
            for h in HORIZONS
        }
        book = book_paired(arm, control, window)
        own, theirs = _row(arm, window), _row(control, window)
        cagr = _f(own["median_cagr"]) - _f(theirs["median_cagr"])
        checks = {
            f"ic_h{h}": bool(_f(ic[f"h{h}"]["t"]) >= IC_T_FLOOR) for h in HORIZONS
        }
        checks["book_t"] = bool(_f(book["hac_t"]) >= BOOK_T_FLOOR)
        checks["cagr"] = bool(cagr >= CAGR_FLOOR)
        passed = passed and all(checks.values())
        cagrs_arm = np.asarray([_f(c) for c in own.get("cagrs", [])])
        cagrs_control = np.asarray([_f(c) for c in theirs.get("cagrs", [])])
        above = (
            int(np.nansum(cagrs_arm > cagrs_control))
            if len(cagrs_arm) == len(cagrs_control)
            else None
        )
        windows[window] = {
            "ic": ic,
            "book": book,
            "cagr_arm": _f(own["median_cagr"]),
            "cagr_control": _f(theirs["median_cagr"]),
            "cagr_difference": cagr,
            "drawdown_arm": _f(own["median_drawdown"]),
            "drawdown_control": _f(theirs["median_drawdown"]),
            "worst_drawdown_arm": _f(own.get("worst_drawdown")),
            "worst_drawdown_control": _f(theirs.get("worst_drawdown")),
            "offsets_above_control": above,
            "affected": {
                f"h{h}": block["sentiment_ic"][f"h{h}"]["windows"][window]["affected"]
                for h in HORIZONS
            },
            "checks": checks,
        }
    deciding, recent = windows[DECIDING[0]]["book"], windows[DECIDING[1]]["book"]
    better = bool(
        _f(deciding["hac_t"]) >= BETTER_T and _f(recent["mean_daily_bp"]) >= 0.0
    )
    return {
        "arm": name,
        "mode": ARMS[name],
        "label": REPLACES if passed else RECORD,
        "windows": windows,
        "better": better,
    }


# Both arms against the control: each judged on the plan's criteria, the
# one proposed (A5-hard when both REPLACE), and the lines. Raises when a
# pair does not describe the same desk.
def verdict(control: Mapping[str, Any], arms: Mapping[str, Mapping[str, Any]]) -> dict:
    """Return the study's verdict record."""
    refused = {
        name: problems(control, arms[name], ARMS[name]) for name in ARMS if name in arms
    }
    missing = [name for name in ARMS if name not in arms]
    bad = {k: v for k, v in refused.items() if v}
    if missing or bad:
        raise ValueError(f"refused: missing arms {missing}; problems {bad}")
    judged = {name: judge(control, arms[name], name) for name in ARMS}
    passing = [name for name in ARMS if judged[name]["label"] == REPLACES]
    proposed = passing[0] if passing else None
    reading = {
        "plan": PLAN,
        "trials": TRIALS,
        "cost_bps": COST_BPS,
        "floors": {
            "ic_t": IC_T_FLOOR,
            "book_t": BOOK_T_FLOOR,
            "cagr": CAGR_FLOOR,
        },
        "asof": control.get("asof"),
        "arms": judged,
        "proposed": proposed,
    }
    reading["lines"] = lines(reading)
    return reading


# A signed number for the lines, "n/a" for NaN.
def _s(value: float, places: int = 2) -> str:
    """Return `value` with its sign, or n/a."""
    v = _f(value)
    return "n/a" if not math.isfinite(v) else f"{v:+.{places}f}"


# The verdict as lines: per arm and window the IC pairs, the book pair, the
# CAGRs and the affected cells' reading, then the label and the proposal.
def lines(reading: Mapping[str, Any]) -> list[str]:
    """Return the verdict as text lines."""
    out = []
    for name, judged in reading["arms"].items():
        out.append(f"{name} ({judged['mode']}): {judged['label']}")
        for window, w in judged["windows"].items():
            ic = "; ".join(
                f"IC {k} {_s(w['ic'][k]['mean'], 4)} (t {_s(w['ic'][k]['t'])}, "
                f"{w['ic'][k]['n']} periods)"
                for k in w["ic"]
            )
            book = w["book"]
            failed = [k for k, ok in w["checks"].items() if not ok]
            out.append(
                f"  {window}: {ic}; book {_s(book['mean_daily_bp'])} bp/session "
                f"(NW t {_s(book['hac_t'])}, {book['sessions']} sessions); median "
                f"CAGR {w['cagr_arm'] * 100:+.1f}% against "
                f"{w['cagr_control'] * 100:+.1f}% ({_s(w['cagr_difference'] * 100, 1)} "
                f"points); {'fails ' + ', '.join(failed) if failed else 'all pass'}"
            )
            hit = w["affected"]["h20"]
            out.append(
                f"    affected cells h20: {hit['cells']} on {hit['dates']} dates, IC "
                f"{_s(hit['incumbent_mean'], 3)} incumbent vs {_s(hit['arm_mean'], 3)} "
                f"arm (paired t {_s(hit['paired']['t'])})"
            )
    proposed = reading.get("proposed")
    out.append(
        f"proposed: {proposed}" if proposed else "proposed: none (RECORD on both arms)"
    )
    return out
