"""Evaluate one frozen skfolio sizing candidate on a supplied, hash-bound snapshot.

No providers, model endpoints, broker accounts or live policy are touched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.market.open_source_portfolio import backtest, load_snapshot, specification


# Describe the fixed research run without allowing outcome-driven parameter grids.
def parser():
    result = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    result.add_argument("--snapshot", type=Path)
    result.add_argument("--provenance", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--start", default="2016-01-04")
    result.add_argument("--specification", action="store_true")
    return result


# Write an exclusive research artifact and summarize coverage and economic results.
def main(argv=None):
    args = parser().parse_args(argv)
    if args.specification:
        print(json.dumps(specification(), indent=2, allow_nan=False))
        return 0
    if not all((args.snapshot, args.provenance, args.output)):
        raise SystemExit("--snapshot, --provenance and --output are required")
    if args.output.exists():
        raise SystemExit(
            "output already exists; source and outcomes are never overwritten"
        )
    panel, grades, eligible, provenance = load_snapshot(args.snapshot, args.provenance)
    payload = backtest(panel, grades, eligible, provenance, start=args.start)
    with args.output.open("x") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
    print(
        f"Research artifact: {args.output}; candidate unavailable resets: "
        f"{payload['candidate_unavailable_resets']}"
    )
    for cost in payload["costs"]:
        print(f"\nOne-way cost: {cost['cost_bps']:g} bp")
        for line in cost["results"]:
            for window in line["windows"]:
                if window["status"] == "measured":
                    print(
                        f"{line['line']} {window['window']}: "
                        f"CAGR {window['cagr']:.2%}, "
                        f"drawdown loss {window['max_drawdown_loss']:.2%}, "
                        f"Sharpe {window['sharpe_zero_cash_yield']}, "
                        f"turnover/year {window['turnover_annualized']:.2f}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
