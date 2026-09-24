"""Independently verify a research account archive without changing any files.

Successful cash/fill reconciliation does not establish historical availability,
real security identity, settlement, predictive skill or adoption readiness.
"""

import argparse
import json
from pathlib import Path

from backend.market.research_journal_replay import verify_archive


# Report the independent replayer's result and fail closed without rewriting evidence.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        report = verify_archive(arguments.archive)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Research journal verification failed: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
