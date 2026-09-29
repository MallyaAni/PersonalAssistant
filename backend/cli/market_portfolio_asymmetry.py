"""Run the registered portfolio loss/gain gate on one saved public /4 account."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

from backend.cli.market_filing_expectations import write_json
from backend.cli.market_laggard_tilt import CACHE_SHA256, load_cache
from backend.market import portfolio_asymmetry as study
from backend.market.session_anatomy import json_ready

BASELINE_REVISION = "2f3562d2d0850e013aef8b9b220186058e7d7428"


# Reject a different strategy, clock, cost or source instead of silently scoring it.
def load_baseline(path):
    with gzip.open(path, "rb") as handle:
        raw = handle.read()
    snapshot = json.loads(raw)
    manifest = snapshot["manifest"]
    expected = {
        "policy_id": "v4",
        "cost_bps": 25,
        "run_id": "laggard-tilt-v4-10-25",
        "status": "complete",
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("registered baseline identity mismatch")
    provenance = manifest["provenance"]
    if provenance["cache_sha256"] != CACHE_SHA256:
        raise ValueError("baseline input cache mismatch")
    if provenance["source_revision"] != BASELINE_REVISION:
        raise ValueError("baseline source revision mismatch")
    if snapshot["events"][0]["session_index"] != 10:
        raise ValueError("baseline start offset mismatch")
    return snapshot, hashlib.sha256(raw).hexdigest()


# Preserve the inputs, complete model state and scores from one clean frozen run.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-cache", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if subprocess.check_output(["git", "status", "--porcelain"], text=True):
        parser.error("commit the research code before running")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    bundle = load_cache(args.trusted_cache)
    snapshot, journal_hash = load_baseline(args.journal)
    rows = study.dataset(bundle, snapshot)
    out = Path(args.out)
    out.mkdir(exist_ok=False, parents=False)
    write_json(out / "dataset.json", json_ready(rows))
    print(f"Saved {len(rows)} decision rows; fitting frozen annual models", flush=True)
    predictions, fits = study.walk_forward(rows)
    write_json(
        out / "predictions.json",
        json_ready({name: values.tolist() for name, values in predictions.items()}),
    )
    write_json(out / "fits.json", json_ready(fits))
    result = study.summarize(rows, predictions)
    result.update(
        plan=study.PLAN,
        source_revision=revision,
        cache_sha256=CACHE_SHA256,
        baseline_journal_sha256_uncompressed=journal_hash,
        features=list(study.FEATURES),
        artifacts={
            name: hashlib.sha256((out / name).read_bytes()).hexdigest()
            for name in ("dataset.json", "predictions.json", "fits.json")
        },
        historical_availability_verified=False,
    )
    write_json(out / "summary.json", json_ready(result))
    print(
        json.dumps({"verdict": result["verdict"], "checks": result["checks"]}, indent=2)
    )


if __name__ == "__main__":
    main()
