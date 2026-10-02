"""Joint context/identity tests; mocked outputs do not establish model behavior."""

import copy
from dataclasses import asdict

import numpy as np
import pytest

from backend.market import open_source_forecasts as base
from backend.market import specialist_forecasts as joint
from backend.tests.test_open_source_forecasts import payload as original_payload


# Supply an explicit broad-market proxy while preserving known baseline timestamps.
def fixture():
    payload = original_payload()
    proxies = []
    for row in payload["rows"]:
        if row["symbol"] == "SPY":
            added = dict(row, symbol="QQQ")
            for field in ("open", "high", "low", "close"):
                added[field] *= 2
            proxies.append(added)
    payload["rows"].extend(proxies)
    decision = payload["decisions"][0]
    evidence = {
        "symbols": ["QQQ"],
        "kind": "broad_market_proxy",
        "source": "synthetic declared research proxy",
        "availability_mode": "assumed_research_map",
        "available_at": decision + "T16:00:00-04:00",
    }
    mappings = {"AAPL": evidence, "SPY": evidence}
    records = []
    for symbol in mappings:
        rows, future = base.context(payload, symbol, decision)
        forecast = [rows[-1]["close"] * 1.01] * base.HORIZON
        records.append(
            {
                "model": "chronos2",
                "symbol": symbol,
                "decision": decision,
                "status": "forecast",
                "context_hash": base.digest(rows),
                "forecast": forecast,
                "predicted_excess_return": 0.0,
            }
        )
    baseline = {
        "protocol": base.PROTOCOL,
        "checkpoint": asdict(base.CHECKPOINTS["chronos2"]),
        "source_revision": payload["source_revision"],
        "input_sha256": "input-test-hash",
        "records": records,
    }
    return payload, mappings, baseline


class Fake:
    # Initialize test identities without pretending to load checkpoint weights.
    def __init__(self):
        self.spec = base.CHECKPOINTS["chronos2"]
        self.runtime = {"mocked": "test-only"}
        self.shapes = {}

    # Return known channel-dependent predictions to test stock-minus-SPY units.
    def predict(self, contexts, future):
        count = len(contexts)
        self.shapes = {
            "input": [count, base.CONTEXT],
            "native_output": [count, 10, 1],
            "median_output": [count, 10],
        }
        return np.array(
            [
                [r[-1]["close"] * (1 + i / 100)] * len(future)
                for i, r in enumerate(contexts)
            ]
        )


# Exercise the common mocked artifact path with immutable baseline comparison inputs.
def candidate(payload, mappings, baseline):
    return joint.run(
        payload,
        "chronos2",
        ["AAPL", "SPY"],
        mappings,
        baseline,
        input_sha256="input-test-hash",
        forecaster=Fake(),
    )


# Future price alterations cannot enter the synchronized causal group.
def test_future_prefix_invariance():
    payload, mappings, baseline = fixture()
    first = candidate(payload, mappings, baseline)
    other = copy.deepcopy(payload)
    for row in other["rows"]:
        if row["session"] > other["decisions"][0]:
            row["close"] = 999999
    assert first == candidate(other, mappings, baseline)


# Missing proxy evidence remains visible rather than silently using SPY alone.
def test_missing_context_is_retained():
    payload, mappings, baseline = fixture()
    mappings.pop("AAPL")
    records = candidate(payload, mappings, baseline)["records"]
    assert len(records) == 2
    assert records[0]["reason"] == "missing_context_evidence"
    assert records[1]["status"] == "forecast"


# Peer context must already exist on the exact same completed exchange grid.
def test_missing_peer_bar_blocks_joint_forecast():
    payload, mappings, baseline = fixture()
    payload["rows"] = [
        r
        for r in payload["rows"]
        if not (r["symbol"] == "QQQ" and r["session"] == payload["decisions"][0])
    ]
    assert all(
        r["status"] == "unavailable"
        for r in candidate(payload, mappings, baseline)["records"]
    )


# Membership declared later cannot become available through a caller clock.
def test_late_context_evidence_blocks():
    payload, mappings, baseline = fixture()
    mappings["AAPL"]["available_at"] = "2027-01-01T00:00:00Z"
    assert (
        candidate(payload, mappings, baseline)["records"][0]["reason"]
        == "context_evidence_not_available"
    )


# SPY is present once, including when it is the target asset.
def test_spy_dedup_and_relative_units():
    payload, mappings, baseline = fixture()
    artifact = candidate(payload, mappings, baseline)
    assert artifact["records"][0]["members"] == ["AAPL", "QQQ", "SPY"]
    assert artifact["records"][0]["predicted_excess_return"] == pytest.approx(-0.02)
    assert artifact["records"][1]["members"] == ["SPY", "QQQ"]
    assert artifact["records"][1]["predicted_excess_return"] == 0
    assert len(joint.validate_artifact(payload, artifact, mappings, baseline)) == 2


# The preserved univariate baseline must share the exact checkpoint and input artifact.
@pytest.mark.parametrize("field", ["input_sha256", "source_revision", "protocol"])
def test_wrong_baseline_identity_refused(field):
    payload, mappings, baseline = fixture()
    baseline[field] = "wrong"
    with pytest.raises(ValueError, match="identity"):
        candidate(payload, mappings, baseline)


# Baseline records with a different causal prefix cannot be paired.
def test_baseline_context_hash_mismatch():
    payload, mappings, baseline = fixture()
    baseline["records"][0]["context_hash"] = "wrong"
    assert (
        candidate(payload, mappings, baseline)["records"][0]["reason"]
        == "univariate_context_mismatch"
    )


# Context kind never defaults to a sector label for a broad benchmark.
def test_explicit_context_kind_required():
    payload, mappings, baseline = fixture()
    mappings["AAPL"].pop("kind")
    assert (
        candidate(payload, mappings, baseline)["records"][0]["status"] == "unavailable"
    )


# Reject altered returns, hashes, channels and opportunity loss.
@pytest.mark.parametrize(
    "mutation", ["excess", "context", "channels", "missing", "profile"]
)
def test_joint_artifact_tampering_refused(mutation):
    payload, mappings, baseline = fixture()
    artifact = candidate(payload, mappings, baseline)
    if mutation == "excess":
        artifact["records"][0]["predicted_excess_return"] += 1
    elif mutation == "context":
        artifact["records"][0]["context_hash"] = "wrong"
    elif mutation == "channels":
        artifact["records"][0]["channel_forecasts"].pop("QQQ")
    elif mutation == "missing":
        artifact["records"].pop()
    else:
        artifact["profile"]["horizon"] = 20
    with pytest.raises(ValueError, match="joint"):
        joint.validate_artifact(payload, artifact, mappings, baseline)


# Restricted weights require research mode even with an injected engine.
def test_timesfm_research_gate():
    payload, mappings, baseline = fixture()
    with pytest.raises(ValueError, match="noncommercial"):
        joint.run(
            payload,
            "timesfm3",
            ["AAPL"],
            mappings,
            baseline,
            input_sha256="input-test-hash",
            forecaster=Fake(),
        )


# A forged cash-only omission is refused when all causal inputs are present.
def test_false_unavailability_refused():
    payload, mappings, baseline = fixture()
    artifact = candidate(payload, mappings, baseline)
    artifact["records"][0].update(status="unavailable", reason="invented")
    with pytest.raises(ValueError, match="falsely_unavailable"):
        joint.validate_artifact(payload, artifact, mappings, baseline)


# A genuine missing proxy remains valid evidence even without a loaded runtime.
def test_all_unavailable_needs_no_model_load():
    payload, mappings, baseline = fixture()
    artifact = candidate(payload, {}, baseline)
    artifact["runtime"] = {}
    assert len(joint.validate_artifact(payload, artifact, {}, baseline)) == 2
