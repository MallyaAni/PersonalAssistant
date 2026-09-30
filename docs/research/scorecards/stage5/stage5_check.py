# Independent check of the stage-5 payload: recompute the registered
# statistics from the per-buy rows (a different code path from the engine's
# summarize) and compare with the payload's results at the registered
# decision; then print what the verdict rests on. Read-only.
import json
import math
import sys

import numpy as np

payload = json.load(open(sys.argv[1]))
rows = payload["rows"]
buys = rows["buys"]
extras = rows["extras"]
windows = payload["windows"]
main = payload["results"]["15:30"]


def inside(d, w):
    lo, hi = windows[w]
    return (lo is None or d >= lo) and (hi is None or d < hi)


def cluster_t(v, c):
    v = np.asarray(v, float)
    c = np.asarray(c)
    if len(v) < 2:
        return math.nan
    _, g = np.unique(c, return_inverse=True)
    k = g.max() + 1
    r = v - v.mean()
    s = np.bincount(g, weights=r, minlength=k)
    var = k / (k - 1.0) * float(s @ s) / (len(v) ** 2)
    return float(v.mean() / math.sqrt(var)) if var > 0 else math.nan


bad = 0
for w in windows:
    el = [b for b in buys if b["status"] == "eligible" and inside(b["date"], w)]
    pr = [b for b in el if b["g_bp"] is not None and not math.isnan(b["g_bp"])]
    g = [b["g_bp"] for b in pr]
    dates = [b["date"] for b in pr]
    mean = float(np.mean(g)) if g else math.nan
    t = cluster_t(g, dates)
    go = [b["matched"] * b["gain_next_open_bp"] if b["matched"] > 0 else 0.0
          for b in el if b["gain_next_open_bp"] is not None and not math.isnan(b["gain_next_open_bp"])]
    mean_open = float(np.mean(go)) if go else math.nan
    # session series: sum weight*g per date plus extras, over every decision
    # session in the window (the engine's count of sessions is trusted here)
    per = {}
    for b in pr:
        per[b["date"]] = per.get(b["date"], 0.0) + b["weight"] * b["g_bp"]
    for x in extras:
        if inside(x["date"], w) and x["pnl_bp"] is not None and not math.isnan(x["pnl_bp"]):
            per[x["date"]] = per.get(x["date"], 0.0) + x["weight"] * x["pnl_bp"]
    n = main[w]["session"]["sessions"]
    sess = sum(per.values()) / n if n else math.nan
    ref = main[w]
    print(f"== {w}: eligible {len(el)} (payload {ref['eligible']['buys']}), priced {len(pr)} (payload {ref['per_buy']['buys']})")
    print(f"   per buy {mean:+.2f} bp (payload {ref['per_buy']['mean_bp']:+.2f}); clustered t {t:+.2f} (payload {ref['per_buy']['t']:+.2f})")
    print(f"   next_open per buy {mean_open:+.2f} (payload {ref['per_buy_next_open']['mean_bp']:+.2f})")
    print(f"   session {sess:+.3f} bp (payload {ref['session']['mean_bp']:+.3f}); extras {sum(inside(x['date'], w) for x in extras)} (payload {ref['extras']['count']})")
    matched = sum(1 for b in el if b["matched"] >= 1 - 1e-12)
    missed = sum(1 for b in el if b["matched"] == 0)
    print(f"   matched {matched} / missed {missed} (payload {ref['eligible']['matched']} / {ref['eligible']['missed']})")
    for mine, theirs, name in ((len(el), ref["eligible"]["buys"], "eligible"), (len(pr), ref["per_buy"]["buys"], "priced")):
        if mine != theirs:
            bad += 1
            print(f"   MISMATCH {name}")
    for mine, theirs, name in ((mean, ref["per_buy"]["mean_bp"], "per_buy"), (t, ref["per_buy"]["t"], "t"), (mean_open, ref["per_buy_next_open"]["mean_bp"], "next_open"), (sess, ref["session"]["mean_bp"], "session")):
        if not (math.isnan(mine) and (theirs is None or math.isnan(theirs))) and (theirs is None or abs(mine - theirs) > 1e-6):
            bad += 1
            print(f"   MISMATCH {name}: {mine} vs {theirs}")
print("criteria:", payload["verdict"]["criteria"])
print("label:", payload["verdict"]["label"])
print("null:", payload["null_test"]["passes"], "offsets:", payload["offsets"])
print("across offsets:", json.dumps(payload["across_offsets"]))
print("independent check:", "OK" if bad == 0 else f"{bad} MISMATCHES")
