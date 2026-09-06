"""Measure how much of each 10-K and 10-Q a company rewrote, resumably.

    python -m backend.cli.market_filings --refresh
    python -m backend.cli.market_filings --refresh --tickers ADBE,NOW --since 2018-01-01
    python -m backend.cli.market_filings --status

For each ticker in the book, list its 10-K and 10-Q filings from SEC's
submissions document, fetch each one's primary document, and compare it
with the same form filed a year earlier. The result is stored as an
immutable `edgar_filings` frame in today's partition, one frame per
ticker; a ticker already in the partition is skipped, so an interrupted
run resumes by being run again.

Nothing about this is expensive. Every fetch is paced at SEC's asked-for
rate, filing documents are a few hundred kilobytes, and the text is
discarded once its word counts are taken. A full run over the book is
about a quarter of an hour and stores a few kilobytes per name.

Why it exists is in `backend/market/filings.py`.
"""

import argparse
import time
from datetime import date
from pathlib import Path

from backend.config.settings import settings
from backend.market import edgar, filings
from backend.market.store import MarketStore
from backend.market.universe import book_sides, build_universe, tickers_with_role

FRAME = "edgar_filings"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the filings tool."""
    parser = argparse.ArgumentParser(description="Measure filing-text change.")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--tickers", default="")
    parser.add_argument("--roles", default="")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2015, 1, 1))
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    return parser


# The tickers a run applies to. With nothing asked for, that is the book —
# the ninety-three names the desk trades — and not the whole universe. The
# universe is several hundred names and a run over it takes hours for data
# no analyst reads, which is a mistake worth making impossible rather than
# documenting.
def _select(args: argparse.Namespace) -> tuple[str, ...]:
    universe = build_universe()
    if args.tickers:
        return tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    if args.roles:
        roles = tuple(r.strip() for r in args.roles.split(",") if r.strip())
        return tickers_with_role(universe, *roles)
    return tuple(sorted(book_sides(universe)))


# Every 10-K and 10-Q a company filed on or after `since`, oldest first.
# The comparison needs the year before the window too, so the fetch reaches
# back a further 460 days and the extra filings are used only as partners.
def _filings_for(cik: int, since: date, pacer: edgar.Pacer) -> list:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    document = edgar._get_json(url, edgar.sec_transport, pacer, time.sleep)
    blocks = [document.get("filings", {}).get("recent", {})]
    for older in document.get("filings", {}).get("files", []) or []:
        name = older.get("name")
        if not name:
            continue
        blocks.append(
            edgar._get_json(
                f"https://data.sec.gov/submissions/{name}",
                edgar.sec_transport,
                pacer,
                time.sleep,
            )
        )
    found: list = []
    for block in blocks:
        found.extend(filings.parse_periodic_block(block))
    reach = date.fromordinal(max(since.toordinal() - 460, 1))
    return sorted(
        {f.accession: f for f in found if f.filed >= reach}.values(),
        key=lambda f: f.filed,
    )


# What is already stored, so a run says what is left rather than repeating.
def _status(store: MarketStore, tickers: tuple[str, ...], asof: date) -> None:
    done, missing = [], []
    for ticker in tickers:
        (done if store.has_frame(FRAME, asof, ticker) else missing).append(ticker)
    print(f"filing similarity as of {asof}: {len(done)} of {len(tickers)} stored")
    if missing:
        print("  not yet measured: " + ", ".join(missing[:20]))
        if len(missing) > 20:
            print(f"  and {len(missing) - 20} more")
    total = 0
    for ticker in done:
        frame = store.read_frame(FRAME, ticker, asof)
        if frame:
            total += len(frame[0].get("similarity", []))
    print(f"  {total} filing comparisons stored")


# Measure one ticker and store its frame. Returns how many comparisons it
# produced, or None when the ticker is already stored.
def _measure(
    store: MarketStore,
    ticker: str,
    cik: int,
    asof: date,
    since: date,
    pacer: edgar.Pacer,
) -> int | None:
    if store.has_frame(FRAME, asof, ticker):
        return None
    found = _filings_for(cik, since, pacer)
    records = filings.measure_company(ticker, cik, found, pacer=pacer)
    kept = [r for r in records if r.filed >= since]
    store.write_frame(
        FRAME,
        asof,
        ticker,
        filings.similarity_frame(kept),
        metadata={"cik": str(cik), "since": since.isoformat()},
    )
    return len(kept)


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    asof = args.asof or date.today()
    tickers = _select(args)
    if args.status or not args.refresh:
        _status(store, tickers, asof)
        return
    pacer = edgar.Pacer()
    cik_map = edgar.fetch_cik_map(pacer=pacer)
    started = time.time()
    measured = 0
    for index, ticker in enumerate(tickers, start=1):
        cik = cik_map.get(ticker)
        if cik is None:
            print(f"{index:3d}/{len(tickers)} {ticker:6} no CIK on file")
            continue
        try:
            count = _measure(store, ticker, cik, asof, args.since, pacer)
        except Exception as exc:  # one bad filer must not end the run
            print(f"{index:3d}/{len(tickers)} {ticker:6} failed: {exc}")
            continue
        if count is None:
            print(f"{index:3d}/{len(tickers)} {ticker:6} already stored")
            continue
        measured += 1
        print(
            f"{index:3d}/{len(tickers)} {ticker:6} {count:3d} comparisons "
            f"({time.time() - started:.0f}s elapsed)"
        )
    print(f"\nmeasured {measured} tickers in {time.time() - started:.0f}s")
    _status(store, tickers, asof)


if __name__ == "__main__":
    main()
