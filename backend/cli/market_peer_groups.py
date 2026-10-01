"""Write a recorded session's peer groups beside its record (`peer_sells`).

The nightly writes `<record folder>/sector-peers.json` itself, right after
the record. This writes the same file for a session whose record exists
but whose nightly ran before the peer rule was deployed, so the executor
can judge that record's sells the next morning. Everything is point in
time: the book's panel is built from the store as of the session (and
refused unless it ends on it), the membership is the history's at that
session, and the scope grades are the record's own.

    python -m backend.cli.market_peer_groups [--session 2026-10-01]
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from backend.config.settings import settings
from backend.market import deskrecord


# The CLI's arguments.
def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=settings.MARKET_DATA_ROOT)
    parser.add_argument(
        "--session", default=None, help="record session (default: the latest)"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace an existing file"
    )
    return parser


# Build and write the peer block of one recorded session; return the path.
# Raises when the record is missing or the store's panel does not end on
# the session (the file would not be point in time).
def run(root: Path, session: str | None = None, overwrite: bool = False) -> Path:
    """Write the session's sector-peers file and return its path."""
    from backend.agents.trading.desk import peer_sells, point_in_time
    from backend.agents.trading.desk.desk import book_panel
    from backend.market.store import MarketStore

    found = deskrecord.sessions(root)
    session = session or (found[-1] if found else None)
    record = deskrecord.load(root, session) if session else None
    if record is None:
        raise FileNotFoundError(f"no desk record for {session}")
    panel, _ = book_panel(MarketStore(root), date.fromisoformat(session))
    last = str(panel.dates[-1])
    if last != session:
        raise ValueError(f"the store's panel ends on {last}, not on {session}")
    tickers = tuple(str(t) for t in panel.tickers)
    membership = point_in_time.eligibility(panel.dates, tickers)
    letters = {
        ticker: str(entry.get("grade"))
        for ticker, entry in (record.get("grades") or {}).items()
        if isinstance(entry, dict) and entry.get("grade")
    }
    block = peer_sells.compute(panel, membership, letters)
    return peer_sells.write(root, block, overwrite=overwrite)


# Entry point.
def main() -> None:
    """Write the file and say where."""
    args = build_parser().parse_args()
    written = run(Path(args.data_dir), args.session, args.overwrite)
    print(f"peer groups written: {written}")


if __name__ == "__main__":
    main()
