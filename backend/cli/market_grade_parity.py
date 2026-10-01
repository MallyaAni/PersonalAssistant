"""Check tonight's live grades and targets against the point-in-time replay.

    python -m backend.cli.market_grade_parity --root data/market [--date 2026-09-26]

Loads the desk record for the date (the latest when none is given), rebuilds
the desk report from the store exactly as the nightly does, replays the
point-in-time grade for the record's session, recomputes the active policy's
targets, and writes the result to `<root>/desk/grade_parity.json`
(`backend.market.grade_parity` says precisely what is compared). Prints the
verdict line and every mismatch.

Exit codes: 0 when live and replay agree; 1 on a parity mismatch - the
replay ran on the record's own code and store and still disagrees (do not
trade from the board until it is understood: inspect membership_history.csv
and the store's latest partition dates); 2 when the check could not run (no
record for the date, the store unreadable); 3 on drift - the checkout or
the store has moved on since the record (the line names the code pair and
the partitions), so the board is stale and the next nightly re-grades.
A name whose drift coincides with a change in its own earnings data after
the record (a release read for the first time or re-read) is printed again
as a `data update:` line; the exit code does not change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.market import grade_parity

OK, MISMATCH, UNAVAILABLE, DRIFT = 0, 1, 2, 3


# The argument parser, separate so a test can drive `main` with a list.
def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default="data/market", help="the market data root")
    parser.add_argument(
        "--date", default=None, help="the record's session (default: latest)"
    )
    parser.add_argument(
        "--membership",
        default=None,
        help="membership_history.csv to replay with (default: the universe's)",
    )
    return parser


# Run the check and turn the result into an exit code: the verdict line and
# each mismatch on stdout; a check that could not run says why on stderr; a
# mismatch exits 1 in parity mode and 3 in drift mode.
def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the exit code."""
    args = build_parser().parse_args(argv)
    try:
        result = grade_parity.run(
            Path(args.root),
            args.date,
            history_path=Path(args.membership) if args.membership else None,
        )
    except Exception as exc:  # noqa: BLE001 - the exit code is the report
        print(
            f"grade parity: not checked ({type(exc).__name__}: {exc})", file=sys.stderr
        )
        return UNAVAILABLE
    print(grade_parity.line(result))
    for m in result["mismatches"]:
        who = f"{m['ticker']}: " if m.get("ticker") else ""
        print(f"  {m['kind']}: {who}{m.get('detail', '')}")
    # The names whose drift coincides with a change in their own earnings
    # data after the record, in the words the board shows.
    for text in (result.get("data_vintage") or {}).get("lines") or []:
        print(f"  data update: {text}")
    print(f"written: {grade_parity.path(Path(args.root))}")
    if result["ok"]:
        return OK
    return DRIFT if result.get("mode") == grade_parity.DRIFT else MISMATCH


if __name__ == "__main__":
    sys.exit(main())
