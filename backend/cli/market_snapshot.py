"""Refresh and audit the daily market snapshot from the command line.

`--refresh` fetches the universe's daily bars from the data source and
stores them, printing one line per ticker; a refused or unparseable ticker
is reported and the command still returns 0 so a partial run is visible
rather than a wall of failure. `--status` reports what the store holds for
each ticker and flags the stale or missing ones.
"""

import argparse
import asyncio
import logging

from backend.config.settings import settings
from backend.database.session import AsyncSessionLocal
from backend.market import snapshot
from backend.market.universe import UNIVERSE_TICKERS, default_tickers

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh or audit the daily market snapshot.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch and store daily bars for the universe.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Report each ticker's stored history and flag stale/missing rows.",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default="",
        help="Comma-separated subset; defaults to the whole universe.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=snapshot.DEFAULT_LOOKBACK_DAYS,
        help="Calendar days of history to fetch per ticker.",
    )
    return parser


async def _run(args: argparse.Namespace) -> None:
    tickers = (
        tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
        if args.tickers
        else UNIVERSE_TICKERS
    )
    async with AsyncSessionLocal() as session:
        if args.refresh:
            report = await snapshot.refresh(session, tickers, args.lookback_days)
            for result in report.results:
                if result.error:
                    print(f"{result.ticker:6} FAILED  {result.error}")
                else:
                    print(f"{result.ticker:6} ok      {result.bars_stored} bars stored")
            if report.failed_tickers:
                print(
                    "FLAGGED (unavailable): "
                    + ", ".join(report.failed_tickers)
                )
        if args.status or not (args.refresh or args.status):
            rows = await snapshot.status(session, tickers)
            for row in rows:
                flags = []
                if row.missing:
                    flags.append("MISSING")
                if row.stale:
                    flags.append("STALE")
                print(
                    f"{row.ticker:6} {str(row.latest_session):10} "
                    f"{row.bar_count:5} bars  {' '.join(flags)}"
                )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
