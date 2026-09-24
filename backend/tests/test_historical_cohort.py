"""Historical imports retain source bytes, clocks, identities and observable gaps."""

import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256

import numpy as np
import pytest

from backend.market import historical_cohort as hc


# Write a test manifest while retaining its exact bytes for archival assertions.
def _write_manifest(path, manifest):
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


# Make a source-bound three-security cohort independent of real market outcomes.
def _fixture(tmp_path):
    published = {
        "baseline": "2019-12-31T17:00:00+00:00",
        "entry": "2020-01-07T21:30:00+00:00",
        "exit": "2020-01-09T21:30:00+00:00",
    }
    descriptions = {
        "baseline": (
            "Alpha common stock; Beta common stock; Gamma common stock; value 10"
        ),
        "entry": "Beta common stock begins trading January 7, 2020",
        "exit": "Gamma common stock canceled January 8, 2020 for USD 25 per share",
    }
    sources = []
    for identity, stamp in published.items():
        body = f"<html><p>{stamp}</p><p>{descriptions[identity]}</p></html>".encode()
        (tmp_path / f"{identity}.html").write_bytes(body)
        sources.append(
            {
                "source_id": identity,
                "url": f"https://example.test/{identity}.html",
                "file": f"{identity}.html",
                "sha256": sha256(body).hexdigest(),
                "media_type": "text/html",
                "publication_precision": "instant",
                "published_at": stamp,
                "ingested_at": "2026-09-24T18:00:00+00:00",
                "publication_evidence": {"source_id": identity, "quote": stamp},
            }
        )
    securities = [
        {
            "security_id": identity,
            "identifier_scheme": "sec_cik_and_share_class",
            "issuer_id": f"{number:010}",
            "share_class": "common stock",
            "ticker": identity.upper(),
            "identity_evidence": {
                "source_id": "baseline",
                "quote": f"{name} common stock",
            },
        }
        for number, (identity, name) in enumerate(
            (("alpha", "Alpha"), ("beta", "Beta"), ("gamma", "Gamma")), start=1
        )
    ]
    baseline_ref = {"source_id": "baseline", "quote": "Alpha common stock"}
    entry_ref = {"source_id": "entry", "quote": descriptions["entry"]}
    exit_ref = {"source_id": "exit", "quote": descriptions["exit"]}
    manifest = {
        "schema": hc.SCHEMA,
        "cohort": {
            "id": "test-cohort",
            "rule": "Three independently declared test identities",
            "selected_at": "2026-09-24T18:00:00+00:00",
            "basis": "retrospective_demonstration",
            "limitations": ["Synthetic parser test; no economic conclusion"],
        },
        "sources": sources,
        "securities": securities,
        "memberships": [
            {
                "security_id": "alpha",
                "entered": "2020-01-02",
                "entry_evidence": baseline_ref,
                "exited": None,
                "exit_evidence": None,
            },
            {
                "security_id": "beta",
                "entered": "2020-01-07",
                "entry_evidence": entry_ref,
                "exited": None,
                "exit_evidence": None,
            },
            {
                "security_id": "gamma",
                "entered": "2020-01-02",
                "entry_evidence": {
                    "source_id": "baseline",
                    "quote": "Gamma common stock",
                },
                "exited": "2020-01-08",
                "exit_evidence": exit_ref,
            },
        ],
        "terminal_outcomes": [
            {
                "security_id": "gamma",
                "effective_on": "2020-01-08",
                "kind": "cash_merger",
                "cash_per_share": 25.0,
                "currency": "USD",
                "settlement_on": None,
                "successor_security_id": None,
                "shares_per_share": None,
                "evidence": exit_ref,
            }
        ],
        "features": [],
    }
    path = _write_manifest(tmp_path / "manifest.json", manifest)
    return path, manifest


# Read five declared session closes without deriving dates from the tested accounts.
def _report(cohort, *, features=("close",)):
    sessions = np.arange("2020-01-06", "2020-01-11", dtype="datetime64[D]")
    decisions = [datetime.fromisoformat(f"{day}T16:00:00-05:00") for day in sessions]
    return hc.readiness(cohort, sessions, decisions, features)


# Retain all identities, including missing entrants and removed names, on every session.
def test_membership_follows_publication_not_retroactive_event_dates(tmp_path):
    path, _ = _fixture(tmp_path)
    report = _report(hc.load_cohort(path))
    assert report["session_security_rows"] == 15
    assert report["all_named_securities_retained"] is True
    histories = {
        name: [
            row["membership"] for row in report["rows"] if row["security_id"] == name
        ]
        for name in ("alpha", "beta", "gamma")
    }
    assert histories["alpha"] == ["present"] * 5
    assert histories["beta"] == ["unknown", "unknown", "present", "present", "present"]
    assert histories["gamma"] == ["present", "present", "present", "present", "absent"]
    assert report["gap_counts"] == {
        "close:unavailable": 12,
        "membership_unknown": 2,
        "terminal_settlement_unknown": 1,
    }
    assert report["feature_complete_rows"] == 0
    assert report["historical_backtest_ready"] is False
    assert report["adoption_eligible"] is False


# Preserve original evidence byte-for-byte and refuse to overwrite an existing archive.
def test_archive_retains_original_manifest_sources_and_roundtrips(tmp_path):
    path, manifest = _fixture(tmp_path)
    original = path.read_bytes()
    cohort = hc.load_cohort(path)
    archive = hc.archive_cohort(cohort, tmp_path / "archive")
    archived = hc.load_cohort(archive)
    assert (archive.parent / "original-manifest.json").read_bytes() == original
    assert archived.manifest["input_manifest_sha256"] == sha256(original).hexdigest()
    for source in manifest["sources"]:
        body = (tmp_path / source["file"]).read_bytes()
        assert archived.source_bytes[source["source_id"]] == body
        assert (
            archive.parent / "sources" / f"{sha256(body).hexdigest()}.bin"
        ).read_bytes() == body
    assert _report(archived)["rows"] == _report(cohort)["rows"]
    with pytest.raises(FileExistsError):
        hc.archive_cohort(cohort, archive.parent)
    assert path.read_bytes() == original
    with pytest.raises(TypeError, match="does not support item assignment"):
        cohort.source_bytes["baseline"] = b"changed"


# Matching filenames or revised hashes do not excuse altered or unquoted content.
def test_corrupted_bytes_and_unsupported_extractions_fail_closed(tmp_path):
    path, manifest = _fixture(tmp_path)
    source = tmp_path / "baseline.html"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        hc.load_cohort(path)
    manifest["sources"][0]["sha256"] = sha256(source.read_bytes()).hexdigest()
    manifest["securities"][0]["identity_evidence"]["quote"] = "unsupported new identity"
    _write_manifest(path, manifest)
    with pytest.raises(ValueError, match="passage is absent"):
        hc.load_cohort(path)


# A source cannot reach outside the scoped artifact directory through paths or symlinks.
@pytest.mark.parametrize("escape", ["absolute", "parent", "symlink"])
def test_source_files_cannot_escape_manifest_directory(tmp_path, escape):
    inner = tmp_path / "inner"
    inner.mkdir()
    path, manifest = _fixture(inner)
    outside = tmp_path / "outside.html"
    outside.write_bytes((inner / "baseline.html").read_bytes())
    if escape == "absolute":
        manifest["sources"][0]["file"] = str(outside)
    elif escape == "parent":
        manifest["sources"][0]["file"] = "../outside.html"
    else:
        (inner / "link.html").symlink_to(outside)
        manifest["sources"][0]["file"] = "link.html"
    _write_manifest(path, manifest)
    with pytest.raises(ValueError, match="inside the manifest directory"):
        hc.load_cohort(path)


# Date-only publications become available the next local day without invented seconds.
def test_date_precision_has_explicit_conservative_bound(tmp_path):
    path, manifest = _fixture(tmp_path)
    source = manifest["sources"][1]
    source.pop("published_at")
    source.update(publication_precision="day_conservative", published_on="2020-01-08")
    report = _report(hc.load_cohort(_write_manifest(path, manifest)))
    beta = [row for row in report["rows"] if row["security_id"] == "beta"]
    assert [row["membership"] for row in beta] == ["unknown"] * 3 + ["present"] * 2
    saved = next(item for item in report["sources"] if item["source_id"] == "entry")
    assert saved["published_on"] == "2020-01-08"
    assert saved["availability_bound_at"] == "2020-01-09T00:00:00-05:00"
    assert "published_at" not in saved


# Same-day ingestion is compatible with a date-only conservative availability bound.
def test_date_only_source_can_be_ingested_before_next_midnight(tmp_path):
    path, manifest = _fixture(tmp_path)
    source = manifest["sources"][1]
    source.pop("published_at")
    source.update(
        publication_precision="day_conservative",
        published_on="2020-01-08",
        ingested_at="2020-01-09T01:30:00+00:00",
    )
    report = _report(hc.load_cohort(_write_manifest(path, manifest)))
    beta = [row for row in report["rows"] if row["security_id"] == "beta"]
    assert [row["membership"] for row in beta] == ["unknown"] * 3 + ["present"] * 2
    source["ingested_at"] = "2020-01-08T01:30:00+00:00"
    with pytest.raises(ValueError, match="publication follows"):
        hc.load_cohort(_write_manifest(path, manifest))


# Invalid source clocks must not turn a later collection into historical availability.
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("published_at", "2019-12-31T17:00:00", "timezone-aware"),
        ("ingested_at", "2019-12-01T17:00:00+00:00", "publication follows"),
        ("url", "https://user:secret@example.test/source", "without credentials"),
        ("publication_precision", "estimated", "publication precision"),
    ],
)
def test_source_clocks_and_public_urls_are_explicit(tmp_path, field, value, message):
    path, manifest = _fixture(tmp_path)
    manifest["sources"][0][field] = value
    with pytest.raises(ValueError, match=message):
        hc.load_cohort(_write_manifest(path, manifest))


# A known merger entitlement remains unspendable without a separately verified ledger.
def test_terminal_consideration_is_not_an_ordinary_mark_or_cash_fill(tmp_path):
    path, manifest = _fixture(tmp_path)
    report = _report(hc.load_cohort(path))
    gamma = [row for row in report["rows"] if row["security_id"] == "gamma"]
    assert all(row["terminal_outcome"] is None for row in gamma[:-1])
    outcome = gamma[-1]["terminal_outcome"]
    assert outcome["cash_per_share"] == 25
    assert outcome["settlement_on"] is None
    assert outcome["cash_is_funded"] is False
    manifest["terminal_outcomes"][0]["settlement_on"] = "2020-01-10"
    last = _report(hc.load_cohort(_write_manifest(path, manifest)))["rows"][-1]
    assert "terminal_settlement_unknown" not in last["gaps"]
    assert last["terminal_outcome"]["cash_is_funded"] is False
    assert last["eligible_under_supplied_membership"] is False


# Missing delisting outcomes are visible rather than represented by a zero return.
def test_known_removal_without_outcome_keeps_a_named_gap(tmp_path):
    path, manifest = _fixture(tmp_path)
    manifest["terminal_outcomes"] = []
    final = _report(hc.load_cohort(_write_manifest(path, manifest)))["rows"][-1]
    assert final["membership"] == "absent"
    assert final["terminal_outcome"] is None
    assert final["gaps"] == ["terminal_outcome_not_supplied_or_not_yet_known"]


# A name announced before entry needs no terminal payout while it has not entered yet.
def test_announced_future_entry_is_absent_without_a_fake_terminal_gap(tmp_path):
    path, manifest = _fixture(tmp_path)
    manifest["memberships"][1]["entered"] = "2020-01-10"
    report = _report(hc.load_cohort(_write_manifest(path, manifest)))
    row = next(
        row
        for row in report["rows"]
        if row["session"] == "2020-01-08" and row["security_id"] == "beta"
    )
    assert row["membership"] == "absent"
    assert row["membership_basis"] == "before_declared_entry"
    assert row["gaps"] == []


# Feature revisions preserve the earlier version until the later one is available.
def test_feature_versions_keep_availability_basis_and_missingness(tmp_path):
    path, manifest = _fixture(tmp_path)
    feature = {
        "security_id": "alpha",
        "session": "2020-01-06",
        "name": "close",
        "value": 10.0,
        "version": "v1",
        "available_at": "2020-01-06T20:00:00+00:00",
        "basis": "source_reconstruction",
        "evidence": {"source_id": "baseline", "quote": "value 10"},
    }
    manifest["features"] = [
        feature,
        feature
        | {"version": "v2", "value": 20.0, "available_at": "2020-01-06T22:00:00+00:00"},
    ]
    cohort = hc.load_cohort(_write_manifest(path, manifest))
    report = _report(cohort)
    first = report["rows"][0]
    assert first["features"]["close"]["value"] == 10
    assert first["features"]["close"]["version"] == "v1"
    assert first["required_features_complete"] is True
    assert report["historical_backtest_ready"] is False
    later = hc.readiness(
        cohort,
        np.array(["2020-01-06"], dtype="datetime64[D]"),
        [datetime.fromisoformat("2020-01-06T23:00:00+00:00")],
        ("close",),
    )
    assert later["rows"][0]["features"]["close"]["value"] == 20
    feature["basis"] = "recorded"
    with pytest.raises(ValueError, match="later source ingestion"):
        hc.load_cohort(_write_manifest(path, manifest))
    feature["basis"] = "retrospective_model"
    assert (
        _report(hc.load_cohort(_write_manifest(path, manifest)))["rows"][0]["features"][
            "close"
        ]["status"]
        == "retrospective_model_unverified"
    )


# Complete feature evidence does not imply that a security was eligible to trade.
def test_feature_completeness_is_separate_from_membership_eligibility(tmp_path):
    path, manifest = _fixture(tmp_path)
    manifest["memberships"][0]["entered"] = "2020-01-10"
    manifest["features"] = [
        {
            "security_id": "alpha",
            "session": "2020-01-06",
            "name": "close",
            "value": 10.0,
            "version": "v1",
            "available_at": "2020-01-06T20:00:00+00:00",
            "basis": "source_reconstruction",
            "evidence": {"source_id": "baseline", "quote": "value 10"},
        }
    ]
    report = _report(hc.load_cohort(_write_manifest(path, manifest)))
    first = report["rows"][0]
    assert first["membership"] == "absent"
    assert first["required_features_complete"] is True
    assert first["eligible_under_supplied_membership"] is False
    assert report["feature_complete_rows"] == 1
    assert report["historical_backtest_ready"] is False


# Later available events cannot revise decisions from an earlier completed prefix.
def test_future_source_and_terminal_changes_preserve_earlier_rows(tmp_path):
    path, manifest = _fixture(tmp_path)
    original = _report(hc.load_cohort(path))["rows"][:6]
    manifest["memberships"][2]["exited"] = "2020-01-06"
    manifest["terminal_outcomes"][0]["cash_per_share"] = 100
    changed = _report(hc.load_cohort(_write_manifest(path, manifest)))["rows"][:6]
    assert changed == original


# Stable identity, interval and terminal contradictions fail before archival writes.
@pytest.mark.parametrize(
    "defect",
    [
        "ticker_identity",
        "issuer",
        "duplicate_identity",
        "overlap",
        "negative_cash",
        "settlement_before_event",
    ],
)
def test_identity_interval_and_terminal_guards(tmp_path, defect):
    path, manifest = _fixture(tmp_path)
    if defect == "ticker_identity":
        manifest["securities"][0]["identifier_scheme"] = "ticker"
    elif defect == "issuer":
        manifest["securities"][0]["issuer_id"] = "AAPL"
    elif defect == "duplicate_identity":
        manifest["securities"].append(deepcopy(manifest["securities"][0]))
    elif defect == "overlap":
        manifest["memberships"].append(deepcopy(manifest["memberships"][0]))
    elif defect == "negative_cash":
        manifest["terminal_outcomes"][0]["cash_per_share"] = -1
    else:
        manifest["terminal_outcomes"][0]["settlement_on"] = "2020-01-07"
    messages = {
        "ticker_identity": "identity scheme",
        "issuer": "ten-digit CIK",
        "duplicate_identity": "Duplicate security",
        "overlap": "Overlapping membership",
        "negative_cash": "nonnegative",
        "settlement_before_event": "Settlement cannot precede",
    }
    with pytest.raises(ValueError, match=messages[defect]):
        hc.load_cohort(_write_manifest(path, manifest))


# Decision timestamp mistakes and collapsed session precision fail explicitly.
def test_readiness_requires_exact_decision_calendar(tmp_path):
    path, _ = _fixture(tmp_path)
    cohort = hc.load_cohort(path)
    sessions = np.array(["2020-01-06"], dtype="datetime64[D]")
    with pytest.raises(ValueError, match="timezone-aware"):
        hc.readiness(cohort, sessions, [datetime(2020, 1, 6, 16)], ("close",))
    with pytest.raises(ValueError, match="differs from its New York session"):
        hc.readiness(
            cohort,
            sessions,
            [datetime.fromisoformat("2020-01-07T16:00:00-05:00")],
            ("close",),
        )
    with pytest.raises(ValueError, match="daily session calendar"):
        hc.readiness(cohort, sessions.astype("datetime64[ns]"), [], ("close",))
    assert (
        json.loads(json.dumps(_report(cohort), allow_nan=False))[
            "session_security_rows"
        ]
        == 15
    )
