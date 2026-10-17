"""Refuse historical publication until full model and live-timing acceptance exists."""

import argparse
import json
from hashlib import sha256
from pathlib import Path


# Authenticate selected bytes without treating declared status as acceptance.
def evidence(path, expected):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("Historical sizing proof bytes differ")
    return json.loads(raw)


# Refuse current proofs before account access or destination writes.
def publish(
    account, proof_path, proof_sha, root, *, frozen_market=None, source_reviews=()
):
    evidence(proof_path, proof_sha)
    raise ValueError(
        "Historical publication blocked: per-session model and installed live "
        "timing acceptance are unverified; current and legacy proof formats "
        "cannot authorize publication"
    )


# Retain the explicit CLI while making the unavailable acceptance boundary fail closed.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("account", "proof", "proof-sha256", "root"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--frozen-market")
    parser.add_argument("--source-review-sha256", action="append", default=[])
    args = parser.parse_args()
    print(
        json.dumps(
            publish(
                args.account,
                args.proof,
                args.proof_sha256,
                args.root,
                frozen_market=args.frozen_market,
                source_reviews=args.source_review_sha256,
            )
        )
    )


if __name__ == "__main__":
    main()
