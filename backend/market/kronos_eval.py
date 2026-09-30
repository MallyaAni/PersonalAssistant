"""Kronos K1 (a daily forecast as a stance) and K3 (its marginal IC): the numbers.

`docs/research/kronos-plan-2026-09-30.md` registers the study; Addendum 1
fixes the cutoff (pre-training data through June 2024) and Addendum 2 the
build choices here. Nothing in this module computes a number the plan did
not ask for.

**K1.** The RTX writes, per graded cell (session t, name), the predicted
20-session log return (`k1_logret_20`) and the predicted path's maximum
drawdown (`k1_mdd`, <= 0). Each is placed on the panel's (T, N) grid
(`score_grid`) and measured exactly as the analysts are measured
(`harness.evaluate_scores`: rank IC against the 20-session beta-adjusted
residual on non-overlapping periods, 10 bp, at least 15 names), on one
shared set of cells per window so coverage cannot flatter an arm, in the
in-window period 2018-01-02..2024-06-30 (contaminated: the model may have
seen these bars) and the post-cutoff period from 2024-07-01, which
decides. The desk's own graded score is measured on the same cells as the
reference, and every arm's per-period ICs are paired against it.

**The IC criterion** (the plan): post-cutoff rank IC >= 0.02 with t >= 2
on at least 60 post-cutoff periods; with fewer periods the study is RECORD
by construction and says so. The book gate (a sixth analyst on the T-S1
scorecard) is a separate run; its status is carried in the payload.

**K3.** K1's two features appended to the stage-1 dataset's scalars
(`deep_intraday.Dataset.x_scalar`, matched on (session, name)); the
stage-1 ridge walked forward on the same folds with and without them; the
daily IC series of both, per window, and the paired difference. Reported,
never a trial.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from backend.market import candidate_stats
from backend.market.harness import evaluate_scores

PLAN = "docs/research/kronos-plan-2026-09-30.md"
STUDY = "kronos"
# Addendum 1: the pre-training data extends up to June 2024.
CUTOFF = date(2024, 6, 30)
POST_START = date(2024, 7, 1)
IN_WINDOW: tuple[date, date | None] = (date(2018, 1, 2), CUTOFF)
POST_WINDOW: tuple[date, date | None] = (POST_START, None)
WINDOWS: dict[str, tuple[date, date | None]] = {
    "in_window": IN_WINDOW,
    "post_window": POST_WINDOW,
}
HORIZON = 20
# The analysts' measurement (market_release_eval, tone validity).
COST_BPS = 10.0
MIN_NAMES = 15
# The plan's K1 IC criterion.
IC_FLOOR = 0.02
IC_T = 2.0
MIN_POST_PERIODS = 60
# The plan's trial counts: two trials (K1, K2), cumulative 464 -> 466.
TRIALS = {"registered": 2, "cumulative": 466}
HAC_LAG = 20
# The K1 arms of one forecast set: the forecast column each reads. A
# second set (Addendum 2's paper-context arm) is labelled by its own prefix.
DESK = "desk score"
FEATURES = {"return": "k1_logret_20", "drawdown": "k1_mdd"}


# The (T, N) grids of one forecast set's arms, labelled "<label> return"
# and "<label> drawdown".
def k1_grids(
    panel: Any, frame: pd.DataFrame, label: str = "K1"
) -> dict[str, np.ndarray]:
    """Return {arm: grid} for the forecast frame."""
    return {
        f"{label} {arm}": score_grid(panel, frame, column)
        for arm, column in FEATURES.items()
    }


RECORD = "RECORD"
PROPOSED = "PROPOSED as a sixth analyst"


# --- placing forecasts on the grid ---------------------------------------------


# A forecast column on the panel's (T, N) grid: the value at (date,
# ticker) where the frame has one, NaN elsewhere. Duplicate (date, ticker)
# rows are refused.
def score_grid(panel: Any, frame: pd.DataFrame, column: str) -> np.ndarray:
    """Return the (T, N) grid of `column`."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    tickers = {str(t): j for j, t in enumerate(panel.tickers)}
    out = np.full((len(dates), len(panel.tickers)), np.nan)
    if not len(frame):
        return out
    when = pd.to_datetime(frame["date"]).to_numpy().astype("datetime64[D]")
    pos = np.searchsorted(dates, when)
    on_panel = (pos < len(dates)) & (dates[np.minimum(pos, len(dates) - 1)] == when)
    cols = np.array([tickers.get(str(t), -1) for t in frame["ticker"]])
    keep = on_panel & (cols >= 0)
    t, j = pos[keep], cols[keep]
    if len(np.unique(t * len(panel.tickers) + j)) != len(t):
        raise ValueError("the forecast frame has duplicate (date, ticker) rows")
    out[t, j] = np.asarray(frame[column], dtype=float)[keep]
    return out


# A (T,) mask of the sessions inside a window, end inclusive.
def window_mask(dates: np.ndarray, start: date | None, end: date | None) -> np.ndarray:
    """Return True for sessions in [start, end]."""
    stamps = np.asarray(dates).astype("datetime64[D]")
    mask = np.ones(len(stamps), dtype=bool)
    if start is not None:
        mask &= stamps >= np.datetime64(start)
    if end is not None:
        mask &= stamps <= np.datetime64(end)
    return mask


# --- the harness --------------------------------------------------------------


# One arm's harness numbers on the cells, plus its per-period ICs by date.
def arm_result(
    scores: np.ndarray, cells: np.ndarray, panel: Any, horizon: int = HORIZON
) -> dict[str, Any]:
    """Return {ic, t, net_sharpe, periods, hit_rate, period_ics}."""
    masked = np.where(cells, scores, np.nan)
    report = evaluate_scores(
        masked, panel, horizon, cost_bps=COST_BPS, min_names=MIN_NAMES
    )
    return {
        "ic": report.mean_ic,
        "t": report.ic_tstat,
        "net_sharpe": report.net_sharpe,
        "periods": report.count,
        "hit_rate": report.ic_hit_rate,
        "period_ics": {str(p.date): p.rank_ic for p in report.periods},
    }


# The paired difference of two arms' per-period ICs on their common periods.
def paired(a: Mapping[str, float], b: Mapping[str, float]) -> dict[str, Any]:
    """Return mean and t of IC(b) - IC(a) over the periods both define."""
    keys = [k for k in a if k in b and np.isfinite(a[k]) and np.isfinite(b[k])]
    diffs = np.array([b[k] - a[k] for k in keys], dtype=float)
    if len(diffs) < 2 or diffs.std(ddof=1) == 0:
        return {
            "delta": float(diffs.mean()) if len(diffs) else math.nan,
            "t": math.nan,
            "periods": int(len(diffs)),
        }
    t = float(diffs.mean() / (diffs.std(ddof=1) / np.sqrt(len(diffs))))
    return {"delta": float(diffs.mean()), "t": t, "periods": int(len(diffs))}


# Every arm on the cells all of them score inside one window, paired
# against the desk's score.
def measure_window(
    scored: Mapping[str, np.ndarray],
    inside: np.ndarray,
    panel: Any,
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """Return {"cells", "arms", "paired_vs_desk"}."""
    cells = inside.copy()
    for scores in scored.values():
        cells &= np.isfinite(scores)
    results = {
        arm: arm_result(scores, cells, panel, horizon) for arm, scores in scored.items()
    }
    pairs = {
        arm: paired(results[DESK]["period_ics"], results[arm]["period_ics"])
        for arm in results
        if arm != DESK and DESK in results
    }
    return {"cells": int(cells.sum()), "arms": results, "paired_vs_desk": pairs}


# The K1 payload: each arm and the desk's score on the shared cells per
# window, the IC criterion on the post-cutoff window, the verdict.
# `cells` is the (T, N) mask of the book's graded, member cells; `grids`
# maps each K1 arm to its (T, N) forecast grid; `desk_scores` the desk's
# (T, N) graded score.
def evaluate_k1(
    panel: Any,
    cells: np.ndarray,
    grids: Mapping[str, np.ndarray],
    desk_scores: np.ndarray | None,
    windows: Mapping[str, tuple[date | None, date | None]] | None = None,
    horizon: int = HORIZON,
) -> dict[str, Any]:
    """Return the K1 payload."""
    windows = windows or WINDOWS
    scored: dict[str, np.ndarray] = dict(grids)
    if desk_scores is not None:
        scored[DESK] = np.asarray(desk_scores, dtype=float)
    per_window: dict[str, Any] = {}
    for name, (start, end) in windows.items():
        inside = window_mask(panel.dates, start, end)[:, None] & np.asarray(
            cells, dtype=bool
        )
        per_window[name] = measure_window(scored, inside, panel, horizon)
    criteria = k1_criteria(per_window)
    return {
        "study": STUDY,
        "plan": PLAN,
        "arm": "K1",
        "horizon": horizon,
        "cutoff": str(CUTOFF),
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in windows.items()
        },
        "cost_bps": COST_BPS,
        "min_names": MIN_NAMES,
        "trials": TRIALS,
        "results": per_window,
        "criteria": criteria,
        "verdict": k1_verdict(criteria),
        "lines": k1_lines(per_window, criteria),
    }


# The plan's K1 IC criterion on the post-cutoff window, per K1 arm: IC >=
# 0.02, t >= 2, at least 60 periods; and whether the period count alone
# makes the study RECORD by construction. The book gate is a separate
# run, recorded as not run here.
def k1_criteria(per_window: Mapping[str, Any]) -> dict[str, Any]:
    """Return the evaluated criteria."""
    post = per_window.get("post_window", {"arms": {}})
    out: dict[str, Any] = {
        "ic_floor": IC_FLOOR,
        "ic_t": IC_T,
        "min_post_periods": MIN_POST_PERIODS,
        "arms": {},
        "book_gate": "not run: the sixth-analyst scorecard is a separate run (registered as follow-up)",
    }
    for arm, r in post["arms"].items():
        if arm == DESK:
            continue
        enough = int(r["periods"]) >= MIN_POST_PERIODS
        clears = bool(
            np.isfinite(r["ic"])
            and np.isfinite(r["t"])
            and r["ic"] >= IC_FLOOR
            and r["t"] >= IC_T
        )
        out["arms"][arm] = {
            "post_ic": r["ic"],
            "post_t": r["t"],
            "post_periods": int(r["periods"]),
            "enough_periods": enough,
            "ic_clears": clears,
            "passes": bool(enough and clears),
        }
    out["record_by_construction"] = not any(
        a["enough_periods"] for a in out["arms"].values()
    )
    return out


# The verdict: PROPOSED only when an arm passes the IC criterion and the
# book gate holds; the book gate is not run here, so RECORD, with the
# reason.
def k1_verdict(criteria: Mapping[str, Any]) -> dict[str, Any]:
    """Return {"label", "reason"}."""
    passing = [a for a, c in criteria["arms"].items() if c["passes"]]
    if criteria["record_by_construction"]:
        return {
            "label": RECORD,
            "reason": f"RECORD by construction: fewer than {MIN_POST_PERIODS} post-cutoff periods",
        }
    if not passing:
        return {"label": RECORD, "reason": "no K1 arm clears the post-cutoff IC floor"}
    return {
        "label": RECORD,
        "reason": f"{', '.join(passing)} clear the IC floor; the book gate is not run here, so not proposed",
    }


# The verdict lines, one per arm and window, then the criterion.
def k1_lines(per_window: Mapping[str, Any], criteria: Mapping[str, Any]) -> list[str]:
    """Return the lines people read."""
    lines = []
    for window, w in per_window.items():
        for arm, r in w["arms"].items():
            pair = w["paired_vs_desk"].get(arm)
            paired_text = (
                f"; vs desk {pair['delta']:+.4f} (paired t {pair['t']:+.2f})"
                if pair
                else ""
            )
            lines.append(
                f"K1 {window} {arm}: rank IC {r['ic']:+.4f} (t {r['t']:+.2f}) over {r['periods']} periods on {w['cells']:,} cells, net Sharpe {r['net_sharpe']:+.2f}{paired_text}"
            )
    for arm, c in criteria["arms"].items():
        lines.append(
            f"K1 criterion {arm}: post-cutoff IC {c['post_ic']:+.4f} (t {c['post_t']:+.2f}) on {c['post_periods']} periods (needs >= {MIN_POST_PERIODS}, IC >= {IC_FLOOR}, t >= {IC_T}) - {'passes' if c['passes'] else 'fails'}"
        )
    return lines


# --- K3: the marginal IC over the stage-1 ridge ---------------------------------


# K1's features on the stage-1 dataset's rows, matched on (session, name):
# (M, 2) of [k1_logret_20, k1_mdd], NaN where the cell has no forecast.
def stage1_features(ds: Any, frame: pd.DataFrame) -> np.ndarray:
    """Return the (M, 2) K1 columns aligned to the dataset's rows."""
    key = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime(frame["date"]).to_numpy().astype("datetime64[D]"),
            frame["ticker"].astype(str),
        ]
    )
    lookup = pd.DataFrame(
        {c: np.asarray(frame[c], dtype=float) for c in ("k1_logret_20", "k1_mdd")},
        index=key,
    )
    if lookup.index.has_duplicates:
        raise ValueError("the forecast frame has duplicate (date, ticker) rows")
    rows = pd.MultiIndex.from_arrays(
        [
            np.asarray(ds.dates, dtype="datetime64[D]"),
            np.asarray(ds.tickers).astype(str),
        ]
    )
    return lookup.reindex(rows).to_numpy(dtype=float)


# The stage-1 ridge with and without K1's features, walked forward on the
# dataset's folds; the daily IC of each per window and the paired
# difference. Rows without a K1 forecast are dropped from both so the
# comparison is on the same rows. `walk` replaces `deep_intraday.
# walk_forward` in tests.
def evaluate_k3(
    ds: Any,
    frame: pd.DataFrame,
    windows: Mapping[str, tuple[date | None, date | None]] | None = None,
    walk=None,
    log=None,
) -> dict[str, Any]:
    """Return the K3 payload."""
    from backend.market import deep_intraday as di

    windows = windows or WINDOWS
    walk = walk or di.walk_forward
    extra = stage1_features(ds, frame)
    keep = np.isfinite(extra).all(axis=1)
    base = _subset(ds, keep)
    with_k1 = replace(base, x_scalar=np.hstack([base.x_scalar, extra[keep]]))
    forecasts = {
        "stage-1 ridge": walk(base, "ridge", "rank", log=log),
        "ridge + K1": walk(with_k1, "ridge", "rank", log=log),
    }
    out: dict[str, Any] = {
        "arm": "K3",
        "rows": int(keep.sum()),
        "rows_without_forecast": int((~keep).sum()),
        "windows": {},
    }
    for name, (start, end) in windows.items():
        # The study's windows end inclusive; `window_rows` ends exclusive.
        inside = di.window_rows(
            base, start, None if end is None else end + timedelta(days=1)
        )
        series = {k: di.daily_ic(base, f, inside) for k, f in forecasts.items()}
        a, b = series["stage-1 ridge"], series["ridge + K1"]
        common = np.intersect1d(a.dates, b.dates)
        diff = np.array(
            [
                b.values[np.searchsorted(b.dates, d)]
                - a.values[np.searchsorted(a.dates, d)]
                for d in common
            ]
        )
        out["windows"][name] = {
            "stage-1 ridge": series["stage-1 ridge"].summary(),
            "ridge + K1": series["ridge + K1"].summary(),
            "marginal": {
                "delta": float(diff.mean()) if len(diff) else math.nan,
                "t": (
                    candidate_stats.hac_t(diff, HAC_LAG) if len(diff) > 2 else math.nan
                ),
                "dates": int(len(diff)),
            },
        }
    out["lines"] = [
        f"K3 {w}: stage-1 ridge daily IC {v['stage-1 ridge']['mean']:+.4f} (t {v['stage-1 ridge']['t']:+.2f}), ridge + K1 {v['ridge + K1']['mean']:+.4f} (t {v['ridge + K1']['t']:+.2f}); marginal {v['marginal']['delta']:+.4f} (t {v['marginal']['t']:+.2f}) over {v['marginal']['dates']} dates"
        for w, v in out["windows"].items()
    ]
    return out


# The dataset restricted to `keep` rows, sessions re-indexed.
def _subset(ds: Any, keep: np.ndarray) -> Any:
    """Return the Dataset on the kept rows."""
    keep = np.asarray(keep, dtype=bool)
    sessions, index = np.unique(ds.dates[keep], return_inverse=True)
    return replace(
        ds,
        dates=ds.dates[keep],
        tickers=ds.tickers[keep],
        x_seq=ds.x_seq[keep],
        x_scalar=ds.x_scalar[keep],
        y_return=ds.y_return[keep],
        y_rank=ds.y_rank[keep],
        y_vol=ds.y_vol[keep],
        trailing_vol=ds.trailing_vol[keep],
        sessions=sessions,
        session_index=index.astype(np.int64),
    )


# Every per-name forecast file under a directory, concatenated: the
# parquet files the RTX writes, or CSV files (a test without pyarrow);
# files named with a leading underscore (the run record) are skipped.
def load_forecasts(directory: Any) -> pd.DataFrame:
    """Return the concatenated forecast frame of `<directory>/*.parquet` (or *.csv)."""
    from pathlib import Path

    root = Path(directory)
    paths = sorted(
        p
        for p in list(root.glob("*.parquet")) + list(root.glob("*.csv"))
        if not p.name.startswith("_")
    )
    frames = [
        pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p) for p in paths
    ]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out
