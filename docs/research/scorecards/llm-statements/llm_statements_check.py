# Independent check of the A2 payload: recompute the statement reader's
# rank IC per horizon and window from the stored `edgar_statements` frames
# and the harness's cells, without the study's own functions. The
# carry-forward, the percentile ranks, the rebalance schedule and the
# Spearman correlation are written again here from the rules the harness
# states (`backend/market/harness.py`); only the panel, the beta-adjusted
# residual and the two comparators' ranks are taken from the repository,
# because they are the cells the plan registered. The direction accuracy
# is recounted from the blocks JSONL that `plan --blocks` wrote: the
# realised next quarter is read from the *next* observation's rendered
# table (its Q8 against its Q4), and every scored record's block digest
# must match the digest of the block in that file.
# Usage, from the repository root with PYTHONPATH=$PWD:
#   python docs/research/scorecards/llm-statements/llm_statements_check.py \
#       --root data/market --payload <evaluate json> --blocks <plan jsonl>
# Read-only; prints OK or MISMATCH per line and exits 1 on any mismatch.
import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk.desk import book_panel
from backend.market.store import MarketStore

TOLERANCE = 1e-9
KIND = "edgar_statements"
ARM = "A2 statement reader"
FUNDAMENTAL = "fundamental analyst"
VALUE = "value analyst"
POST_START = date(2025, 6, 1)


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


# Per-observation stances carried from the first session on or after the
# availability date to the next observation of the name; NaN before the first.
def carry(dates, tickers, rows):
    size = len(dates)
    out = np.full((size, len(tickers)), np.nan)
    stamps = dates.astype("datetime64[D]")
    for n, ticker in enumerate(tickers):
        items = sorted(rows.get(ticker, []), key=lambda r: r[0])
        for k, (when, value) in enumerate(items):
            start = int(np.searchsorted(stamps, np.datetime64(when), "left"))
            stop = size
            if k + 1 < len(items):
                stop = int(
                    np.searchsorted(stamps, np.datetime64(items[k + 1][0]), "left")
                )
            if start < stop:
                out[start:stop, n] = value
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


# A (T,) window mask from the payload's window bounds.
def window(dates, bounds):
    stamps = dates.astype("datetime64[D]")
    mask = stamps >= np.datetime64(bounds[0])
    if bounds[1]:
        mask &= stamps <= np.datetime64(bounds[1])
    return mask


# The eight values of one labelled row of a rendered block, None for n/a.
def row_values(block, label):
    for line in block.splitlines():
        if line.startswith(label):
            cells = line[22:].split()
            return [None if c == "n/a" else float(c.replace(",", "")) for c in cells]
    return None


# Read the frames, the payload and the blocks; recompute; compare.
def main():  # noqa: C901 - one pass over the payload's lines
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--blocks", type=Path, default=None)
    parser.add_argument("--min-names", type=int, default=15)
    args = parser.parse_args()
    payload = json.loads(args.payload.read_text())
    store = MarketStore(args.root)
    panel, sides = book_panel(store)
    dates, tickers = panel.dates, panel.tickers
    in_book = np.array([t in sides for t in tickers])
    excluded = np.zeros(len(tickers), dtype=bool)
    excluded[panel.index(panel.benchmark)] = True

    # The arm from the stored frames: probability less one half, carried.
    rows = {}
    records = {}
    for ticker in tickers:
        frame = store.read_frame(KIND, ticker)
        if frame is None:
            continue
        columns = frame[0]
        items = []
        for i in range(len(columns["quarter_end"])):
            items.append(
                (
                    date.fromisoformat(columns["available"][i]),
                    float(columns["probability"][i]) - 0.5,
                )
            )
            records.setdefault(ticker, []).append(
                {
                    "quarter_end": columns["quarter_end"][i],
                    "available": date.fromisoformat(columns["available"][i]),
                    "direction": columns["direction"][i],
                    "sha": columns["block_sha256"][i],
                    "anchor": columns["anchor"][i],
                }
            )
        rows[ticker] = items
    arm = percentile(carry(dates, tickers, rows))

    # The comparators as the desk builds them (the registered cells).
    from backend.cli.market_statements import comparator_ranks

    comparators = comparator_ranks(store, panel, sides)
    arms = {ARM: arm, FUNDAMENTAL: comparators[FUNDAMENTAL], VALUE: comparators[VALUE]}

    failures = 0
    print(f"names scored {len(records)} payload {payload['names_scored']}")
    failures += len(records) != payload["names_scored"]
    for horizon, windows in payload["horizons"].items():
        h = int(horizon)
        residual = panel.forward_residual(h)
        for name, block in windows.items():
            inside = window(dates, payload["windows"][name])[:, None] & in_book[None, :]
            cells = inside.copy()
            for scores in arms.values():
                cells &= np.isfinite(scores)
            for arm_name, scores in arms.items():
                masked = np.where(cells, scores, np.nan)
                ics = period_ics(masked, residual, excluded, h, args.min_names)
                ic, t = summary(ics)
                got = block["arms"][arm_name]
                ok = (
                    same(ic, got["ic"])
                    and same(t, got["t"])
                    and len(ics) == got["periods"]
                )
                failures += not ok
                print(
                    f"{'OK' if ok else 'MISMATCH'} h{h} {name} {arm_name}: "
                    f"IC {ic:+.4f} t {t:+.2f} periods {len(ics)} "
                    f"(payload {f(got['ic']):+.4f} {f(got['t']):+.2f} {got['periods']})"
                )
            ok = int(cells.sum()) == block["cells"]
            failures += not ok
            print(f"{'OK' if ok else 'MISMATCH'} h{h} {name} cells {int(cells.sum())}")

    # The accuracy report, recounted from the rendered blocks, and every
    # scored record's digest against the block it was scored on.
    if args.blocks is not None and args.blocks.exists():
        blocks = {}
        for line in args.blocks.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                blocks[(row["ticker"], row["quarter_end"])] = row
        n = correct = persist_n = persist_correct = 0
        post_n = post_correct = 0
        mismatched = 0
        for ticker, items in records.items():
            items.sort(key=lambda r: r["quarter_end"])
            for k, record in enumerate(items):
                block = blocks.get((ticker, record["quarter_end"]))
                if block is None:
                    mismatched += 1
                    continue
                digest = hashlib.sha256(block["block"].encode("utf-8")).hexdigest()
                if digest != record["sha"]:
                    mismatched += 1
                if k + 1 >= len(items):
                    continue
                following = blocks.get((ticker, items[k + 1]["quarter_end"]))
                if following is None:
                    continue
                gap = (
                    date.fromisoformat(items[k + 1]["quarter_end"])
                    - date.fromisoformat(record["quarter_end"])
                ).days
                if not 75 <= gap <= 105 or following["anchor"] != record["anchor"]:
                    continue
                label = "Net income" if record["anchor"] == "net_income" else "Revenue"
                nxt = row_values(following["block"], label)
                own = row_values(block["block"], label)
                if nxt is None or nxt[-1] is None or nxt[-5] is None:
                    continue
                realised = np.sign(nxt[-1] - nxt[-5])
                if realised == 0:
                    continue
                call = 1 if record["direction"] == "up" else -1
                n += 1
                correct += int(call == realised)
                if record["available"] >= POST_START:
                    post_n += 1
                    post_correct += int(call == realised)
                if own[-1] is not None and own[-5] is not None:
                    persist = np.sign(own[-1] - own[-5])
                    if persist != 0:
                        persist_n += 1
                        persist_correct += int(persist == realised)
        acc = payload["accuracy"]["windows"]
        for name, got_n, got_c, mine_n, mine_c in (
            ("all", acc["all"]["n"], acc["all"]["correct"], n, correct),
            (
                "post_window",
                acc["post_window"]["n"],
                acc["post_window"]["correct"],
                post_n,
                post_correct,
            ),
            (
                "persistence",
                acc["all"]["persistence_n"],
                acc["all"]["persistence_correct"],
                persist_n,
                persist_correct,
            ),
        ):
            ok = got_n == mine_n and got_c == mine_c
            failures += not ok
            print(
                f"{'OK' if ok else 'MISMATCH'} accuracy {name}: {mine_c}/{mine_n} "
                f"(payload {got_c}/{got_n})"
            )
        ok = mismatched == 0
        failures += not ok
        print(f"{'OK' if ok else 'MISMATCH'} block digests: {mismatched} mismatched")
    else:
        print("blocks JSONL not given: accuracy and digests not rechecked")

    # No four-digit run anywhere in a stored block (the anonymity rule).
    if args.blocks is not None and args.blocks.exists():
        leaks = sum(
            1
            for line in args.blocks.read_text().splitlines()
            if line.strip() and re.search(r"\d{4}", json.loads(line)["block"])
        )
        ok = leaks == 0
        failures += not ok
        print(
            f"{'OK' if ok else 'MISMATCH'} anonymity: {leaks} blocks with a 4-digit run"
        )

    print("ALL OK" if not failures else f"{failures} MISMATCHES")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
