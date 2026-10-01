# Independent check of the insider-stance payload: recompute both arms'
# rank IC per horizon and window from the per-row table `build` wrote and
# the harness's cells, without the study's own functions. The trailing
# window sum, the median dollar volume, the percentile ranks, the
# rebalance schedule and the Spearman correlation are all written again
# here from the rules the plan states; only the panel, the beta-adjusted
# residual and the desk's scores (the comparison arm, not the thing under
# test) are taken from the repository, because they are the cells the
# plan registered. The per-row table is checked against the rule too: no
# row may be known on or before its filing date.
# Usage, from the repository root with PYTHONPATH=$PWD:
#   python docs/research/scorecards/insider-stance/insider_stance_check.py \
#       --root data/market --tables <build dir> --payload <evaluate json>
# Read-only; prints OK or MISMATCH per line and exits 1 on any mismatch.
import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from backend.agents.trading.desk import desk
from backend.agents.trading.desk.desk import book_panel
from backend.market.store import MarketStore

WINDOW = 90
MIN_SESSIONS = 45
TOLERANCE = 1e-9
ARM_DESK = "D desk (five analysts)"
ARM_OPP = "A4-opp opportunistic insiders"
ARM_ALL = "A4-all all insiders"


# Average ranks, 0-based, ties sharing their mean, written from the rule.
def ranks_of(values):
    order = np.argsort(values, kind="mergesort")
    out = np.empty(len(values))
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        out[order[i : j + 1]] = (i + j) / 2.0
        i = j + 1
    return out


# Spearman correlation of two 1-D arrays by the rank formula.
def spearman(a, b):
    if len(a) < 3:
        return math.nan
    ra, rb = ranks_of(a), ranks_of(b)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    d = math.sqrt(float(ra @ ra) * float(rb @ rb))
    return float(ra @ rb / d) if d else math.nan


# Percentile rank in [0, 1] across each row's finite values, NaN kept.
def percentile(matrix):
    out = np.full(matrix.shape, np.nan)
    for t in range(matrix.shape[0]):
        known = np.isfinite(matrix[t])
        n = int(known.sum())
        if n >= 2:
            out[t, known] = ranks_of(matrix[t, known]) / (n - 1)
    return out


# The signal from the row table by the plan's rule: signed dollars summed
# over the ninety sessions ending at t, over the median of close times
# volume over the same sessions (NaN under forty-five bars).
def signal_of(panel, rows, keep):
    size, names = len(panel.dates), len(panel.tickers)
    stamps = panel.dates.astype("datetime64[D]")
    daily = np.zeros((size, names))
    for i in range(len(rows["ticker"])):
        if not keep(i):
            continue
        when = np.datetime64(rows["known_session"][i][:10])
        t = int(np.searchsorted(stamps, when))
        n = panel.tickers.index(rows["ticker"][i])
        daily[t, n] += float(rows["dollars"][i])
    out = np.full((size, names), np.nan)
    with np.errstate(invalid="ignore"):
        dollars = panel.close * panel.volume
    for t in range(size):
        lo = max(0, t - WINDOW + 1)
        net = daily[lo : t + 1].sum(axis=0)
        block = dollars[lo : t + 1]
        for n in range(names):
            column = block[:, n]
            column = column[np.isfinite(column)]
            if len(column) >= MIN_SESSIONS:
                median = float(np.median(column))
                if median > 0:
                    out[t, n] = net[n] / median
    out[:, panel.tickers.index(panel.benchmark)] = np.nan
    return out


# The harness's rebalance schedule and per-period IC on masked scores.
def period_ics(scores, residual, excluded, horizon, min_names):
    out = {}
    t = 0
    rows = scores.shape[0]
    while t + horizon < rows:
        eligible = np.isfinite(scores[t]) & np.isfinite(residual[t]) & ~excluded
        if eligible.sum() < min_names:
            t += 1
            continue
        cols = np.flatnonzero(eligible)
        out[t] = spearman(scores[t, cols], residual[t, cols])
        t += horizon
    return out


# Mean and t of the defined ICs.
def summary(ics):
    v = np.asarray([x for x in ics.values() if np.isfinite(x)])
    if not len(v):
        return math.nan, math.nan
    t = (
        v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))
        if len(v) > 1 and v.std(ddof=1)
        else math.nan
    )
    return float(v.mean()), float(t)


# A payload number (None for NaN) as a float.
def f(x):
    return math.nan if x is None else float(x)


# Two numbers agree: both NaN, or within the tolerance.
def same(a, b):
    a, b = f(a), f(b)
    return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= TOLERANCE


# Read the table and the payload, recompute, compare.
def main():  # noqa: C901 - one pass over the payload's lines
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--tables", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--min-names", type=int, default=15)
    args = parser.parse_args()
    payload = json.loads(args.payload.read_text())
    store = MarketStore(args.root)
    panel, sides = book_panel(store)
    tickers = list(panel.tickers)
    in_book = np.array([t in sides for t in tickers])
    excluded = np.zeros(len(tickers), dtype=bool)
    excluded[tickers.index(panel.benchmark)] = True
    failures = 0

    # The row table: every row known strictly after its filing date.
    rows = pq.read_table(args.tables / "insider_rows.parquet").to_pydict()
    late = sum(
        1
        for i in range(len(rows["ticker"]))
        if date.fromisoformat(rows["known_session"][i][:10])
        <= date.fromisoformat(rows["filed"][i])
    )
    print(
        f"{'OK' if late == 0 else 'MISMATCH'} rows known after their filing: "
        f"{len(rows['ticker'])} rows, {late} known on or before"
    )
    failures += late > 0
    signed = sum(
        1
        for i in range(len(rows["ticker"]))
        if (rows["code"][i] == "P") != (float(rows["dollars"][i]) > 0)
    )
    print(f"{'OK' if signed == 0 else 'MISMATCH'} sign of dollars follows the code")
    failures += signed > 0

    # The arms, recomputed; the desk from the repository.
    arms = {
        ARM_OPP: percentile(signal_of(panel, rows, lambda i: rows["opportunistic"][i])),
        ARM_ALL: percentile(signal_of(panel, rows, lambda i: True)),
    }
    report = desk.run(store, None, inputs=())
    arms[ARM_DESK] = percentile(np.asarray(report.scores, dtype=float))

    # The null: an empty table gives no defined IC.
    null = percentile(
        np.where(in_book[None, :], signal_of(panel, rows, lambda i: False), np.nan)
    )
    residual20 = panel.forward_residual(20)
    null_defined = sum(
        1
        for v in period_ics(null, residual20, excluded, 20, args.min_names).values()
        if np.isfinite(v)
    )
    print(
        f"{'OK' if null_defined == 0 else 'MISMATCH'} null: {null_defined} defined ICs"
    )
    failures += null_defined > 0

    stamps = panel.dates.astype("datetime64[D]")
    for horizon, windows in payload["horizons"].items():
        residual = panel.forward_residual(int(horizon))
        for name, window in windows.items():
            start, end = payload["windows"][name]
            inside = stamps >= np.datetime64(start)
            if end:
                inside &= stamps <= np.datetime64(end)
            cells = inside[:, None] & in_book[None, :]
            for arm in arms.values():
                cells &= np.isfinite(arm)
            ok_cells = int(cells.sum()) == int(window["cells"])
            print(
                f"{'OK' if ok_cells else 'MISMATCH'} h{horizon} {name} cells "
                f"{int(cells.sum())} vs {window['cells']}"
            )
            failures += not ok_cells
            for arm, scores in arms.items():
                masked = np.where(cells, scores, np.nan)
                ics = period_ics(
                    masked, residual, excluded, int(horizon), args.min_names
                )
                mine = {str(panel.dates[t]): v for t, v in ics.items()}
                theirs = window["arms"][arm]["period_ics"]
                agree = list(mine) == list(theirs) and all(
                    same(mine[k], theirs[k]) for k in mine
                )
                mean, t = summary(ics)
                ok = (
                    agree
                    and same(mean, window["arms"][arm]["ic"])
                    and same(t, window["arms"][arm]["t"])
                )
                print(
                    f"{'OK' if ok else 'MISMATCH'} h{horizon} {name} {arm}: "
                    f"IC {mean:+.4f} (t {t:+.2f}) vs payload "
                    f"{f(window['arms'][arm]['ic']):+.4f} "
                    f"(t {f(window['arms'][arm]['t']):+.2f}), {len(ics)} periods"
                )
                failures += not ok
    print("ALL OK" if not failures else f"{failures} MISMATCH")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
