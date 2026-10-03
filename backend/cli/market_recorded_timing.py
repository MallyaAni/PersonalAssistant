"""Evaluate exactly two preregistered archived baskets without network or orders."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from backend.market import (
    recorded_timing_inputs,
    recorded_timing_replay,
    sequential_execution_shadow,
)

RECORDS = {
    "2026-10-01": "a86daeb422d8bc0f6bb71e292f69fab9cef780c53cba3a1269562e50ca9d2546",
    "2026-10-02": "fca9ea80fe38dbd421cadc3d3cd4a1d72be392b48b09e1c8b36dfc952a0c54a2",
}


# Write immutable private results from historical bytes and frozen parameters.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-root", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    inputs = [
        recorded_timing_inputs.load(args.market_root, session) for session in RECORDS
    ]
    if any(
        row.provenance["record_sha256"] != RECORDS[row.session.isoformat()]
        for row in inputs
    ):
        raise ValueError("Exact preregistered ordinary-intention records required")
    model = sequential_execution_shadow.load_model(args.models)
    sessions = [recorded_timing_replay.evaluate(row, model) for row in inputs]
    source = Path(__file__).resolve().parents[2]
    files = [
        Path(__file__),
        Path(recorded_timing_inputs.__file__),
        Path(recorded_timing_replay.__file__),
        source / "docs/research/recorded-timing-plan-2026-10-03.md",
    ]
    report = dict(
        schema="recorded-timing/1",
        sessions=sessions,
        source_revision=os.environ.get("ANIOS_RESEARCH_SOURCE_REVISION", "unavailable"),
        image=os.environ.get("ANIOS_RESEARCH_IMAGE", "unavailable"),
        source_sha256={
            str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
        model_manifest_sha256=model.manifest_sha256,
        model_archive_sha256=model.archive_sha256,
        interpretation=(
            "Two independent prior-night reset accounts; historical price "
            "proxies, not broker fills or full-policy performance"
        ),
    )
    content = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(
        args.output / "report.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
    print(
        json.dumps(
            {
                "sessions": len(sessions),
                "opportunities": sum(row["opportunities"] for row in sessions),
                "report_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
