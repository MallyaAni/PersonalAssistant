"""Noncontiguous saved evidence, reused arithmetic and real account reconciliation."""

import ast
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from backend.cli import verify_actual_policy_continuation as verifier
from backend.cli import verify_actual_policy_timing as ledger
from backend.cli import verify_joint_funded as funded
from backend.tests.test_continue_actual_policy_timing import original_study
from backend.tests.test_live_policy_replay import fixture
from backend.tests.test_verify_actual_policy_timing import actual_account, saved_archive


# Persist an acknowledgment independently of its completed account receipt.
def acknowledge(study, row, count):
    receipts = study / "receipts"
    receipts.mkdir(exist_ok=True)
    (receipts / (row["id"] + ".json")).write_text(json.dumps(row))
    (receipts / f"completed-{count:03d}.json").write_text(
        json.dumps({"completed": count, "account": row["id"], "sha256": row["sha256"]})
    )


# Build a full declared grid with a fee account completed ahead of zero-cost phases.
def noncontiguous(tmp_path):
    study = tmp_path / "study"
    identity, progress = original_study(study)
    plan = {
        "identity": identity,
        "progress": progress,
        "pending": identity["accounts"][2:],
    }
    spec = next(row for row in identity["accounts"] if row["id"] == "rule-10-0")
    row = saved_archive(study, {"comparison_account": spec}, spec)
    row["scores"] = {}
    acknowledge(study, row, 3)
    return study, identity, plan, row


# Preserve noncontiguous fee evidence and all pending accounts without prefix coercion.
def test_noncontiguous_receipts_and_unacknowledged_accounts(tmp_path):
    study, identity, plan, row = noncontiguous(tmp_path)
    loose = copy.deepcopy(row)
    loose["id"] = "unacknowledged"
    (study / "receipts" / "unacknowledged.json").write_text(json.dumps(loose))
    rows, artifacts = verifier.receipt_snapshot(study, plan, identity)
    assert [item["id"] for item in rows] == ["rule-0-0", "boosting-0-0", "rule-10-0"]
    assert len(identity["accounts"]) - len(rows) == 297
    assert len(artifacts) == 2


# Reject ambiguous coordinator clocks, changed specifications and corrupted archives.
@pytest.mark.parametrize("defect", ["gap", "duplicate", "spec", "hash", "bytes"])
def test_noncontiguous_receipt_tampering_rejected(tmp_path, defect):
    study, identity, plan, row = noncontiguous(tmp_path)
    receipts = study / "receipts"
    if defect == "gap":
        (receipts / "completed-003.json").rename(receipts / "completed-004.json")
    elif defect == "duplicate":
        acknowledge(study, row, 4)
    elif defect == "spec":
        row["cost_bps"] = 0
        acknowledge(study, row, 3)
    elif defect == "hash":
        row["sha256"] = "0" * 64
        acknowledge(study, row, 3)
    else:
        (study / row["file"]).write_bytes(b"corrupted original archive")
    with pytest.raises(
        ValueError, match="coordinator|repeated|receipt spec|closed bytes"
    ):
        verifier.receipt_snapshot(study, plan, identity)


# Prior verified rows cannot be silently removed, relabelled or numerically changed.
@pytest.mark.parametrize(
    "defect", [None, "missing", "duplicate", "score", "spec", "hash"]
)
def test_reuse_requires_unchanged_verified_evidence(tmp_path, defect):
    study, identity, plan, _ = noncontiguous(tmp_path)
    rows, _ = verifier.receipt_snapshot(study, plan, identity)
    prior = copy.deepcopy(rows[0])
    prior.pop("file")
    prior["counts"] = {"sessions": 1}
    previous = {
        "status": "VERIFIED_SAVED_PREFIX_ARITHMETIC",
        "adoption_eligible": False,
        "verified_control_accounts": 1,
        "control_accounts": [prior],
    }
    if defect == "missing":
        rows = rows[1:]
    elif defect == "duplicate":
        previous["control_accounts"].append(copy.deepcopy(prior))
        previous["verified_control_accounts"] = 2
    elif defect == "score":
        prior["scores"]["fabricated"] = 1
    elif defect == "spec":
        prior["cost_bps"] = 25
    elif defect == "hash":
        prior["sha256"] = "0" * 64
    if defect is not None:
        with pytest.raises(ValueError, match="verified account|prior"):
            verifier.reuse_verified(rows, previous)
    else:
        reused, new = verifier.reuse_verified(rows, previous)
        assert list(reused) == ["rule-0-0"]
        assert [row["id"] for row in new] == ["boosting-0-0", "rule-10-0"]


# Combine real saved accounts with existing proof while forbidding any replay or fit.
def test_incremental_real_ledger_and_pending_comparisons(tmp_path, monkeypatch):
    study = tmp_path / "study"
    study.mkdir()
    rows, accounts = [], []
    for arm in ("rule", "SPY", "QQQ"):
        setup = tmp_path / arm
        setup.mkdir()
        account, spec, data = actual_account(setup, arm)
        row = saved_archive(study, account, spec)
        row["scores"] = {
            name: ledger.independent_score(account, lower, upper)
            for name, lower, upper in ledger.WINDOWS
        }
        rows.append(row)
        accounts.append(spec)
    original = rows[:1]
    plan = {
        "identity": {"accounts": accounts},
        "progress": {"accounts": original, "completed": 1, "declared": 3},
        "pending": accounts[1:],
        "identity_sha256": "a" * 64,
        "original_source": {"manifest_sha256": "b" * 64},
    }
    # Only SPY is acknowledged; QQQ's archive must remain pending.
    acknowledge(study, rows[1], 2)
    identity = {"accounts": accounts, "original_files": {}}
    prior = funded.verify_rows(study, original, data)
    candidates = [
        {**prior[0], "id": f"market-{cost}-0", "cost_bps": cost} for cost in (0, 10, 25)
    ]
    candidate_study = tmp_path / "candidate"
    (candidate_study / "accounts").mkdir(parents=True)
    for row in candidates:
        path = candidate_study / "accounts" / (row["id"] + ".json.gz")
        path.write_bytes(b"previous independently verified candidate")
        row["sha256"] = ledger.digest(path)
    previous = {
        "status": "VERIFIED_SAVED_PREFIX_ARITHMETIC",
        "adoption_eligible": False,
        "verified_control_accounts": 1,
        "control_accounts": prior,
        "candidate_accounts": candidates,
        "control_identity_sha256": plan["identity_sha256"],
        "sources": {"control": plan["original_source"]},
    }
    config = {
        "study": str(study),
        "candidate_study": str(candidate_study),
        "input_arguments": {"snapshot": str(tmp_path / "snapshot.npz")},
        "verifier_revision": "c" * 40,
    }
    _, raw, _ = fixture()
    data["grades"], data["eligible"] = raw.grades.copy(), raw.eligible.copy()
    np.savez(
        config["input_arguments"]["snapshot"],
        grades=data["grades"],
        eligible=data["eligible"],
    )
    identity["original_files"] = {
        config["input_arguments"]["snapshot"]: ledger.digest(
            config["input_arguments"]["snapshot"]
        )
    }
    for name, value in (("plan", plan), ("previous", previous)):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value))
        config[name], config[name + "_sha256"] = str(path), ledger.digest(path)
    (study / "identity.json").write_text(json.dumps(identity))
    config["identity_sha256"] = ledger.digest(study / "identity.json")
    monkeypatch.setattr(verifier, "continuation_identity", lambda *args: None)
    monkeypatch.setattr(ledger, "load_original_data", lambda *args, **kwargs: data)
    monkeypatch.setattr(ledger, "fixed_grid", lambda dates: accounts)

    # The verification path must fold saved transactions, never regenerate them.
    def forbidden(*args, **kwargs):
        raise AssertionError("Account replay or fitting is forbidden")

    monkeypatch.setattr("backend.market.live_policy_replay.run_account", forbidden)
    monkeypatch.setattr("backend.market.live_policy_replay.run_benchmark", forbidden)
    seen = []
    original_verify = funded.verify_rows

    # Observe that only the newly acknowledged SPY ledger is folded.
    def record_new(root, new, supplied):
        seen.extend(row["id"] for row in new)
        return original_verify(root, new, supplied)

    monkeypatch.setattr(funded, "verify_rows", record_new)
    output = tmp_path / "verified.json"
    result = verifier.verify(config, output)
    assert seen == ["SPY-10-0"]
    assert result["newly_verified_controls"] == ["SPY-10-0"]
    assert result["pending_control_accounts"] == ["QQQ-10-0"]
    assert result["reused_verified_controls"] == 1
    assert result["accounts_replayed"] == result["models_fitted"] == 0
    assert not result["adoption_eligible"]
    assert output.stat().st_mode & 0o777 == 0o600
    matched = [
        row
        for row in result["paired"]
        if row["cost_bps"] == 10 and row["window"] == "full"
    ]
    assert {row["reference"]: row["status"] for row in matched} == {
        "rule": "paired_complete_wealth",
        "SPY": "paired_complete_wealth",
        "QQQ": "pending_control",
        "boosting": "pending_control",
        "ridge": "pending_control",
    }
    with pytest.raises(ValueError, match="Fresh external"):
        verifier.verify(config, output)


# Keep economic producers and model prediction modules outside the verifier imports.
def test_verifier_imports_only_saved_ledger_helpers():
    source = Path(verifier.__file__).read_text()
    tree = ast.parse(source)
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all(
        "market_actual_policy_timing" not in ast.unparse(node) for node in imports
    )
    assert all("live_policy_replay" not in ast.unparse(node) for node in imports)
    assert all("sklearn" not in ast.unparse(node) for node in imports)


# Reject changed runtime ownership or lineage before accessing any economic account.
@pytest.mark.parametrize(
    "defect",
    [
        None,
        "network",
        "cpu",
        "memory",
        "root",
        "source",
        "writable",
        "active_original",
        "original_oom",
        "scheduler",
        "reused",
        "economic_identity",
    ],
)
def test_continuation_runtime_and_lineage_guards(tmp_path, monkeypatch, defect):
    scheduler = tmp_path / "scheduler.py"
    scheduler.write_bytes(b"reviewed scheduler bytes")
    terminal = {
        "Id": "original",
        "Image": "image",
        "State": {
            "Status": "exited",
            "Running": False,
            "OOMKilled": False,
            "FinishedAt": "2026-10-07T18:48:31Z",
        },
    }
    runtime = {
        "Id": "continuation",
        "Image": "image",
        "State": {"OOMKilled": False},
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "NanoCpus": 2_000_000_000,
            "Memory": 4 * 1024**3,
        },
        "Config": {"User": "1000:1000", "Cmd": ["python", "/scheduler.py", "execute"]},
        "Mounts": [
            {"Destination": "/app", "Source": "original-source", "RW": False},
            {"Destination": "/scheduler.py", "Source": "scheduler", "RW": False},
            {"Destination": "/continuation", "Source": "private-output", "RW": True},
        ],
    }
    plan = {
        "original_container": "original",
        "original_image": "image",
        "scheduler_sha256": ledger.digest(scheduler),
        "progress": {"accounts": [1, 2]},
        "identity": {"economic_contract": "unchanged", "runtime": "old"},
        "original_source": {"git_commit": "a" * 40},
    }
    if defect in ("network", "cpu", "memory"):
        key = {"network": "NetworkMode", "cpu": "NanoCpus", "memory": "Memory"}[defect]
        runtime["HostConfig"][key] = "bridge" if defect == "network" else 1
    elif defect == "root":
        runtime["Config"]["User"] = "0"
    elif defect == "source":
        runtime["Mounts"][0]["Source"] = "different-source"
    elif defect == "writable":
        runtime["Mounts"][0]["RW"] = True
    elif defect == "active_original":
        terminal["State"]["Running"] = True
    elif defect == "original_oom":
        terminal["State"]["OOMKilled"] = True
    elif defect == "scheduler":
        plan["scheduler_sha256"] = "0" * 64
    config = {
        "container_id": "continuation",
        "host_source": "original-source",
        "host_scheduler": "scheduler",
        "host_continuation": "private-output",
        "scheduler": str(scheduler),
        "plan_sha256": "plan",
        "manifest": str(tmp_path / "manifest.json"),
        "source": "unused-in-test",
    }
    for name, value in (("terminal", terminal), ("inspection", [runtime])):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value))
        config[name], config[name + "_sha256"] = str(path), ledger.digest(path)
    identity = {
        "economic_contract": "unchanged",
        "runtime": "new",
        "continuation": {
            "plan_sha256": "plan",
            "scheduler_sha256": ledger.digest(scheduler),
            "original_container": "original",
            "terminal_receipt_sha256": config["terminal_sha256"],
            "reused_accounts": 2,
            "workers": 2,
            "partial_original_state_resumed": False,
        },
    }
    if defect == "reused":
        identity["continuation"]["reused_accounts"] = 3
    elif defect == "economic_identity":
        identity["economic_contract"] = "modified"
    monkeypatch.setattr(ledger, "check_identity", lambda *args: None)
    if defect is None:
        verifier.continuation_identity(config, plan, identity)
    else:
        with pytest.raises(
            ValueError, match="producer|runtime|mount|lineage|identity|evidence"
        ):
            verifier.continuation_identity(config, plan, identity)
