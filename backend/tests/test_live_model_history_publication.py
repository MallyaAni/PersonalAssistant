"""Historical publication must persist original amounts before switching a manifest."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest

from backend.cli.market_publish_live_history import publish
from backend.market import live_model_history_projection as projection
from backend.market.live_model_history_reader import read
from backend.tests.test_live_model_history_reader import publication


# Publish a complete cohort without replacing any earlier stored version.
def test_publication_readback_complete_cohort_and_bad_proof_no_write(
    tmp_path, monkeypatch
):
    value, old_path = publication(tmp_path)
    stock_views = {
        f"TEST{index}": {**deepcopy(value), "ticker": f"TEST{index}"}
        for index in range(94)
    }
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(
        json.dumps({"account_sha256": value["provenance"]["account_sha256"]})
    )
    proof_sha = sha256(proof_path.read_bytes()).hexdigest()
    monkeypatch.setattr(projection, "project", lambda *_: stock_views)
    old_manifest = (tmp_path / projection.DIRECTORY / "manifest.json").read_bytes()
    old_payload = old_path.read_bytes()
    with pytest.raises(ValueError, match="proof bytes"):
        publish(tmp_path / "unused-account", proof_path, "0" * 64, tmp_path)
    assert (
        tmp_path / projection.DIRECTORY / "manifest.json"
    ).read_bytes() == old_manifest
    result = publish(tmp_path / "unused-account", proof_path, proof_sha, tmp_path)
    assert result["stocks"] == 94
    for name in stock_views:
        assert read(tmp_path, name)["decisions"][0]["qty"] == 5
    assert old_path.read_bytes() == old_payload
    selected = (tmp_path / projection.DIRECTORY / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        publish(tmp_path / "unused-account", proof_path, proof_sha, tmp_path)
    assert (tmp_path / projection.DIRECTORY / "manifest.json").read_bytes() == selected


# A source-invalid staged payload cannot displace an earlier readable publication.
def test_publication_validates_contract_before_switching_manifest(
    tmp_path, monkeypatch
):
    value, _ = publication(tmp_path)
    value["provenance"]["source_sha256"] = {}
    stock_views = {
        f"TEST{index}": {**deepcopy(value), "ticker": f"TEST{index}"}
        for index in range(94)
    }
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(
        json.dumps({"account_sha256": value["provenance"]["account_sha256"]})
    )
    proof_sha = sha256(proof_path.read_bytes()).hexdigest()
    monkeypatch.setattr(projection, "project", lambda *_: stock_views)
    manifest = tmp_path / projection.DIRECTORY / "manifest.json"
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="live trading source"):
        publish(tmp_path / "unused-account", proof_path, proof_sha, tmp_path)
    assert manifest.read_bytes() == before
