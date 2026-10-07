"""Verify newly closed continuation accounts without fitting or replaying them.

Completion order is deliberately noncontiguous. Only coordinator-acknowledged
receipts enter this snapshot; every other declared account remains pending.
Previously verified arithmetic is reused only with unchanged account bytes,
specifications and scores. A partial report never authorizes live adoption.
"""

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.cli import verify_actual_policy_timing as ledger
from backend.cli import verify_joint_funded as funded

SPEC_KEYS = ("arm", "cost_bps", "start", "first", "last", "first_session", "id")
STATUS = "VERIFIED_CONTINUATION_SNAPSHOT_ARITHMETIC"


# Read only completed coordinator acknowledgments, retaining the full original grid.
def receipt_snapshot(study, plan, identity):
    grid, reused = plan["identity"]["accounts"], plan["progress"]["accounts"]
    ledger.same(identity["accounts"], grid, "continuation grid")
    ledger.same(plan["progress"]["completed"], len(reused), "reused count")
    ledger.same(plan["progress"]["declared"], len(grid), "declared count")
    ledger.same(plan["pending"], grid[len(reused) :], "original pending accounts")
    ledger.same(
        [{key: row[key] for key in SPEC_KEYS} for row in reused],
        grid[: len(reused)],
        "original completed prefix",
    )
    by_id = {spec["id"]: spec for spec in grid}
    ledger.require(len(by_id) == len(grid), "Duplicate declared account")
    rows = {row["id"]: row for row in reused}
    paths = sorted((study / "receipts").glob("completed-*.json"))
    artifacts = {}
    for count, path in enumerate(paths, len(reused) + 1):
        ledger.same(path.name, f"completed-{count:03d}.json", "coordinator sequence")
        expected = ledger.digest(path)
        ack = ledger.read_json(path, expected)
        ledger.same(ack["completed"], count, "coordinator count")
        identifier = ack["account"]
        ledger.require(
            identifier in by_id and identifier not in rows,
            "Unknown or repeated completed receipt",
        )
        receipt = study / "receipts" / (identifier + ".json")
        receipt_hash = ledger.digest(receipt)
        row = ledger.read_json(receipt, receipt_hash)
        ledger.same(
            {key: row[key] for key in SPEC_KEYS}, by_id[identifier], "receipt spec"
        )
        ledger.same(row["sha256"], ack["sha256"], "acknowledged account bytes")
        rows[identifier] = row
        artifacts[str(path)] = expected
        artifacts[str(receipt)] = receipt_hash
    for row in rows.values():
        ledger.same(row["file"], f"accounts/{row['id']}.json.gz", "closed account path")
        ledger.same(ledger.digest(study / row["file"]), row["sha256"], "closed bytes")
    return [rows[spec["id"]] for spec in grid if spec["id"] in rows], artifacts


# Reuse authenticated prior arithmetic only for identical currently closed accounts.
def reuse_verified(rows, previous):
    ledger.require(
        previous["status"] in ("VERIFIED_SAVED_PREFIX_ARITHMETIC", STATUS)
        and previous["adoption_eligible"] is False,
        "Independent prior arithmetic required",
    )
    prior = previous["control_accounts"]
    ledger.same(previous["verified_control_accounts"], len(prior), "prior count")
    indexed = {row["id"]: row for row in prior}
    ledger.require(len(indexed) == len(prior), "Duplicate prior verified account")
    closed = {row["id"]: row for row in rows}
    ledger.require(set(indexed) <= set(closed), "Previously verified account missing")
    for identifier, verified in indexed.items():
        row = closed[identifier]
        ledger.same(
            {key: verified[key] for key in SPEC_KEYS},
            {key: row[key] for key in SPEC_KEYS},
            "prior specification",
        )
        ledger.same(verified["sha256"], row["sha256"], "prior account bytes")
        ledger.same(verified["scores"], row["scores"], "prior scores")
    return indexed, [row for row in rows if row["id"] not in indexed]


# Authenticate the stopped original, unchanged engine and isolated continuation.
def continuation_identity(config, plan, identity):
    runtime = ledger.read_json(config["inspection"], config["inspection_sha256"])
    ledger.require(len(runtime) == 1, "One actual continuation runtime required")
    actual = runtime[0]
    terminal = ledger.read_json(config["terminal"], config["terminal_sha256"])
    ledger.require(
        terminal["Id"] == plan["original_container"]
        and terminal["Image"] == plan["original_image"]
        and terminal["State"]["Status"] == "exited"
        and terminal["State"]["Running"] is False
        and terminal["State"]["OOMKilled"] is False
        and terminal["State"]["FinishedAt"] not in ("", "0001-01-01T00:00:00Z"),
        "Stopped original producer required",
    )
    ledger.require(
        actual["Id"] == config["container_id"]
        and actual["Image"] == plan["original_image"]
        and actual["State"]["OOMKilled"] is False
        and actual["HostConfig"]["NetworkMode"] == "none"
        and actual["HostConfig"]["ReadonlyRootfs"] is True
        and actual["HostConfig"]["NanoCpus"] == 2_000_000_000
        and actual["HostConfig"]["Memory"] == 4 * 1024**3
        and actual["Config"]["User"] in ("1000", "1000:1000")
        and actual["Config"]["Cmd"][:3] == ["python", "/scheduler.py", "execute"],
        "Actual bounded continuation runtime differs",
    )
    mounts = {row["Destination"]: row for row in actual["Mounts"]}
    ledger.require(
        len(mounts) == len(actual["Mounts"])
        and all(not row["RW"] for key, row in mounts.items() if key != "/continuation")
        and mounts["/continuation"]["Source"] == config["host_continuation"]
        and mounts["/continuation"]["RW"] is True
        and mounts["/app"]["Source"] == config["host_source"]
        and mounts["/scheduler.py"]["Source"] == config["host_scheduler"],
        "Continuation ownership or source mount differs",
    )
    ledger.same(ledger.digest(config["scheduler"]), plan["scheduler_sha256"])
    ledger.same(
        identity["continuation"],
        {
            "plan_sha256": config["plan_sha256"],
            "scheduler_sha256": plan["scheduler_sha256"],
            "original_container": terminal["Id"],
            "terminal_receipt_sha256": config["terminal_sha256"],
            "reused_accounts": len(plan["progress"]["accounts"]),
            "workers": 2,
            "partial_original_state_resumed": False,
        },
        "continuation lineage",
    )
    ledger.same(
        {
            key: value
            for key, value in identity.items()
            if key not in ("runtime", "continuation")
        },
        {key: value for key, value in plan["identity"].items() if key != "runtime"},
        "unchanged economic identity",
    )
    ledger.check_identity(
        identity,
        Path(config["manifest"]),
        plan["original_source"]["git_commit"],
        plan["original_image"],
        Path(config["source"]),
    )


# Check only new closed rows and publish all matched comparisons with pending IDs.
def verify(config, output):
    output, study = Path(output), Path(config["study"])
    ledger.require(
        not output.exists() and not output.resolve().is_relative_to(study.resolve()),
        "Fresh external verification artifact required",
    )
    plan = ledger.read_json(config["plan"], config["plan_sha256"])
    identity = ledger.read_json(study / "identity.json", config["identity_sha256"])
    previous = ledger.read_json(config["previous"], config["previous_sha256"])
    continuation_identity(config, plan, identity)
    lineage = {
        "plan_sha256": config["plan_sha256"],
        "identity_sha256": config["identity_sha256"],
        "source": plan["original_source"],
        "original_identity_sha256": plan["identity_sha256"],
    }
    if previous["status"] == STATUS:
        ledger.same(previous["lineage"], lineage, "previous continuation")
    else:
        ledger.same(previous["control_identity_sha256"], plan["identity_sha256"])
        ledger.same(
            previous["sources"]["control"]["manifest_sha256"],
            plan["original_source"]["manifest_sha256"],
        )
    rows, artifacts = receipt_snapshot(study, plan, identity)
    checked, pending_check = reuse_verified(rows, previous)
    args = SimpleNamespace(
        **{key: Path(value) for key, value in config["input_arguments"].items()}
    )
    data = ledger.load_original_data(args, identity, reviewed=True)
    ledger.same(identity["accounts"], ledger.fixed_grid(data["dates"]))
    with np.load(args.snapshot, allow_pickle=False) as archive:
        data["grades"], data["eligible"] = archive["grades"], archive["eligible"]
    new = funded.verify_rows(study, pending_check, data)
    checked.update({row["id"]: row for row in new})
    controls = [
        checked[spec["id"]] for spec in identity["accounts"] if spec["id"] in checked
    ]
    candidates = previous["candidate_accounts"]
    ledger.require(
        len(candidates) == 3
        and {row["cost_bps"] for row in candidates} == {0, 10, 25}
        and all(row["start"] == 0 for row in candidates),
        "All three original candidate accounts required",
    )
    for row in candidates:
        ledger.same(
            ledger.digest(
                Path(config["candidate_study"]) / "accounts" / (row["id"] + ".json.gz")
            ),
            row["sha256"],
            "previous candidate bytes",
        )
    candidate_grid = [{key: row[key] for key in SPEC_KEYS} for row in candidates]
    result = {
        "status": STATUS,
        "adoption_eligible": False,
        "lineage": lineage,
        "previous_sha256": config["previous_sha256"],
        "verifier_revision": config["verifier_revision"],
        "evidence": config,
        "snapshot_receipts": artifacts,
        "verified_control_accounts": len(controls),
        "newly_verified_controls": [row["id"] for row in new],
        "reused_verified_controls": len(controls) - len(new),
        "pending_control_accounts": [
            spec["id"] for spec in identity["accounts"] if spec["id"] not in checked
        ],
        "candidate_accounts": candidates,
        "control_accounts": controls,
        "paired": funded.paired_results(
            candidates,
            controls,
            candidate_grid,
            references=("rule", "boosting", "ridge", "SPY", "QQQ"),
        ),
        "timing_paired": {
            method: funded.paired_results(
                [row for row in controls if row["arm"] == method],
                controls,
                [spec for spec in identity["accounts"] if spec["arm"] == method],
            )
            for method in ("boosting", "ridge")
        },
        "models_fitted": 0,
        "accounts_replayed": 0,
        "limitations": previous.get("limitations", [])
        + [
            "noncontiguous_closed_snapshot_not_completed_study",
            "unacknowledged_accounts_remain_pending",
            "unchanged_grade_reset_and_FOMC_holding_exits",
        ],
    }
    ledger.check_originals(identity["original_files"])
    for path, expected in artifacts.items():
        ledger.same(ledger.digest(path), expected, "snapshot receipt stability")
    for row in rows:
        ledger.same(
            ledger.digest(study / row["file"]), row["sha256"], "closed stability"
        )
    ledger.same(ledger.digest(config["previous"]), config["previous_sha256"])
    ledger.same(ledger.digest(config["plan"]), config["plan_sha256"])
    ledger.same(ledger.digest(study / "identity.json"), config["identity_sha256"])
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    return result


# Require a hash-bound evidence configuration and an exclusive output path.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(ledger.read_json(args.evidence, args.evidence_sha256), args.output)


if __name__ == "__main__":
    main()
