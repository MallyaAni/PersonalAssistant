# Stage-4 exploratory diagnostic, run BEFORE any registration (descriptive only;
# no candidate rule is priced). For the grade decisions of the book - a name
# entering A/A+ (buy), leaving A/A+ (sell), and any A/A+ day (a reset top-up) -
# the price path over the next 1-20 sessions from the next open P0: the drift
# (what waiting W sessions costs), the oracle saving (the best close in the
# window), the chance a lower (higher) close comes at all, and when it comes.
import json, math, sys
import numpy as np
sys.path.insert(0, ".")  # run from a repository checkout
from backend.market import stage3_io as io
from backend.market import candidate_stats as cs

ROOT = "/home/animallya96/deploy/anios/data/market/research/stage3"
b = io.load_ohlcv(f"{ROOT}/stage3_ohlcv.npz")
d = io.load_data(f"{ROOT}/stage3_s1.npz")
dates = np.asarray(b.dates, dtype="datetime64[D]")
tick = [str(t) for t in b.tickers]
T, N = b.close.shape
col = {t: j for j, t in enumerate(tick)}
pos = np.searchsorted(dates, np.asarray(d.dates, dtype="datetime64[D]"))
G = np.full((T, N), -1, dtype=np.int8)
jj = np.array([col.get(str(t), -1) for t in d.tickers])
ok = (jj >= 0) & (pos < T)
G[pos[ok], jj[ok]] = np.asarray(d.extra["grade"])[ok]
names = list(d.feature_names)
vix = np.full(T, np.nan)
vcol = names.index("d_vix_level")
vix[pos] = np.exp(np.asarray(d.x[:, vcol], dtype=float))  # the column is ln(VIX)
O, C = b.open.astype(float), b.close.astype(float)
with np.errstate(all="ignore"):
    ret = np.vstack([np.full((1, N), np.nan), np.log(C[1:] / C[:-1])])
sig = np.full((T, N), np.nan)
for t in range(20, T):
    sig[t] = np.nanstd(ret[t - 19 : t + 1], axis=0)
sma50 = np.full((T, N), np.nan)
for t in range(49, T):
    sma50[t] = np.nanmean(C[t - 49 : t + 1], axis=0)
Ws = (1, 3, 5, 10, 20)

# Each event's path from the next open over 1-20 sessions: drift, oracle,
# chance of a better close and the day it comes (buys: lower; sells: higher).
def paths(events, side):
    rows = []
    for t, j in events:
        if t + 20 >= T:
            continue
        p0 = O[t + 1, j]
        c = C[t + 1 : t + 21, j]
        if not (np.isfinite(p0) and p0 > 0 and np.isfinite(c).all()):
            continue
        rel = 1e4 * (c / p0 - 1.0)  # bp of each later close against P0
        r = {"t": t, "year": int(str(dates[t])[:4]), "sig": sig[t, j] * 1e4, "vix": vix[t], "g0": int(G[t - 1, j]), "g1": int(G[t, j]),
             "above50": bool(C[t, j] > sma50[t, j]) if np.isfinite(sma50[t, j]) else None,
             "ret20": 1e4 * (C[t, j] / C[t - 20, j] - 1) if t >= 20 else np.nan}
        for W in Ws:
            w = rel[:W]
            if side == "buy":
                r[f"drift{W}"] = w[-1]
                r[f"oracle{W}"] = max(0.0, -w.min())
                r[f"lower{W}"] = float(w.min() < 0)
                r[f"dip1{W}"] = float(w.min() <= -r["sig"])
                r[f"argmin{W}"] = int(np.argmin(w)) + 1
            else:
                r[f"drift{W}"] = -w[-1]
                r[f"oracle{W}"] = max(0.0, w.max())
                r[f"lower{W}"] = float(w.max() > 0)
                r[f"dip1{W}"] = float(w.max() >= r["sig"])
                r[f"argmin{W}"] = int(np.argmax(w)) + 1
        rows.append(r)
    return rows

up, down, held = [], [], []
for t in range(1, T):
    g0, g1 = G[t - 1], G[t]
    for j in np.flatnonzero((g0 >= 0) & (g0 < 2) & (g1 >= 2)):
        up.append((t, j))
    for j in np.flatnonzero((g0 >= 2) & (g1 >= 0) & (g1 < 2)):
        down.append((t, j))
    for j in np.flatnonzero(g1 >= 2):
        held.append((t, j))
sets = {"buy: enters A/A+": (up, "buy"), "sell: leaves A/A+": (down, "sell"), "buy: any A/A+ day": (held, "buy")}

# Means, medians and HAC t of the path readings at W = 5, 10 and 20.
def summ(rows, label):
    out = {"n": len(rows)}
    for W in (5, 10, 20):
        dr = np.array([r[f"drift{W}"] for r in rows]); orc = np.array([r[f"oracle{W}"] for r in rows])
        tt = np.array([r["t"] for r in rows])
        order = np.argsort(tt, kind="stable")
        out[W] = {"drift": float(np.mean(dr)), "drift_med": float(np.median(dr)),
                  "drift_t": cs.hac_t(dr[order], 20), "oracle": float(np.mean(orc)),
                  "p_better": float(np.mean([r[f"lower{W}"] for r in rows])),
                  "p_1sd": float(np.mean([r[f"dip1{W}"] for r in rows])),
                  "day_best_med": float(np.median([r[f"argmin{W}"] for r in rows]))}
    return out

report = {}
for name, (ev, side) in sets.items():
    rows = paths(ev, side)
    groups = {"all": rows,
              "2016-2023": [r for r in rows if r["year"] <= 2023],
              "2024-2026": [r for r in rows if r["year"] >= 2024],
              "above SMA50": [r for r in rows if r["above50"] is True],
              "below SMA50": [r for r in rows if r["above50"] is False],
              "VIX >= 25": [r for r in rows if np.isfinite(r["vix"]) and r["vix"] >= 25],
              "VIX < 25": [r for r in rows if np.isfinite(r["vix"]) and r["vix"] < 25]}
    if side == "buy" and name.startswith("buy: enters"):
        groups["to A+"] = [r for r in rows if r["g1"] == 3]
        groups["to A"] = [r for r in rows if r["g1"] == 2]
        groups["from C"] = [r for r in rows if r["g0"] == 0]
        groups["from B"] = [r for r in rows if r["g0"] == 1]
    if side == "sell":
        groups["from A+"] = [r for r in rows if r["g0"] == 3]
        groups["from A"] = [r for r in rows if r["g0"] == 2]
        groups["to C"] = [r for r in rows if r["g1"] == 0]
        groups["to B"] = [r for r in rows if r["g1"] == 1]
    if name.startswith("buy: any"):
        groups["A+ day"] = [r for r in rows if r["g1"] == 3]
        groups["A day"] = [r for r in rows if r["g1"] == 2]
    rq = np.array([r["ret20"] for r in rows]); med = np.nanmedian(rq)
    groups["20d return below median"] = [r for r in rows if r["ret20"] < med]
    groups["20d return above median"] = [r for r in rows if r["ret20"] >= med]
    report[name] = {k: summ(v, k) for k, v in groups.items() if len(v) >= 30}
    report[name]["sig_med_bp"] = float(np.nanmedian([r["sig"] for r in rows]))
json.dump(report, open("/home/animallya96/scratch/stage4_prize.json", "w"), indent=1)
for name, block in report.items():
    print("==", name, "(median daily sd %.0f bp)" % block["sig_med_bp"])
    for g, s in block.items():
        if g == "sig_med_bp":
            continue
        cells = []
        for W in (5, 10, 20):
            x = s[W]
            cells.append("W%-2d drift %+5.0f (t %+.1f) oracle %4.0f p_better %.2f p_1sd %.2f best day %.0f" % (
                W, x["drift"], x["drift_t"], x["oracle"], x["p_better"], x["p_1sd"], x["day_best_med"]))
        print("  %-24s n %6d | %s" % (g, s["n"], " | ".join(cells)))
