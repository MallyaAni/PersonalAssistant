"""Print stage 3's post-hoc A/A+ book diagnostics and write them as JSON.

    python -m backend.cli.market_stage3_diagnostics \\
        --data data/market/research/stage3/stage3_s1.npz \\
        --forecast lgbm=out/s1_lgbm.npz --forecast seq=out/s1_seq.npz \\
        --reference seq --features d_ret20,d_mom12_1 --min-names 3 4 5 \\
        --out docs/research/scorecards/stage3/book_diagnostics.json

Not a registered test (`backend/market/stage3_diagnostics.py` says what it
reads and why it exists). Per forecast and minimum book size it prints the
IC across every graded name and inside the A/A+ book, and the lowest- and
highest-forecast book name's 20-session return against the book mean; per
feature, the same spread for dropping the book's lowest or highest name
by that feature, on the reference forecast's book.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from backend.market import stage3_diagnostics as diag
from backend.market import stage3_io as io


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True, help="the T-S1 export (stage3_s1.npz)")
    parser.add_argument(
        "--forecast", action="append", default=[], metavar="FAMILY=PATH", help="a T-S1 forecast file; repeatable"
    )
    parser.add_argument("--reference", default=None, help="the forecast whose book the feature rules use")
    parser.add_argument("--features", default="", help="comma-separated daily columns for the one-feature rules")
    parser.add_argument("--min-names", type=int, nargs="+", default=[io.S1_MIN_NAMES])
    parser.add_argument("--out", type=Path, default=None)
    return parser


# One summary as "mean (t)" for the first two windows.
def _pair(summary: dict[str, Any], scale: str) -> str:
    cells = []
    for name, _, _ in diag.WINDOWS:
        block = summary.get(name, {})
        mean, t = block.get("mean"), block.get("t")
        if mean is None or mean != mean:
            cells.append(f"{name} -")
        else:
            cells.append(f"{name} {mean:{scale}} (t {t:+.2f})")
    return ", ".join(cells)


# Load, diagnose per minimum book size, print, optionally write.
def run(args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """Print the diagnostics; return the exit code."""
    data = io.load_data(args.data)
    forecasts: dict[str, io.Stage3Forecast] = {}
    for item in args.forecast:
        family, sep, path = item.partition("=")
        if not sep or not family or not path:
            print(f"--forecast wants FAMILY=PATH, not {item!r}", file=out)
            return 2
        forecasts[family] = io.load_forecast(Path(path))
    features = tuple(f.strip() for f in args.features.split(",") if f.strip())
    record: dict[str, Any] = {"note": diag.NOTE, "data": str(args.data), "by_min_names": {}}
    print(diag.NOTE, file=out)
    for minimum in args.min_names:
        result = diag.diagnose(data, forecasts, features=features, reference=args.reference, min_names=minimum)
        record["by_min_names"][str(minimum)] = result
        print(f"-- book of at least {minimum} names", file=out)
        for family, block in result["forecasts"].items():
            print(
                f"{family}: IC all {_pair(block['ic_all'], '+.3f')}; IC book {_pair(block['ic_book'], '+.3f')}; "
                f"lowest {_pair(block['lowest'], '+.0f')}; highest {_pair(block['highest'], '+.0f')}",
                file=out,
            )
        for feature, block in result["rules"].items():
            if feature == "reference":
                continue
            print(
                f"  rule {feature}: drop lowest {_pair(block['drop_lowest'], '+.0f')}; "
                f"drop highest {_pair(block['drop_highest'], '+.0f')}; "
                f"correlation with {args.reference} {_pair(block['correlation_with_reference'], '+.2f')}",
                file=out,
            )
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(io.clean_json(record), indent=2, sort_keys=True))
        print(f"wrote {args.out}", file=out)
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
