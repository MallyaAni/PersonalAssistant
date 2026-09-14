"""Refresh research allocations from stored inputs; no broker calls or orders."""

import argparse
import json
from pathlib import Path

from backend.market import deskrecord, intraday_research


# Exercise the exact production research path independently of the trading balancer.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/market"))
    args = parser.parse_args()
    record, _ = deskrecord.latest_pair(args.data_dir)
    if record is None:
        raise SystemExit("No evening decision")
    snapshot = json.loads((args.data_dir / "desk" / "live.json").read_text())
    result = intraday_research.publish(args.data_dir, record, snapshot)
    print(
        json.dumps(
            {key: result.get(key) for key in ("status", "reason", "bar", "macro")}
        )
    )


if __name__ == "__main__":
    main()
