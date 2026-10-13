"""Publish chart projections from a reconciled account without rerunning it."""

import argparse
import gzip
import hashlib
import json
import os
from datetime import date
from pathlib import Path

from backend.market import strategy_simulation as simulation
from backend.market.strategy_research import archive_configuration


# Authenticate original input bytes before loading private replay evidence.
def verified(path, digest):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Original simulation evidence hash differs")
    return raw


# Attach original split dates without rewriting any simulated execution size.
def attach_splits(projected, splits_path, splits_sha):
    events_by_stock = json.loads(verified(splits_path, splits_sha))
    if set(events_by_stock) != set(projected["tickers"]):
        raise ValueError("Original split metadata must cover the whole cohort")
    for name, stock in projected["tickers"].items():
        events = events_by_stock[name]
        dates = [event["date"] for event in events]
        if len(set(dates)) != len(dates):
            raise ValueError("Split event dates must be unique")
        for event in events:
            date.fromisoformat(event["date"])
            simulation.number(event["ratio"], positive=True)
        stock["splits"] = events
    projected["provenance"]["split_metadata_sha256"] = splits_sha


# Authenticate a prior configuration when only its reviewed source approval changes.
def prior_configuration(config, original_sha, prior_path):
    if prior_path is None:
        raise ValueError("Original continuation configuration required")
    prior = json.loads(verified(prior_path, original_sha))
    before = {
        key: value for key, value in prior.items() if key != "release_receipt_sha256"
    }
    after = {
        key: value for key, value in config.items() if key != "release_receipt_sha256"
    }
    if before != after:
        raise ValueError("Only source-release approval may change for preserved replay")


# Publish content-addressed stock views and switch the manifest only after readback.
def publish(
    account_path,
    account_sha,
    proof_path,
    proof_sha,
    root,
    continuation_path=None,
    continuation_sha=None,
    continuation_proof=None,
    splits_path=None,
    splits_sha=None,
    prior_config_path=None,
):
    raw = verified(account_path, account_sha)
    proof = json.loads(verified(proof_path, proof_sha))
    if proof["status"] != "VERIFIED_THREE_CARRIED_ACCOUNT_COMPONENT_SCREEN":
        raise ValueError("Independent reconciled account proof required")
    config_bytes = (Path(root) / "desk/learned-holding/config.json").read_bytes()
    config = json.loads(config_bytes)
    matches = [row for row in proof["accounts"] if row["sha256"] == account_sha]
    if len(matches) != 1 or matches[0]["cost_bps"] != config["cost_bps"]:
        raise ValueError("Exact installed-cost account required")
    if proof["candidate_policy"] != config["policy"]:
        raise ValueError("Exact installed policy account required")
    provenance = {
        "account_sha256": account_sha,
        "proof_sha256": proof_sha,
        "source_revision": proof["source"]["source_revision"],
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "risk_receipt_sha256": config["risk_receipt_sha256"],
        "installed_model_receipt_sha256": config["model_receipt_sha256"],
        "timing_config_sha256": config["timing_config_sha256"],
        "cost_bps": config["cost_bps"],
        "basis": "current-vintage hypothetical strategy replay",
        "projection_source_sha256": hashlib.sha256(
            Path(simulation.__file__).read_bytes()
        ).hexdigest(),
    }
    account = json.loads(gzip.decompress(raw))
    if continuation_path is not None:
        evidence = json.loads(Path(continuation_proof).read_bytes())
        if (
            evidence["status"] != "VERIFIED_COUNTERFACTUAL_CONTINUATION"
            or evidence["sha256"] != continuation_sha
            or evidence["parent_account_sha256"] != account_sha
            or evidence["real_orders"] is not False
        ):
            raise ValueError("Independent continuation verification required")
        if evidence["config_sha256"] != provenance["config_sha256"]:
            prior_configuration(config, evidence["config_sha256"], prior_config_path)
            provenance["continuation_config_sha256"] = evidence["config_sha256"]
            provenance["configuration_change"] = "source_release_approval_only"
        child = json.loads(
            gzip.decompress(verified(continuation_path, continuation_sha))
        )
        account = simulation.continue_account(account, child, account_sha)
        provenance["continuation_sha256"] = continuation_sha
        provenance["continuation_proof_sha256"] = hashlib.sha256(
            Path(continuation_proof).read_bytes()
        ).hexdigest()
        provenance["october_artifact_assumption"] = child["assumption"]
        provenance["original_october_model_publication"] = child[
            "original_model_publication"
        ]
    projected = simulation.project(account, provenance)
    attach_splits(projected, splits_path, splits_sha)
    version = hashlib.sha256(
        json.dumps(provenance, sort_keys=True).encode()
    ).hexdigest()
    parent = Path(root) / simulation.DIRECTORY
    folder = parent / version
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    stocks = projected.pop("tickers")
    manifest = {
        "schema": simulation.SCHEMA,
        "version": version,
        "config_sha256": provenance["config_sha256"],
        "cost_bps": config["cost_bps"],
        "files": {},
    }
    for name, stock in {"summary": projected, **stocks}.items():
        value = {
            **stock,
            **{
                key: projected[key]
                for key in (
                    "schema",
                    "policy",
                    "start",
                    "through",
                    "provenance",
                    "counterfactual",
                    "real_orders",
                )
            },
        }
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        path = folder / (name + ".json")
        path.write_bytes(encoded)
        path.chmod(0o600)
        manifest["files"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if (Path(root) / "desk/learned-holding/config.json").read_bytes() != config_bytes:
        raise ValueError("Installed simulation configuration changed during projection")
    archive_configuration(root, config_bytes)
    pending = parent / (version + ".manifest.tmp")
    pending.write_text(json.dumps(manifest, indent=2))
    pending.chmod(0o600)
    os.replace(pending, parent / "manifest.json")
    return {
        "version": version,
        "stocks": len(stocks),
        "through": projected["through"],
        "account_replayed": False,
        "orders_submitted": False,
    }


# Parse explicit frozen evidence and the operator's publication destination.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "account",
        "account-sha256",
        "proof",
        "proof-sha256",
        "root",
        "splits",
        "splits-sha256",
    ):
        parser.add_argument("--" + name, required=True)
    for name in (
        "continuation",
        "continuation-sha256",
        "continuation-proof",
        "prior-config-path",
    ):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    print(
        json.dumps(
            publish(
                args.account,
                args.account_sha256,
                args.proof,
                args.proof_sha256,
                args.root,
                args.continuation,
                args.continuation_sha256,
                args.continuation_proof,
                args.splits,
                args.splits_sha256,
                args.prior_config_path,
            )
        )
    )


if __name__ == "__main__":
    main()
