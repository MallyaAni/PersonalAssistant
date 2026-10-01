# Independent check of the sector-sells payload, read-only, in two parts.
#
# Part A recomputes what the verdict rests on from the payload's per-sell
# rows at the median offset (not the engine's session_series / summarize):
# per candidate g from the fills (ln(fill / control) in scope, 0 out of
# scope or unpriced), the session series, its own Newey-West and clustered
# t, the drift adjustment from the wait, the criteria and the label.
#
# Part B (with --root) recomputes the peer groups from the store with its
# own code: per decision date, numpy least squares of each name's 60
# daily log returns on SPY's with an intercept, np.corrcoef of the
# residuals, the 5 best point-in-time members by sorted(); sigma_g as the
# ddof-1 std of the peers' mean log return over the last 20 sessions; R_g
# from each peer's cube (first-bar close x adjusted / official close of
# t+1, over the adjusted close of t); the two triggers. Compared with every
# sell row, the named groups and the case.
#
# Usage: python sector_sells_check.py sector_sells.json [--root STORE]
#        [--membership CSV]
import argparse
import json
import math

import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("payload")
parser.add_argument("--root", default=None)
parser.add_argument("--membership", default=None)
args = parser.parse_args()
with open(args.payload, encoding="utf-8") as handle:
    payload = json.load(handle)
rows = payload["rows"]
windows = payload["windows"]
results = payload["results"]
constants = payload["constants"]
LAG = payload["hac_lag"]
bad = 0


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


# Two numbers agree: both NaN, or within `tol`.
def same(a, b, tol=1e-6):
    a, b = f(a), f(b)
    return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= tol


# The session series of weight x value over a window's decision sessions.
def series_of(sessions, dates, weights, values, keep):
    per = dict.fromkeys(sessions, 0.0)
    for d, wt, v in zip(dates[keep], weights[keep], values[keep], strict=True):
        per[d] += wt * v
    return np.asarray([per[d] for d in sessions], float)


# --- Part A -------------------------------------------------------------------
dates = np.asarray(rows["date"])
weights = np.asarray(rows["weight"], float)
control = np.asarray([f(x) for x in rows["control"]])
nb_control = np.asarray([f(x) for x in rows["next_bar_control"]])
mus = {w: f(d["mu_bp"]) for w, d in payload["drift"].items()}
for c, record in payload["candidates"].items():
    print(f"== {c} ({record['rule']}, {record['scope']})")
    cand = rows["candidates"][c]
    scope = np.asarray(cand["in_scope"], bool)
    if np.asarray(cand["unpriced"], bool).sum() != int(
        (
            ~(
                np.isfinite(np.asarray([f(v) for v in cand["fill"]]))
                & np.isfinite(control)
            )
        ).sum()
    ):
        bad += 1
        print("   MISMATCH the unpriced flags")
    for mode, key, fill_key, ctrl in (
        ("default", "g_bp", "fill", control),
        ("next_bar", "next_bar_g_bp", "next_bar_fill", nb_control),
    ):
        g = np.asarray([f(v) for v in cand[key]], float)
        fill = np.asarray([f(v) for v in cand[fill_key]], float)
        with np.errstate(all="ignore"):
            mine = np.where(
                scope & np.isfinite(fill) & np.isfinite(ctrl),
                1e4 * np.log(fill / ctrl),
                0.0,
            )
        priced_mode = np.isfinite(fill) & np.isfinite(ctrl)
        unpriced = ~priced_mode
        waits = np.where(unpriced, 0.0, np.asarray(cand["wait"], float))
        mismatch = np.abs(np.where(priced_mode, mine, 0.0) - g) > 1e-6
        if mismatch.any():
            bad += 1
            print(f"   MISMATCH {mode} g from the fills on {int(mismatch.sum())} sells")
        if (g[~scope] != 0).any():
            bad += 1
            print(f"   MISMATCH {mode}: a sell out of scope has g != 0")
        for w in windows:
            sessions = [d for d in rows["sessions"] if inside(d, w)]
            keep = np.array([inside(d, w) for d in dates])
            series = series_of(sessions, dates, weights, g, keep)
            adjusted = series_of(sessions, dates, weights, g - mus[w] * waits, keep)
            ref = results[c][mode][w]
            mean = float(series.mean()) if len(series) else math.nan
            t = nw_t(series, LAG)
            dm = float(adjusted.mean()) if len(series) else math.nan
            dt = nw_t(adjusted, LAG)
            retimed = keep & (g != 0)
            per_order = float(g[retimed].mean()) if retimed.any() else math.nan
            per_t = cluster_t(g[retimed], dates[retimed])
            checks = [
                ("sessions", len(series), ref["sessions"]),
                ("orders", int(keep.sum()), ref["orders"]),
                ("mean_bp", mean, ref["mean_bp"]),
                ("hac_t", t, ref["hac_t"]),
                ("drift_mean_bp", dm, ref["drift_mean_bp"]),
                ("drift_hac_t", dt, ref["drift_hac_t"]),
                ("retimed", int(retimed.sum()), ref["retimed"]),
                ("retimed_bp", per_order, ref["retimed_bp"]),
                ("retimed_t", per_t, ref["retimed_t"]),
                ("unpriced", int((keep & unpriced).sum()), ref["unpriced"]),
                ("waited", int((keep & (waits > 0)).sum()), ref["waited"]),
                ("in_scope", int((keep & scope & ~unpriced).sum()), ref["in_scope"]),
            ]
            if mode == "default":
                print(
                    f"   {w}: {mean:+.3f} bp/session (t {t:+.2f}); drift-adjusted "
                    f"{dm:+.3f} (t {dt:+.2f}); per re-timed sell {per_order:+.1f} bp "
                    f"(t {per_t:+.2f}) over {int(retimed.sum())} of {int(keep.sum())}"
                )
            for name, a, b in checks:
                if not same(a, b):
                    bad += 1
                    print(f"   MISMATCH {mode}/{w}/{name}: {a} vs {b}")
    model = results[c]["default"]["model"]
    bar = results[c]["next_bar"]["model"]
    later = results[c]["default"]["2024-2026"]
    offsets = payload["per_offset"][c]["model_bp"]
    positive = sum(1 for v in offsets if v is not None and v > 0)
    dsr = payload["deflated"][c]
    crit = {
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
    immaterial = (
        not crit["1_floor"]
        and f(model["retimed_bp"]) >= constants["IMMATERIAL_BP"]
        and f(model["retimed_t"]) >= constants["IMMATERIAL_T"]
    )
    label = (
        "REPLACES"
        if all(crit.values())
        else ("RECORD: real but immaterial" if immaterial else "RECORD")
    )
    engine = payload["verdict"]["candidates"][c]
    print(f"   positive at {positive} of {len(offsets)}; criteria {crit}")
    print(f"   verdict {engine['label']} (recomputed {label})")
    if crit != engine["criteria"] or label != engine["label"]:
        bad += 1
        print(f"   MISMATCH verdict: engine {engine['criteria']}")

# --- Part B -------------------------------------------------------------------
if args.root:
    from pathlib import Path

    from backend.agents.trading.desk import desk, point_in_time
    from backend.market import sip_cube, universe
    from backend.market.store import MarketStore

    store = MarketStore(Path(args.root))
    panel, _ = desk.book_panel(store)
    tickers = list(panel.tickers)
    spy = tickers.index(panel.benchmark)
    history = (
        Path(args.membership) if args.membership else universe.MEMBERSHIP_HISTORY_PATH
    )
    member = point_in_time.eligibility(panel.dates, tuple(tickers), history)
    member[:, spy] = False
    adj = np.asarray(panel.adj_close, float)
    with np.errstate(all="ignore"):
        logret = np.vstack(
            [np.full((1, adj.shape[1]), np.nan), np.log(adj[1:] / adj[:-1])]
        )
    day_index = {str(d): i for i, d in enumerate(panel.dates)}
    cubes = {}

    # One name's cube, loaded once.
    def cube_of(name):
        if name not in cubes:
            try:
                cubes[name] = sip_cube.load(store, name)
            except Exception:  # noqa: BLE001 - a name without a cube is unpriced
                cubes[name] = None
        return cubes[name]

    # The first-bar log return of t+1 over the adjusted close of t, NaN when
    # the cube lacks t+1.
    def first_bar(name, t):
        cube = cube_of(name)
        if cube is None or t + 1 >= len(panel.dates):
            return math.nan
        day = np.datetime64(panel.dates[t + 1], "D")
        hit = np.flatnonzero(np.asarray(cube.dates, dtype="datetime64[D]") == day)
        if not len(hit):
            return math.nan
        r = int(hit[0])
        auction = float(cube.auction_open[r])
        official = (
            auction
            if math.isfinite(auction) and auction > 0
            else float(cube.close[r, -1])
        )
        j = tickers.index(name)
        price = float(cube.close[r, 0]) * adj[t + 1, j] / official
        return math.log(price / adj[t, j])

    peer_cache = {}

    # Every name's (peers, correlations, sigma_g) on panel row t, from the
    # store, by least squares and np.corrcoef.
    def groups_on(t):
        if t in peer_cache:
            return peer_cache[t]
        out = {}
        if t >= 60:
            win = logret[t - 59 : t + 1]
            m = win[:, spy]
            if np.isfinite(m).all():
                x = np.column_stack([np.ones(60), m])
                valid = [
                    j
                    for j in range(len(tickers))
                    if j != spy and np.isfinite(win[:, j]).all()
                ]
                res = {}
                for j in valid:
                    coef, *_ = np.linalg.lstsq(x, win[:, j], rcond=None)
                    e = win[:, j] - x @ coef
                    if float(e @ e) > 0:
                        res[j] = e
                cols = sorted(res)
                if len(cols) >= 2:
                    cm = np.corrcoef(np.vstack([res[j] for j in cols]))
                    pos = {j: k for k, j in enumerate(cols)}
                    for i in cols:
                        cands = [
                            (-cm[pos[i], pos[j]], j)
                            for j in cols
                            if j != i and member[t, j]
                        ]
                        if len(cands) < 5:
                            continue
                        best = sorted(cands)[:5]
                        peers = [j for _, j in best]
                        g = logret[t - 19 : t + 1][:, peers].mean(axis=1)
                        out[tickers[i]] = (
                            [tickers[j] for j in peers],
                            [-v for v, _ in best],
                            float(np.std(g, ddof=1)),
                        )
        peer_cache[t] = out
        return out

    # The peer reading of one (date, ticker): peers, correlations, sigma_g,
    # R_g and the peers priced.
    def reading(day, name):
        t = day_index.get(day)
        if t is None:
            return None
        entry = groups_on(t).get(name)
        if entry is None:
            return [], [], math.nan, math.nan, 0
        peers, corr, sigma = entry
        values = [first_bar(p, t) for p in peers]
        priced = [v for v in values if math.isfinite(v)]
        morning = float(np.mean(priced)) if len(priced) >= 3 else math.nan
        return peers, corr, sigma, morning, len(priced)

    threshold = math.log1p(constants["DIP"])
    checked = mism = 0
    for k, (day, name) in enumerate(zip(rows["date"], rows["ticker"], strict=True)):
        got = reading(day, name)
        if got is None:
            continue
        peers, _, sigma, morning, priced = got
        checked += 1
        fired_defer = (
            math.isfinite(morning) and math.isfinite(sigma) and morning > sigma
        )
        fired_close = math.isfinite(morning) and morning > threshold
        ok = (
            peers == rows["peers"][k]
            and same(sigma, rows["sigma_g"][k], 1e-9)
            and same(morning, rows["morning"][k], 1e-9)
            and priced == rows["priced_peers"][k]
            and fired_defer == rows["fired"]["peer_rally_defer"][k]
            and fired_close == rows["fired"]["peer_rally_close"][k]
        )
        if not ok:
            mism += 1
            if mism <= 10:
                print(
                    f"   MISMATCH peers {day} {name}: {peers} {sigma} {morning} "
                    f"vs {rows['peers'][k]} {rows['sigma_g'][k]} {rows['morning'][k]}"
                )
    bad += mism
    print(f"== peer groups: {checked} sell rows recomputed, {mism} mismatches")
    named = payload["peers"]["named"]
    for name, entry in named["groups"].items():
        got = reading(named["date"], name)
        if entry is None or got is None:
            print(f"   {name}: not in the panel on {named['date']}")
            continue
        peers, corr, sigma, _, _ = got
        theirs = [p for p, _ in entry["peers"]]
        flag = (
            ""
            if peers == theirs and same(sigma, entry["sigma_g"], 1e-9)
            else " MISMATCH"
        )
        if flag:
            bad += 1
        text = ", ".join(f"{p} {c:+.2f}" for p, c in zip(peers, corr, strict=True))
        print(f"   {name} on {named['date']}: {text}; sigma_g {sigma:.4f}{flag}")
    case = payload.get("case")
    if case:
        got = reading(case["decision"], case["ticker"])
        peers, _, sigma, morning, _ = got
        print(
            f"   case {case['ticker']} {case['decision']}: R_g {morning:+.4f} sigma_g "
            f"{sigma:.4f} (payload {f(case['peers'].get('morning')):+.4f})"
        )
        if not same(morning, case["peers"].get("morning"), 1e-9):
            bad += 1
            print("   MISMATCH case R_g")
print("offsets:", payload["offsets"])
print("independent check:", "OK" if bad == 0 else f"{bad} MISMATCHES")
