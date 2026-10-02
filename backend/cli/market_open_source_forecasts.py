"""Run pinned CPU forecasts on an explicitly supplied immutable research export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.market import open_source_forecasts as forecasts


# Preserve each requested opportunity in a standalone artifact without live writes.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=forecasts.CHECKPOINTS, required=True)
    parser.add_argument(
        "--symbols", required=True, help="Comma-separated frozen cohort, including SPY"
    )
    parser.add_argument("--noncommercial-research", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() == args.input.resolve():
        parser.error("output must be a new artifact")
    symbols = args.symbols.split(",")
    if not all(symbols) or len(symbols) != len(set(symbols)) or "SPY" not in symbols:
        parser.error("cohort must contain unique symbols and SPY")
    source_bytes = args.input.read_bytes()
    payload = json.loads(source_bytes)
    result = forecasts.run(
        payload, args.model, symbols, research_only=args.noncommercial_research
    )
    import hashlib

    result["input_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    counts = {
        status: sum(r["status"] == status for r in result["records"])
        for status in sorted({r["status"] for r in result["records"]})
    }
    print(
        json.dumps(
            {
                "model": args.model,
                "opportunities": len(result["records"]),
                "counts": counts,
                "output": str(args.output),
            }
        )
    )
    if counts.get("model_error", 0):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
