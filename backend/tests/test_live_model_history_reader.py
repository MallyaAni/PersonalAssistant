"""Current-model historical amounts must stay bound to live configuration and bytes."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from backend.market import learned_live_holding
from backend.market import live_model_history_projection as projection
from backend.market.grade_led_policy import POLICY
from backend.market.live_model_history_reader import read


# Save one publication with separate current holding and timing identities.
def publication(root):
    config_digests = {}
    for name in ("holding", "timing"):
        path = root / "desk" / ("learned-" + name) / "config.json"
        path.parent.mkdir(parents=True)
        raw = json.dumps({"policy": POLICY, "model": name}).encode()
        path.write_bytes(raw)
        config_digests[name + "_config_sha256"] = sha256(raw).hexdigest()
    account = "a" * 64
    value = {
        "schema": projection.SCHEMA,
        "policy": POLICY,
        "ticker": "AAA",
        "start": "2019-03-01",
        "through": "2026-10-12",
        "counterfactual": True,
        "real_orders": False,
        "decisions": [{"action": "ADD", "qty": 5}],
        "trades": [],
        "provenance": {
            **config_digests,
            "basis": "fixed_current_models_applied_retrospectively",
            "cost_bps": 10,
            "source_sha256": learned_live_holding.source_identity(),
            "account_sha256": account,
            "projection_source_sha256": sha256(
                Path(projection.__file__).read_bytes()
            ).hexdigest(),
            "verification": {
                "status": "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT",
                "account_sha256": account,
            },
        },
    }
    folder = root / projection.DIRECTORY
    version = "b" * 64
    path = folder / version / "AAA.json"
    path.parent.mkdir(parents=True)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    manifest = {
        "schema": projection.SCHEMA,
        "version": version,
        "account_sha256": account,
        "files": {"AAA": sha256(raw).hexdigest()},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return value, path


# Preserve amounts and refuse payload corruption or a changed live model selector.
def test_reader_preserves_exact_amounts_and_checks_live_identity(tmp_path):
    value, path = publication(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert read(tmp_path, "aaa") == value
    assert {
        str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    } == before
    path.write_text(path.read_text().replace('"qty": 5', '"qty": 6'))
    with pytest.raises(ValueError, match="bytes differ"):
        read(tmp_path, "AAA")
    path.write_bytes(before[str(path)])
    (tmp_path / "desk/learned-holding/config.json").write_text("{}")
    with pytest.raises(ValueError, match="live configuration"):
        read(tmp_path, "AAA")
    with pytest.raises(ValueError, match="unavailable"):
        read(tmp_path, "../BBB")


# A correctly hashed payload still fails when its historical policy source is stale.
def test_reader_rejects_changed_live_source_even_with_valid_payload_hash(tmp_path):
    value, path = publication(tmp_path)
    value["provenance"]["source_sha256"] = {}
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    manifest_path = tmp_path / projection.DIRECTORY / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["AAA"] = sha256(raw).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="live trading source"):
        read(tmp_path, "AAA")
