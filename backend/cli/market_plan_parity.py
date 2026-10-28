"""Check a session's paper plan against the account simulator's plan.

    python -m backend.cli.market_plan_parity --root data/market [--date 2026-10-27]

The 20:40 replay job runs this check every night on the report it has just
built (`market_policy_replay_research.check_plan`). This command re-runs it
for one record (the latest when no date is given): it rebuilds the desk
report as of the record's session from the store, compares the record's
paper plan with the simulator's plan on the same inputs, and writes the
result to `<root>/desk/plan_parity.json` (`backend.market.plan_parity` says
precisely what is compared). Prints the verdict line and every mismatch.
`--no-write` prints without writing.

A record re-checked days later is compared with the code and store as they
are now, so a rule or data change since the record shows as a mismatch;
read the rows before treating one as a fault of the night's plan.

Exit codes: 0 when the plans agree, 1 on a mismatch, 2 when the check could
not run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.market import plan_parity
from backend.market.labels import PlanParity, parse

OK, MISMATCH, UNAVAILABLE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="the market data root")
    parser.add_argument(
        "--date", default=None, help="the record's session (default: latest)"
    )
    parser.add_argument(
        "--no-write", action="store_true", help="print the result without writing it"
    )
    parser.add_argument(
        "--json", action="store_true", help="print the whole result as JSON"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the exit code."""
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if args.no_write:
        result = plan_parity.check(root, args.date)
    else:
        result = plan_parity.run(root, args.date)
    print(plan_parity.line(result))
    for m in result["mismatches"]:
        who = f"{m['ticker']}: " if m.get("ticker") else ""
        values = f" (live {m.get('live')}, simulator {m.get('simulator')})"
        print(f"  {m['kind']}: {who}{m.get('detail', '')}{values}")
    if args.json:
        print(json.dumps(result, indent=1, default=float))
    verdict = parse(PlanParity, result["verdict"])
    if verdict is PlanParity.OK:
        return OK
    return MISMATCH if verdict is PlanParity.MISMATCH else UNAVAILABLE


if __name__ == "__main__":
    raise SystemExit(main())
