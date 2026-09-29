"""Run the registered daily learned-position experiment on existing local data."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from backend.market import daily_action_study, universe
from backend.market.store import MarketStore


# Require a clean source checkpoint and a separate new research destination.
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--membership", type=Path, default=universe.MEMBERSHIP_HISTORY_PATH
    )
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.root.resolve()):
        parser.error("Output must be separate from the source market store")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    if dirty:
        parser.error("Commit the research implementation before fitting")
    result = daily_action_study.run(
        MarketStore(args.root),
        args.membership,
        args.output,
        source_revision=revision,
    )
    print(json.dumps(result["verdict"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
