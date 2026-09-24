"""Exercise the offline import command and its durable evidence/readiness outputs."""

import hashlib
import json
import subprocess
import sys

import pytest

from backend.cli import market_historical_cohort as command


# Fingerprint actual files independently of the importer being tested.
def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Serialize a clearly synthetic reviewed manifest for offline command tests.
def _json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


# Build a tiny test-only continuing, entering and exiting cohort with no features.
@pytest.fixture
def evidence(tmp_path):
    input_root = tmp_path / "input"
    input_root.mkdir()
    sources = []
    for source_id, day, body in (
        (
            "initial",
            "2020-11-24",
            "Continuing common stock. Entering common stock. Removed common stock.",
        ),
        (
            "later",
            "2020-11-29",
            "Entering common stock enters the cohort. Removed shares cease trading. "
            "Removed shares receive a USD 17 cash entitlement.",
        ),
    ):
        filename = f"{source_id}.html"
        path = input_root / filename
        path.write_text(f"<p>Publication date {day}</p><p>{body}</p>")
        sources.append(
            {
                "source_id": source_id,
                "url": f"https://example.org/{filename}",
                "file": filename,
                "sha256": _hash(path),
                "media_type": "text/html",
                "publication_precision": "day_conservative",
                "published_on": day,
                "ingested_at": "2026-09-24T12:00:00Z",
                "publication_evidence": {
                    "source_id": source_id,
                    "quote": f"Publication date {day}",
                },
            }
        )
    securities, memberships = [], []
    for index, label in enumerate(("Continuing", "Entering", "Removed"), start=1):
        identity = f"sec:{index:010d}:common"
        identity_evidence = {
            "source_id": "initial",
            "quote": f"{label} common stock.",
        }
        securities.append(
            {
                "security_id": identity,
                "identifier_scheme": "sec_cik_and_share_class",
                "issuer_id": f"{index:010d}",
                "share_class": "common stock",
                "ticker": label.upper(),
                "identity_evidence": identity_evidence,
            }
        )
        entry_evidence = (
            {"source_id": "later", "quote": "Entering common stock enters the cohort."}
            if label == "Entering"
            else identity_evidence
        )
        memberships.append(
            {
                "security_id": identity,
                "entered": "2020-11-30" if label == "Entering" else "2020-11-25",
                "entry_evidence": entry_evidence,
                "exited": "2020-11-27" if label == "Removed" else None,
                "exit_evidence": (
                    {"source_id": "later", "quote": "Removed shares cease trading."}
                    if label == "Removed"
                    else None
                ),
            }
        )
    manifest = {
        "schema": "historical-cohort/1",
        "cohort": {
            "id": "synthetic-cli-test",
            "rule": "Three invented securities for an offline test, not real evidence.",
            "selected_at": "2026-09-24T12:00:00Z",
            "basis": "retrospective_demonstration",
            "limitations": ["Synthetic fixture only; every feature is unavailable."],
        },
        "sources": sources,
        "securities": securities,
        "memberships": memberships,
        "terminal_outcomes": [
            {
                "security_id": "sec:0000000003:common",
                "effective_on": "2020-11-27",
                "kind": "cash_merger",
                "cash_per_share": 17,
                "currency": "USD",
                "successor_security_id": None,
                "shares_per_share": None,
                "settlement_on": None,
                "evidence": {
                    "source_id": "later",
                    "quote": "Removed shares receive a USD 17 cash entitlement.",
                },
            }
        ],
        "features": [],
    }
    _json(input_root / "cohort.json", manifest)
    return input_root / "cohort.json", tmp_path / "archive"


# Invoke the real CLI process instead of mocking the artifact or calendar boundary.
def _run(manifest, archive, *extra):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.cli.market_historical_cohort",
            "--manifest",
            str(manifest),
            "--archive",
            str(archive),
            "--start",
            "2020-11-25",
            "--end",
            "2020-12-01",
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


# Verify persisted original bytes, all calendar/name rows and truthful unavailable data.
def test_real_command_archives_sources_and_persists_complete_readiness(evidence):
    manifest, archive = evidence
    original = {path.name: path.read_bytes() for path in manifest.parent.iterdir()}
    process = _run(manifest, archive)
    assert process.returncode == 0, process.stderr
    receipt = json.loads(process.stdout)
    assert receipt == json.loads((archive / "import-receipt.json").read_bytes())
    assert receipt["readiness_sha256"] == _hash(archive / "readiness.json")
    assert receipt["manifest_sha256"] == _hash(archive / "cohort.json")
    assert (archive / "original-manifest.json").read_bytes() == original["cohort.json"]
    assert original == {
        path.name: path.read_bytes() for path in manifest.parent.iterdir()
    }
    report = json.loads((archive / "readiness.json").read_bytes())
    assert report["sessions"] == 4
    assert report["source_count"] == 2
    assert report["security_count"] == 3
    assert report["session_security_rows"] == 12
    assert report["all_named_securities_retained"] is True
    assert report["feature_complete_rows"] == 0
    for flag in (
        "historical_backtest_ready",
        "adoption_eligible",
        "independent_validation",
    ):
        assert report[flag] is receipt[flag] is False
    assert receipt["accounts_changed"] is False
    for source in report["sources"]:
        body = (archive / source["file"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == source["sha256"]
        assert body == original[f"{source['source_id']}.html"]
    by_key = {(row["session"], row["ticker"]): row for row in report["rows"]}
    assert by_key["2020-11-25", "ENTERING"]["membership"] == "unknown"
    assert by_key["2020-11-30", "ENTERING"]["membership"] == "present"
    assert by_key["2020-11-27", "REMOVED"]["membership"] == "present"
    removed = by_key["2020-11-30", "REMOVED"]
    assert removed["membership"] == "absent"
    assert removed["terminal_outcome"]["cash_per_share"] == 17
    assert removed["terminal_outcome"]["cash_is_funded"] is False
    assert removed["terminal_outcome"]["settlement_on"] is None
    assert "terminal_settlement_unknown" in removed["gaps"]
    assert by_key["2020-11-27", "CONTINUING"]["decision_at"] == (
        "2020-11-27T18:15:00+00:00"
    )
    assert by_key["2020-11-25", "CONTINUING"]["decision_at"] == (
        "2020-11-25T21:15:00+00:00"
    )
    for row in report["rows"]:
        assert set(row["features"]) == set(command.DEFAULT_FEATURES)
        assert all(
            item == {"status": "unavailable", "value": None}
            for item in row["features"].values()
        )


# Refuse damaged bytes, missing files and invented quotations before writing anything.
@pytest.mark.parametrize("damage", ["bytes", "missing", "quote"])
def test_invalid_evidence_fails_without_creating_archive(evidence, damage):
    manifest, archive = evidence
    source = manifest.parent / "initial.html"
    if damage == "bytes":
        source.write_bytes(source.read_bytes() + b"changed")
    elif damage == "missing":
        source.unlink()
    else:
        value = json.loads(manifest.read_bytes())
        value["securities"][0]["identity_evidence"]["quote"] = "Invented assertion."
        _json(manifest, value)
    process = _run(manifest, archive)
    assert process.returncode == 2
    assert "Historical cohort import failed" in process.stderr
    assert not process.stdout
    assert not archive.exists()


# A second import cannot overwrite a completed archive, even with the same input.
def test_existing_archive_is_unchanged_on_repeat(evidence):
    manifest, archive = evidence
    assert _run(manifest, archive).returncode == 0
    before = {
        str(path.relative_to(archive)): _hash(path)
        for path in archive.rglob("*")
        if path.is_file()
    }
    process = _run(manifest, archive)
    assert process.returncode == 2
    assert before == {
        str(path.relative_to(archive)): _hash(path)
        for path in archive.rglob("*")
        if path.is_file()
    }


# Invalid or empty exchange windows must fail before the fresh archive is created.
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2020-12-01", "2020-11-25"),
        ("2020-11-28", "2020-11-29"),
        ("20201125", "2020-12-01"),
    ],
)
def test_bad_calendar_request_has_no_output(evidence, start, end):
    manifest, archive = evidence
    with pytest.raises(ValueError, match="Calendar|calendar"):
        command.import_and_assess(manifest, archive, start=start, end=end)
    assert not archive.exists()


# Preserve the exact explicit feature set rather than silently restoring defaults.
def test_custom_required_features_are_persisted(evidence):
    manifest, archive = evidence
    process = _run(
        manifest, archive, "--required-feature", "close", "--required-feature", "grade"
    )
    assert process.returncode == 0, process.stderr
    report = json.loads((archive / "readiness.json").read_bytes())
    assert report["required_features"] == ["close", "grade"]
    assert all(set(row["features"]) == {"close", "grade"} for row in report["rows"])


# Repeated feature requirements are invalid and cannot leave a partially valid archive.
def test_duplicate_required_features_fail_preflight(evidence):
    manifest, archive = evidence
    process = _run(
        manifest, archive, "--required-feature", "grade", "--required-feature", "grade"
    )
    assert process.returncode == 2
    assert not archive.exists()


# A damaged copied source cannot acquire a readiness report or import receipt.
def test_corrupt_archive_readback_cannot_report_success(evidence, monkeypatch):
    manifest, archive = evidence
    archive_cohort = command.historical_cohort.archive_cohort

    # Damage one persisted source after the real archive writer completes.
    def corrupt_copy(cohort, destination):
        path = archive_cohort(cohort, destination)
        first = json.loads(path.read_bytes())["sources"][0]
        (path.parent / first["file"]).write_bytes(b"corrupt copy")
        return path

    monkeypatch.setattr(command.historical_cohort, "archive_cohort", corrupt_copy)
    with pytest.raises(ValueError, match="hash mismatch"):
        command.import_and_assess(
            manifest, archive, start="2020-11-25", end="2020-12-01"
        )
    assert not (archive / "readiness.json").exists()
    assert not (archive / "import-receipt.json").exists()
