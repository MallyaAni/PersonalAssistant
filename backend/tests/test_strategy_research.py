"""Frozen research keeps its original policy and authenticated publication bytes."""

import json

import pytest

from backend.market import strategy_research
from backend.tests.test_strategy_simulation import publication


# A live policy change cannot rewrite or hide separately authenticated research.
def test_original_research_survives_live_policy_change_without_writes(tmp_path):
    _, expected, _ = publication(tmp_path)
    config = tmp_path / "desk/learned-holding/config.json"
    digest = strategy_research.archive_configuration(tmp_path, config.read_bytes())
    config.write_text('{"policy":"grade-led-learned-sizing/1","cost_bps":20}')
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert strategy_research.read(tmp_path, "stock") == expected
    assert {
        str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    } == before
    archive = tmp_path / "desk/strategy-simulation/configurations" / (digest + ".json")
    archive.write_text("{}")
    with pytest.raises(ValueError, match="original configuration"):
        strategy_research.read(tmp_path, "STOCK")


# Missing snapshots, altered projection source and malformed digests fail closed.
@pytest.mark.parametrize("failure", ["missing", "source", "path"])
def test_research_rejects_missing_or_changed_authentication(tmp_path, failure):
    path, stock, manifest = publication(tmp_path)
    if failure == "missing":
        (tmp_path / "desk/learned-holding/config.json").write_text("{}")
    elif failure == "source":
        import hashlib

        stock["provenance"]["projection_source_sha256"] = "0" * 64
        raw = json.dumps(stock).encode()
        path.write_bytes(raw)
        manifest["files"]["STOCK"] = hashlib.sha256(raw).hexdigest()
    else:
        manifest["config_sha256"] = "../config"
    (tmp_path / "desk/strategy-simulation/manifest.json").write_text(
        json.dumps(manifest)
    )
    with pytest.raises(ValueError, match="Simulation"):
        strategy_research.read(tmp_path, "STOCK")
