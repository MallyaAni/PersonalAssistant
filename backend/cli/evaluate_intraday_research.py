"""Measure archived forward decisions at subsequent observed prices."""

import argparse
import json
from pathlib import Path

from backend.market.forward_evidence import report


# Print both ordinary and stressed transaction costs without modifying trading state.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/market"))
    args = parser.parse_args()
    print(json.dumps(report(args.data_dir), indent=2))


if __name__ == "__main__":
    main()
