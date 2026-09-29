"""Stage 4's decision test: the 14 registered candidates on the executor's orders.

    python -m backend.cli.market_stage4_decisions --root data/market \\
        --s1 data/market/research/stage3/stage3_s1.npz \\
        --forecast lgbm_buy=<npz> --forecast lgbm_sell=<npz> \\
        --forecast cnn_i20_buy=<npz> --forecast cnn_i20_sell=<npz> \\
        --forecast seq_buy=<npz> --forecast seq_sell=<npz> \\
        --labels data/market/research/stage4/stage4_labels.npz \\
        --offsets 20 --out data/market/research/stage4/stage4_decisions.json

`docs/research/stage4-plan-2026-09-29.md` registers the test;
`backend/market/stage4_orders.py` makes the orders and
`backend/market/stage4_decisions.py` prices and judges them. The command
runs the desk as the stage-3 overlay does (`market_profit_taking.
default_desk`), restricts it to the point-in-time book, loads the SIP cubes
(`market_session_anatomy.load_cubes`) and the EDGAR records as the stage-3
export does (strict publication), reads the VIX and the row keys from the
T-S1 export, places each model's forecast file (`--forecast
<family>_<side>=<path>`, families lgbm, cnn_i20 and seq, all optional), runs
the control executor from each of the `--offsets` start offsets
(`--max-offsets` prices fewer, a smoke run), writes the payload (`--out`)
and prints one verdict line per candidate. `--labels` adds each model's
population skill. Every input is checked before the desk runs. Nothing
here trades or changes the executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.market import stage3_export, universe
from backend.market import stage3_io as io
from backend.market import stage4_decisions as sd
from backend.market import stage4_orders as so
from backend.market.store import MarketStore

FILE = "research/stage4/stage4_decisions.json"
# The families a forecast key may name, one per model decider.
FAMILIES = tuple(sd.MODEL_FAMILIES.values())


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default="data/market", help="market store root")
    parser.add_argument(
        "--s1", type=Path, required=True, help="the stage-3 T-S1 export (npz)"
    )
    parser.add_argument(
        "--membership",
        type=Path,
        default=universe.MEMBERSHIP_HISTORY_PATH,
        help="dated membership history CSV for the point-in-time book",
    )
    parser.add_argument(
        "--forecast",
        action="append",
        default=[],
        metavar="FAMILY_SIDE=PATH",
        help="a model's forecast, e.g. lgbm_buy=<npz>; families lgbm, cnn_i20, seq",
    )
    parser.add_argument(
        "--labels", type=Path, default=None, help="stage-4 labels (population skill)"
    )
    parser.add_argument(
        "--offsets", type=int, default=sd.OFFSETS, help="the registered offsets"
    )
    parser.add_argument(
        "--max-offsets", type=int, default=None, help="price only this many (smoke)"
    )
    parser.add_argument(
        "--cost", type=float, default=so.COST_BPS, help="the control run's cost, bp"
    )
    parser.add_argument(
        "--basis", choices=so.BASES, default=so.EXECUTED, help="which change counts"
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--out", type=Path, default=None, help=f"the payload (default <root>/{FILE})"
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    return parser


# A file's sha256, read in chunks.
def _sha256(path: Path) -> str:
    """Return the hex sha256 of the file at `path`."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# The code revision the run used: the git commit, and whether anything
# under backend/ - a tracked change or an untracked file, such as a module
# not yet committed - differs from it; None where git cannot say.
def revision() -> dict[str, Any] | None:
    """Return {"commit", "dirty"} of the checkout, None when unavailable."""
    root = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if head.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "backend"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return {
        "commit": head.stdout.strip(),
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


# Split "family_side=path" into ((family, side), path), refusing an unknown
# family or side.
def parse_forecast(text: str) -> tuple[tuple[str, str], Path]:
    """Return ((family, side), path) of one --forecast argument."""
    key, sep, path = text.partition("=")
    family, _, side = key.rpartition("_")
    if not sep or not path or family not in FAMILIES or side not in sd.SIDES:
        raise ValueError(
            f"--forecast {text!r}: expected <family>_<side>=<path>, family one of "
            f"{', '.join(FAMILIES)}, side buy or sell"
        )
    return (family, side), Path(path)


# The desk report, the cubes of the panel's names and the EDGAR records, as
# the stage-3 overlay and export load them. Tests pass their own loader.
def load_inputs(
    store: MarketStore, workers: int, log: Callable[[str], None]
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Return (report, {ticker: cube}, {ticker: EDGAR record})."""
    from backend.cli.market_profit_taking import default_desk
    from backend.cli.market_session_anatomy import load_cubes

    began = time.perf_counter()
    report = default_desk(store)
    panel = report.panel
    log(f"desk: {len(panel.dates)} sessions x {len(panel.tickers)} names")
    names = tuple(t for t in panel.tickers if t != panel.benchmark)
    cubes, _ = load_cubes(store, names, workers=workers)
    log(f"cubes: {len(cubes)} of {len(names)} names")
    records = stage3_export._edgar_records(store, panel, None)
    log(f"edgar: {len(records)} names ({time.perf_counter() - began:.0f} s)")
    return report, cubes, records


@dataclass
class Checked:
    """The file inputs, read and checked before the desk runs."""

    data: io.Stage3Data  # the T-S1 export
    keys: tuple[np.ndarray, np.ndarray]  # its row dates and tickers
    forecasts: dict[tuple[str, str], io.Stage3Forecast]
    identities: dict[tuple[str, str], dict[str, Any]]
    labels: dict[str, Any] | None  # {"buy", "sell", "meta"} in the export's rows


# Read the export, the forecast files and the labels, and check them: a
# T-S1 export, each file this family's and side's with exactly the export's
# rows (`stage4_decisions.check_forecast`), the labels on the export's rows.
# Raises ValueError on the first refusal.
def read_inputs(
    s1: Path, keyed: list[tuple[tuple[str, str], Path]], labels_path: Path | None
) -> Checked:
    """Return the Checked inputs."""
    data = io.load_data(s1)
    if data.kind != io.S1:
        raise ValueError(f"{s1} is a {data.kind!r} dataset; stage 4 reads the T-S1 one")
    keys = (
        np.asarray(data.dates, dtype="datetime64[D]"),
        np.asarray(data.tickers).astype(str),
    )
    forecasts: dict[tuple[str, str], io.Stage3Forecast] = {}
    identities: dict[tuple[str, str], dict[str, Any]] = {}
    for (family, side), path in keyed:
        forecast = io.load_forecast(path)
        sd.check_forecast(forecast, family, side, keys)
        forecasts[(family, side)] = forecast
        identities[(family, side)] = {
            "file": str(path),
            "sha256": _sha256(path),
            "meta": forecast.meta,
        }
    labels = None
    if labels_path is not None:
        from backend.cli import market_stage4_labels

        dates, tickers, g_buy, g_sell, meta = market_stage4_labels.load(labels_path)
        if not (np.array_equal(dates, keys[0]) and np.array_equal(tickers, keys[1])):
            raise ValueError(f"{labels_path}: the labels are not the export's rows")
        labels = {"buy": g_buy, "sell": g_sell, "meta": meta}
    return Checked(data, keys, forecasts, identities, labels)


# Each model file's population skill, from the labels and the export's
# grades, on the payload's windows.
def population(checked: Checked, payload: dict[str, Any]) -> dict[str, Any]:
    """Return {family_side: population skill}."""
    assert checked.labels is not None
    start = np.datetime64(payload["model_start"]["date"], "D").astype(object)
    spans = sd.windows(start)
    grades = np.asarray(checked.data.extra.get("grade", np.full(len(checked.data), -1)))
    return {
        f"{family}_{side}": sd.population_skill(
            forecast.yhat, checked.labels[side], grades, checked.keys[0], spans
        )
        for (family, side), forecast in checked.forecasts.items()
    }


# The run's record: the store, the code revision, the cost and basis, every
# input file with its sha256, the panel, the cubes and the EDGAR coverage.
def run_record(
    args: argparse.Namespace,
    checked: Checked,
    panel: Any,
    coverage: dict[str, Any],
    records: dict[str, Any],
    earnings: np.ndarray,
) -> dict[str, Any]:
    """Return the payload's "run" block."""
    tickers = [t for t in panel.tickers if t != panel.benchmark]
    return {
        "root": str(args.root),
        "revision": revision(),
        "cost_bps": float(args.cost),
        "basis": args.basis,
        "inputs": {
            "s1": {
                "file": str(args.s1),
                "sha256": _sha256(args.s1),
                "rows": len(checked.data),
            },
            "membership": {
                "file": str(args.membership),
                "sha256": _sha256(args.membership),
            },
            "forecasts": {
                f"{f}_{s}": {"file": i["file"], "sha256": i["sha256"]}
                for (f, s), i in checked.identities.items()
            },
        },
        "panel": {
            "sessions": len(panel.dates),
            "names": len(tickers),
            "benchmark": panel.benchmark,
        },
        "cubes": coverage,
        "edgar": {
            "names": len(records),
            "names_without_record": sorted(t for t in tickers if t not in records),
            "earnings_sessions": int(np.asarray(earnings).sum()),
        },
    }


# The files an invocation names, refusing a malformed or repeated forecast
# key: ([(key, path)], every path that must exist).
def _named_files(
    args: argparse.Namespace,
) -> tuple[list[tuple[tuple[str, str], Path]], list[Path]]:
    """Return the keyed forecast files and all paths the run reads."""
    keyed = [parse_forecast(text) for text in args.forecast]
    keys = [key for key, _ in keyed]
    if len(set(keys)) != len(keys):
        raise ValueError("--forecast names a family and side twice")
    paths = [Path(args.s1), Path(args.membership), *(path for _, path in keyed)]
    if args.labels is not None:
        paths.append(Path(args.labels))
    return keyed, paths


# Check the inputs, run the offsets, price, judge, write and print.
# `loader` replaces `load_inputs` (tests). Exit codes: 0 done, 1 a file is
# missing, 2 an input is refused - both before the desk runs.
def run(
    args: argparse.Namespace,
    out: TextIO = sys.stdout,
    loader: Callable[..., tuple[Any, dict[str, Any], dict[str, Any]]] | None = None,
) -> int:
    """Run the decision test; return the exit code."""
    began = time.perf_counter()

    # Print one timed progress line.
    def say(text: str) -> None:
        print(f"[{time.perf_counter() - began:7.0f} s] {text}", file=out, flush=True)

    try:
        keyed, paths = _named_files(args)
    except ValueError as error:
        print(str(error), file=out)
        return 2
    missing = [path for path in paths if not path.exists()]
    if missing:
        print(f"file not found: {missing[0]}", file=out)
        return 1
    if args.offsets < 1 or (args.max_offsets is not None and args.max_offsets < 1):
        print("--offsets and --max-offsets must be at least 1", file=out)
        return 2
    try:
        checked = read_inputs(args.s1, keyed, args.labels)
    except ValueError as error:
        print(str(error), file=out)
        return 2
    named = ", ".join(f"{f}_{s}" for f, s in checked.forecasts) or "none"
    say(f"export: {len(checked.data):,} T-S1 rows; forecasts: {named}")
    root = Path(args.root)
    load = loader or load_inputs
    report, cubes, records = load(MarketStore(root), args.workers, say)
    restricted, mask = point_in_time.point_in_time(report, args.membership)
    panel = restricted.panel
    earnings = stage3_export.earnings_days(panel, records)
    forecasts = {
        key: sd.place_forecast(
            forecast,
            panel.dates,
            panel.tickers,
            *key,
            checked.keys,
            checked.identities[key],
        )
        for key, forecast in checked.forecasts.items()
    }
    fills, next_bar, oracle, coverage = sd.fill_grids(panel, cubes)
    say(f"fills: {coverage['names_with_cube']} names with a cube")
    market = sd.build_market(
        panel,
        restricted.graded.grades,
        fills,
        next_bar,
        oracle,
        sd.vix_from_export(checked.data, panel.dates),
        earnings,
        forecasts,
    )
    priced = args.offsets if args.max_offsets is None else args.max_offsets
    priced = min(args.offsets, priced)
    runs = so.run_offsets(restricted, mask, priced, args.cost, args.basis, say)
    payload = sd.evaluate(runs, market, registered=args.offsets)
    if checked.labels is not None:
        payload["population_skill"] = population(checked, payload)
        payload["labels"] = {
            "file": str(args.labels),
            "sha256": _sha256(args.labels),
            "meta": checked.labels["meta"],
        }
    payload["run"] = run_record(args, checked, panel, coverage, records, earnings)
    payload["run"]["seconds"] = time.perf_counter() - began
    target = Path(args.out) if args.out is not None else root / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(io.clean_json(payload), indent=2, allow_nan=False)
    target.write_text(text, encoding="utf-8")
    print(text if args.json else render(json.loads(text)), file=out)
    print(f"wrote {target}", file=out)
    return 0


# A number to `digits` decimals with its sign, "n/a" when missing.
def _num(x: Any, digits: int = 2) -> str:
    """Return `x` signed, "n/a" for None or NaN."""
    return "n/a" if x is None or x != x else f"{float(x):+.{digits}f}"


# The payload as the lines people read: what was run, the orders, the
# drift, then the verdict and one line per candidate.
def render(payload: dict[str, Any]) -> str:
    """Return the verdict text of a payload."""
    offsets = payload["offsets"]
    control = payload["control"]
    median = payload["orders"]["median_by_window"]
    model = payload["windows"][sd.MODEL][0]
    head = (
        f"stage-4 decision test ({payload['plan']}) as of {payload['asof']}: "
        f"14 candidates on the {control['basis']} orders of {control['executor']} "
        f"against {control['fills']}; {offsets['priced']} of "
        f"{offsets['registered']} offsets, statistics at offset {offsets['median']}; "
        f"model window {model}..2023-12-29 ({payload['model_start']['source']}); "
        f"Newey-West lag {payload['hac_lag']}"
    )
    orders = "; ".join(
        f"{w} {m['orders']} ({m['buys']} buys, {m['sells']} sells)"
        for w, m in median.items()
    )
    drift = "; ".join(
        f"{w} {_num(d['mu_bp'])} bp/session over {d['name_days']} A/A+ name-days"
        for w, d in payload["drift"].items()
    )
    lines = [
        head,
        f"orders at the median offset: {orders}",
        f"drift: {drift}",
        "",
        payload["verdict"]["text"],
    ]
    lines += [f"  {line}" for line in payload["verdict"]["lines"]]
    return "\n".join(lines)


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
