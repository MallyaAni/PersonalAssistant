"""Observe frozen ML paper accounts once; never submit a broker order."""

import argparse
import json
from pathlib import Path

from backend.market import opportunity_shadow


# Run the same isolated observer used by the nightly refresh and print its receipt.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    row = opportunity_shadow.observe(args.data_dir, folder=args.output)
    print(
        json.dumps(
            {
                "status": row["status"],
                "session": row["session"],
                "sequence": row["sequence"],
                "started_at": row["started_at"],
                "equity": {name: a["equity"] for name, a in row["accounts"].items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
