"""Evaluate fixed forecast artifacts with explicit immutable source bindings."""

import argparse
import hashlib
import json
from pathlib import Path

from backend.market.open_source_forecast_evaluation import SOURCE_SHA256, evaluate
from backend.market.open_source_portfolio import load_snapshot


# Read frozen local files and publish a strict funded scorecard without inference.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("portfolio", type=Path)
    parser.add_argument("provenance", type=Path)
    parser.add_argument("artifacts", nargs=4, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Refusing to overwrite an input or prior outcome")
    source = args.input.read_bytes()
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("Frozen source file hash mismatch")
    payload = json.loads(source)
    artifacts = [json.loads(path.read_bytes()) for path in args.artifacts]
    panel, grades, eligible, provenance = load_snapshot(args.portfolio, args.provenance)
    result = evaluate(
        payload,
        artifacts,
        panel,
        grades,
        eligible,
        provenance,
        source_sha256=SOURCE_SHA256,
    )
    result["artifact_file_sha256"] = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in args.artifacts
    }
    with args.output.open("x") as output:
        output.write(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )


if __name__ == "__main__":
    main()
