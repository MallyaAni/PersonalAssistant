"""The actual verification command must reconcile saved files and never rewrite them."""

import hashlib
import json
import subprocess
import sys

import numpy as np
import pytest

from backend.market.research_journal import ResearchJournal


# Write canonical synthetic evidence independently from the production archive writer.
def _json(path, value):
    path.write_bytes(
        (
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode()
    )


# Fingerprint the exact bytes a read-only verification must leave unchanged.
def _hashes(folder):
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.iterdir()
        if path.is_file()
    }


# Build one synthetic funded account with independently known fees and closing marks.
@pytest.fixture
def archive(tmp_path):
    journal = ResearchJournal(
        np.array(["2024-01-02", "2024-01-03"], dtype="datetime64[D]"),
        ["TEST"],
        np.array([[90.0], [100.0]]),
        np.array([[100.0], [110.0]]),
        run_id="cli-synthetic-run",
        account_id="cli-synthetic-account",
        policy_id="test-only/1",
        cost_bps=10,
        provenance={"basis": "synthetic test, not historical evidence"},
    )
    journal.open_account(0, 101, [0])
    journal.mark(0, 101, [0], 101, 0)
    decision = journal.decision(0, [1], [1], "one test purchase")
    journal.fill_batch(
        decision, 1, "open", [1], [100], [0], 101, [1], 0.9, 101, 1, False
    )
    journal.mark(1, 0.9, [1], 110.9, 100)
    journal.finish(1, 0.9, [1], 100, {})
    return journal.archive(tmp_path / "archive").parent


# Exercise argument parsing, archive loading and independent replay in a real process.
def _run(path):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.cli.market_verify_journal",
            "--archive",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


# Repin synthetic edits so tests reach accounting validation beyond mere byte identity.
def _repin_events(folder, events, *, status=None):
    _json(folder / "events.json", events)
    manifest = json.loads((folder / "manifest.json").read_bytes())
    if status is not None:
        manifest["status"] = status
    body = (folder / "events.json").read_bytes()
    manifest["files"]["events.json"] = {
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }
    _json(folder / "manifest.json", manifest)


# Both supported entry paths produce independently reconciled results without writes.
@pytest.mark.parametrize("manifest_path", [False, True])
def test_cli_verifies_fills_and_keeps_original_bytes(archive, manifest_path):
    before = _hashes(archive)
    process = _run(archive / "manifest.json" if manifest_path else archive)
    assert process.returncode == 0, process.stderr or process.stdout
    report = json.loads(process.stdout)
    assert report["ok"] is True
    assert report["accounting_verified"] is True
    assert report["integrity_verified"] is True
    assert report["complete"] is True
    assert report["total_fees"] == pytest.approx(0.1)
    assert report["total_traded"] == 100
    assert [row["nav"] for row in report["marks"]] == pytest.approx([101, 110.9])
    assert report["terminal"]["positions"] == [1]
    assert report["terminal"]["cash"] == pytest.approx(0.9)
    assert report["terminal"]["pending"] == {}
    for key in (
        "historical_availability_verified",
        "security_identity_verified",
        "settlement_verified",
        "adoption_eligible",
    ):
        assert report[key] is False
    assert before == _hashes(archive)


# Changed original bytes must produce a failed report and a nonzero command status.
def test_cli_rejects_changed_source_bytes_without_repairing_them(archive):
    path = archive / "prices.json"
    prices = json.loads(path.read_bytes())
    prices["open"][1][0] += 1
    _json(path, prices)
    before = _hashes(archive)
    process = _run(archive)
    assert process.returncode == 1
    report = json.loads(process.stdout)
    assert report["ok"] is False
    assert report["integrity_verified"] is False
    assert report["errors"]
    assert before == _hashes(archive)


# Matching new hashes cannot make false fees into a reconciled account.
def test_cli_detects_rehashed_false_accounting(archive):
    events = json.loads((archive / "events.json").read_bytes())
    events[3]["fees"][0] = 0.2
    _repin_events(archive, events)
    before = _hashes(archive)
    process = _run(archive)
    assert process.returncode == 1
    report = json.loads(process.stdout)
    assert report["integrity_verified"] is True
    assert report["accounting_verified"] is False
    assert any("fee" in error.lower() for error in report["errors"])
    assert before == _hashes(archive)


# Incomplete evidence must remain a failed verification, not an implicitly finished run.
def test_cli_cannot_complete_an_interrupted_journal(archive):
    events = json.loads((archive / "events.json").read_bytes())[:-1]
    _repin_events(archive, events, status="recording")
    before = _hashes(archive)
    process = _run(archive)
    assert process.returncode == 1
    report = json.loads(process.stdout)
    assert report["complete"] is False
    assert report["ok"] is False
    assert any("incomplete" in error for error in report["errors"])
    assert before == _hashes(archive)


# Unknown locations fail without creating directories or offering a partial success.
def test_cli_missing_archive_has_no_side_effects(tmp_path):
    destination = tmp_path / "absent"
    process = _run(destination)
    assert process.returncode == 1
    report = json.loads(process.stdout)
    assert report["ok"] is False
    assert report["errors"]
    assert not destination.exists()


# A symlinked archive is refused even when its target contains otherwise valid evidence.
def test_cli_refuses_symlink_archive(archive, tmp_path):
    link = tmp_path / "linked"
    link.symlink_to(archive, target_is_directory=True)
    before = _hashes(archive)
    process = _run(link)
    assert process.returncode == 1
    report = json.loads(process.stdout)
    assert any("symlink" in error for error in report["errors"])
    assert before == _hashes(archive)
