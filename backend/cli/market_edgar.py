"""Fetch and audit the EDGAR layer: earnings events and quarterly fundamentals.

    python -m backend.cli.market_edgar --refresh
    python -m backend.cli.market_edgar --refresh --roles focus
    python -m backend.cli.market_edgar --status
    python -m backend.cli.market_edgar --audit-6k --tickers TSM,ASML,ARM,NBIS,SIMO

`--refresh` resolves each ticker to its CIK, fetches its 8-K item 2.02
events (and, for a listed foreign issuer, its 6-K results releases) and
company facts, and stores both as immutable frames in today's partition
(kinds `edgar_events` and `edgar_facts`), skipping tickers the partition
already holds. A refused or unknown ticker is reported per ticker and the
run continues. The 6-K decisions (accession -> admitted) ride on the
events frame's metadata as `classified_6k` and are carried into the next
refresh so only new 6-Ks are read. `--status` reports, per ticker, how
many events and quarterly facts the newest partition holds. `--audit-6k`
lists the admitted 6-K releases per name per year from the stored frames
and flags any full year without four, which is what a results filer
produces; nothing is fetched.
"""

import argparse
import time
from datetime import UTC, date, datetime, timedelta
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
    parser.add_argument("--audit-6k", action="store_true")
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
def refresh(
    store: MarketStore, tickers: tuple[str, ...], asof: date
) -> tuple[str, ...]:
    """Fetch events and facts per ticker into the as-of partition.

    Returns the names whose fetch failed. A successful fetch with no new
    filing still writes today's partition (the same facts, a new source
    time); a failed fetch writes nothing, and the store keeps serving that
    name's last successful partition, which is the cached-data policy.
    """
    pacer = edgar.Pacer()
    cik_map = edgar.fetch_cik_map(pacer=pacer)
    stored = failed = skipped = 0
    failed_names: list[str] = []
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
            failed_names.append(ticker)
            continue
        try:
            record = edgar.fetch_company(
                ticker, cik, pacer=pacer, decisions=prior_decisions(store, ticker, asof)
            )
        except edgar.EdgarUnavailableError as exc:
            print(f"{ticker:6} FAILED  {exc}", flush=True)
            failed += 1
            failed_names.append(ticker)
            continue
        events, facts = edgar.record_frames(record)
        meta = {
            "cik": str(cik),
            "source_time": record.source_time.isoformat(),
        }
        if record.decisions_6k:
            meta["classified_6k"] = edgar.decisions_to_metadata(record.decisions_6k)
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
    return tuple(failed_names)


# The 6-K decisions stored with the ticker's newest events frame before
# `asof`, so a refresh reads only the 6-Ks it has not classified.
def prior_decisions(store: MarketStore, ticker: str, asof: date) -> dict[str, bool]:
    """Return {accession: admitted} carried from the previous partition."""
    frame = store.read_frame(EVENTS, ticker, asof - timedelta(days=1))
    if frame is None:
        return {}
    return edgar.decisions_from_metadata(frame[1])


# The admitted 6-K releases per year for one events frame, and the years
# that do not hold four. The first and last years on file are partial by
# nature and are reported but not flagged.
def audit_6k_frame(columns: dict[str, list]) -> tuple[dict[int, int], list[int]]:
    """Return ({year: admitted 6-K count}, years with a count other than 4)."""
    counts: dict[int, int] = {}
    for event in edgar.events_from_columns(columns):
        if event.form != "6-K":
            continue
        counts[event.filed.year] = counts.get(event.filed.year, 0) + 1
    if not counts:
        return counts, []
    first, last = min(counts), max(counts)
    for year in range(first + 1, last):
        counts.setdefault(year, 0)
    short = [y for y in sorted(counts) if first < y < last and counts[y] != 4]
    return counts, short


# Print the 6-K audit per ticker from stored frames; True when every full
# year of every name holds four releases.
def audit_6k(store: MarketStore, tickers: tuple[str, ...], asof: date | None) -> bool:
    """Print admitted 6-K releases per name per year; return whether all pass."""
    ok = True
    for ticker in tickers:
        frame = store.read_frame(EVENTS, ticker, asof)
        if frame is None:
            print(f"{ticker:6} MISSING")
            ok = False
            continue
        columns, meta = frame
        decided = edgar.decisions_from_metadata(meta)
        counts, short = audit_6k_frame(columns)
        refused = sum(1 for v in decided.values() if not v)
        years = " ".join(f"{y}:{n}" for y, n in sorted(counts.items()))
        verdict = "ok" if not short else f"CHECK {short}"
        print(
            f"{ticker:6} 6-K admitted={sum(counts.values()):3d} "
            f"refused={refused:4d} {verdict} {years}"
        )
        for event in edgar.events_from_columns(columns):
            if event.form == "6-K":
                print(
                    f"       {event.filed} {event.accession} "
                    f"reacts {event.reaction_date}"
                )
        ok = ok and not short
    return ok


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
    if args.audit_6k:
        if not audit_6k(store, tickers, args.asof):
            raise SystemExit(1)
        return
    if args.status or not args.refresh:
        status(store, tickers, args.asof)


if __name__ == "__main__":
    main()
