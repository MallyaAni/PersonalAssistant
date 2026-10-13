"""Publish new current-model historical amounts without replaying any account."""

import argparse
import json
import os
from hashlib import sha256
from pathlib import Path

from backend.market import live_model_history_projection as projection
from backend.market.live_model_history_reader import _read_version


# Authenticate the selected independent proof bytes before using their result.
def evidence(path, expected):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("Historical sizing proof bytes differ")
    return json.loads(raw)


# Save one new immutable stock payload and verify its original encoded bytes.
def write_stock(folder, name, value):
    if not name.replace("-", "").isalnum():
        raise ValueError("Explicit historical stock filename required")
    raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    path = folder / (name + ".json")
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)
    if path.read_bytes() != raw:
        raise ValueError("Historical stock readback differs")
    return sha256(raw).hexdigest()


# Save a new immutable version and select it only after complete integrity readback.
def publish(account, proof_path, proof_sha, root):
    proof = evidence(proof_path, proof_sha)
    stocks = projection.project(account, proof)
    if len(stocks) != 94:
        raise ValueError("Complete installed historical stock cohort required")
    root = Path(root)
    before = {
        name: (root / ("desk/learned-" + name + "/config.json")).read_bytes()
        for name in ("holding", "timing")
    }
    for stock in stocks.values():
        for name, raw in before.items():
            if sha256(raw).hexdigest() != stock["provenance"][name + "_config_sha256"]:
                raise ValueError(
                    "Historical account differs from installed live model configuration"
                )
    version = sha256(
        json.dumps(
            {
                "account": proof["account_sha256"],
                "proof": proof_sha,
                "projection_source": sha256(
                    Path(projection.__file__).read_bytes()
                ).hexdigest(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    parent = root / projection.DIRECTORY
    folder = parent / version
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {
        "schema": projection.SCHEMA,
        "version": version,
        "account_sha256": proof["account_sha256"],
        "proof_sha256": proof_sha,
        "files": {},
    }
    for name, value in stocks.items():
        manifest["files"][name] = write_stock(folder, name, value)
    for name, expected in stocks.items():
        if _read_version(root, name, manifest) != expected:
            raise ValueError("Historical staged readback contract differs")
    if any(
        (root / ("desk/learned-" + name + "/config.json")).read_bytes() != raw
        for name, raw in before.items()
    ):
        raise ValueError("Live configuration changed during historical publication")
    temporary = parent / (version + ".manifest.tmp")
    with temporary.open("x") as stream:
        json.dump(manifest, stream, indent=2)
    temporary.chmod(0o600)
    # All payloads are immutable and read back before the manifest becomes visible.
    os.replace(temporary, parent / "manifest.json")
    return {
        "version": version,
        "stocks": len(stocks),
        "through": stocks[next(iter(stocks))]["through"],
        "account_replayed": False,
        "real_orders": False,
    }


# Require explicit verified account, proof digest and guarded publication destination.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("account", "proof", "proof-sha256", "root"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.account, args.proof, args.proof_sha256, args.root)))


if __name__ == "__main__":
    main()
