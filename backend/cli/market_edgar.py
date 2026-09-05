"""Fetch and audit the EDGAR layer: earnings events and quarterly fundamentals.

    python -m backend.cli.market_edgar --refresh
    python -m backend.cli.market_edgar --refresh --roles focus
    python -m backend.cli.market_edgar --status

`--refresh` resolves each ticker to its CIK, fetches its 8-K item 2.02
events and company facts, and stores both as immutable frames in today's
partition (kinds `edgar_events` and `edgar_facts`), skipping tickers the
partition already holds. A refused or unknown ticker is reported per
ticker and the run continues. `--status` reports, per ticker, how many
events and quarterly facts the newest partition holds.
"""

import argparse
import time
from datetime import UTC, date, datetime
from pathlib import Path

from backend.config.settings import settings
from backend.market import edgar
from backend.market.store import MarketStore
from backend.market.universe import build_universe, tickers_with_role

EVENTS = "edgar_events"
FACTS = "edgar_facts"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the EDGAR tool."""
    parser = argparse.ArgumentParser(description="Fetch or audit the EDGAR layer.")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--tickers", default="")
    parser.add_argument("--roles", default="")
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


# Fetch and store every ticker not already in the partition.
def refresh(store: MarketStore, tickers: tuple[str, ...], asof: date) -> None:
    """Fetch events and facts per ticker into the as-of partition."""
    pacer = edgar.Pacer()
    cik_map = edgar.fetch_cik_map(pacer=pacer)
    stored = failed = skipped = 0
    started = time.time()
    for ticker in tickers:
        if store.has_frame(EVENTS, asof, ticker):
            skipped += 1
            continue
        # SEC lists class shares with a hyphen, the same as the market source.
        cik = cik_map.get(ticker) or cik_map.get(ticker.replace("-", ""))
        if cik is None:
            print(f"{ticker:6} FAILED  no CIK on SEC's ticker list", flush=True)
            failed += 1
            continue
        try:
            record = edgar.fetch_company(ticker, cik, pacer=pacer)
        except edgar.EdgarUnavailableError as exc:
            print(f"{ticker:6} FAILED  {exc}", flush=True)
            failed += 1
            continue
        events, facts = edgar.record_frames(record)
        meta = {
            "cik": str(cik),
            "source_time": record.source_time.isoformat(),
        }
        store.write_frame(EVENTS, asof, ticker, events, meta)
        store.write_frame(FACTS, asof, ticker, facts, meta)
        stored += 1
        quarters = sum(1 for f in record.facts if f.name == "revenue")
        print(
            f"{ticker:6} ok      {len(record.events):3d} events, "
            f"{quarters:3d} revenue quarters",
            flush=True,
        )
    minutes = (time.time() - started) / 60
    print(
        f"partition {asof}: {stored} stored, {skipped} kept, {failed} failed "
        f"in {minutes:.1f} min"
    )


# Report what the newest partition holds per ticker.
def status(store: MarketStore, tickers: tuple[str, ...], asof: date | None) -> None:
    """Print events and revenue quarters per ticker."""
    for ticker in tickers:
        events = store.read_frame(EVENTS, ticker, asof)
        facts = store.read_frame(FACTS, ticker, asof)
        if events is None or facts is None:
            print(f"{ticker:6} MISSING")
            continue
        columns, meta = facts
        quarters = sum(1 for n in columns.get("name", []) if n == "revenue")
        last_event = max(events[0].get("filed") or [None], default=None)
        count = len(events[0].get("filed", []))
        print(
            f"{ticker:6} cik={meta.get('cik', '-'):>8} events={count:3d} "
            f"last={last_event} revenue_quarters={quarters:3d}"
        )


# Run the tool.
def main() -> None:
    """Entry point: refresh and/or report the EDGAR layer."""
    args = build_parser().parse_args()
    tickers = _select(args)
    store = MarketStore(args.data_dir)
    asof = args.asof or datetime.now(tz=UTC).date()
    if args.refresh:
        refresh(store, tickers, asof)
    if args.status or not args.refresh:
        status(store, tickers, args.asof)


if __name__ == "__main__":
    main()
