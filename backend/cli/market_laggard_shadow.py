"""The forward shadow of the sequence model's A/A+ laggard.

    # once, on the training machine: the frozen model and its parity record
    python -m backend.cli.market_laggard_shadow fit --data stage3_s1.npz \\
        --seq stage3_seq.npz --out models/m3_s1.pt --device cuda
    # once, on spark1's CPU, before the first forward date
    python -m backend.cli.market_laggard_shadow parity --model models/m3_s1.pt \\
        --data stage3_s1.npz --seq stage3_seq.npz
    # each night after the SIP append
    python -m backend.cli.market_laggard_shadow nightly --root data/market \\
        --model models/m3_s1.pt --dir data/market/research/laggard_shadow

`docs/research/laggard-shadow-plan-2026-09-29.md` registers every step.
`nightly` exports the T-S1 rows and the sequence tensor into
`<dir>/export/` with the stage-3 export, then:
- forecasts every forward date the ledger lacks (`<dir>/ledger.jsonl`);
- scores every entry whose returns have matured;
- rewrites `<dir>/summary.json` and `<dir>/scores.json`.

Nothing here trades or reaches the board.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.market import laggard_shadow as shadow
from backend.market import stage3_final as final
from backend.market import stage3_io as io
from backend.market import stage3_nn as nn3

PARITY_TOLERANCE = 1e-4


# The command-line parser, one subcommand per step.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    fit = sub.add_parser("fit", help="fit and save the frozen model")
    fit.add_argument("--data", type=Path, required=True)
    fit.add_argument("--seq", type=Path, required=True)
    fit.add_argument("--out", type=Path, required=True)
    fit.add_argument("--device", default="auto")
    # Smoke runs and tests only: each makes the model's meta record
    # registered: false.
    fit.add_argument("--grid-first", type=int, default=None, help="use the registered grid's first N")
    fit.add_argument("--seeds", default=None, help="comma-separated seeds")
    fit.add_argument("--max-epochs", type=int, default=None)
    fit.add_argument("--validation", type=int, default=None)
    fit.add_argument("--gap", type=int, default=None)
    fit.add_argument("--batch", type=int, default=None)
    parity = sub.add_parser("parity", help="check a saved model reproduces its fit")
    parity.add_argument("--model", type=Path, required=True)
    parity.add_argument("--data", type=Path, required=True)
    parity.add_argument("--seq", type=Path, required=True)
    parity.add_argument("--device", default="cpu")
    nightly = sub.add_parser("nightly", help="export, forecast new dates, score, summarize")
    nightly.add_argument("--root", default="data/market")
    nightly.add_argument("--model", type=Path, required=True)
    nightly.add_argument("--dir", type=Path, required=True)
    nightly.add_argument("--workers", type=int, default=8)
    nightly.add_argument("--no-export", action="store_true", help="use <dir>/export as it is")
    nightly.add_argument("--device", default="cpu")
    return parser


# The parity record written beside a model: the validation rows and the
# fit's own forecasts for them.
def parity_path(model: Path) -> Path:
    """Return the parity file of a model file."""
    return Path(model).with_suffix(".parity.npz")


# The fit's settings: the registration, with any smoke flag applied.
def fit_settings(args: argparse.Namespace) -> nn3.Settings:
    """Return the Settings the fit runs with."""
    changes: dict[str, Any] = {"device": args.device}
    if args.grid_first is not None:
        changes["grid"] = tuple(io.SEQ_GRID[: args.grid_first])
    if args.seeds is not None:
        changes["seeds"] = tuple(int(s) for s in args.seeds.split(",") if s.strip())
    for name in ("max_epochs", "gap", "batch"):
        if getattr(args, name) is not None:
            changes[name] = getattr(args, name)
    if args.validation is not None:
        changes["validation"] = args.validation
    return nn3.Settings(**changes)


# Fit the frozen model, save it and its parity record.
def run_fit(args: argparse.Namespace, out: TextIO) -> int:
    """Fit, save and report the model id."""
    data = io.load_data(args.data)
    tensor = io.load_seq(args.seq)
    result = final.fit_final(
        data, tensor, fit_settings(args), log=lambda line: print(line, file=out, flush=True)
    )
    meta = dict(result.model.meta)
    meta["inputs_files"] = {"data": str(args.data), "data_sha256": final.sha256(args.data),
                            "seq": str(args.seq), "seq_sha256": final.sha256(args.seq)}
    model = dataclasses.replace(result.model, meta=meta)
    model_id = final.save_final(args.out, model)
    np.savez(
        parity_path(args.out),
        rows=result.validation_rows,
        forecast=result.validation_forecast,
        model_id=np.asarray(model_id),
    )
    print(f"model {model_id} -> {args.out}; chose {model.config}; parity -> {parity_path(args.out)}", file=out)
    return 0


# Reload the model twice on this machine and compare with the fit's
# forecasts (within PARITY_TOLERANCE) and with itself (exactly).
def run_parity(args: argparse.Namespace, out: TextIO) -> int:
    """Return 0 when the saved model reproduces its fit, else 1."""
    record = np.load(parity_path(args.model))
    model_id = final.sha256(args.model)
    if str(record["model_id"]) != model_id:
        print(f"parity record is for {record['model_id']}, the model is {model_id}", file=out)
        return 1
    data = io.load_data(args.data)
    tensor = io.load_seq(args.seq)
    rows = np.asarray(record["rows"], dtype=np.int64)
    first = final.predict_final(final.load_final(args.model), data, tensor, rows, device=args.device)
    second = final.predict_final(final.load_final(args.model), data, tensor, rows, device=args.device)
    expected = np.asarray(record["forecast"], dtype=float)
    gap = float(np.nanmax(np.abs(first - expected))) if len(rows) else 0.0
    same = bool(np.array_equal(first, second, equal_nan=True))
    missing = int(np.isnan(first).sum())
    ok = gap <= PARITY_TOLERANCE and same and missing == 0
    print(
        f"parity {'ok' if ok else 'FAILED'}: {len(rows):,} validation rows, largest difference "
        f"{gap:.2e} (tolerance {PARITY_TOLERANCE:.0e}), reload identical {same}, missing {missing}",
        file=out,
    )
    return 0 if ok else 1


# The stage-3 export of the T-S1 rows and the sequence tensor into `folder`.
def export(root: str, folder: Path, workers: int, out: TextIO) -> int:
    """Run the export; return its exit code."""
    from backend.cli import market_stage3_export

    args = market_stage3_export.build_parser().parse_args(
        ["--root", root, "--out-dir", str(folder), "--only", "s1,seq", "--workers", str(workers)]
    )
    return market_stage3_export.run(args, out=out)


# The book names whose own session has no complete cube, per forward date.
def own_invalid(tensor: io.SeqTensor, day: np.datetime64, tickers: list[str]) -> list[str]:
    """Return the tickers without a valid cube session on `day`."""
    sessions = np.asarray(tensor.sessions, dtype="datetime64[D]")
    names = [str(t) for t in np.asarray(tensor.tickers)]
    where = np.flatnonzero(sessions == np.datetime64(day, "D"))
    if not len(where):
        return sorted(tickers)
    s = int(where[0])
    bad = []
    for ticker in tickers:
        if ticker not in names or not bool(tensor.valid[names.index(ticker), s]):
            bad.append(ticker)
    return sorted(bad)


# Export (unless told not to), forecast the new forward dates, score and
# summarize. `exporter` replaces the stage-3 export (tests).
def run_nightly(
    args: argparse.Namespace,
    out: TextIO,
    exporter: Callable[[str, Path, int, TextIO], int] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Run one night of the shadow; return the exit code."""
    folder = Path(args.dir)
    export_dir = folder / "export"
    if not args.no_export:
        code = (exporter or export)(args.root, export_dir, args.workers, out)
        if code != 0:
            print(f"export failed ({code}); nothing forecast", file=out)
            return code
    data_path = export_dir / "stage3_s1.npz"
    seq_path = export_dir / "stage3_seq.npz"
    data = io.load_data(data_path)
    tensor = io.load_seq(seq_path)
    model_id = final.sha256(args.model)
    model = final.load_final(args.model)
    ledger_path = folder / "ledger.jsonl"
    ledger = shadow.read_ledger(ledger_path)
    known = {e["date"] for e in ledger}
    after = str(model.meta.get("fold", {}).get("last_session") or shadow.TRAINED_THROUGH)
    cube_days = set(np.asarray(tensor.sessions, dtype="datetime64[D]").tolist())
    forward = [d for d in shadow.forward_dates(data.dates, after) if str(d) not in known]
    todo = [d for d in forward if d.astype(object) in cube_days]
    waiting = [str(d) for d in forward if d.astype(object) not in cube_days]
    export_sha = final.sha256(data_path)
    made_at = now().isoformat(timespec="seconds")
    entries: list[dict[str, Any]] = []
    if todo:
        rows = np.concatenate([shadow.date_rows(data.dates, d) for d in todo])
        yhat = np.full(len(data), np.nan)
        yhat[rows] = final.predict_final(model, data, tensor, rows, device=args.device)
        for d in todo:
            e = shadow.entry(data, yhat, d, model_id=model_id, export_sha256=export_sha, made_at=made_at)
            e["unclean"] = own_invalid(tensor, d, [b["ticker"] for b in e["book"]])
            entries.append(e)
        shadow.append(ledger_path, entries)
    if waiting:
        print(f"waiting for cubes: {', '.join(waiting)} (not forecast tonight)", file=out)
    ledger = shadow.read_ledger(ledger_path)
    returns = shadow.r_lookup(data)
    scores = [s for e in ledger if (s := shadow.score(e, returns)) is not None]
    summary = shadow.summarize(scores, entries=len(ledger))
    summary["as_of"] = made_at
    summary["export_sha256"] = export_sha
    summary["model_id"] = model_id
    (folder / "summary.json").write_text(json.dumps(io.clean_json(summary), indent=2, sort_keys=True))
    (folder / "scores.json").write_text(json.dumps(io.clean_json(scores), indent=2, sort_keys=True))
    for e in entries:
        names = ", ".join(f"{b['ticker']} {b['forecast']:+.3f}" for b in e["book"])
        flag = f" unclean {e['unclean']}" if e["unclean"] else ""
        print(f"{e['date']}: laggard {e['laggard']} of {e['n']} [{names}]{flag}", file=out)
    primary = summary["primary"]
    print(
        f"ledger {len(ledger)} dates, {len(scores)} scored; primary {primary['n']} dates, "
        f"mean spread {primary['mean']:+.0f} bp (t {primary['t']:+.2f}); verdict {summary['verdict']['label']}",
        file=out,
    )
    return 0


# Dispatch the subcommand.
def run(args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """Run the chosen step; return its exit code."""
    if args.command == "fit":
        return run_fit(args, out)
    if args.command == "parity":
        return run_parity(args, out)
    return run_nightly(args, out)


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
