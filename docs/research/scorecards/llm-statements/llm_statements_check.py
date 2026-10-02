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
#
# A2b (docs/research/llm-statements-a2b-plan-2026-10-02.md): `--variant`
# rebuilds the stance from the frames' direction and probability columns
# with its own sign rule (a2: p - 0.5; a2b: sign x |2p - 1|; a2b-direction:
# the sign), and the check also recomputes the paired difference against the
# fundamental analyst, the correlations, the three criteria and the verdict
# at 20 sessions. Names are counted as the payload counts them: every name
# with a frame, empty or not (A2's recorded 86-vs-91 line).
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
# The arm's payload name per variant, and the plan's floors.
ARMS = {
    "a2": "A2 statement reader",
    "a2b": "A2b direction-signed reader",
    "a2b-direction": "A2b-dir stated direction",
}
IC_FLOOR, T_FLOOR, NOT_NEGATIVE_T, LOW_CORRELATION = 0.02, 2.0, -1.0, 0.3


# One answer's stance under a variant, from the rule in the A2b plan.
def stance_of(direction, probability, variant):
    if variant == "a2":
        return probability - 0.5
    sign = {"up": 1.0, "down": -1.0}[direction]
    if variant == "a2b":
        return sign * abs(2.0 * probability - 1.0)
    return sign


# Mean and t of per-period differences b - a on periods both define.
def paired_diff(a, b):
    keys = [k for k in a if k in b and np.isfinite(a[k]) and np.isfinite(b[k])]
    d = np.asarray([b[k] - a[k] for k in keys])
    if len(d) < 2 or not d.std(ddof=1):
        return (float(d.mean()) if len(d) else math.nan), math.nan
    return float(d.mean()), float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


# Mean per-session Spearman of two score matrices over cells, >= min names.
def mean_corr(a, b, cells, min_names):
    both = cells & np.isfinite(a) & np.isfinite(b)
    values = []
    for t in range(a.shape[0]):
        cols = np.flatnonzero(both[t])
        if len(cols) >= min_names:
            rho = spearman(a[t, cols], b[t, cols])
            if np.isfinite(rho):
                values.append(rho)
    return float(np.mean(values)) if values else math.nan


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
    parser.add_argument("--variant", choices=tuple(ARMS), default="a2")
    args = parser.parse_args()
    arm_key = ARMS[args.variant]
    payload = json.loads(args.payload.read_text())
    store = MarketStore(args.root)
    panel, sides = book_panel(store)
    dates, tickers = panel.dates, panel.tickers
    in_book = np.array([t in sides for t in tickers])
    excluded = np.zeros(len(tickers), dtype=bool)
    excluded[panel.index(panel.benchmark)] = True

    # The arm from the stored frames under the variant's rule, carried.
    rows = {}
    records = {}
    framed = 0
    for ticker in tickers:
        frame = store.read_frame(KIND, ticker)
        if frame is None:
            continue
        framed += ticker in sides
        columns = frame[0]
        items = []
        for i in range(len(columns["quarter_end"])):
            items.append(
                (
                    date.fromisoformat(columns["available"][i]),
                    stance_of(
                        columns["direction"][i],
                        float(columns["probability"][i]),
                        args.variant,
                    ),
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
    arms = {
        arm_key: arm,
        FUNDAMENTAL: comparators[FUNDAMENTAL],
        VALUE: comparators[VALUE],
    }

    failures = 0
    ok = framed == payload["names_scored"]
    failures += not ok
    print(
        f"{'OK' if ok else 'MISMATCH'} names with a frame {framed} "
        f"({len(records)} with answers) payload {payload['names_scored']}"
    )
    mine = {}
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
                mine[(h, name, arm_name)] = (ic, t, ics, cells)
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

    # The criteria and the verdict at 20 sessions, from this check's numbers.
    ic, t, ics_arm, cells = mine[(20, "in_window", arm_key)]
    ic_post, t_post, _, _ = mine[(20, "post_window", arm_key)]
    delta, delta_t = paired_diff(mine[(20, "in_window", FUNDAMENTAL)][2], ics_arm)
    corr = {
        c: mean_corr(arms[c], arms[arm_key], cells, args.min_names)
        for c in (FUNDAMENTAL, VALUE)
    }
    c1 = bool(np.isfinite(ic) and ic >= IC_FLOOR and np.isfinite(t) and t >= T_FLOOR)
    c2 = not (
        np.isfinite(ic_post)
        and ic_post < 0
        and np.isfinite(t_post)
        and t_post <= NOT_NEGATIVE_T
    )
    c3 = not (
        np.isfinite(delta)
        and delta < 0
        and np.isfinite(delta_t)
        and delta_t <= NOT_NEGATIVE_T
    )
    low = all(np.isfinite(v) and v < LOW_CORRELATION for v in corr.values())
    crit = payload["criteria"]
    for label, a, b in (
        ("paired delta vs fundamental", delta, crit["paired_delta_vs_fundamental"]),
        ("paired t vs fundamental", delta_t, crit["paired_t_vs_fundamental"]),
        (
            "correlation with fundamental",
            corr[FUNDAMENTAL],
            crit["correlation_with"][FUNDAMENTAL],
        ),
        ("correlation with value", corr[VALUE], crit["correlation_with"][VALUE]),
    ):
        ok = same(a, b)
        failures += not ok
        print(
            f"{'OK' if ok else 'MISMATCH'} {label}: {f(a):+.4f} (payload {f(b):+.4f})"
        )
    for label, a, b in (
        ("criterion 1 IC floor", c1, crit["1_clears_ic_floor"]),
        ("criterion 2 post-cutoff", c2, crit["2_post_window_not_negative"]),
        ("criterion 3 paired", c3, crit["3_not_worse_than_fundamental"]),
        ("role sixth analyst", low, crit["role"] == "sixth analyst"),
    ):
        ok = a == b
        failures += not ok
        print(f"{'OK' if ok else 'MISMATCH'} {label}: {a} (payload {b})")
    verdict = "CANDIDATE" if (c1 and c2 and c3) else "RECORD"
    ok = payload["verdict"].split(" ")[0].rstrip(":") == verdict
    failures += not ok
    print(
        f"{'OK' if ok else 'MISMATCH'} verdict {verdict} (payload {payload['verdict']})"
    )

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
