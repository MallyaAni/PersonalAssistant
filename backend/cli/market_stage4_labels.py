"""Make stage 4's timing target for every T-S1 row of the stage-3 export.

    python -m backend.cli.market_stage4_labels --root data/market \\
        --s1 data/market/research/stage3/stage3_s1.npz \\
        --out data/market/research/stage4/stage4_labels.npz

`docs/research/stage4-plan-2026-09-29.md` registers the target, and
`backend/market/stage4_labels.py` defines it. The command runs the desk for
the panel, as the stage-3 export does, and loads the SIP cubes. For every
row it computes `g_buy` and `g_sell`: D0's gain over the board's
dip_or_close, in bp. It writes them in the export's row order, with the
row keys and a JSON summary beside the file. Nothing is trained, and
nothing trades.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.market import stage3_io as io
from backend.market import stage4_labels as lab
from backend.market.store import MarketStore


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="data/market")
    parser.add_argument("--s1", type=Path, required=True, help="the stage-3 T-S1 export (stage3_s1.npz)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    return parser


# A file's sha256.
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# The desk's panel and the cubes of the export's names, as the stage-3
# export loads them.
def load_inputs(store: MarketStore, tickers: tuple[str, ...], workers: int, log: Callable[[str], None]) -> tuple[Any, dict]:
    """Return (panel, {ticker: cube})."""
    from backend.cli.market_deep_intraday import default_desk
    from backend.cli.market_session_anatomy import load_cubes

    began = time.perf_counter()
    cubes, _ = load_cubes(store, tickers, workers=workers)
    log(f"cubes: {len(cubes)} ({time.perf_counter() - began:.0f} s)")
    report = default_desk(store)
    log(f"desk: {len(report.panel.dates)} sessions ({time.perf_counter() - began:.0f} s)")
    return report.panel, cubes


# Load, label, write, summarize. `loader` replaces `load_inputs` (tests).
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., tuple[Any, dict]] | None = None,
) -> int:
    """Write the labels; return the exit code."""
    began = time.perf_counter()

    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    data = io.load_data(args.s1)
    tickers = tuple(sorted({str(t) for t in data.tickers}))
    panel, cubes = (loader or load_inputs)(MarketStore(Path(args.root)), tickers, args.workers, say)
    labels = lab.label_rows(data, panel, cubes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    meta = {**labels.meta, "s1": str(args.s1), "s1_sha256": _sha256(args.s1)}
    with args.out.open("wb") as handle:
        np.savez(
            handle,
            dates=np.asarray(data.dates, dtype="datetime64[D]"),
            tickers=np.asarray(data.tickers, dtype=str),
            g_buy=labels.g_buy.astype(np.float32),
            g_sell=labels.g_sell.astype(np.float32),
            meta=np.asarray(json.dumps(io.clean_json(meta), sort_keys=True)),
        )
    summary = {
        **io.clean_json(meta),
        "file": str(args.out),
        "sha256": _sha256(args.out),
        "quantiles_bp": {
            side: [float(np.nanquantile(v, q)) for q in (0.01, 0.1, 0.5, 0.9, 0.99)]
            for side, v in (("buy", labels.g_buy), ("sell", labels.g_sell))
        },
        "mean_bp": {side: float(np.nanmean(v)) for side, v in (("buy", labels.g_buy), ("sell", labels.g_sell))},
        "positive_share": {
            side: float(np.nanmean(v[np.isfinite(v)] > 0)) for side, v in (("buy", labels.g_buy), ("sell", labels.g_sell))
        },
    }
    args.out.with_suffix(".json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    say(f"labels: {meta['priced']} priced of {len(data):,} rows; level reached {meta['level_reached_share']} -> {args.out}")
    return 0


# Read the labels a run wrote: (dates, tickers, g_buy, g_sell, meta).
def load(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    """Return the arrays and meta of a labels file."""
    with np.load(Path(path), allow_pickle=False) as npz:
        return (
            npz["dates"].astype("datetime64[D]"),
            npz["tickers"].astype(str),
            npz["g_buy"].astype(np.float64),
            npz["g_sell"].astype(np.float64),
            json.loads(str(npz["meta"])),
        )


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
