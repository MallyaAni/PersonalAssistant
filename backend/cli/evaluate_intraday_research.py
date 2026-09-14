"""Measure archived forward decisions at subsequent observed prices."""

import argparse
import json
from pathlib import Path

from backend.market.intraday_evaluation import evaluate


# Print both ordinary and stressed transaction costs without modifying trading state.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/market"))
    args = parser.parse_args()
    rows = [
        json.loads(path.read_text())
        for path in (args.data_dir / "desk" / "intraday-research").glob(
            "decision-*.json"
        )
    ]
    print(json.dumps([evaluate(rows, cost) for cost in (10, 25)], indent=2))


if __name__ == "__main__":
    main()
