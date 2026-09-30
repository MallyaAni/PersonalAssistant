"""Kronos forecasts for the book's cells, on the RTX: K1 (daily) and K2 (intraday).

    python backend/research/kronos_forecast.py --arm k1 --data E:/.../kronos/export \\
        --out E:/.../kronos/forecasts --kronos E:/AgentWorkspace/Kronos \\
        --hf E:/AgentWorkspace/rtx-data/kronos/hf --device cuda --batch 256
    python backend/research/kronos_forecast.py --arm k2 ...

Standalone: numpy, pandas, torch and the Kronos repository (`--kronos`, on
`sys.path` for `from model import Kronos, KronosTokenizer, KronosPredictor`);
nothing from `backend/` is imported, so the file runs on a machine without
the repository's dependencies. The windowing is pure and is tested in
`backend/tests/test_kronos_forecast.py`.

Registered in `docs/research/kronos-plan-2026-09-30.md` (Addendum 1 fixes
the sampling defaults, Addendum 2 the build choices below).

**K1.** For every cell (session t, name): the context is the last
`DAILY_CONTEXT` (512) adjusted daily bars through t (a cell with fewer is
not forecast and is counted); the horizon is `DAILY_HORIZON` (20)
sessions, timestamped by the panel's next sessions (business days past the
panel's end). Written per cell: the predicted 20 closes, `k1_logret_20` =
ln(predicted close 20 / close t) and `k1_mdd` = the predicted path's
maximum drawdown in log terms from close t (<= 0).

**K2.** The context is the last `INTRADAY_CONTEXT` (512) 15-minute bars
through the end of session t (the 26 regular bars a session, adjusted
basis); the horizon is the 26 bars of t+1, timestamped at t+1's slot
times (the cells table's `next_date`; the next business day past the
panel's end). Written per cell: the predicted open (bar 0's open), the
session low (min of the 26 lows), high (max of the highs), close (bar
25's close), each bar's low, high and close, and the ratios to the
predicted open and to close t.

**The model call.** `KronosPredictor.generate(x, x_stamp, y_stamp,
pred_len, T, top_k, top_p, sample_count, verbose)` on a batch normalised
exactly as `KronosPredictor.predict_batch` normalises each series (mean
and std over the context per column, clip at 5), the amount column
volume x mean(OHLC) as `predict_batch` builds it, the time stamps
`calc_time_stamps` (minute, hour, weekday, day, month); the predictions
are de-normalised per series. `max_context` 512, `clip` 5; sampling
T=1.0, top_k=0, top_p=0.9, sample_count=1 (the README's `predict`
example); `torch.manual_seed` per (name, batch) from `--seed`.

**Checkpointing.** One parquet per name under `<out>/<arm>/`; a name whose
file exists is skipped, so a restart resumes. Throughput (cells a second)
is logged per name and in `<out>/<arm>/_run.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DAILY_CONTEXT = 512
INTRADAY_CONTEXT = 512
DAILY_HORIZON = 20
SLOTS = 26
INTRADAY_HORIZON = SLOTS
SLOT_MINUTES = 9 * 60 + 30 + 15 * np.arange(SLOTS)
PRICE_COLS = ["open", "high", "low", "close"]
FEATURE_COLS = PRICE_COLS + ["volume", "amount"]
# The README's `predict` defaults (Addendum 1).
SAMPLING = {"T": 1.0, "top_k": 0, "top_p": 0.9, "sample_count": 1}
MAX_CONTEXT = 512
CLIP = 5
ARMS = ("k1", "k2")


# --- windowing (pure) ---------------------------------------------------------


# Timestamps of the next `n` sessions after position `p` in `sessions`,
# business days past the end.
def next_sessions(sessions: np.ndarray, p: int, n: int) -> np.ndarray:
    """Return (n,) datetime64[D] of the sessions after `sessions[p]`."""
    sessions = np.asarray(sessions, dtype="datetime64[D]")
    have = sessions[p + 1 : p + 1 + n]
    if len(have) == n:
        return have
    last = sessions[p] if not len(have) else have[-1]
    extra = np.busday_offset(last, np.arange(1, n - len(have) + 1), roll="forward")
    return np.concatenate([have, extra])


# K1's windows for one name: the (M, 512, 5) OHLCV contexts of the cells
# whose position in the name's daily rows is at least 511, their x and y
# dates, the close at t and the cell rows kept. `daily` is the name's
# daily table sorted by date; `cell_dates` the cells' dates; `sessions`
# the panel's dates.
def daily_windows(
    daily: pd.DataFrame,
    cell_dates: np.ndarray,
    sessions: np.ndarray,
    context: int = DAILY_CONTEXT,
    horizon: int = DAILY_HORIZON,
) -> dict[str, np.ndarray]:
    """Return {"x", "x_dates", "y_dates", "close_t", "kept"}."""
    days = np.asarray(daily["date"], dtype="datetime64[D]")
    values = daily[PRICE_COLS + ["volume"]].to_numpy(dtype=np.float64)
    cell_dates = np.asarray(cell_dates, dtype="datetime64[D]")
    sessions = np.asarray(sessions, dtype="datetime64[D]")
    pos = np.searchsorted(days, cell_dates)
    found = (pos < len(days)) & (days[np.minimum(pos, len(days) - 1)] == cell_dates)
    kept = np.flatnonzero(found & (pos >= context - 1))
    p = pos[kept]
    offsets = np.arange(-context + 1, 1)
    index = p[:, None] + offsets[None, :]
    x = values[index]
    x_dates = days[index]
    spos = np.searchsorted(sessions, cell_dates[kept])
    y_dates = (
        np.stack([next_sessions(sessions, int(s), horizon) for s in spos])
        if len(kept)
        else np.zeros((0, horizon), dtype="datetime64[D]")
    )
    return {
        "x": x,
        "x_dates": x_dates,
        "y_dates": y_dates,
        "close_t": values[p, 3] if len(kept) else np.zeros(0),
        "kept": kept,
    }


# K2's windows for one name: the (M, 512, 5) contexts of the cells whose
# session t ends at least 512 bars into the name's bars, their x
# timestamps (date + slot time), y timestamps (t+1's 26 slots), the close
# at t and the cell rows kept. `bars` is the name's bars sorted by (date,
# slot); `next_dates` the cells' next session dates (NaT: the next
# business day).
def intraday_windows(
    bars: pd.DataFrame,
    cell_dates: np.ndarray,
    next_dates: np.ndarray,
    context: int = INTRADAY_CONTEXT,
) -> dict[str, np.ndarray]:
    """Return {"x", "x_stamps", "y_stamps", "close_t", "kept"}."""
    days = np.asarray(bars["date"], dtype="datetime64[D]")
    slots = np.asarray(bars["slot"], dtype=np.int64)
    values = bars[PRICE_COLS + ["volume"]].to_numpy(dtype=np.float64)
    stamps = days.astype("datetime64[m]") + SLOT_MINUTES[slots].astype("timedelta64[m]")
    cell_dates = np.asarray(cell_dates, dtype="datetime64[D]")
    next_dates = np.asarray(next_dates, dtype="datetime64[D]")
    # The last bar of each session t: the row holding slot 25 on that date.
    last_rows = np.flatnonzero(slots == SLOTS - 1)
    last_days = days[last_rows]
    pos = np.searchsorted(last_days, cell_dates)
    found = (pos < len(last_days)) & (
        last_days[np.minimum(pos, len(last_days) - 1)] == cell_dates
    )
    end = (
        np.where(found, last_rows[np.minimum(pos, max(len(last_rows) - 1, 0))], -1)
        if len(last_rows)
        else np.full(len(cell_dates), -1)
    )
    kept = np.flatnonzero(found & (end >= context - 1))
    e = end[kept]
    offsets = np.arange(-context + 1, 1)
    index = e[:, None] + offsets[None, :]
    x = values[index]
    x_stamps = stamps[index]
    nd = next_dates[kept]
    missing = np.isnat(nd)
    if missing.any():
        nd = nd.copy()
        nd[missing] = np.busday_offset(cell_dates[kept][missing], 1, roll="forward")
    y_stamps = nd[:, None].astype("datetime64[m]") + SLOT_MINUTES[None, :].astype(
        "timedelta64[m]"
    )
    return {
        "x": x,
        "x_stamps": x_stamps,
        "y_stamps": y_stamps,
        "close_t": values[e, 3] if len(kept) else np.zeros(0),
        "kept": kept,
    }


# The time features Kronos reads from timestamps (`calc_time_stamps`):
# minute, hour, weekday, day, month, as float32 (M, L, 5).
def time_features(stamps: np.ndarray) -> np.ndarray:
    """Return (M, L, 5) time stamps for (M, L) datetime64 values."""
    s = pd.DatetimeIndex(np.asarray(stamps).reshape(-1).astype("datetime64[ns]"))
    out = np.stack([s.minute, s.hour, s.weekday, s.day, s.month], axis=-1).astype(
        np.float32
    )
    return out.reshape(*np.shape(stamps), 5)


# `predict_batch`'s per-series normalisation of OHLCV contexts: the amount
# column added (volume x mean OHLC), then (x - mean) / (std + 1e-5) per
# column over the context, clipped at +-CLIP. Returns (x_norm, mean, std).
def normalise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ((M, L, 6) normalised, (M, 1, 6) mean, (M, 1, 6) std)."""
    x = np.asarray(x, dtype=np.float32)
    amount = x[..., 4:5] * x[..., :4].mean(axis=-1, keepdims=True)
    full = np.concatenate([x, amount], axis=-1)
    mean = full.mean(axis=1, keepdims=True)
    std = full.std(axis=1, keepdims=True)
    norm = np.clip((full - mean) / (std + 1e-5), -CLIP, CLIP)
    return norm.astype(np.float32), mean, std


# Predictions back on the series' scale.
def denormalise(preds: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """Return (M, H, 6) de-normalised predictions."""
    return preds * (std + 1e-5) + mean


# K1's derived features from a predicted close path and the close at t:
# the 20-session log return and the path's maximum log drawdown from t.
def k1_features(close_t: np.ndarray, path: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ((M,) log return, (M,) max drawdown <= 0)."""
    close_t = np.asarray(close_t, dtype=float)[:, None]
    path = np.asarray(path, dtype=float)
    with np.errstate(all="ignore"):
        full = np.concatenate([close_t, path], axis=1)
        logp = np.log(full)
        peak = np.maximum.accumulate(logp, axis=1)
        drawdown = (logp - peak).min(axis=1)
        logret = logp[:, -1] - logp[:, 0]
    return logret, drawdown


# K2's derived features from a predicted 26-bar session (M, 26, 4 OHLC):
# the predicted open, low, high, close and their ratios to the open and
# to close t.
def k2_features(close_t: np.ndarray, ohlc: np.ndarray) -> dict[str, np.ndarray]:
    """Return the per-cell K2 columns."""
    ohlc = np.asarray(ohlc, dtype=float)
    open_ = ohlc[:, 0, 0]
    low = ohlc[:, :, 2].min(axis=1)
    high = ohlc[:, :, 1].max(axis=1)
    close = ohlc[:, -1, 3]
    close_t = np.asarray(close_t, dtype=float)
    with np.errstate(all="ignore"):
        return {
            "pred_open": open_,
            "pred_low": low,
            "pred_high": high,
            "pred_close": close,
            "k2_low_rel_open": low / open_,
            "k2_high_rel_open": high / open_,
            "k2_close_rel_open": close / open_,
            "k2_open_rel_close_t": open_ / close_t,
            "k2_low_rel_close_t": low / close_t,
            "k2_high_rel_close_t": high / close_t,
            "k2_close_rel_close_t": close / close_t,
        }


# Batches of row indices.
def batches(n: int, size: int) -> list[np.ndarray]:
    """Return the index arrays of consecutive batches of `size`."""
    return [np.arange(lo, min(lo + size, n)) for lo in range(0, n, max(size, 1))]


# --- the model ----------------------------------------------------------------


# Load the tokenizer and the model from the local HF directories.
def load_predictor(kronos_repo: Path, hf_dir: Path, device: str):
    """Return the KronosPredictor on `device`."""
    sys.path.insert(0, str(kronos_repo))
    from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

    tokenizer = KronosTokenizer.from_pretrained(str(hf_dir / "Kronos-Tokenizer-base"))
    model = Kronos.from_pretrained(str(hf_dir / "Kronos-base"))
    predictor = KronosPredictor(
        model, tokenizer, device=device, max_context=MAX_CONTEXT, clip=CLIP
    )
    predictor.model.eval()
    predictor.tokenizer.eval()
    return predictor


# One batch through the model: normalise, generate, de-normalise; returns
# (M, H, 6) predictions on the series' scale.
def forecast_batch(
    predictor,
    x: np.ndarray,
    x_stamps: np.ndarray,
    y_stamps: np.ndarray,
    horizon: int,
    seed: int,
    autocast: bool,
) -> np.ndarray:
    """Return the de-normalised predictions of one batch."""
    import torch

    norm, mean, std = normalise(x)
    torch.manual_seed(seed)
    xs = time_features(x_stamps)
    ys = time_features(y_stamps)
    if autocast and str(predictor.device).startswith("cuda"):
        with torch.autocast("cuda", dtype=torch.bfloat16):
            preds = predictor.generate(
                norm,
                xs,
                ys,
                horizon,
                SAMPLING["T"],
                SAMPLING["top_k"],
                SAMPLING["top_p"],
                SAMPLING["sample_count"],
                False,
            )
    else:
        preds = predictor.generate(
            norm,
            xs,
            ys,
            horizon,
            SAMPLING["T"],
            SAMPLING["top_k"],
            SAMPLING["top_p"],
            SAMPLING["sample_count"],
            False,
        )
    return denormalise(np.asarray(preds, dtype=np.float64), mean, std)


# --- the run --------------------------------------------------------------------


# Read a table in either format.
def read_table(data: Path, name: str) -> pd.DataFrame:
    """Return <data>/<name>.parquet (or .csv)."""
    parquet = data / f"{name}.parquet"
    if parquet.exists():
        return pd.read_parquet(parquet)
    return pd.read_csv(data / f"{name}.csv")


# K1 for one name: its windows, the batches, the output frame.
def run_k1_name(
    predictor,
    ticker: str,
    daily: pd.DataFrame,
    cells: pd.DataFrame,
    sessions: np.ndarray,
    batch: int,
    seed: int,
    autocast: bool,
) -> tuple[pd.DataFrame, int]:
    """Return (frame, cells skipped for a short context)."""
    w = daily_windows(daily, cells["date"].to_numpy(), sessions)
    kept = w["kept"]
    skipped = len(cells) - len(kept)
    if not len(kept):
        return pd.DataFrame(), skipped
    paths = np.full((len(kept), DAILY_HORIZON, 6), np.nan)
    for b, rows in enumerate(batches(len(kept), batch)):
        paths[rows] = forecast_batch(
            predictor,
            w["x"][rows],
            w["x_dates"][rows],
            w["y_dates"][rows],
            DAILY_HORIZON,
            seed * 100_003 + b,
            autocast,
        )
    closes = paths[:, :, 3]
    logret, mdd = k1_features(w["close_t"], closes)
    out = pd.DataFrame(
        {
            "ticker": ticker,
            "date": cells["date"].to_numpy()[kept],
            "close_t": w["close_t"],
            "k1_logret_20": logret,
            "k1_mdd": mdd,
        }
    )
    for k in range(DAILY_HORIZON):
        out[f"pred_close_{k + 1:02d}"] = closes[:, k]
    return out, skipped


# K2 for one name: its windows, the batches, the output frame.
def run_k2_name(
    predictor,
    ticker: str,
    bars: pd.DataFrame,
    cells: pd.DataFrame,
    batch: int,
    seed: int,
    autocast: bool,
) -> tuple[pd.DataFrame, int]:
    """Return (frame, cells skipped for a short context)."""
    w = intraday_windows(bars, cells["date"].to_numpy(), cells["next_date"].to_numpy())
    kept = w["kept"]
    skipped = len(cells) - len(kept)
    if not len(kept):
        return pd.DataFrame(), skipped
    paths = np.full((len(kept), INTRADAY_HORIZON, 6), np.nan)
    for b, rows in enumerate(batches(len(kept), batch)):
        paths[rows] = forecast_batch(
            predictor,
            w["x"][rows],
            w["x_stamps"][rows],
            w["y_stamps"][rows],
            INTRADAY_HORIZON,
            seed * 100_003 + b,
            autocast,
        )
    ohlc = paths[:, :, :4]
    out = pd.DataFrame(
        {
            "ticker": ticker,
            "date": cells["date"].to_numpy()[kept],
            "next_date": cells["next_date"].to_numpy()[kept],
            "close_t": w["close_t"],
        }
    )
    for name, values in k2_features(w["close_t"], ohlc).items():
        out[name] = values
    for k in range(INTRADAY_HORIZON):
        out[f"low_{k:02d}"] = ohlc[:, k, 2]
        out[f"high_{k:02d}"] = ohlc[:, k, 1]
        out[f"close_{k:02d}"] = ohlc[:, k, 3]
    return out, skipped


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--arm", required=True, choices=ARMS)
    parser.add_argument("--data", required=True, type=Path, help="the export directory")
    parser.add_argument(
        "--out", required=True, type=Path, help="the forecasts directory"
    )
    parser.add_argument(
        "--kronos", required=True, type=Path, help="the Kronos repository"
    )
    parser.add_argument(
        "--hf", required=True, type=Path, help="the HF checkpoints directory"
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--tickers", default="", help="comma-separated subset (smoke)")
    parser.add_argument(
        "--limit", type=int, default=0, help="at most this many cells a name (smoke)"
    )
    parser.add_argument("--no-autocast", action="store_true", help="fp32 throughout")
    return parser


# Run one arm over every name, resuming past names already written.
def main(argv: list[str] | None = None) -> int:
    """Run the forecasts; return the exit code."""
    args = build_parser().parse_args(argv)
    out_dir = args.out / args.arm
    out_dir.mkdir(parents=True, exist_ok=True)
    cells = read_table(args.data, "cells")
    cells["date"] = pd.to_datetime(cells["date"]).to_numpy().astype("datetime64[D]")
    cells["next_date"] = (
        pd.to_datetime(cells["next_date"]).to_numpy().astype("datetime64[D]")
    )
    sessions = (
        pd.to_datetime(read_table(args.data, "sessions")["date"])
        .to_numpy()
        .astype("datetime64[D]")
    )
    table = read_table(args.data, "daily" if args.arm == "k1" else "bars15")
    table["date"] = pd.to_datetime(table["date"]).to_numpy().astype("datetime64[D]")
    names = sorted(cells["ticker"].unique())
    if args.tickers:
        chosen = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        names = [n for n in names if n in chosen]
    predictor = load_predictor(args.kronos, args.hf, args.device)
    autocast = not args.no_autocast
    record: dict[str, Any] = {
        "arm": args.arm,
        "sampling": SAMPLING,
        "max_context": MAX_CONTEXT,
        "clip": CLIP,
        "seed": args.seed,
        "batch": args.batch,
        "autocast": autocast,
        "names": {},
    }
    run_path = out_dir / "_run.json"
    if run_path.exists():
        record["names"] = json.loads(run_path.read_text()).get("names", {})
    began = time.perf_counter()
    total = 0
    for i, ticker in enumerate(names):
        target = out_dir / f"{ticker}.parquet"
        if target.exists():
            print(f"{ticker}: done already", flush=True)
            continue
        own = cells[cells["ticker"] == ticker].sort_values("date")
        if args.limit:
            own = own.tail(args.limit)
        rows = table[table["ticker"] == ticker]
        started = time.perf_counter()
        if args.arm == "k1":
            frame, skipped = run_k1_name(
                predictor,
                ticker,
                rows.sort_values("date"),
                own,
                sessions,
                args.batch,
                args.seed + i,
                autocast,
            )
        else:
            frame, skipped = run_k2_name(
                predictor,
                ticker,
                rows.sort_values(["date", "slot"]),
                own,
                args.batch,
                args.seed + i,
                autocast,
            )
        seconds = time.perf_counter() - started
        frame.to_parquet(target, index=False)
        total += len(frame)
        record["names"][ticker] = {
            "cells": int(len(own)),
            "forecast": int(len(frame)),
            "skipped_short_context": int(skipped),
            "seconds": round(seconds, 1),
            "cells_per_second": round(len(frame) / seconds, 2) if seconds > 0 else None,
        }
        run_path.write_text(json.dumps(record, indent=2))
        print(
            f"{ticker}: {len(frame)} cells in {seconds:.0f} s ({len(frame) / max(seconds, 1e-9):.1f}/s), {skipped} short; {total} so far, {time.perf_counter() - began:.0f} s",
            flush=True,
        )
    record["seconds"] = round(time.perf_counter() - began, 1)
    record["cells_forecast"] = int(sum(v["forecast"] for v in record["names"].values()))
    run_path.write_text(json.dumps(record, indent=2))
    print(f"done: {record['cells_forecast']} cells", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
