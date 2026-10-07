"""Fit only the fixed new continuation candidate from the original read-only bank."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from backend.market import nonlinear_continuation_study as study


# Require explicit immutable source identities and a separate private output directory.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    revision = os.environ.get("ANIOS_RESEARCH_SOURCE_REVISION", "")
    image = os.environ.get("ANIOS_RESEARCH_IMAGE_ID", "")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision) or (
        not image.startswith("sha256:") or len(image) != 71
    ):
        raise ValueError("Exact source revision and image identity required")
    if args.output.resolve().is_relative_to(args.prepared.resolve()):
        raise ValueError("Private output must be separate from original inputs")
    dataset, identity = study.load_original(args.prepared)
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = {"source_revision": revision, "image": image,
               "started_at": datetime.now(UTC).isoformat(),
               "policy": study.model.POLICY, "inputs": identity,
               "historical_publication": False, "adoption_eligible": False}
    (args.output / "runtime.json").write_text(json.dumps(runtime, indent=2) + "\n")
    _, manifest = study.walk_forward(
        dataset, args.output / "models", input_identity=identity
    )
    runtime.update(completed_at=datetime.now(UTC).isoformat(),
                   monthly_receipts=len(manifest["months"]), status="fitted")
    (args.output / "complete.json").write_text(json.dumps(runtime, indent=2) + "\n")


if __name__ == "__main__":
    main()
