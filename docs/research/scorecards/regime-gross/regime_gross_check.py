# Independent check of the regime-gross verdict: recompute, from the
# scorecard payloads' median-offset curves, per-offset CAGRs and recorded
# probabilities and nothing else, every number the verdict rests on -
# against BOTH controls (the gross-1 control and B1's best registered
# target): the paired daily difference (mean in bp a session, its own
# Newey-West t at lag 20), the offsets above each control, the
# median-offset CAGR, worst drawdown and Sharpe of the rule line on each
# window (against the payload's own per-offset CAGR at that offset), the
# gross path itself (g_low where the probability read at t-1 is at or
# above the threshold, else 1; for the reported combination the minimum
# with min(1, target / sigma-hat) from the control's gross-1 curve)
# against the gross the scaled run recorded, re-derive each pair's label
# from the plan's two-control criteria, and, when given, assert the null
# payload (threshold 1.0) reproduces the control's rows, paired evidence
# and curves and that the regime run's own control equals B1's.
# Usage: python regime_gross_check.py regime_gross_verdict.json [null.json]
# [rg_control.json] (payload paths are read from the verdict's `sources`).
# Read-only.
import json
import math
import sys
from pathlib import Path

import numpy as np


# A JSON file as a dict.
def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


verdict = load(sys.argv[1])
control = load(verdict["sources"]["control"])
vol = load(verdict["sources"]["vol_target"])
candidates = {tag: load(path) for tag, path in verdict["sources"]["candidates"].items()}
LINE = "rule / point-in-time"
COST = f"{verdict['cost_bps']:g}"
LAG = 20
ANNUAL = 252
WINDOWS = ("2016-2023", "2024-2026")
CONTROLS = (("against_control", control), ("against_vol_target", vol))


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


# The rule line's daily returns of a payload at the study's cost, keyed by date.
def curve(payload):
    c = payload["curves"][COST]
    return dict(zip(c["dates"], [f(v) for v in c["lines"][LINE]], strict=True))


# CAGR, worst drawdown from the starting NAV, and annualised Sharpe of a
# daily series, written from the definitions.
def stats(r):
    r = np.asarray(r, float)
    r = r[np.isfinite(r)]
    n = len(r)
    nav = np.concatenate(([1.0], np.cumprod(1.0 + r)))
    cagr = nav[-1] ** (ANNUAL / n) - 1.0
    dd = (nav / np.maximum.accumulate(nav) - 1.0).min()
    sd = r.std(ddof=1)
    return cagr, dd, (r.mean() / sd * math.sqrt(ANNUAL) if sd > 0 else math.nan)


# The rule line's row of a payload on a window at the study's cost.
def row(payload, w):
    for r in payload["rows"]:
        if r["line"] == LINE and r["window"] == w and f(r["cost_bps"]) == f(COST):
            return r
    raise KeyError(w)


# B1's trade from a reading's windows and paired blocks, as the plan fixes it.
def trade(wins, pairs):
    drawdown = all(
        f(wins[w]["drawdown_gain"]) >= 0.05 and f(wins[w]["cagr_difference"]) >= -0.03
        for w in WINDOWS
    )
    sharpe = all(
        f(wins[w]["sharpe_difference"]) >= 0.15
        and f(wins[w]["drawdown_gain"]) >= -1e-12
        for w in WINDOWS
    )
    not_negative = all(not (f(pairs[w]["hac_t"]) <= -2.0) for w in WINDOWS)
    return (drawdown or sharpe) and not_negative


bad = 0
k = control["curves"][COST]["offset"]
base = curve(control)
print(
    f"controls: {control.get('arm')} and {vol.get('arm')} "
    f"(tag {vol.get('vol_target', {}).get('tag')}), as of {control.get('asof')}"
)
if vol.get("asof") != control.get("asof") or vol["curves"][COST]["offset"] != k:
    bad += 1
    print("  MISMATCH: the two controls are not as of the same session and offset")
for tag, payload in candidates.items():
    reading = verdict["candidates"][tag]
    spec = payload["regime_gross"]
    own = curve(payload)
    print(
        f"{tag}: threshold {spec['threshold']}, g_low {spec['g_low']}, "
        f"combined with {spec['combine_target']}, registered {spec['registered']}"
    )
    for name, against in CONTROLS:
        theirs = curve(against)
        got_all = reading[name]
        print(f"  {name} ({against.get('arm')}):")
        for w in WINDOWS:
            # 1. The paired daily difference per window, from the curves.
            days = [
                d
                for d in own
                if inside(d, w, payload)
                and d in theirs
                and math.isfinite(own[d])
                and math.isfinite(theirs[d])
            ]
            diff = np.asarray([own[d] - theirs[d] for d in days], float)
            got = got_all["paired"][w]
            ok = (
                got["sessions"] == len(diff)
                and same(got["mean_daily_bp"], diff.mean() * 1e4, 1e-6)
                and same(got["hac_t"], nw_t(diff, LAG), 1e-6)
            )
            bad += not ok
            print(
                f"    {w}: paired {diff.mean() * 1e4:+.4f} bp/session "
                f"(t {nw_t(diff, LAG):+.3f}) over {len(diff)} sessions; verdict "
                f"{got['mean_daily_bp']:+.4f} (t {got['hac_t']:+.3f}) over "
                f"{got['sessions']}: {'OK' if ok else 'MISMATCH'}"
            )
            # 2. The rows' readings against this control.
            v = got_all["windows"][w]
            r, c = row(payload, w), row(against, w)
            ok = (
                same(v["drawdown"], r["median_drawdown"])
                and same(v["drawdown_control"], c["median_drawdown"])
                and same(v["cagr"], r["median_cagr"])
                and same(v["cagr_control"], c["median_cagr"])
                and same(v["sharpe"], r["median_sharpe"])
                and same(v["sharpe_control"], c["median_sharpe"])
                and same(
                    v["drawdown_gain"],
                    f(r["median_drawdown"]) - f(c["median_drawdown"]),
                )
                and same(
                    v["cagr_difference"], f(r["median_cagr"]) - f(c["median_cagr"])
                )
                and same(
                    v["sharpe_difference"],
                    f(r["median_sharpe"]) - f(c["median_sharpe"]),
                )
            )
            bad += not ok
            print(
                f"    {w}: rows' medians - drawdown "
                f"{f(r['median_drawdown']) * 100:+.1f}% vs "
                f"{f(c['median_drawdown']) * 100:+.1f}%, CAGR "
                f"{f(r['median_cagr']) * 100:+.1f}% vs "
                f"{f(c['median_cagr']) * 100:+.1f}%, Sharpe "
                f"{f(r['median_sharpe']):.2f} vs {f(c['median_sharpe']):.2f}: "
                f"{'OK' if ok else 'MISMATCH'}"
            )
        # 3. Offsets above this control on the deciding window.
        mine = np.asarray(row(payload, WINDOWS[0])["cagrs"], float)
        other = np.asarray(row(against, WINDOWS[0])["cagrs"], float)
        above = int(np.nansum(mine > other))
        ok = above == got_all["offsets_above"] and len(other) == got_all["offsets"]
        bad += not ok
        print(
            f"    above at {above} of {len(other)} offsets: "
            f"{'OK' if ok else 'MISMATCH'}"
        )
        # 4. The trade against this control, from the verdict's own numbers.
        cleared = trade(got_all["windows"], got_all["paired"])
        ok = cleared == (got_all["label"] == "REPLACES")
        bad += not ok
        print(
            f"    clears the trade: {cleared}; verdict {got_all['label']}: "
            f"{'OK' if ok else 'MISMATCH'}"
        )
    # 5. The median-offset window statistics against the row's per-offset
    # CAGR at that offset.
    for w in WINDOWS:
        series = [own[d] for d in own if inside(d, w, payload)]
        cagr, dd, sharpe = stats(series)
        r = row(payload, w)
        ok = same(r["cagrs"][k], cagr, 1e-9)
        bad += not ok
        print(
            f"  {w}: median-offset CAGR {cagr * 100:+.2f}% (row's offset {k}: "
            f"{f(r['cagrs'][k]) * 100:+.2f}%), worst drawdown {dd * 100:+.2f}%, "
            f"Sharpe {sharpe:.3f}: {'OK' if ok else 'MISMATCH'}"
        )
    # 6. The gross path from the recorded probability read at t-1: g_low
    # where it is at or above the threshold, 1 elsewhere (and undefined is
    # 1); the combination takes the minimum with the volatility target's
    # gross from the control's gross-1 curve.
    record = payload["regime_gross"][COST]["median_offset"]
    dates = record["dates"]
    gross = np.asarray([f(g) for g in record["gross"]], float)
    read = np.asarray([f(p) for p in record["probability"]], float)
    expect = np.ones(len(dates))
    fires = np.isfinite(read) & (read >= f(spec["threshold"]))
    expect[fires] = f(spec["g_low"])
    if spec["combine_target"] is not None:
        unit = np.asarray([base.get(d, math.nan) for d in dates], float)
        target = np.ones(len(dates))
        for t in range(20, len(dates)):
            block = unit[t - 20 : t]
            if np.isfinite(block).all():
                s = block.std(ddof=1) * math.sqrt(ANNUAL)
                if s > 0:
                    target[t] = min(1.0, f(spec["combine_target"]) / s)
        expect = np.minimum(expect, target)
    ok = record["offset"] == k and np.allclose(gross, expect, atol=1e-9)
    bad += not ok
    defined = np.isfinite(read)
    top = np.nanmax(read) if defined.any() else math.nan
    print(
        f"  gross path from the recorded p(t-1): fired on "
        f"{fires.mean() * 100:.1f}% of sessions (p defined on "
        f"{defined.mean() * 100:.0f}%, max p {top:.3f}); "
        f"recorded path {'matches' if ok else 'DIFFERS'}"
    )
    # 7. The label from the two controls.
    clears = {
        name: trade(reading[name]["windows"], reading[name]["paired"])
        for name, _ in CONTROLS
    }
    if not spec["registered"]:
        label = "REPORTED"
    elif clears["against_control"] and clears["against_vol_target"]:
        label = "REPLACES"
    elif clears["against_control"]:
        label = "RECORD (does not beat the vol target)"
    else:
        label = "RECORD"
    ok = label == reading["label"]
    bad += not ok
    print(
        f"  criteria: clears the control {clears['against_control']}, clears the "
        f"vol target {clears['against_vol_target']} -> {label}; verdict "
        f"{reading['label']}: {'OK' if ok else 'MISMATCH'}"
    )


# A block as canonical JSON, so two blocks compare as values.
def strip(block):
    return json.dumps(block, sort_keys=True, allow_nan=True)


# 8. The null payload, when given: rows, paired evidence and curves equal
# to the control's, gross all one, and no probability read at or above 1.
if len(sys.argv) > 2:
    null = load(sys.argv[2])
    rows_ok = strip(null["rows"]) == strip(control["rows"])
    paired_ok = strip(null["paired"]) == strip(control["paired"])
    curves_ok = strip(null["curves"]) == strip(control["curves"])
    gross_ok = all(
        f(g) == 1.0
        for cost in null["costs_bps"]
        for g in null["regime_gross"][f"{cost:g}"]["median_offset"]["gross"]
    )
    reads = [
        f(p)
        for cost in null["costs_bps"]
        for p in null["regime_gross"][f"{cost:g}"]["median_offset"]["probability"]
    ]
    below_one = all(not (math.isfinite(p) and p >= 1.0) for p in reads)
    ok = rows_ok and paired_ok and curves_ok and gross_ok and below_one
    bad += not ok
    print(
        f"null test (threshold 1.0 against the control): rows {rows_ok}, paired "
        f"{paired_ok}, curves {curves_ok}, gross all one {gross_ok}, every p "
        f"below 1 {below_one}: {'OK' if ok else 'MISMATCH'}"
    )

# 9. The regime run's own control against B1's, when given: the two
# studies priced the same book on the same session.
if len(sys.argv) > 3:
    own_control = load(sys.argv[3])
    if own_control.get("asof") != control.get("asof"):
        print(
            f"regime control as of {own_control.get('asof')} against B1's "
            f"{control.get('asof')}: not comparable (different sessions)"
        )
    else:
        rows_ok = strip(own_control["rows"]) == strip(control["rows"])
        curves_ok = strip(own_control["curves"]) == strip(control["curves"])
        ok = rows_ok and curves_ok
        bad += not ok
        print(
            f"regime control against B1's control: rows {rows_ok}, curves "
            f"{curves_ok}: {'OK' if ok else 'MISMATCH'}"
        )

print(f"independent check: {'OK' if bad == 0 else f'{bad} MISMATCH(ES)'}")
sys.exit(1 if bad else 0)
