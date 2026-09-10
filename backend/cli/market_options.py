"""Fetch the option chains for the book and read the walls.

    python -m backend.cli.market_options --refresh          # today's chains
    python -m backend.cli.market_options --walls ADBE NTAP  # the levels
    python -m backend.cli.market_options --walls-book       # every book name

`--refresh` stores one immutable frame per name per session under
`data/market/options/asof=DATE/`, every listed contract within 180
days with its open interest, implied volatility and gamma, from Cboe's
free delayed feed. That is the history nobody else keeps; the walls
can be tested against forward returns once a quarter of it exists
(see `backend/market/options.py`). `--walls` reads the newest frame
and prints the put wall, the call wall and the dealer-gamma proxy at
the chain's own price. Nothing here trades.
"""

import argparse
import time
from datetime import UTC, date, datetime
from pathlib import Path

from backend.config.settings import settings
from backend.market import options
from backend.market.store import MarketStore
from backend.market.universe import book_sides, build_universe
from backend.market.yahoo import impersonating_transport

PACE_SECONDS = 0.75
BACKOFF_SECONDS = 8.0


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", default=settings.MARKET_DATA_ROOT)
    parser.add_argument("--refresh", action="store_true", help="fetch today's chains")
    parser.add_argument("--walls", nargs="*", default=[], help="names to read")
    parser.add_argument(
        "--walls-book", action="store_true", help="read every book name"
    )
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    return parser


# Fetch and store every book name's chain for `asof`; return the count.
def refresh(
    store: MarketStore,
    tickers: tuple[str, ...],
    asof: date,
    transport=impersonating_transport,
    sleep=time.sleep,
) -> tuple[int, list[str]]:
    """Store the chains; return (stored, failed tickers)."""
    stored = 0
    failed: list[str] = []
    for ticker in tickers:
        # A frame already on file for the session is not fetched again, so a
        # rerun after a refusal costs only the names that were refused.
        if store._path(options.KIND, asof, ticker).exists():
            print(f"{ticker:6} kept")
            continue
        price, rows = None, []
        # The feed refuses a burst; a refusal is retried after a pause, twice.
        for attempt in range(3):
            try:
                price, rows = options.fetch_chain(ticker, transport, asof)
            except Exception as exc:  # noqa: BLE001 - one name must not stop the rest
                print(f"{ticker:6} error {type(exc).__name__}: {exc}")
                price, rows = None, []
            if price is not None and rows:
                break
            sleep(BACKOFF_SECONDS * (attempt + 1))
        if price is None or not rows:
            failed.append(ticker)
            print(f"{ticker:6} FAILED no chain")
        else:
            written = store.write_frame(
                options.KIND,
                asof,
                ticker,
                options.frame(rows),
                {
                    "price": f"{price:.4f}",
                    "source_time": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            )
            stored += int(written)
            print(
                f"{ticker:6} {'ok' if written else 'kept'} "
                f"{len(rows):5d} contracts at {price:.2f}"
            )
        sleep(PACE_SECONDS)
    return stored, failed


def _print_walls(store: MarketStore, ticker: str, today: date) -> None:
    frame = store.read_frame(options.KIND, ticker)
    if frame is None:
        print(f"{ticker:6} no chain on file")
        return
    columns, meta = frame
    rows = options.rows_from_frame(columns)
    price = float(meta.get("price", "0") or 0.0)
    w = options.walls(rows, price, today)
    put = f"{w.put_wall:.0f} ({w.put_wall_oi:,} OI)" if w.put_wall else "none in range"
    call = (
        f"{w.call_wall:.0f} ({w.call_wall_oi:,} OI)" if w.call_wall else "none in range"
    )
    print(
        f"{ticker:6} price {price:8.2f}  expiry {w.expiry}  put wall {put:22}  "
        f"call wall {call:22}  dealer gamma {w.net_gamma:+,.0f} shares per 1%"
    )


def main() -> None:
    """Run the tool."""
    args = build_parser().parse_args()
    store = MarketStore(Path(args.data_dir))
    today = args.asof or datetime.now(UTC).date()
    names = tuple(sorted(book_sides(build_universe())))
    if args.refresh:
        stored, failed = refresh(store, names, today)
        print(
            f"options {today}: {stored} stored, {len(failed)} failed"
            + (f" ({', '.join(failed)})" if failed else "")
        )
    wanted = list(args.walls) + (list(names) if args.walls_book else [])
    for ticker in wanted:
        _print_walls(store, ticker.upper(), today)


if __name__ == "__main__":
    main()
