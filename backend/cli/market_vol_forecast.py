"""Export the CNN's out-of-sample next-session volatility forecasts to one npz.

    python -m backend.cli.market_vol_forecast --dataset stage1_dataset.npz \
        --out vol_forecasts.npz --device cuda

Loads a dataset written by `market_deep_intraday --export` (no store, no
desk run: the desktop GPU has neither), walks the stage-1 CNN forward on
the volatility target alone with the plan's schedule (refit every 63
sessions, first fit after 500, purge 5) and writes, per (name, session t)
row, the out-of-sample forecast of the next session's log realized
variance, the trailing-20-session baseline and the realized value
(`vol_forecast.export_forecasts`). The file is the input of
`market_vol_sizing --forecasts`. Prints the fits, the timing and the
out-of-sample R² against the baseline per window. `--model ridge` runs the
linear baseline where torch is absent. Nothing here trades.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from backend.market import deep_intraday, vol_forecast
from backend.market.session_anatomy import json_ready


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the forecast export."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="dataset npz written by market_deep_intraday --export",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="where to write the forecasts npz"
    )
    parser.add_argument(
        "--device",
        choices=deep_intraday.DEVICES,
        default="auto",
        help="where the CNN trains: auto (cuda when available), cpu or cuda",
    )
    parser.add_argument(
        "--model",
        choices=deep_intraday.MODELS,
        default=vol_forecast.MODEL,
        help="the volatility head to export (the CNN; ridge runs without torch)",
    )
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    return parser


# Export and print the summary.
def run(args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """Run the export for the parsed arguments; return the exit code."""
    quiet = bool(args.json)

    # Progress lines, silenced under --json so the output stays JSON.
    def say(text: str) -> None:
        if not quiet:
            print(text, file=out)

    if not args.dataset.exists():
        print(f"dataset not found: {args.dataset}", file=out)
        return 1
    meta = vol_forecast.export_forecasts(
        args.dataset, args.out, device=args.device, model=args.model, log=say
    )
    meta = json_ready(meta)
    if quiet:
        print(json.dumps(meta, indent=2, allow_nan=False), file=out)
        return 0
    for window, r2 in meta["vol_r2"].items():
        value = "n/a" if r2["r2"] is None else f"{r2['r2']:.4f}"
        say(f"  {window}: R2 against trailing volatility {value} on {r2['n']:,} rows")
    say(f"wrote {args.out}")
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
