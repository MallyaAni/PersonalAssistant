"""Import one already acquired public filing response into the research archive.

This command makes no network request and does not change the nightly policy.
The caller explicitly supplies source hash, issuer, symbol and capture time;
those assertions are retained, not promoted to proof of historical availability.
"""

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from backend.market import fundamental_source_store as archive
from backend.market import fundamental_unit_sources as units
from backend.market.store import MarketStore

MAX_SOURCE_BYTES = 16 * 1024 * 1024


# Require explicit local provenance without fetching or inferring a source.
def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--cik", type=int, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--asof", type=date.fromisoformat, required=True)
    parser.add_argument("--captured-at", type=datetime.fromisoformat, required=True)
    return parser


# Import bounded original bytes and report the actual stored identity, even on reruns.
def main(argv=None):
    args = build_parser().parse_args(argv)
    with args.source.open("rb") as handle:
        body = handle.read(MAX_SOURCE_BYTES + 1)
    if len(body) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds the 16-MiB import limit")
    source = units.parse(body, expected_sha256=args.sha256, expected_cik=args.cik)
    store = MarketStore(args.data_dir)
    written = archive.save(
        store, args.ticker, args.asof, source, captured_at=args.captured_at
    )
    stored = archive.load(store, args.ticker, args.asof)
    if stored is None:
        raise ValueError("source archive could not be read back after import")
    print(
        json.dumps(
            {
                "status": "written" if written else "kept_existing",
                "ticker": stored.ticker,
                "asof": stored.asof.isoformat(),
                "captured_at": stored.captured_at.isoformat(),
                "stored_source_sha256": stored.source.sha256,
                "requested_source_sha256": hashlib.sha256(body).hexdigest(),
                "cik": stored.source.cik,
                "bytes": len(stored.source.body),
                "facts": len(stored.source.facts),
                "historical_authenticity_verified": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
