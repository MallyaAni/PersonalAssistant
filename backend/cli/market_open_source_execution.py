"""Run the optional native funded quote benchmark from a frozen JSON dataset."""

import argparse
import json
from pathlib import Path

from backend.market.open_source_execution import compare, run


# Read a supplied immutable dataset and emit both arms without provider calls.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--mode", choices=("both", "incumbent", "bounded"), default="both"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and (
        args.output.exists() or args.output.resolve() == args.input.resolve()
    ):
        parser.error("output must be a new artifact")
    payload = json.loads(args.input.read_text())
    result = compare(payload) if args.mode == "both" else run(payload, mode=args.mode)
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        with args.output.open("x") as stream:
            stream.write(rendered + "\n")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
