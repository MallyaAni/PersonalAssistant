# Independent check of the volatility-targeting verdict: recompute, from
# the scorecard payloads' median-offset curves and per-offset CAGRs and
# nothing else, every number the verdict rests on - the paired daily
# difference against the control (mean in bp a session, its own Newey-West
# t at lag 20), the offsets above the control, the median-offset CAGR,
# worst drawdown and Sharpe of the rule line on each window (against the
# payload's own per-offset CAGR at that offset), the gross path itself
# (sigma-hat from the control's gross-1 curve, gross = min(1, target /
# sigma-hat), against the gross the scaled run recorded), re-derive each
# target's label from the plan's criteria, and assert the null payload
# (target inf) reproduces the control's rows, paired evidence and curves.
# Usage: python vol_target_check.py vol_target_verdict.json [null.json]
# (payload paths are read from the verdict's `sources`). Read-only.
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
targets = {tag: load(path) for tag, path in verdict["sources"]["targets"].items()}
LINE = "rule / point-in-time"
COST = f"{verdict['cost_bps']:g}"
LAG = 20
ANNUAL = 252
WINDOWS = ("2016-2023", "2024-2026")


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


bad = 0
base = curve(control)
k = control["curves"][COST]["offset"]
for tag, payload in targets.items():
    reading = verdict["targets"][tag]
    spec = payload["vol_target"]
    own = curve(payload)
    print(f"{tag}: sigma* {spec['target']}, window {spec['window']}")
    # 1. The paired daily difference per window, from the curves.
    for w in WINDOWS:
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
            and same(got["mean_daily_bp"], diff.mean() * 1e4, 1e-6)
            and same(got["hac_t"], nw_t(diff, LAG), 1e-6)
        )
        bad += not ok
        print(
            f"  {w}: paired {diff.mean() * 1e4:+.4f} bp/session "
            f"(t {nw_t(diff, LAG):+.3f}) "
            f"over {len(diff)} sessions; verdict {got['mean_daily_bp']:+.4f} "
            f"(t {got['hac_t']:+.3f}) over {got['sessions']}: "
            f"{'OK' if ok else 'MISMATCH'}"
        )
        # 2. The median-offset window statistics against the row's per-offset
        # CAGR at that offset, and the verdict's reading of the rows.
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
        v = reading["windows"][w]
        c = row(control, w)
        ok = (
            same(v["drawdown"], r["median_drawdown"])
            and same(v["drawdown_control"], c["median_drawdown"])
            and same(v["cagr"], r["median_cagr"])
            and same(v["cagr_control"], c["median_cagr"])
            and same(v["sharpe"], r["median_sharpe"])
            and same(v["sharpe_control"], c["median_sharpe"])
            and same(
                v["drawdown_gain"], f(r["median_drawdown"]) - f(c["median_drawdown"])
            )
            and same(v["cagr_difference"], f(r["median_cagr"]) - f(c["median_cagr"]))
            and same(
                v["sharpe_difference"], f(r["median_sharpe"]) - f(c["median_sharpe"])
            )
        )
        bad += not ok
        print(
            f"  {w}: rows' medians - drawdown {f(r['median_drawdown']) * 100:+.1f}% vs "
            f"{f(c['median_drawdown']) * 100:+.1f}%, CAGR "
            f"{f(r['median_cagr']) * 100:+.1f}% vs {f(c['median_cagr']) * 100:+.1f}%, "
            f"Sharpe {f(r['median_sharpe']):.2f} vs "
            f"{f(c['median_sharpe']):.2f}: {'OK' if ok else 'MISMATCH'}"
        )
    # 3. Offsets above the control on the deciding window.
    mine = np.asarray(row(payload, WINDOWS[0])["cagrs"], float)
    theirs = np.asarray(row(control, WINDOWS[0])["cagrs"], float)
    above = int(np.nansum(mine > theirs))
    ok = above == reading["offsets_above"] and len(theirs) == reading["offsets"]
    bad += not ok
    print(
        f"  above the control at {above} of {len(theirs)} offsets: "
        f"{'OK' if ok else 'MISMATCH'}"
    )
    # 4. The gross path from the control's gross-1 curve at the median
    # offset: sigma-hat over the `window` returns before t, annualised,
    # gross = min(1, target / sigma-hat); the switches are reported
    # variants and are checked only when off.
    record = payload["vol_target"][COST]["median_offset"]
    dates = record["dates"]
    gross = np.asarray([f(g) for g in record["gross"]], float)
    sigma = np.asarray([f(s) for s in record["sigma_hat"]], float)
    unit = np.asarray([base.get(d, math.nan) for d in dates], float)
    n = int(spec["window"])
    expect = np.ones(len(dates))
    expect_sigma = np.full(len(dates), math.nan)
    for t in range(n, len(dates)):
        block = unit[t - n : t]
        if np.isfinite(block).all():
            s = block.std(ddof=1) * math.sqrt(ANNUAL)
            expect_sigma[t] = s
            if s > 0 and math.isfinite(f(spec["target"])):
                expect[t] = min(1.0, f(spec["target"]) / s)
    if spec["switch_return"] or spec["switch_intercept"]:
        print("  gross path: switches on, not recomputed here (reported variant)")
    else:
        ok = (
            record["offset"] == k
            and np.allclose(gross, expect, atol=1e-9)
            and np.array_equal(np.isfinite(sigma), np.isfinite(expect_sigma))
            and np.allclose(
                sigma[np.isfinite(sigma)], expect_sigma[np.isfinite(sigma)], atol=1e-9
            )
        )
        bad += not ok
        below = (gross < 1).mean() * 100
        print(
            f"  gross path from the control's curve: mean {gross.mean():.3f}, "
            f"below 1 on "
            f"{below:.0f}% of sessions, lowest {gross.min():.3f}; recorded path "
            f"{'matches' if ok else 'DIFFERS'}"
        )
    # 5. The label from the plan's criteria and the verdict's own numbers.
    wins = verdict["targets"][tag]["windows"]
    pairs = verdict["targets"][tag]["paired"]
    drawdown_trade = all(
        f(wins[w]["drawdown_gain"]) >= 0.05 and f(wins[w]["cagr_difference"]) >= -0.03
        for w in WINDOWS
    )
    sharpe_trade = all(
        f(wins[w]["sharpe_difference"]) >= 0.15
        and f(wins[w]["drawdown_gain"]) >= -1e-12
        for w in WINDOWS
    )
    not_negative = all(not (f(pairs[w]["hac_t"]) <= -2.0) for w in WINDOWS)
    label = (
        "REPLACES" if (drawdown_trade or sharpe_trade) and not_negative else "RECORD"
    )
    ok = label == reading["label"]
    bad += not ok
    print(
        f"  criteria: drawdown trade {drawdown_trade}, Sharpe trade {sharpe_trade}, "
        f"not negative {not_negative} -> {label}; verdict {reading['label']}: "
        f"{'OK' if ok else 'MISMATCH'}"
    )

# 6. The null payload, when given: rows, paired evidence and curves equal
# to the control's.
if len(sys.argv) > 2:
    null = load(sys.argv[2])

    # A block as canonical JSON, so two blocks compare as values.
    def strip(block):
        return json.dumps(block, sort_keys=True, allow_nan=True)

    rows_ok = strip(null["rows"]) == strip(control["rows"])
    paired_ok = strip(null["paired"]) == strip(control["paired"])
    curves_ok = strip(null["curves"]) == strip(control["curves"])
    gross_ok = all(
        f(g) == 1.0
        for cost in null["costs_bps"]
        for g in null["vol_target"][f"{cost:g}"]["median_offset"]["gross"]
    )
    ok = rows_ok and paired_ok and curves_ok and gross_ok
    bad += not ok
    print(
        f"null test (target inf against the control): rows {rows_ok}, "
        f"paired {paired_ok}, "
        f"curves {curves_ok}, gross all one {gross_ok}: {'OK' if ok else 'MISMATCH'}"
    )

print(f"independent check: {'OK' if bad == 0 else f'{bad} MISMATCH(ES)'}")
sys.exit(1 if bad else 0)
