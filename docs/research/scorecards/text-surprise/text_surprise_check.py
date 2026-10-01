# Independent check of the text-surprise payload: recompute every arm's
# rank IC per horizon, window and group from the score tables `build`
# wrote and the harness's cells, without the study's own functions. The
# carry-forward, the percentile ranks, the leg average, the rebalance
# schedule and the Spearman correlation are all written again here from
# the rules the harness states (`backend/market/harness.py`); only the
# panel and the beta-adjusted residual are taken from the repository,
# because they are the cells the plan registered. The stored tone (arm A)
# is rebuilt from the `edgar_tone` frames by the same rules.
# Usage, from the repository root with PYTHONPATH=$PWD:
#   python docs/research/scorecards/text-surprise/text_surprise_check.py \
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

from backend.agents.trading.desk.desk import book_panel
from backend.market import language
from backend.market.store import MarketStore

FIELDS = ("tone_guidance", "tone_demand", "tone_guidance_change", "tone_pricing")
TOLERANCE = 1e-9


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


# The mean percentile rank of several legs, NaN where any leg is NaN.
def blend(*legs):
    return np.mean(np.stack([percentile(x) for x in legs]), axis=0)


# Per-release values carried from the first session on or after the
# release date to the next release of the name; NaN before the first.
def carry(dates, tickers, rows, width):
    size = len(dates)
    out = np.full((size, len(tickers), width), np.nan)
    stamps = dates.astype("datetime64[D]")
    for n, ticker in enumerate(tickers):
        items = sorted(rows.get(ticker, []), key=lambda r: r[0])
        for k, (when, values) in enumerate(items):
            start = int(np.searchsorted(stamps, np.datetime64(when), "left"))
            stop = size
            if k + 1 < len(items):
                stop = int(
                    np.searchsorted(stamps, np.datetime64(items[k + 1][0]), "left")
                )
            if start < stop:
                out[start:stop, n, :] = values
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


# Read the tables and the payload, recompute, compare.
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
    dates, tickers = panel.dates, panel.tickers
    in_book = np.array([t in sides for t in tickers])
    excluded = np.zeros(len(tickers), dtype=bool)
    excluded[panel.index(panel.benchmark)] = True

    # Arm A from the stored frames: the four ranked fields, the change
    # field as value minus the previous release's (0 on the first).
    level_rows = {}
    for ticker in tickers:
        frame = store.read_frame(language.TONE_KIND, ticker)
        if frame is None:
            continue
        records = language.records_from_frame(frame[0])
        previous = None
        items = []
        for r in records:
            change = r.guidance - previous.guidance if previous else 0.0
            values = np.array(
                [r.guidance, r.demand, change, r.pricing], dtype=np.float32
            )
            items.append((r.reaction_date, values.astype(float)))
            previous = r
        level_rows[ticker] = items
    level = carry(dates, tickers, level_rows, 4)
    arms = {"A stored tone": percentile(blend(*[level[:, :, j] for j in range(4)]))}

    # A1-1 from the table.
    tone = pq.read_table(args.tables / "tone_surprise.parquet").to_pydict()
    lv_rows, ch_rows = {}, {}
    for i in range(len(tone["ticker"])):
        when = date.fromisoformat(tone["reaction_date"][i])
        lv = np.array([tone[f"level_{n}"][i] for n in FIELDS], dtype=np.float32).astype(
            float
        )
        ch = np.array([tone[f"change_{n}"][i] for n in FIELDS], dtype=float)
        lv_rows.setdefault(tone["ticker"][i], []).append((when, lv))
        ch_rows.setdefault(tone["ticker"][i], []).append((when, ch))
    lv = carry(dates, tickers, lv_rows, 4)
    ch = carry(dates, tickers, ch_rows, 4)
    with np.errstate(invalid="ignore"):
        gated = np.where(np.isnan(ch), np.nan, np.where(np.abs(ch) >= 0.5, ch, 0.0))
    arms["A1-0 level only (null)"] = percentile(blend(*[lv[:, :, j] for j in range(4)]))
    arms["A1-1 change"] = percentile(blend(*[ch[:, :, j] for j in range(4)]))
    arms["A1-1 change_plus_level"] = percentile(
        blend(*[ch[:, :, j] for j in range(4)], *[lv[:, :, j] for j in range(4)])
    )
    arms["A1-1 change_gated"] = percentile(blend(*[gated[:, :, j] for j in range(4)]))

    # A1-3 from the table, when built.
    word_path = args.tables / "word_surprise.parquet"
    if word_path.exists():
        word = pq.read_table(word_path).to_pydict()
        w_rows = {}
        for i in range(len(word["ticker"])):
            w_rows.setdefault(word["ticker"][i], []).append(
                (
                    date.fromisoformat(word["reaction_date"][i]),
                    np.array([word["score"][i]]),
                )
            )
        arms["A1-3 word surprise"] = percentile(
            carry(dates, tickers, w_rows, 1)[:, :, 0]
        )

    bad = 0
    checked = 0
    stamps = dates.astype("datetime64[D]")
    for horizon, windows in payload["horizons"].items():
        h = int(horizon)
        residual = panel.forward_residual(h)
        for window, groups in windows.items():
            start, end = payload["windows"][window]
            inside = stamps >= np.datetime64(start)
            if end:
                inside &= stamps <= np.datetime64(end)
            for group, block in groups.items():
                names = list(block["arms"])
                missing = [n for n in names if n not in arms]
                if missing:
                    print(f"SKIP h{h} {window} {group}: no table for {missing}")
                    continue
                cells = inside[:, None] & in_book[None, :]
                for n in names:
                    cells &= np.isfinite(arms[n])
                got, want = int(cells.sum()), block["cells"]
                if got != want:
                    print(f"MISMATCH h{h} {window} {group} cells: {got} vs {want}")
                    bad += 1
                for n in names:
                    masked = np.where(cells, arms[n], np.nan)
                    ics = period_ics(masked, residual, excluded, h, args.min_names)
                    mean, t = summary(ics)
                    r = block["arms"][n]
                    ok = same(mean, r["ic"]) and same(t, r["t"])
                    ok = ok and len(ics) == r["periods"]
                    checked += 1
                    bad += 0 if ok else 1
                    print(
                        f"{'OK' if ok else 'MISMATCH'} h{h} {window} {group} {n}: "
                        f"IC {mean:+.6f} (t {t:+.3f}, {len(ics)} periods) vs payload "
                        f"{f(r['ic']):+.6f} (t {f(r['t']):+.3f}, {r['periods']})"
                    )
    # The null test, independently: the level arm from the table against A
    # from the frames, on their shared cells, every period equal to the bit.
    for h in (20, 60):
        residual = panel.forward_residual(h)
        cells = (
            in_book[None, :]
            & np.isfinite(arms["A stored tone"])
            & np.isfinite(arms["A1-0 level only (null)"])
        )
        a = period_ics(
            np.where(cells, arms["A stored tone"], np.nan),
            residual,
            excluded,
            h,
            args.min_names,
        )
        b = period_ics(
            np.where(cells, arms["A1-0 level only (null)"], np.nan),
            residual,
            excluded,
            h,
            args.min_names,
        )
        equal = list(a) == list(b) and all(
            (math.isnan(a[k]) and math.isnan(b[k])) or a[k] == b[k] for k in a
        )
        word = "OK" if equal else "MISMATCH"
        print(f"{word} null test h{h}: {len(a)} periods, bit-equal {equal}")
        bad += 0 if equal else 1
    null = payload["null_test"]["pass"]
    print(f"\n{checked} arm lines checked, {bad} mismatches; payload null test: {null}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
