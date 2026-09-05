"""Refresh and audit the daily market snapshot from the command line.

    python -m backend.cli.market_snapshot --refresh   # whole universe, today
    python -m backend.cli.market_snapshot --refresh --roles focus,benchmark
    python -m backend.cli.market_snapshot --status
    python -m backend.cli.market_snapshot --refresh --roles focus,benchmark

`--refresh` fetches each ticker into one as-of partition, paced, printing a
line per ticker as it lands; a refused ticker is reported and the command
still exits 0 so a partial run is visible rather than a wall of failure.
Re-running the same day skips what is already stored, which is how a
throttled run is resumed. `--status` reports what the newest partition
holds per ticker and flags the stale or missing ones.
"""

import argparse
import logging
from datetime import date
from pathlib import Path

from backend.config.settings import settings
from backend.market import snapshot
from backend.market.store import MarketStore, summarize
from backend.market.universe import build_universe, tickers_with_role

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the snapshot tool."""
    parser = argparse.ArgumentParser(
        description="Refresh or audit the daily market snapshot."
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Fetch and store daily history."
    )
    parser.add_argument(
        "--status", action="store_true", help="Report what the store holds per ticker."
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated subset; defaults to the universe.",
    )
    parser.add_argument(
        "--roles", default="", help="Comma-separated roles: focus, member, benchmark."
    )
    parser.add_argument(
        "--asof",
        type=date.fromisoformat,
        default=None,
        help="Partition date (default today).",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=snapshot.DEFAULT_START,
        help="First session to fetch.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(settings.MARKET_DATA_ROOT),
        help="Store root.",
    )
    return parser


# The tickers a run applies to, from --tickers, --roles, or the universe.
def _select_tickers(args: argparse.Namespace) -> tuple[str, ...]:
    if args.tickers:
        return tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    roles = tuple(r.strip() for r in args.roles.split(",") if r.strip())
    return tickers_with_role(build_universe(), *roles)


# Print one refresh result as it happens.
def _print_result(result: snapshot.RefreshResult) -> None:
    if result.error:
        print(f"{result.ticker:6} FAILED  {result.error}", flush=True)
    elif result.skipped:
        print(
            f"{result.ticker:6} kept    already stored for this partition", flush=True
        )
    else:
        print(f"{result.ticker:6} ok      {result.bars_stored} bars", flush=True)


# Run the tool.
def main() -> None:
    """Entry point: refresh and/or report the snapshot store."""
    args = build_parser().parse_args()
    tickers = _select_tickers(args)
    store = MarketStore(args.data_dir)
    if args.refresh:
        report = snapshot.refresh(
            store, tickers, asof=args.asof, start=args.start, on_result=_print_result
        )
        print(
            f"partition {report.asof}: {report.stored_count} stored, "
            f"{len(report.failed_tickers)} failed"
        )
        if report.failed_tickers:
            print("FLAGGED (unavailable): " + ", ".join(report.failed_tickers))
    if args.status or not args.refresh:
        rows = snapshot.status(store, tickers, asof=args.asof)
        for row in rows:
            flags = " ".join(
                f for f, on in (("MISSING", row.missing), ("STALE", row.stale)) if on
            )
            print(
                f"{row.ticker:6} asof={str(row.asof or '-'):10} "
                f"through={str(row.complete_through or '-'):10} "
                f"{row.bar_count:5} bars  {flags}"
            )
        print(f"partitions: {summarize(store)}")


if __name__ == "__main__":
    main()
