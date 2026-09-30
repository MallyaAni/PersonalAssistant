# Independent check of the structure-rules payload: recompute what the
# verdict rests on from the payload's per-order rows at the median offset
# (a different code path from the engine's session_series / summarize,
# with its own Newey-West and clustered t), per candidate on the orders of
# its side, the drift adjustment from the wait, compare with the payload's
# results and re-derive each candidate's six criteria from the numbers.
# Usage: python structure_rules_check.py structure_rules.json. Read-only.
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


# The session series of weight x value over a window's decision sessions.
def series_of(sessions, dates, weights, values, keep):
    per = dict.fromkeys(sessions, 0.0)
    for d, wt, v in zip(dates[keep], weights[keep], values[keep], strict=True):
        per[d] += wt * v
    return np.asarray([per[d] for d in sessions], float)


bad = 0
all_dates = np.asarray(rows["date"])
all_weights = np.asarray(rows["weight"], float)
all_sides = np.asarray(rows["side"])
mus = {w: f(d["mu_bp"]) for w, d in payload["drift"].items()}
for c, record in payload["candidates"].items():
    side = record["side"]
    print(f"== {c} ({record['rule']}, {side})")
    cand = rows["candidates"][c]
    mine_rows = np.asarray(cand["rows"], int)
    if not (all_sides[mine_rows] == side).all():
        bad += 1
        print("   MISMATCH side: a row of the other side")
    dates = all_dates[mine_rows]
    weights = all_weights[mine_rows]
    waits = np.asarray(cand["wait"], float)
    sign = 1.0 if side == "sell" else -1.0
    for mode, key in (("default", "g_bp"), ("next_bar", "next_bar_g_bp")):
        g = np.asarray([f(v) for v in cand[key]], float)
        for w in windows:
            sessions = [d for d in rows["sessions"] if inside(d, w)]
            keep = np.array([inside(d, w) for d in dates])
            series = series_of(sessions, dates, weights, g, keep)
            adjusted = series_of(
                sessions, dates, weights, g - sign * mus[w] * waits, keep
            )
            ref = results[c][mode][w]
            mean = float(series.mean()) if len(series) else math.nan
            t = nw_t(series, LAG)
            drift_mean = (
                float(adjusted.mean())
                if len(series) and math.isfinite(mus[w])
                else math.nan
            )
            drift_t = nw_t(adjusted, LAG) if math.isfinite(mus[w]) else math.nan
            retimed = keep & (g != 0)
            per_order = float(g[retimed].mean()) if retimed.any() else math.nan
            per_t = cluster_t(g[retimed], dates[retimed])
            unpriced = int(sum(cand["unpriced"][k] for k in np.flatnonzero(keep)))
            waited = int((keep & (waits > 0)).sum())
            checks = [
                ("sessions", len(series), ref["sessions"]),
                ("orders", int(keep.sum()), ref["orders"]),
                ("mean_bp", mean, ref["mean_bp"]),
                ("hac_t", t, ref["hac_t"]),
                ("drift_mean_bp", drift_mean, ref["drift_mean_bp"]),
                ("drift_hac_t", drift_t, ref["drift_hac_t"]),
                ("retimed", int(retimed.sum()), ref["retimed"]),
                ("retimed_bp", per_order, ref["retimed_bp"]),
                ("retimed_t", per_t, ref["retimed_t"]),
                ("unpriced", unpriced, ref["unpriced"]),
                ("waited", waited, ref["waited"]),
            ]
            if mode == "default":
                print(
                    f"   {w}: {mean:+.3f} bp/session (payload {f(ref['mean_bp']):+.3f}), "
                    f"NW t {t:+.2f} (payload {f(ref['hac_t']):+.2f}); drift-adjusted "
                    f"{drift_mean:+.3f} (t {drift_t:+.2f}); per re-timed order "
                    f"{per_order:+.1f} bp (t {per_t:+.2f}) over {int(retimed.sum())} of "
                    f"{int(keep.sum())} {side}s, {unpriced} unpriced, {waited} waited"
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
        "1_floor": f(model["mean_bp"]) >= constants["FLOOR_BP"]
        and f(model["hac_t"]) >= constants["FLOOR_T"],
        "2_next_bar": f(bar["mean_bp"]) >= constants["FLOOR_BP"]
        and f(bar["hac_t"]) >= constants["FLOOR_T"],
        "3_not_negative_2024_2026": f(later["mean_bp"]) >= 0.0,
        "4_deflated_sharpe": f(dsr["dsr"]) >= constants["DSR_GATE"],
        "5_drift_adjusted": f(model["drift_mean_bp"]) >= constants["DRIFT_FLOOR_BP"]
        and f(model["drift_hac_t"]) >= constants["DRIFT_FLOOR_T"],
        "6_offsets_positive": positive >= constants["OFFSETS_POSITIVE"],
    }
    theirs = payload["verdict"]["candidates"][c]["criteria"]
    immaterial = (
        not mine["1_floor"]
        and f(model["retimed_bp"]) >= constants["IMMATERIAL_BP"]
        and f(model["retimed_t"]) >= constants["IMMATERIAL_T"]
    )
    label = (
        "REPLACES"
        if all(mine.values())
        else ("RECORD: real but immaterial" if immaterial else "RECORD")
    )
    trials = constants["TRIALS"]["registered"]
    print(
        f"   positive at {positive} of {len(offsets)} offsets; DSR {f(dsr['dsr']):.3f} "
        f"at N={trials} ({f(dsr['dsr_cumulative']):.3f} at "
        f"{constants['TRIALS']['cumulative']}); fired {f(model['acted_share']):.3f}, "
        f"tagged {f(model['tagged_share']):.3f}"
    )
    print(f"   criteria {mine}")
    print(
        f"   verdict {payload['verdict']['candidates'][c]['label']} (recomputed {label})"
    )
    if mine != theirs:
        bad += 1
        print(f"   MISMATCH criteria: engine {theirs}")
    if label != payload["verdict"]["candidates"][c]["label"]:
        bad += 1
        print("   MISMATCH label")
print("offsets:", payload["offsets"])
print("independent check:", "OK" if bad == 0 else f"{bad} MISMATCHES")
