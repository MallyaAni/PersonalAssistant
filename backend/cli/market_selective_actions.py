"""Run the preregistered selective action-value backtest on trusted local data."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from backend.market import selective_action_study as study
from backend.market import universe
from backend.market.store import MarketStore


# Refuse dirty code and unsafe output placement before preparing or fitting research.
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--membership", type=Path, default=universe.MEMBERSHIP_HISTORY_PATH
    )
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--trusted-input-cache", type=Path)
    parser.add_argument("--cache-sha256")
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.root.resolve()):
        parser.error("Output must be outside the input market store")
    if bool(args.trusted_input_cache) != bool(args.cache_sha256):
        parser.error("A trusted cache requires its separately supplied SHA-256")
    if args.prepare_only and args.trusted_input_cache:
        parser.error("Prepare-only and cache reuse are mutually exclusive")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], text=True):
        parser.error("Commit the research implementation before running")
    if args.trusted_input_cache:
        bundle = study.load_inputs(args.trusted_input_cache, args.cache_sha256)
        original = json.loads(
            args.trusted_input_cache.with_name("inputs.json").read_text()
        )
        if original.get("cache_sha256") != args.cache_sha256:
            parser.error("Input receipt does not match the explicitly trusted cache")
        receipt = {
            **original,
            "cache_sha256": args.cache_sha256,
            "trusted_input_cache": str(args.trusted_input_cache),
        }
    else:
        cache_output = (
            args.output
            if args.prepare_only
            else args.output.with_name(args.output.name + "-inputs")
        )
        bundle, receipt = study.prepare_inputs(
            MarketStore(args.root),
            args.membership,
            cache_output,
            source_revision=revision,
        )
    if args.prepare_only:
        return 0
    result = study.run(
        bundle, args.output, source_revision=revision, input_receipt=receipt
    )
    print(json.dumps(result["verdict"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
