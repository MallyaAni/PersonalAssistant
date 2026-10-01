# Independent check of A5 tone expiry (docs/research/tone-expiry-plan-2026-10-01.md):
# recompute, from the control's and the two arms' point-in-time scorecard
# payloads and by a different code path from the engine's
# (backend/market/tone_expiry_study.py), every number the verdict rests on -
# the paired sentiment IC per horizon and window from the stored per-period
# series (its own t), the affected cells' IC per date from the stored
# per-cell p and q (12 x mean(p x q)) and its paired t, the book's paired
# daily difference from the median-offset curves with its own Newey-West t,
# the median CAGRs from the per-offset lists - then re-derive each arm's
# criteria, its label and the proposal and compare them with the verdict
# file. Also checked: each arm's incumbent series is the control's, the
# per-year affected counts add up to the windows', and the board words
# carry no advice word.
# Usage: python tone_expiry_check.py control.json hard.json decay.json verdict.json
# Read-only. Prints "independent check: OK" and exits 0 when every number
# agrees; prints each mismatch and exits 1 otherwise.
import json
import math
import re
import statistics
import sys

ARMS = {"A5-hard": "hard", "A5-decay": "decay"}
HORIZONS = ("h20", "h60")
DECIDING = ("2016-2023", "2024-2026")
COST = "25"
LINE = "rule / point-in-time"
LAG = 20
IC_FLOOR, BOOK_FLOOR, CAGR_FLOOR = -1.0, -1.0, -0.005
ADVICE = (
    "trade",
    "buy",
    "sell",
    "should",
    "avoid",
    "safe",
    "consider",
    "recommend",
    "own",
    "wait",
)
TOL = 1e-9


# A payload number (None for NaN) as a float.
def f(x):
    return math.nan if x is None else float(x)


# Two numbers agree: both NaN, both the same infinity, or within TOL.
def same(a, b):
    a, b = f(a), f(b)
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= TOL * max(1.0, abs(a), abs(b))


# Whether an ISO date lies in [lo, hi) of a window given as [lo, hi].
def inside(day, window):
    lo, hi = window
    return (lo is None or day >= lo) and (hi is None or day < hi)


# The plain t of a mean over independent periods, written from the formula;
# every difference zero is 0 (the plan's convention), a constant non-zero
# difference is +-inf.
def plain_t(xs):
    xs = [x for x in xs if math.isfinite(x)]
    n = len(xs)
    if n == 0:
        return 0, math.nan, math.nan
    mean = sum(xs) / n
    if n < 2:
        return n, mean, 0.0 if mean == 0 else math.nan
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    if var == 0:
        return n, mean, 0.0 if mean == 0 else math.copysign(math.inf, mean)
    return n, mean, mean / math.sqrt(var / n)


# The Newey-West (Bartlett) t of the mean at `lag`, written from the formula;
# a series of zeros is t = 0.
def nw_t(xs, lag):
    n = len(xs)
    if n and all(x == 0 for x in xs):
        return 0.0
    if n < 3:
        return math.nan
    mean = sum(xs) / n
    e = [x - mean for x in xs]
    var = sum(v * v for v in e) / n
    for k in range(1, min(lag, n - 1) + 1):
        var += (
            2.0
            * (1.0 - k / (lag + 1.0))
            * sum(e[i] * e[i - k] for i in range(k, n))
            / n
        )
    return mean / math.sqrt(var / n) if var > 0 else math.nan


# The rule line's row of a payload on a window at 25 bp.
def row(payload, window):
    for r in payload["rows"]:
        if r["line"] == LINE and r["window"] == window and f(r["cost_bps"]) == 25.0:
            return r
    raise KeyError(window)


bad = []


# Record a mismatch.
def complain(text):
    bad.append(text)
    print("MISMATCH", text)


# Read one JSON payload.
def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


control, hard, decay, verdict = (load(p) for p in sys.argv[1:5])
arms = {"A5-hard": hard, "A5-decay": decay}
windows = control["windows"]
labels = {}

for name, payload in arms.items():
    block = payload["tone_expiry"]
    if block["mode"] != ARMS[name]:
        complain(f"{name}: mode {block['mode']}")
    if not block["report_matches_rule"]:
        complain(f"{name}: report not built by its rule")
    if payload["asof"] != control["asof"]:
        complain(f"{name}: asof {payload['asof']} vs {control['asof']}")
    if block["incumbent_fingerprint"] != control["desk_fingerprint"]:
        complain(f"{name}: incumbent desk differs from the control's")
    judged = verdict["arms"][name]
    passed = True
    for window in DECIDING:
        checks = {}
        for h in HORIZONS:
            series = block["sentiment_ic"][h]["periods"]
            own = control["sentiment_ic"][h]["periods"]
            if series["dates"] != own["dates"]:
                complain(f"{name} {h}: dates differ from the control's")
            for a, b in zip(series["incumbent"], own["ic"], strict=True):
                if not same(a, b):
                    complain(f"{name} {h}: incumbent IC {a} vs control {b}")
                    break
            diffs = [
                f(a) - f(i)
                for d, a, i in zip(
                    series["dates"], series["arm"], series["incumbent"], strict=True
                )
                if inside(d, windows[window])
            ]
            n, mean, t = plain_t(diffs)
            stored = block["sentiment_ic"][h]["windows"][window]["paired"]
            if (
                n != stored["n"]
                or not same(mean, stored["mean"])
                or not same(t, stored["t"])
            ):
                complain(f"{name} {window} {h}: paired IC {n} {mean} {t} vs {stored}")
            v = judged["windows"][window]["ic"][h]
            if not same(t, v["t"]):
                complain(f"{name} {window} {h}: verdict t {v['t']} vs {t}")
            checks[f"ic_{h}"] = f(t) >= IC_FLOOR
            # The affected cells: 12 x mean(p x q) per date from the cells.
            per_date = {}
            for c in block["sentiment_ic"][h]["affected_cells"]:
                per_date.setdefault(c["date"], []).append(c)
            rows_by_date = {
                r["date"]: r for r in block["sentiment_ic"][h]["affected_dates"]
            }
            if set(per_date) != set(rows_by_date):
                complain(f"{name} {h}: affected dates differ from the cells' dates")
            day_diffs = []
            for day, cells in sorted(per_date.items()):
                s0 = 12.0 * sum(c["p_incumbent"] * c["q"] for c in cells) / len(cells)
                s1 = 12.0 * sum(c["p_arm"] * c["q"] for c in cells) / len(cells)
                stored_day = rows_by_date.get(day, {})
                if not (
                    same(s0, stored_day.get("incumbent"))
                    and same(s1, stored_day.get("arm"))
                ):
                    complain(f"{name} {h} {day}: affected IC {s0} {s1} vs {stored_day}")
                if inside(day, windows[window]):
                    day_diffs.append(s1 - s0)
            n, mean, t = plain_t(day_diffs)
            stored = block["sentiment_ic"][h]["windows"][window]["affected"]["paired"]
            if (
                n != stored["n"]
                or not same(mean, stored["mean"])
                or not same(t, stored["t"])
            ):
                complain(
                    f"{name} {window} {h}: affected paired {n} {mean} {t} vs {stored}"
                )
        # The book: the rule line's median-offset curves, paired by date.
        a, b = payload["curves"][COST], control["curves"][COST]
        theirs = dict(zip(b["dates"], b["lines"][LINE], strict=True))
        diffs = []
        for day, x in zip(a["dates"], a["lines"][LINE], strict=True):
            y = theirs.get(day)
            if not inside(day, windows[window]) or x is None or y is None:
                continue
            if math.isfinite(x) and math.isfinite(y):
                diffs.append(x - y)
        t = nw_t(diffs, LAG)
        book = judged["windows"][window]["book"]
        mean_bp = sum(diffs) / len(diffs) * 1e4 if diffs else math.nan
        if (
            len(diffs) != book["sessions"]
            or not same(t, book["hac_t"])
            or not same(mean_bp, book["mean_daily_bp"])
        ):
            complain(f"{name} {window}: book {len(diffs)} {mean_bp} {t} vs {book}")
        checks["book_t"] = f(t) >= BOOK_FLOOR
        # The median CAGRs from the per-offset lists.
        mine = [
            f(c)
            for c in row(payload, window)["cagrs"]
            if c is not None and math.isfinite(f(c))
        ]
        base = [
            f(c)
            for c in row(control, window)["cagrs"]
            if c is not None and math.isfinite(f(c))
        ]
        m1, m0 = statistics.median(mine), statistics.median(base)
        if not same(m1, row(payload, window)["median_cagr"]) or not same(
            m0, row(control, window)["median_cagr"]
        ):
            complain(f"{name} {window}: median CAGR {m1} {m0} vs the rows")
        if not same(m1 - m0, judged["windows"][window]["cagr_difference"]):
            complain(f"{name} {window}: CAGR difference {m1 - m0} vs the verdict's")
        checks["cagr"] = (m1 - m0) >= CAGR_FLOOR
        theirs = judged["windows"][window]["checks"]
        if checks != theirs:
            complain(f"{name} {window}: checks {checks} vs {theirs}")
        passed = passed and all(checks.values())
    labels[name] = "REPLACES" if passed else "RECORD"
    if labels[name] != judged["label"]:
        complain(f"{name}: label {labels[name]} vs {judged['label']}")
    # The per-year counts add up to the windows'.
    years = block["affected"]["years"]
    for window, (lo, hi) in windows.items():
        first = int(lo[:4]) if lo else -1
        last = int(hi[:4]) if hi else 10**6
        for scope in ("panel", "book"):
            total = sum(
                v[scope]["cells"] for y, v in years.items() if first <= int(y) < last
            )
            if total != block["affected"]["windows"][window][scope]["cells"]:
                complain(
                    f"{name} {window} {scope}: per-year cells {total} vs the window's"
                )
    for entry in block["board_words"]:
        words = set(re.findall(r"[a-z]+", entry["words"].lower()))
        if words & set(ADVICE):
            complain(f"{name} {entry['ticker']}: advice words {words & set(ADVICE)}")

passing = [n for n in ARMS if labels.get(n) == "REPLACES"]
proposed = passing[0] if passing else None
if proposed != verdict["proposed"]:
    complain(f"proposed {proposed} vs {verdict['proposed']}")
for name in ARMS:
    print(f"{name}: {labels.get(name)}")
print(f"proposed: {proposed}")
print(
    "independent check: OK" if not bad else f"independent check: {len(bad)} mismatches"
)
sys.exit(0 if not bad else 1)
