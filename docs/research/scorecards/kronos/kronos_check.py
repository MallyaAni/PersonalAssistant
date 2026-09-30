"""Independent check of the Kronos payloads: the headline numbers recomputed from the rows.

    python docs/research/scorecards/kronos/kronos_check.py \\
        docs/research/scorecards/kronos/kronos_k1.json \\
        docs/research/scorecards/kronos/kronos_k2.json

Only numpy and json: nothing from `backend/` is imported, so a mistake
in the harness would not be reproduced here.

K1: from each window's per-period ICs the mean and its t (mean over the
standard error), the period count, and the criterion (post-cutoff IC >=
0.02, t >= 2, at least 60 periods) - against the payload's numbers.

K2: from the per-order rows at the median offset, per candidate, the
session series (the sum over the orders decided at t of weight x g, in
bp of equity, over the run's decision sessions), the model-window
(post-cutoff) mean and its Newey-West t at lag 20, the contaminated
window's mean, the re-timed orders' mean, and each order's g from the
control and candidate fills (g = 1e4 ln(control / fill) for a buy, the
reverse for a sell) - against the payload's numbers and the label the
criteria imply from those numbers.
"""

from __future__ import annotations

import json
import math
import sys

import numpy as np

TOL = 1e-6
HAC_LAG = 20
FLOOR_BP, FLOOR_T = 2.0, 2.0
IC_FLOOR, IC_T, MIN_PERIODS = 0.02, 2.0, 60


# The Newey-West t of the mean of `x` at `lag` (Bartlett weights).
def hac_t(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 3:
        return math.nan
    d = x - x.mean()
    s = float(d @ d) / n
    for k in range(1, lag + 1):
        if k >= n:
            break
        w = 1.0 - k / (lag + 1.0)
        s += 2.0 * w * float(d[k:] @ d[:-k]) / n
    if s <= 0:
        return math.nan
    return float(x.mean() / math.sqrt(s / n))


# A payload number as a float (None is NaN).
def f(x) -> float:
    return math.nan if x is None else float(x)


# Compare two numbers, NaN equal to NaN.
def same(a, b, tol=TOL) -> bool:
    a = math.nan if a is None else float(a)
    b = math.nan if b is None else float(b)
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# K1: recompute each arm's mean IC, t and period count per window.
def check_k1(payload: dict) -> list[str]:
    problems = []
    for window, w in payload["results"].items():
        for arm, r in w["arms"].items():
            ics = np.array(
                [
                    v
                    for v in r["period_ics"].values()
                    if v is not None and math.isfinite(v)
                ],
                dtype=float,
            )
            mean = float(ics.mean()) if len(ics) else math.nan
            t = (
                float(mean / (ics.std(ddof=1) / math.sqrt(len(ics))))
                if len(ics) >= 2 and ics.std(ddof=1) > 0
                else math.nan
            )
            print(
                f"K1 {window:11} {arm:16} IC {mean:+.4f} (t {t:+.2f}) over {len(r['period_ics'])} periods; payload {f(r['ic']):+.4f} (t {f(r['t']):+.2f})"
            )
            if (
                not same(mean, r["ic"])
                or not same(t, r["t"])
                or len(r["period_ics"]) != r["periods"]
            ):
                problems.append(
                    f"K1 {window} {arm}: IC/t/periods differ from the payload"
                )
    post = payload["results"].get("post_window", {"arms": {}})
    for arm, c in payload["criteria"]["arms"].items():
        r = post["arms"][arm]
        enough = r["periods"] >= MIN_PERIODS
        clears = bool(
            math.isfinite(f(r["ic"]))
            and math.isfinite(f(r["t"]))
            and f(r["ic"]) >= IC_FLOOR
            and f(r["t"]) >= IC_T
        )
        if (
            enough != c["enough_periods"]
            or clears != c["ic_clears"]
            or (enough and clears) != c["passes"]
        ):
            problems.append(
                f"K1 criterion {arm}: the payload's criterion disagrees with its numbers"
            )
    record = not any(
        post["arms"][a]["periods"] >= MIN_PERIODS for a in payload["criteria"]["arms"]
    )
    if record != payload["criteria"]["record_by_construction"]:
        problems.append("K1: record_by_construction disagrees with the period counts")
    if payload["verdict"]["label"] != "RECORD":
        problems.append(
            "K1: the verdict is not RECORD although the book gate was not run"
        )
    return problems


# K2: recompute each candidate's session series and window statistics.
def check_k2(payload: dict) -> list[str]:
    problems = []
    rows = payload["rows"]
    sessions = np.array(rows["sessions"], dtype="datetime64[D]")
    dates = np.array(rows["date"], dtype="datetime64[D]")
    weight = np.array(rows["weight"], dtype=float)
    control = np.array(rows["control"], dtype=float)
    session_pos = np.searchsorted(sessions, dates)
    windows = {
        name: (np.datetime64(lo) if lo else None, np.datetime64(hi) if hi else None)
        for name, (lo, hi) in payload["windows"].items()
    }
    for candidate, c in rows["candidates"].items():
        idx = np.array(c["rows"], dtype=int)
        fill = np.array(c["fill"], dtype=float)
        g = np.array(c["g_bp"], dtype=float)
        unpriced = np.array(c["unpriced"], dtype=bool)
        side = c["side"]
        with np.errstate(all="ignore"):
            own = (
                1e4 * np.log(control[idx] / fill)
                if side == "buy"
                else 1e4 * np.log(fill / control[idx])
            )
        own = np.where(unpriced, 0.0, own)
        if not np.allclose(own, g, atol=1e-6, equal_nan=False):
            problems.append(f"{candidate}: g differs from ln(control / fill)")
        series = np.bincount(
            session_pos[idx], weights=weight[idx] * g, minlength=len(sessions)
        )[: len(sessions)]
        result = payload["results"][candidate]["default"]
        for name, (lo, hi) in windows.items():
            keep = np.ones(len(sessions), dtype=bool)
            if lo is not None:
                keep &= sessions >= lo
            if hi is not None:
                keep &= sessions < hi
            s = series[keep]
            mean = float(s.mean()) if len(s) else math.nan
            t = hac_t(s, HAC_LAG) if len(s) > 2 else math.nan
            inside = keep[session_pos[idx]]
            retimed = inside & (g != 0)
            retimed_bp = float(g[retimed].mean()) if retimed.any() else math.nan
            r = result[name]
            print(
                f"K2 {candidate:8} {name:13} {mean:+.2f} bp/session (t {t:+.2f}) over {len(s)} sessions, re-timed {retimed_bp:+.1f} bp over {int(retimed.sum())}; payload {f(r['mean_bp']):+.2f} (t {f(r['hac_t']):+.2f}) over {r['sessions']}"
            )
            if (
                not same(mean, r["mean_bp"], 1e-6)
                or not same(t, r["hac_t"], 1e-4)
                or len(s) != r["sessions"]
                or not same(retimed_bp, r["retimed_bp"], 1e-6)
            ):
                problems.append(
                    f"{candidate} {name}: the window statistics differ from the payload"
                )
        info = payload["verdict"]["candidates"][candidate]
        floor = bool(
            math.isfinite(f(info["model_bp"]))
            and math.isfinite(f(info["model_t"]))
            and f(info["model_bp"]) >= FLOOR_BP
            and f(info["model_t"]) >= FLOOR_T
        )
        if floor != info["criteria"]["1_floor"]:
            problems.append(f"{candidate}: criterion 1 disagrees with its numbers")
        expected = (
            "REPLACES"
            if all(info["criteria"].values())
            else (
                "RECORD: real but immaterial"
                if info["real_but_immaterial"]
                else "RECORD"
            )
        )
        if info["label"] != expected:
            problems.append(
                f"{candidate}: the label {info['label']!r} does not follow from the criteria"
            )
    return problems


# Run the checks on every payload given; exit 1 on a problem.
def main(paths: list[str]) -> int:
    problems: list[str] = []
    for path in paths:
        with open(path) as handle:
            payload = json.load(handle)
        print(f"== {path}")
        if payload.get("arm") == "K1":
            problems += check_k1(payload)
        elif payload.get("study") == "kronos_fill":
            problems += check_k2(payload)
        else:
            print("  (no check for this payload)")
    for p in problems:
        print("PROBLEM:", p)
    print("independent check:", "PASS" if not problems else "FAIL")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
