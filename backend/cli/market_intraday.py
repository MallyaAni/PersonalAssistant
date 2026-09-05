"""Fetch 15-minute bars from Alpaca into the store, resumably.

    python -m backend.cli.market_intraday --refresh --roles focus
    python -m backend.cli.market_intraday --refresh --since 2018-01-01
    python -m backend.cli.market_intraday --status

Needs APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment (a free
Alpaca account). Each ticker's bars land as one immutable `bars_15m` frame
in today's partition; tickers already present are skipped.
"""

import argparse
import time
from datetime import UTC, date, datetime
from pathlib import Path

from backend.config.settings import settings
from backend.market import alpaca
from backend.market.store import MarketStore
from backend.market.universe import build_universe, tickers_with_role


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the intraday tool."""
    parser = argparse.ArgumentParser(description="Fetch 15-minute bars from Alpaca.")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--tickers", default="")
    parser.add_argument("--roles", default="")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    return parser


# The tickers a run applies to.
def _select(args: argparse.Namespace) -> tuple[str, ...]:
    if args.tickers:
        return tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    roles = tuple(r.strip() for r in args.roles.split(",") if r.strip())
    return tickers_with_role(build_universe(), *roles)


# Run the tool.
def main() -> None:
    """Entry point: fetch and/or report 15-minute bars."""
    args = build_parser().parse_args()
    tickers = _select(args)
    store = MarketStore(args.data_dir)
    asof = args.asof or datetime.now(tz=UTC).date()
    if args.refresh:
        headers = alpaca.credentials()
        started = time.time()
        stored = failed = 0
        for ticker in tickers:
            if store.has_frame(alpaca.BARS_KIND, asof, ticker):
                print(f"{ticker:6} kept", flush=True)
                continue
            t0 = time.time()
            try:
                bars = alpaca.fetch_bars(ticker, args.since, asof, headers=headers)
            except alpaca.AlpacaUnavailableError as exc:
                print(f"{ticker:6} FAILED  {exc}", flush=True)
                failed += 1
                continue
            store.write_frame(
                alpaca.BARS_KIND,
                asof,
                ticker,
                alpaca.bars_frame(bars),
                {"source": "alpaca-iex", "since": args.since.isoformat()},
            )
            stored += 1
            print(
                f"{ticker:6} ok      {len(bars):7d} bars, {time.time() - t0:5.0f}s",
                flush=True,
            )
        minutes = (time.time() - started) / 60
        print(
            f"partition {asof}: {stored} stored, {failed} failed in {minutes:.1f} min"
        )
    if args.status or not args.refresh:
        for ticker in tickers:
            frame = store.read_frame(alpaca.BARS_KIND, ticker, args.asof)
            if frame is None:
                print(f"{ticker:6} MISSING")
                continue
            columns, meta = frame
            count = len(columns.get("start", []))
            last = columns["start"][-1][:10] if count else "-"
            print(
                f"{ticker:6} bars={count:7d} since={meta.get('since', '-')} last={last}"
            )


if __name__ == "__main__":
    main()
