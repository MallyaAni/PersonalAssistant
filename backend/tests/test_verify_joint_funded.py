"""Saved-only funded account proof and rejection of misleading artifact changes."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from backend.cli import verify_actual_policy_timing as ledger
from backend.cli import verify_joint_funded as verifier
from backend.cli.market_actual_policy_timing import archive_account
from backend.market.direct_error_band import VolatilityHoldingReader
from backend.market.joint_funded_policy import JointFundedPolicy
from backend.market.live_policy_replay import run_account
from backend.tests.test_direct_feature_arithmetic import risk_example_factory
from backend.tests.test_live_policy_replay import fixture
from backend.tests.test_verify_actual_policy_timing import direct_data


# Build actual private-account artifacts once; verification never calls this producer.
@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    root = tmp_path_factory.mktemp("saved-funded")
    example = risk_example_factory(tmp_path_factory, with_volatility=True)
    reader = VolatilityHoldingReader(example[-1], example[1])
    panel, raw, cubes = fixture(tuple(map(str, reader.dates)))
    policy = JointFundedPolicy(reader, 10)

    # Isolate ordinary policy receipts from synthetic event calendar fixtures.
    def features(kind, report):
        return (
            {"calendar_known": True, "factor": 1.0}
            if kind == "event"
            else (set(), {})
            if kind == "blocked"
            else {}
        )

    first, last = len(reader.dates) - 2, len(reader.dates) - 1
    account = run_account(
        panel,
        raw,
        cubes,
        root / "private",
        first,
        last,
        10,
        holding_policy=policy,
        feature_reader=features,
    )
    spec = {
        "arm": verifier.POLICY,
        "cost_bps": 10,
        "start": 0,
        "first": first,
        "last": last,
        "first_session": str(reader.dates[first]),
        "id": "joint-10-0",
    }
    account["comparison_account"] = spec
    data = {
        **direct_data(raw, cubes),
        "grades": raw.grades.copy(),
        "eligible": raw.eligible.copy(),
    }
    source = {
        "backend/market/joint_funded_policy.py": policy.identity["source_sha256"],
        verifier.PROTOCOL: policy.identity["protocol_sha256"],
    }
    return account, spec, data, source


# Persist a compressed immutable account and its independently recomputed score index.
def save(tmp_path, account, spec):
    path = tmp_path / "accounts" / (spec["id"] + ".json.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = archive_account(path, account)
    return {
        **spec,
        "file": str(path.relative_to(tmp_path)),
        "sha256": digest,
        "scores": {
            name: ledger.independent_score(account, lo, hi)
            for name, lo, hi in ledger.WINDOWS
        },
    }


# Verify saved accounts with all simulation and prediction entry points forbidden.
def test_actual_saved_account_checks_without_producer(tmp_path, saved, monkeypatch):
    account, spec, data, source = saved
    row = save(tmp_path, account, spec)

    # Any accidentally invoked producer is an acceptance failure, not a fallback.
    def forbidden(*args, **kwargs):
        raise AssertionError("No resimulation or predictions permitted")

    monkeypatch.setattr(JointFundedPolicy, "decide", forbidden)
    monkeypatch.setattr(VolatilityHoldingReader, "distribution", forbidden)
    monkeypatch.setattr("backend.market.live_policy_replay.run_account", forbidden)
    checked = verifier.verify_rows(tmp_path, [row], data, candidate=True, source=source)
    assert checked[0]["ordinary_receipts"] == 3
    assert checked[0]["counts"]["sessions"] == 2
    with pytest.raises(ValueError, match="Account policy differs"):
        ledger.reconcile_account(account, spec, data)


# Rehashed archives cannot hide altered cash, shares, source prices or permissions.
@pytest.mark.parametrize(
    "mutation",
    [
        "cash",
        "shares",
        "price",
        "fee",
        "grade",
        "policy",
        "clock",
        "certificate",
        "projection",
        "target",
    ],
)
def test_saved_candidate_tampering_rejected(tmp_path, saved, mutation):
    original, spec, data, source = saved
    account = copy.deepcopy(original)
    receipt = account["nightlies"][-1]["entry"]["joint_funded"]["receipt"]
    if mutation == "cash":
        account["sessions"][-1]["cash"] += 100
    elif mutation == "shares":
        account["sessions"][-1]["holdings"]["AAA"] = 1
    elif mutation == "price":
        account["sessions"][-1]["nav"] += 100
    elif mutation == "fee":
        account["cost_bps"] = 0
    elif mutation == "grade":
        receipt["grades"]["AAA"] = 0
    elif mutation == "policy":
        account["policy"] = ledger.POLICY
    elif mutation == "clock":
        account["nightlies"][-1]["at"] = account["nightlies"][-2]["at"]
    elif mutation == "certificate":
        receipt["optimizer"]["certificate"]["certified"] = False
    elif mutation == "projection":
        receipt["execution"]["projection_is_fill"] = True
    else:
        receipt["targets"]["SPY"] = 0.25
    row = save(tmp_path, account, spec)
    with pytest.raises(ValueError, match="differ|violates|Missing|relabelled"):
        verifier.verify_rows(tmp_path, [row], data, candidate=True, source=source)


# An altered score cannot pass by being repeated in the producer's own index.
def test_reported_gain_is_recomputed(tmp_path, saved):
    account, spec, data, source = saved
    row = save(tmp_path, account, spec)
    row["scores"]["full"]["total_gain"] += 1
    with pytest.raises(ValueError, match="independent account scores"):
        verifier.verify_rows(tmp_path, [row], data, candidate=True, source=source)


# Partial progress must retain the exact declared prefix and explicit missing accounts.
@pytest.mark.parametrize(
    "mutation", [None, "omit", "reorder", "count", "declared", "adoption"]
)
def test_partial_index_is_not_a_selected_subset(tmp_path, mutation):
    grid = [{"id": f"joint-{i}"} for i in range(3)]
    rows = copy.deepcopy(grid[:2])
    index = {
        "status": "running",
        "completed": 2,
        "declared": 3,
        "accounts": rows,
        "source": {"revision": "fixed"},
        "adoption_eligible": False,
    }
    identity = {"source": index["source"], "adoption_eligible": False}
    if mutation == "omit":
        rows[0] = grid[1]
    elif mutation == "reorder":
        rows.reverse()
    elif mutation == "count":
        index["completed"] = 3
    elif mutation == "declared":
        index["declared"] = 2
    elif mutation == "adoption":
        index["adoption_eligible"] = True
    (tmp_path / "progress.json").write_text(json.dumps(index))
    if mutation is None:
        checked, receipt = verifier.read_index(tmp_path, grid, identity, candidate=True)
        assert checked == grid[:2]
        assert receipt["status"] == "running"
    else:
        with pytest.raises(ValueError, match="differs|missing"):
            verifier.read_index(tmp_path, grid, identity, candidate=True)


# Pending first books are explicit, while unindexed saved books cannot disappear.
def test_first_account_pending_and_orphan_rejected(tmp_path):
    (tmp_path / "accounts").mkdir()
    assert verifier.read_index(tmp_path, [], {}, candidate=True)[0] == []
    (tmp_path / "accounts/orphan.json.gz").write_bytes(b"not an index")
    with pytest.raises(ValueError, match="lack a progress index"):
        verifier.read_index(tmp_path, [], {}, candidate=True)


# Original final reports bind their full grid through identity rather than a new field.
def test_original_completed_index_contract(tmp_path):
    grid = [{"id": "rule-0-0"}]
    identity = {"accounts": grid, "adoption_eligible": False}
    (tmp_path / "identity.json").write_text(json.dumps(identity))
    report = {
        "status": "complete_pending_independent_verification",
        "policy": ledger.POLICY,
        "accounts": grid,
        "adoption_eligible": False,
        "identity_sha256": ledger.digest(tmp_path / "identity.json"),
    }
    (tmp_path / "report.json").write_text(json.dumps(report))
    assert verifier.read_index(tmp_path, grid, identity, candidate=False)[0] == grid
    report["accounts"] = []
    (tmp_path / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="Incomplete final report"):
        verifier.read_index(tmp_path, grid, identity, candidate=False)


# All sixty start/cost opportunities survive pairing even with only one finished book.
def test_pairing_retains_missing_controls_and_incomplete_wealth():
    dates = np.arange(np.datetime64("2018-01-01"), np.datetime64("2026-10-01"))
    grid = verifier.candidate_grid(dates)
    score = {
        name: {"status": "complete", "total_gain": 0.5} for name, _, _ in ledger.WINDOWS
    }
    left = [{**grid[0], "scores": score}]
    right = [
        {
            "arm": "rule",
            "cost_bps": 0,
            "start": 0,
            "scores": {
                name: {"status": "missing_wealth_observations", "total_gain": 0.2}
                for name in score
            },
        }
    ]
    pairs = verifier.paired_results(left, right, grid)
    assert len(pairs) == 60 * 3 * 4
    assert pairs[0]["status"] == "paired_incomplete_wealth"
    assert pairs[0]["funded_gain_difference"] == pytest.approx(0.3)
    assert sum(row["status"] == "pending_candidate" for row in pairs) == 59 * 12
    assert sum(row["status"] == "pending_control" for row in pairs) == 8
    right[0]["arm"] = "SPY"
    right[0]["scores"]["full"]["benchmark_reference_available"] = False
    pairs = verifier.paired_results(left, right, grid)
    assert pairs[4]["status"] == "benchmark_entry_unavailable"
    assert pairs[4]["funded_gain_difference"] is None


# Scenario labels must have been known before the declared publication cutoff.
@pytest.mark.parametrize(
    ("indices", "cutoff"),
    [
        ([2], "2020-01-05"),
        ([1, 1], "2020-01-06"),
        ([False], "2020-01-06"),
        ([0], "2020-01-08"),
    ],
)
def test_scenario_future_or_duplicate_rows_rejected(indices, cutoff):
    dates = np.arange(np.datetime64("2020-01-01"), np.datetime64("2020-01-07"))
    with pytest.raises(ValueError, match="scenario"):
        verifier.scenario_receipt(
            {
                "decision_date": "2020-01-06",
                "decision_indices": indices,
                "label_end_before": cutoff,
            },
            "2020-01-06",
            dates,
        )


# The verifier does not import strategy, optimizer, predictor or producer modules.
def test_saved_verifier_dependencies_are_independent():
    import ast

    tree = ast.parse(Path(verifier.__file__).read_text())
    imports = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert all(
        not name
        or name in {"datetime", "pathlib", "types", "backend.cli", "backend.market"}
        for name in imports
    )


# A full-tree proof rejects image, isolation or mounted-byte substitution.
@pytest.mark.parametrize("mutation", [None, "byte", "image", "writable", "network"])
def test_source_and_actual_image_boundaries(tmp_path, mutation):
    source = tmp_path / "source"
    source.mkdir()
    files = {}
    for index in range(2300):
        path = source / str(index)
        path.write_bytes(b"frozen")
        files[path.name] = ledger.digest(path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"git_commit": "a" * 40, "files": files}))
    runtime = [
        {
            "Id": "container",
            "Image": "pinned-image",
            "State": {"OOMKilled": False},
            "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "none"},
            "Mounts": [
                {"Destination": "/app", "Source": "/frozen-source", "RW": False}
            ],
        }
    ]
    if mutation == "byte":
        (source / "0").write_bytes(b"changed")
    elif mutation == "image":
        runtime[0]["Image"] = "other-image"
    elif mutation == "writable":
        runtime[0]["Mounts"][0]["RW"] = True
    elif mutation == "network":
        runtime[0]["HostConfig"]["NetworkMode"] = "bridge"
    inspection = tmp_path / "inspection.json"
    inspection.write_text(json.dumps(runtime))
    spec = {
        "manifest": manifest,
        "manifest_sha256": ledger.digest(manifest),
        "revision": "a" * 40,
        "source": source,
        "inspection": inspection,
        "inspection_sha256": ledger.digest(inspection),
        "container_id": "container",
        "image_id": "pinned-image",
        "host_source": "/frozen-source",
    }
    if mutation is None:
        assert verifier.source_proof(spec)["files"] == files
    else:
        with pytest.raises(ValueError, match="differ"):
            verifier.source_proof(spec)
