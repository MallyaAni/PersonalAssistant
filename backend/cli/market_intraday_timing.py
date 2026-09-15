"""Two registered intraday timing studies on the 15-minute store.

    python -m backend.cli.market_intraday_timing --session-timing --report OUT.json
    python -m backend.cli.market_intraday_timing --reversal-entry --report OUT.json

Registered in docs/research/intraday-timing-2026-09-15.md before the run.
Research only; nothing here trades or changes a decision.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path

import numpy as np

from backend.market import intraday, reversal
from backend.market.calendar import fomc_decisions
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import book_sides, build_universe

SINCE = date(2021, 1, 4)
GAP = 0.02
FLUSH = -0.02
SLOTS = {"close_15m": 0, "close_30m": 1, "close_60m": 3, "close_day": 25}
EMA_SPAN = 9
SEED_SESSIONS = 3
LAST_ENTRY_SLOT = 24  # 15:30 bar's close; the 15:45 bar is the session's last


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default="data/market")
    parser.add_argument("--session-timing", action="store_true")
    parser.add_argument("--reversal-entry", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    return parser


def _stats(values) -> dict:
    x = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    n = len(x)
    if n < 2:
        return {"n": n, "mean": float(x.mean()) if n else None, "t": None}
    sd = float(x.std(ddof=1))
    return {
        "n": n,
        "mean": float(x.mean()),
        "median": float(np.median(x)),
        "t": float(x.mean() / (sd / math.sqrt(n))) if sd > 0 else None,
        "share_positive": float((x > 0).mean()),
    }


# One name's clean sessions with the official open and raw close of the day
# and the prior close from the daily panel, aligned by date.
def _name_sessions(part: Path, panel, ticker: str):
    if ticker not in panel.tickers or not (part / f"{ticker}.parquet").exists():
        return None
    ep = intraday.episodes(part, ticker)
    if ep is None:
        return None
    days, close, high, low, volume, open0, _prev = ep
    j = panel.index(ticker)
    dates = panel.dates.astype("datetime64[D]")
    row = {str(d): i for i, d in enumerate(dates)}
    keep, open_raw, close_raw, prev_raw = [], [], [], []
    for i, d in enumerate(days.astype("datetime64[D]")):
        t = row.get(str(d))
        if t is None or t == 0:
            continue
        o, c, p = panel.open[t, j], panel.close[t, j], panel.close[t - 1, j]
        if (
            not (np.isfinite(o) and np.isfinite(c) and np.isfinite(p))
            or min(o, c, p) <= 0
        ):
            continue
        if d.astype(object) < SINCE:
            continue
        keep.append(i)
        open_raw.append(o)
        close_raw.append(c)
        prev_raw.append(p)
    if not keep:
        return None
    k = np.array(keep)
    return {
        "days": days[k],
        "close": close[k],
        "low": low[k],
        "volume": volume[k],
        "open_raw": np.array(open_raw),
        "close_raw": np.array(close_raw),
        "prev_raw": np.array(prev_raw),
    }


# Study 1: log distance from the official open to each intraday reference,
# built as ln(ref/close_iex) + ln(close_raw/open_raw) so IEX only supplies
# the within-session ratio and the daily store the open and close.
def session_timing(part: Path, panel, members: set[str]) -> dict:  # noqa: C901
    """Return per-session cross-sectional means by condition, with statistics."""
    per_session: dict[str, dict[str, list[float]]] = {}
    gaps: dict[str, dict[str, list[float]]] = {}
    for ticker in sorted(members):
        s = _name_sessions(part, panel, ticker)
        if s is None:
            continue
        iex_close = s["close"][:, 25]
        day_move = np.log(s["close_raw"] / s["open_raw"])
        gap = np.log(s["open_raw"] / s["prev_raw"])
        with np.errstate(all="ignore"):
            vol = s["volume"][:, :2]
            vwap30 = (s["close"][:, :2] * vol).sum(axis=1) / vol.sum(axis=1)
        refs = {
            name: np.log(s["close"][:, slot] / iex_close) + day_move
            for name, slot in SLOTS.items()
        }
        refs["vwap_30m"] = np.log(vwap30 / iex_close) + day_move
        flush = refs["close_15m"] <= FLUSH
        for i, d in enumerate(s["days"]):
            key = str(d.astype("datetime64[D]"))
            bucket = per_session.setdefault(key, {})
            gaps.setdefault(key, {"gap": [], "flush": []})
            gaps[key]["gap"].append(float(gap[i]))
            gaps[key]["flush"].append(bool(flush[i]))
            for name, arr in refs.items():
                if np.isfinite(arr[i]):
                    bucket.setdefault(name, []).append(float(arr[i]))
                    # Conditional cells are per name: a name's own gap and flush.
                    cond = (
                        "gap_down"
                        if gap[i] <= -GAP
                        else "gap_up" if gap[i] >= GAP else "gap_flat"
                    )
                    bucket.setdefault(f"{name}|{cond}", []).append(float(arr[i]))
                    if flush[i]:
                        bucket.setdefault(f"{name}|flush", []).append(float(arr[i]))
    # Series of per-session means for every cell, then statistics on the series.
    cells: dict[str, list[float]] = {}
    for key in sorted(per_session):
        for cell, values in per_session[key].items():
            cells.setdefault(cell, []).append(float(np.mean(values)))
    out = {cell: {**_stats(series), "bp": None} for cell, series in cells.items()}
    for s in out.values():
        if s["mean"] is not None:
            s["bp"] = s["mean"] * 1e4
    return {
        "sessions": len(per_session),
        "names": len({t for t in members if t in panel.tickers}),
        "cells": out,
        "reading": (
            "positive: the price rose after the open, a buyer who waited paid more; "
            "negative: the open was the worst print and waiting helped; sells mirror"
        ),
    }


# The EMA of a bar series with the registered span.
def _ema(x: np.ndarray, span: int = EMA_SPAN) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


# The first slot on the entry day where the aggregated close crosses above
# its EMA, or None; `block` is the aggregation in 15-minute bars.
def _confirm_ema(
    seed_closes: np.ndarray, day_closes: np.ndarray, block: int
) -> int | None:
    seed = seed_closes[block - 1 :: block] if block > 1 else seed_closes
    ends = list(range(block - 1, 26, block))
    if ends[-1] != 25:
        ends.append(25)
    series = np.concatenate((seed, day_closes[ends]))
    ema = _ema(series)
    offset = len(seed)
    for k, slot in enumerate(ends):
        if slot > LAST_ENTRY_SLOT:
            break
        if day_closes[slot] > ema[offset + k]:
            return slot
    return None


def _confirm_prior_low(prior_low: float, day_closes: np.ndarray) -> int | None:
    for slot in range(LAST_ENTRY_SLOT + 1):
        if day_closes[slot] > prior_low:
            return slot
    return None


# Study 2: the registered reversal episodes with five entries on the session
# after the signal, exits unchanged, each variant paired against the open.
def reversal_entry(part: Path, panel, members: set[str]) -> dict:  # noqa: C901
    """Return per-variant paired differences against the open entry."""
    sessions = {
        t: _name_sessions(part, panel, t) for t in sorted(members | {panel.benchmark})
    }
    sessions = {t: s for t, s in sessions.items() if s is not None}
    dates = [str(d) for d in panel.dates.astype("datetime64[D]")]
    variants = ("open", "ema_15m", "ema_30m", "ema_60m", "prior_low_15m")
    results = {}
    for label, rows in (
        ("any_day", reversal.backtest_any_day(panel, members)["episodes"]),
        ("meetings", reversal.backtest(panel, fomc_decisions(), members)["meetings"]),
    ):
        per_variant: dict[str, list[float]] = {v: [] for v in variants}
        confirmed_share: dict[str, list[float]] = {v: [] for v in variants}
        for row in rows:
            e, x = dates.index(row["entry"]), dates.index(row["exit"])
            beta = row["beta"]
            spy_j = panel.index(panel.benchmark)
            spy_open = reversal.adjusted_open(panel)[e, spy_j]
            spy_ret = panel.adj_close[x, spy_j] / spy_open - 1
            basket: dict[str, list[float]] = {v: [] for v in variants}
            for name in row["names"]:
                s = sessions.get(name)
                j = panel.index(name)
                adj_exit = panel.adj_close[x, j]
                adj_entry_day = panel.adj_close[e, j]
                opens = reversal.adjusted_open(panel)
                if not np.isfinite(opens[e, j]) or opens[e, j] <= 0:
                    continue
                basket["open"].append(adj_exit / opens[e, j] - 1)
                idx = None
                if s is not None:
                    match = np.flatnonzero(
                        s["days"].astype("datetime64[D]") == np.datetime64(row["entry"])
                    )
                    idx = int(match[0]) if len(match) else None
                if idx is None or idx < SEED_SESSIONS:
                    for v in variants[1:]:
                        basket[v].append(0.0)
                        confirmed_share[v].append(0.0)
                    continue
                day = s["close"][idx]
                seed = s["close"][idx - SEED_SESSIONS : idx].ravel()
                iex_close = day[25]
                prior_low = float(np.nanmin(s["low"][idx - 1]))
                slots = {
                    "ema_15m": _confirm_ema(seed, day, 1),
                    "ema_30m": _confirm_ema(seed, day, 2),
                    "ema_60m": _confirm_ema(seed, day, 4),
                    "prior_low_15m": _confirm_prior_low(prior_low, day),
                }
                for v, slot in slots.items():
                    if slot is None:
                        basket[v].append(0.0)
                        confirmed_share[v].append(0.0)
                        continue
                    entry_adj = adj_entry_day * (day[slot] / iex_close)
                    basket[v].append(adj_exit / entry_adj - 1)
                    confirmed_share[v].append(1.0)
            if len(basket["open"]) < reversal.MIN_NAMES:
                continue
            for v in variants:
                raw = float(np.mean(basket[v]))
                per_variant[v].append(raw - beta * spy_ret - 2 * 30 / 1e4)
        base = np.array(per_variant["open"])
        results[label] = {
            "episodes": len(base),
            "open": _stats(base),
            "variants": {
                v: {
                    **_stats(per_variant[v]),
                    "paired_vs_open": _stats(np.array(per_variant[v]) - base),
                    "confirmed_share": (
                        float(np.mean(confirmed_share[v]))
                        if confirmed_share[v]
                        else None
                    ),
                }
                for v in variants[1:]
            },
        }
    return results


def main() -> None:
    """Run the requested study."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.data_dir))
    members = set(book_sides(build_universe()))
    panel = build_panel(store, sorted(members), "SPY", {})
    part = intraday.partition(Path(args.data_dir) / "bars_15m")
    out = {}
    if args.session_timing:
        out["session_timing"] = session_timing(part, panel, members)
        cells = out["session_timing"]["cells"]
        print(f"study 1: {out['session_timing']['sessions']} sessions")
        for cell in sorted(cells):
            s = cells[cell]
            if s["mean"] is None:
                continue
            t = f"{s['t']:+.2f}" if s["t"] is not None else "—"
            print(f"  {cell:26} n={s['n']:5} mean {s['bp']:+7.1f} bp  t {t}")
    if args.reversal_entry:
        out["reversal_entry"] = reversal_entry(part, panel, members)
        for label, r in out["reversal_entry"].items():
            print(
                f"study 2 [{label}]: {r['episodes']} episodes; open entry mean "
                f"{100 * r['open']['mean']:+.2f}% t {r['open']['t']:+.2f}"
            )
            for v, s in r["variants"].items():
                p = s["paired_vs_open"]
                print(
                    f"  {v:14} mean {100 * s['mean']:+.2f}%  "
                    f"paired vs open {100 * p['mean']:+.2f}% "
                    f"t {p['t']:+.2f}  confirmed {100 * s['confirmed_share']:.0f}%"
                )
    if args.report:
        args.report.write_text(json.dumps(out, indent=1), encoding="utf-8")
        print("report written:", args.report)


if __name__ == "__main__":
    main()
