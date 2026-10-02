# Independent check of the cluster-cap (R1) verdict: recompute, from the
# scorecard payloads' median-offset curves, per-offset CAGRs and per-offset
# drawdowns and nothing else, every number the verdict rests on - the
# paired daily difference against the control (mean bp a session, its own
# Newey-West t at lag 20), the median-offset CAGR and worst drawdown of the
# rule line on each window (against the row's own per-offset values), the
# median across offsets of the CAGR and the worst drawdown, the offsets
# above and shallower - and re-derive each arm's label from the plan's
# criteria (docs/research/cluster-cap-plan-2026-10-02.md). Then, for every
# session on which an arm's cap bound, redo the cap from the recorded
# weights before and the recorded clusters with this file's own arithmetic
# and compare the weights after; assert no cluster ends above C, no name
# above 25%, the weight is conserved up to the cash, and every cluster of
# two or more has an average residual correlation of at least rho*.
# Finally assert the C = 100% payload reproduces the control's rows,
# paired evidence and curves and never binds.
# Usage: python cluster_cap_check.py cluster_cap_verdict.json [cc100_r60.json]
# (the payload paths are read from the verdict's `sources`). Read-only.
import json
import math
import sys
from pathlib import Path

import numpy as np


# A JSON file as a dict.
def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


LINE = "rule / point-in-time"
LAG = 20
ANNUAL = 252
WINDOWS = ("2016-2023", "2024-2026")
NAME_CAP = 0.25
TOL = 1e-9


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


# A payload number (None for NaN) as a float.
def f(x):
    return math.nan if x is None else float(x)


# Two numbers agree: both NaN, or within tol.
def same(a, b, tol=1e-6):
    a, b = f(a), f(b)
    return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= tol


# Whether a date string lies in [lo, hi) of a payload window.
def inside(d, w, payload):
    lo, hi = payload["windows"][w]
    return (lo is None or d >= lo) and (hi is None or d < hi)


# The rule line's daily returns of a payload at a cost, keyed by date.
def curve(payload, cost):
    c = payload["curves"][cost]
    return dict(zip(c["dates"], [f(v) for v in c["lines"][LINE]], strict=True))


# CAGR and worst drawdown from the starting NAV of a daily series.
def stats(r):
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    nav = np.concatenate(([1.0], np.cumprod(1.0 + r)))
    cagr = nav[-1] ** (ANNUAL / len(r)) - 1.0
    dd = (nav / np.maximum.accumulate(nav) - 1.0).min()
    return cagr, dd


# The rule line's row of a payload on a window at a cost.
def row(payload, w, cost):
    for r in payload["rows"]:
        if r["line"] == LINE and r["window"] == w and f(r["cost_bps"]) == f(cost):
            return r
    raise KeyError(w)


# The cap redone by name: scale every binding cluster to C, hand the
# excess to names outside capped clusters pro rata under the name cap,
# repeat; return (weights after by name, cash).
def recap(before, clusters, cap):
    w = dict(before)
    capped, carry = set(), 0.0
    while True:
        over = [
            i
            for i, g in enumerate(clusters)
            if i not in capped and sum(w[n] for n in g) > cap + TOL
        ]
        if not over:
            return w, carry
        for i in over:
            total = sum(w[n] for n in clusters[i])
            for n in clusters[i]:
                w[n] *= cap / total
            carry += total - sum(w[n] for n in clusters[i])
            capped.add(i)
        locked = {n for i in capped for n in clusters[i]}
        while carry > TOL:
            room = [n for n in w if n not in locked and 0 < w[n] < NAME_CAP - TOL]
            if not room:
                break
            base = sum(w[n] for n in room)
            given = 0.0
            spill = False
            for n in room:
                want = carry * w[n] / base
                take = min(want, NAME_CAP - w[n])
                spill |= want > take
                w[n] += take
                given += take
            carry -= given
            if not spill:
                break
        carry = max(carry, 0.0)


bad = 0
verdict = load(sys.argv[1])
control = load(verdict["sources"]["control"])
arms = {tag: load(path) for tag, path in verdict["sources"]["arms"].items()}
COST = f"{verdict['cost_bps']:g}"
crit = None
for tag, payload in arms.items():
    reading = verdict["arms"][tag]
    crit = reading["criteria"]
    spec = payload["cluster_cap"]["spec"]
    own, base = curve(payload, COST), curve(control, COST)
    k = control["curves"][COST]["offset"]
    print(f"{tag}: C {spec['cap']}, rho* {spec['rho']}")
    windows = {}
    for w in WINDOWS:
        # 1. The paired daily difference from the curves.
        days = [
            d
            for d in own
            if inside(d, w, payload)
            and d in base
            and math.isfinite(own[d])
            and math.isfinite(base[d])
        ]
        diff = np.asarray([own[d] - base[d] for d in days], float)
        got = reading["paired"][w]
        ok = (
            got["sessions"] == len(diff)
            and same(got["mean_daily_bp"], diff.mean() * 1e4)
            and same(got["hac_t"], nw_t(diff, LAG))
        )
        bad += not ok
        print(
            f"  {w}: paired {diff.mean() * 1e4:+.4f} bp/session "
            f"(t {nw_t(diff, LAG):+.3f}) over {len(diff)}; verdict "
            f"{f(got['mean_daily_bp']):+.4f} (t {f(got['hac_t']):+.3f}): "
            f"{'OK' if ok else 'MISMATCH'}"
        )
        # 2. The median offset's CAGR and drawdown against the row's own.
        r, c = row(payload, w, COST), row(control, w, COST)
        cagr, dd = stats([own[d] for d in own if inside(d, w, payload)])
        ok = same(r["cagrs"][k], cagr, 1e-9) and same(r["drawdowns"][k], dd, 1e-9)
        bad += not ok
        print(
            f"  {w}: offset {k} CAGR {cagr * 100:+.2f}%, worst drawdown "
            f"{dd * 100:+.2f}% against the row's: {'OK' if ok else 'MISMATCH'}"
        )
        # 3. The medians across offsets, the counts, the verdict's reading.
        a_c = np.asarray([f(x) for x in r["cagrs"]])
        b_c = np.asarray([f(x) for x in c["cagrs"]])
        a_d = np.asarray([f(x) for x in r["drawdowns"]])
        b_d = np.asarray([f(x) for x in c["drawdowns"]])
        mine = {
            "drawdown_gain": np.nanmedian(a_d) - np.nanmedian(b_d),
            "cagr_difference": np.nanmedian(a_c) - np.nanmedian(b_c),
            "offsets_above": int(np.nansum(a_c > b_c)),
            "offsets_shallower": int(np.nansum(a_d > b_d)),
        }
        v = reading["windows"][w]
        ok = (
            same(v["drawdown"], np.nanmedian(a_d))
            and same(v["drawdown_control"], np.nanmedian(b_d))
            and same(v["cagr"], np.nanmedian(a_c))
            and same(v["cagr_control"], np.nanmedian(b_c))
            and same(v["drawdown_gain"], mine["drawdown_gain"])
            and same(v["cagr_difference"], mine["cagr_difference"])
            and v["offsets_above"] == mine["offsets_above"]
            and v["offsets_shallower"] == mine["offsets_shallower"]
        )
        bad += not ok
        windows[w] = mine
        print(
            f"  {w}: drawdown {np.nanmedian(a_d) * 100:+.2f}% vs "
            f"{np.nanmedian(b_d) * 100:+.2f}% ({mine['drawdown_gain'] * 100:+.2f} "
            f"points, shallower at {mine['offsets_shallower']}), CAGR "
            f"{mine['cagr_difference'] * 100:+.2f} points (above at "
            f"{mine['offsets_above']}): {'OK' if ok else 'MISMATCH'}"
        )

    # 4. The label from the plan's criteria.
    def trade(points, windows=windows, crit=crit):
        return all(
            m["drawdown_gain"] >= points
            and m["cagr_difference"] >= -crit["cagr_give_up"]
            for m in windows.values()
        )

    if trade(crit["drawdown_points"]):
        want = "REPLACES"
    elif trade(crit["immaterial_points"]) and all(
        m["offsets_shallower"] >= crit["offsets_shallower"] for m in windows.values()
    ):
        want = "RECORD: real but immaterial"
    else:
        want = "RECORD"
    ok = want == reading["label"]
    bad += not ok
    print(
        f"  label {reading['label']} (re-derived {want}): {'OK' if ok else 'MISMATCH'}"
    )
    # 5. Every binding session's cap, redone.
    sessions = payload["cluster_cap"]["binding"]["sessions"]
    worst = 0.0
    fails = 0
    for s in sessions:
        before = dict(zip(s["names"], s["before"], strict=True))
        after = dict(zip(s["names"], s["after"], strict=True))
        redone, cash = recap(before, s["clusters"], spec["cap"])
        gap = max(abs(redone[n] - after[n]) for n in after)
        worst = max(worst, gap)
        sound = (
            gap <= 1e-9
            and abs(cash - s["cash"]) <= 1e-9
            and all(
                sum(after[n] for n in g) <= spec["cap"] + 1e-9 for g in s["clusters"]
            )
            and max(after.values()) <= NAME_CAP + 1e-9
            and abs(sum(after.values()) + s["cash"] - sum(before.values())) <= 1e-9
            and all(
                len(g) < 2 or f(corr) >= spec["rho"] - 1e-12
                for g, corr in zip(s["clusters"], s["cluster_corr"], strict=True)
            )
        )
        fails += not sound
    bad += fails > 0
    print(
        f"  cap redone on {len(sessions)} binding sessions: largest weight gap "
        f"{worst:.1e}, {fails} failing: {'OK' if not fails else 'MISMATCH'}"
    )

# 6. The null payload is the control.
if len(sys.argv) > 2:
    null = load(sys.argv[2])
    ok = (
        json.dumps(null["rows"]) == json.dumps(control["rows"])
        and json.dumps(null["paired"]) == json.dumps(control["paired"])
        and json.dumps(null["curves"]) == json.dumps(control["curves"])
        and null["cluster_cap"]["spec"]["cap"] == 1.0
        and not null["cluster_cap"]["binding"]["sessions"]
    )
    bad += not ok
    print(
        "null (C = 100%): rows, paired, curves equal to the control's and never "
        f"binds: {'OK' if ok else 'MISMATCH'}"
    )

print("independent check: OK" if not bad else f"independent check: {bad} MISMATCH(ES)")
sys.exit(1 if bad else 0)
