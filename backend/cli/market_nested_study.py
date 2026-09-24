"""Run the frozen research comparison once into a new, independently checked archive."""

import argparse
from pathlib import Path

from backend.market import nested_market_study as study


# Load only pinned market inputs and refuse an existing output before starting work.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        study.check_destination(arguments.output)
        from backend.market.nested_market_inputs import load

        inputs = load(arguments.report, arguments.store_root, arguments.manifest)
        evidence = study.run(inputs.report, inputs)
        manifest = study.archive(evidence, arguments.output)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        parser.exit(2, f"Nested market study failed: {exc}\n")
    print(f"Verified research archive: {manifest}; adoption eligible: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
