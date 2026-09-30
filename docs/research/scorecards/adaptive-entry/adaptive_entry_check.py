# Independent check of the adaptive-entry payload: recompute what the
# verdict rests on from the payload's per-order rows at the median offset
# (a different code path from the engine's session_series / summarize,
# with its own Newey-West and clustered t), compare with the payload's
# results and re-derive each candidate's six criteria from the numbers.
# Usage: python adaptive_entry_check.py adaptive_entry.json. Read-only.
import json
import math
import sys

import numpy as np

payload = json.load(open(sys.argv[1]))
rows = payload["rows"]
windows = payload["windows"]
results = payload["results"]
constants = payload["constants"]
LAG = payload["hac_lag"]


# Whether a date string lies in [lo, hi) of a window.
def inside(d, w):
    lo, hi = windows[w]
    return (lo is None or d >= lo) and (hi is None or d < hi)


# Newey-West (Bartlett) t of the mean, written from the formula.
def nw_t(x, lag):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return math.nan
    e = x - x.mean()
    var = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2.0 * (1.0 - k / (lag + 1.0)) * float(e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n)) if var > 0 else math.nan


# t of the mean with standard errors clustered by date (G/(G-1) factor).
def cluster_t(v, c):
    v = np.asarray(v, float)
    c = np.asarray(c)
    if len(v) < 2:
        return math.nan
    _, g = np.unique(c, return_inverse=True)
    k = g.max() + 1
    if k < 2:
        return math.nan
    r = v - v.mean()
    s = np.bincount(g, weights=r, minlength=k)
    var = k / (k - 1.0) * float(s @ s) / (len(v) ** 2)
    return float(v.mean() / math.sqrt(var)) if var > 0 else math.nan


# A payload number (None for NaN) as a float.
def f(x):
    return math.nan if x is None else float(x)


# Two numbers agree: both NaN, or within 1e-6.
def same(a, b):
    a, b = f(a), f(b)
    return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= 1e-6


bad = 0
dates = rows["date"]
weights = np.asarray(rows["weight"], float)
for c, record in payload["candidates"].items():
    print(f"== {c} ({record['rule']})")
    cand = rows["candidates"][c]
    for mode, key in (("default", "g_bp"), ("next_bar", "next_bar_g_bp")):
        g = np.asarray([f(v) for v in cand[key]], float)
        for w in windows:
            sessions = [d for d in rows["sessions"] if inside(d, w)]
            per = dict.fromkeys(sessions, 0.0)
            keep = np.array([inside(d, w) for d in dates])
            for d, wt, v in zip(np.asarray(dates)[keep], weights[keep], g[keep], strict=True):
                per[d] += wt * v
            series = np.asarray([per[d] for d in sessions], float)
            ref = results[c][mode][w]
            mean = float(series.mean()) if len(series) else math.nan
            t = nw_t(series, LAG)
            retimed = keep & (g != 0)
            per_order = float(g[retimed].mean()) if retimed.any() else math.nan
            per_t = cluster_t(g[retimed], np.asarray(dates)[retimed])
            unpriced = int(sum(cand["unpriced"][k] for k in np.flatnonzero(keep)))
            checks = [
                ("sessions", len(series), ref["sessions"]),
                ("orders", int(keep.sum()), ref["orders"]),
                ("mean_bp", mean, ref["mean_bp"]),
                ("hac_t", t, ref["hac_t"]),
                ("retimed", int(retimed.sum()), ref["retimed"]),
                ("retimed_bp", per_order, ref["retimed_bp"]),
                ("retimed_t", per_t, ref["retimed_t"]),
                ("unpriced", unpriced, ref["unpriced"]),
            ]
            if mode == "default":
                print(
                    f"   {w}: {mean:+.3f} bp/session (payload {f(ref['mean_bp']):+.3f}), "
                    f"NW t {t:+.2f} (payload {f(ref['hac_t']):+.2f}); per re-timed order "
                    f"{per_order:+.1f} bp (t {per_t:+.2f}) over {int(retimed.sum())} of "
                    f"{int(keep.sum())} buys, {unpriced} unpriced"
                )
            for name, mine, theirs in checks:
                if not same(mine, theirs):
                    bad += 1
                    print(f"   MISMATCH {mode}/{w}/{name}: {mine} vs {theirs}")
    # The criteria from the numbers, against the engine's.
    model = results[c]["default"]["model"]
    bar = results[c]["next_bar"]["model"]
    later = results[c]["default"]["2024-2026"]
    offsets = payload["per_offset"][c]["model_bp"]
    positive = sum(1 for v in offsets if v is not None and v > 0)
    dsr = payload["deflated"][c]
    mine = {
        "1_floor": f(model["mean_bp"]) >= constants["FLOOR_BP"] and f(model["hac_t"]) >= constants["FLOOR_T"],
        "2_next_bar": f(bar["mean_bp"]) >= constants["FLOOR_BP"] and f(bar["hac_t"]) >= constants["FLOOR_T"],
        "3_not_negative_2024_2026": f(later["mean_bp"]) >= 0.0,
        "4_deflated_sharpe": f(dsr["dsr"]) >= constants["DSR_GATE"],
        "5_drift_adjusted": f(model["drift_mean_bp"]) >= constants["DRIFT_FLOOR_BP"]
        and f(model["drift_hac_t"]) >= constants["DRIFT_FLOOR_T"],
        "6_offsets_positive": positive >= constants["OFFSETS_POSITIVE"],
    }
    theirs = payload["verdict"]["candidates"][c]["criteria"]
    label = "REPLACES" if all(mine.values()) else "RECORD"
    print(f"   positive at {positive} of {len(offsets)} offsets; DSR {f(dsr['dsr']):.3f} at N=3")
    print(f"   criteria {mine}")
    print(f"   verdict {payload['verdict']['candidates'][c]['label']} (recomputed {label})")
    if mine != theirs:
        bad += 1
        print(f"   MISMATCH criteria: engine {theirs}")
    if label != payload["verdict"]["candidates"][c]["label"].split(":")[0]:
        bad += 1
        print("   MISMATCH label")
print("offsets:", payload["offsets"])
print("independent check:", "OK" if bad == 0 else f"{bad} MISMATCHES")
