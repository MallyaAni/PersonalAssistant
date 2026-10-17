"""Current historical audit formats cannot authorize production publication."""

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from backend.cli import market_publish_live_history as publisher
from backend.market import live_model_history_projection as projection
from backend.tests.live_history_publication_fixture import stage_private_fixture


# Reject declared success, partial scope and forged flags before account access.
@pytest.mark.parametrize(
    "proof",
    [
        {},
        {"status": "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT"},
        {"status": "VERIFIED_HISTORICAL_LEDGER_SOURCE_AND_HOLDING_CHECKS_ONLY"},
        {
            "status": "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT",
            "historical_publication_authorized": True,
            "learned_timing_inference_verified": True,
            "every_saved_nightly_model_proposal_verified": True,
            "full_model_and_live_timing_acceptance": "VERIFIED",
        },
    ],
)
def test_current_and_forged_proofs_never_create_or_select_history(
    tmp_path, monkeypatch, proof
):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(proof))
    destination = tmp_path / "absent-destination"
    account = tmp_path / "absent-account"

    # Any projection would cross the unavailable acceptance boundary.
    def forbidden(*args, **kwargs):
        raise AssertionError("Publication must stop before projection")

    monkeypatch.setattr(projection, "project", forbidden)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="publication blocked.*unverified"):
        publisher.publish(
            account,
            path,
            sha256(before).hexdigest(),
            destination,
            frozen_market=tmp_path / "absent-frozen",
            source_reviews=("f" * 64,),
        )
    assert path.read_bytes() == before
    assert not destination.exists() and not account.exists()
    with pytest.raises(ValueError, match="proof bytes differ"):
        publisher.publish(account, path, "0" * 64, destination)


# Exercise the actual CLI under optimization and preserve an existing selected version.
@pytest.mark.parametrize("optimized", [False, True])
def test_publication_cli_fails_closed_without_touching_existing_history(
    tmp_path, optimized
):
    proof = tmp_path / "forged.json"
    proof.write_text(
        json.dumps(
            {
                "status": "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT",
                "historical_publication_authorized": True,
                "learned_timing_inference_verified": True,
            }
        )
    )
    manifest = tmp_path / projection.DIRECTORY / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"original selected manifest\r\n")
    before = {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    command = [sys.executable, *(["-O"] if optimized else []), "-m"]
    result = subprocess.run(
        command
        + [
            "backend.cli.market_publish_live_history",
            "--account",
            str(tmp_path / "absent-account"),
            "--proof",
            str(proof),
            "--proof-sha256",
            sha256(proof.read_bytes()).hexdigest(),
            "--root",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Historical publication blocked" in result.stderr
    assert not result.stdout
    assert {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before


# The retained synthetic staging helper is unavailable without both private test guards.
@pytest.mark.parametrize("missing", ["pytest", "marker"])
def test_controlled_staging_is_only_a_private_pytest_fixture(
    tmp_path, monkeypatch, missing
):
    if missing == "pytest":
        (tmp_path / "PRIVATE_CONTROLLED_FIXTURE").touch()
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    before = {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    with pytest.raises(ValueError, match="private controlled fixture"):
        stage_private_fixture(None, None, None, tmp_path)
    assert {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before
