"""Run the fixed entry/exit timing diagnostic on existing immutable caches."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import policy_v5, simulate
from backend.market import entry_exit_study as study
from backend.market import fill_timing, open_source_portfolio
from backend.market.open_source_portfolio import load_snapshot


# Read explicit frozen inputs and write a new costed result without live side effects.
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--cubes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.resolve() in (
        args.snapshot.resolve(),
        args.provenance.resolve(),
    ):
        parser.error("output must be new; inputs and earlier results are immutable")
    panel, grades, eligible, provenance = load_snapshot(args.snapshot, args.provenance)
    cubes, hashes = study.read_cubes(args.cubes, panel.tickers)
    print(f"Read {len(cubes)} frozen cubes; evaluating fixed A2/B2 rules", flush=True)
    result = study.backtest(panel, grades, eligible, provenance, cubes)
    result["cube_sha256"] = hashes
    result["cube_exclusions"] = {
        symbol: {key: int(value) for key, value in cube.excluded.items()}
        for symbol, cube in cubes.items()
    }
    result["dependency_sha256"] = {
        module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (simulate, policy_v5, fill_timing, open_source_portfolio)
    }
    result["implementation_sha256"] = hashlib.sha256(
        Path(study.__file__).read_bytes()
    ).hexdigest()
    result["specification_sha256"] = hashlib.sha256(
        json.dumps(study.specification(), sort_keys=True).encode()
    ).hexdigest()
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    for run in result["costs"]:
        print(f"One-way costs {run['cost_bps']:g} bp")
        for arm in study.ARMS:
            totals = [
                next(row for row in phase["results"] if row["line"] == arm)["windows"][
                    0
                ]["total_return"]
                for phase in run["phases"]
            ]
            control = [
                phase["results"][0]["windows"][0]["total_return"]
                for phase in run["phases"]
            ]
            wins = np.count_nonzero(np.array(totals) > control)
            print(
                f"{arm}: median total net return {np.median(totals):.2%}; "
                f"beats control {wins}/20 phases"
            )
    print(f"Wrote {args.output}; diagnostic only, no policy adoption")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
