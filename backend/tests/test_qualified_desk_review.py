"""Independent connected-boundary checks for source-qualified research.

The 2026-09-25 baseline had 16 failures among 21 cases: metadata alignment,
record identity/archive completeness, hidden history evaluation and root aliases.
Those assertions remain; two added cases cover boolean CIKs and the allowed CLI.
Two later alias cases also failed before resolved destination containment guards.
"""

import json
import sys
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import desk, fundamental
from backend.cli import market_daily, market_desk
from backend.market import qualified_fundamentals as qualified
from backend.market.universe import AI_COMPUTE, AI_SIDE, SOFTWARE, SOFTWARE_SIDE
from backend.tests.test_fundamental_current_path import _score_panel
from backend.tests.test_qualified_desk_path import ASOF, _store
from backend.tests.test_trading_desk import torch_loaders  # noqa: F401


# Build qualified opinions, grades and record inputs from temporary byte archives.
@pytest.fixture
def prepared(tmp_path, monkeypatch, request):
    request.getfixturevalue("torch_loaders")
    store = _store(tmp_path / "market", newer=True)
    panel = replace(_score_panel(), themes={"TEST": (AI_COMPUTE,), "PEER": (SOFTWARE,)})

    # Keep prices synthetic while fundamental and downstream grading steps stay real.
    def book_panel(*args, **kwargs):
        return panel, {"TEST": AI_SIDE, "PEER": SOFTWARE_SIDE}

    monkeypatch.setattr(desk, "book_panel", book_panel)
    report = desk.run(store, ASOF, inputs=(), fundamentals="qualified")
    return store, report


# Inconsistent per-row declarations cannot acquire a qualified label from valid numbers.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ticker", "PEER"),
        ("decision", "1900-01-01"),
        ("source_sha256", "f" * 64),
        ("cik", False),
        ("cik", True),
        ("unit", "EUR"),
        ("revenue_tag", "us-gaap:Revenues"),
        ("period_kind", "year"),
        ("selection_policy", "newest-tag-wins"),
        ("revenue_period_end", "1900-01-01"),
    ],
)
def test_loader_rejects_row_source_and_date_mismatch(
    tmp_path, monkeypatch, field, value
):
    store = _store(tmp_path)
    real_features = qualified.features

    # Change only evidence identity after the real declared-concept calculation.
    def mismatched_features(panel, sources):
        result = deepcopy(real_features(panel, sources))
        result.observations[-1][0][field] = value
        return result

    monkeypatch.setattr(qualified, "features", mismatched_features)
    with pytest.raises(fundamental.FundamentalSourceError):
        desk._fundamental_opinion(store, _score_panel(), ASOF, "qualified")


# Record keys and session dates must match the observation that produced the opinion.
@pytest.mark.parametrize("mismatch", ["tickers", "decision"])
def test_record_refuses_panel_alignment_mismatch(prepared, mismatch):
    _, report = prepared
    if mismatch == "tickers":
        panel = replace(report.panel, tickers=("PEER", "TEST", "SPY"))
    else:
        days = report.panel.dates.copy()
        days[-1] += np.timedelta64(1, "D")
        panel = replace(report.panel, dates=days)
    with pytest.raises(ValueError, match="qualified"):
        market_daily.record(replace(report, panel=panel))


# Qualified records with real source rows require matching persisted archive provenance.
@pytest.mark.parametrize("mismatch", ["missing", "hash", "cik"])
def test_record_refuses_missing_or_mismatched_archive(prepared, mismatch):
    _, report = prepared
    opinion = report.opinions[fundamental.NAME]
    meta = deepcopy(opinion.meta)
    if mismatch == "missing":
        meta["source_archives"].pop("TEST")
    elif mismatch == "hash":
        meta["source_archives"]["TEST"]["source_sha256"] = "0" * 64
    else:
        meta["source_archives"]["TEST"]["cik"] = 99
    changed = replace(opinion, meta=meta)
    report = replace(report, opinions={**report.opinions, fundamental.NAME: changed})
    with pytest.raises(ValueError, match="qualified"):
        market_daily.record(report)


# Delivered record evidence is independently owned and cannot mutate a later record.
def test_qualification_citations_do_not_alias_opinion_or_archive(prepared):
    _, report = prepared
    opinion = report.opinions[fundamental.NAME]
    last = len(report.panel.dates) - 1
    original = fundamental.cited_qualification(opinion, last, 0)
    delivered = fundamental.cited_qualification(opinion, last, 0)
    delivered["archive"]["source_sha256"] = "0" * 64
    delivered["features"]["revenue_qoq"]["inputs"]["q0"][0]["components"][0][
        "value"
    ] = -999
    assert fundamental.cited_qualification(opinion, last, 0) == original
    first = market_daily.record(report)
    first["fundamental"]["qualification"]["TEST"]["ticker"] = "WRONG"
    assert (
        market_daily.record(report)["fundamental"]["qualification"]["TEST"] == original
    )


# The history flag includes return evaluation and must obey the research prohibition.
def test_qualified_history_command_is_refused_before_loading(monkeypatch, capsys):
    # A refusal must happen before any store, model or historical evaluator is reached.
    def refuse(*args, **kwargs):
        raise AssertionError("qualified history reached desk assembly")

    monkeypatch.setattr(market_desk.trading_desk, "run", refuse)
    monkeypatch.setattr(
        sys,
        "argv",
        ["market_desk", "--fundamentals", "qualified", "--history", "TEST"],
    )
    with pytest.raises(SystemExit) as exc:
        market_desk.main()
    assert exc.value.code == 2
    assert "histor" in capsys.readouterr().err.lower()


# Research record roots cannot name the operational store directly or through an alias.
@pytest.mark.parametrize("alias", ["same", "dotdot", "symlink", "desk_symlink"])
def test_qualified_record_root_cannot_alias_operational_store(
    tmp_path, monkeypatch, alias
):
    operational = tmp_path / "market"
    operational.mkdir()
    if alias == "dotdot":
        (operational / "nested").mkdir()
        research = operational / "nested" / ".."
    elif alias == "symlink":
        research = tmp_path / "research-link"
        research.symlink_to(operational, target_is_directory=True)
    elif alias == "desk_symlink":
        (operational / "desk").mkdir()
        research = tmp_path / "research"
        research.mkdir()
        (research / "desk").symlink_to(operational / "desk", target_is_directory=True)
    else:
        research = operational

    # Unsafe destination choices should stop before any read or record can run.
    def refuse(*args, **kwargs):
        raise AssertionError("research mode accepted the operational record root")

    monkeypatch.setattr(market_desk.trading_desk, "run", refuse)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_desk",
            "--fundamentals",
            "qualified",
            "--data-dir",
            str(operational),
            "--research-record-root",
            str(research),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        market_desk.main()
    assert exc.value.code == 2
    assert not list(operational.rglob("*.json"))


# A session-directory alias must be refused before the actual writer touches the store.
def test_qualified_session_record_alias_is_refused_before_save(
    prepared, tmp_path, monkeypatch
):
    store, report = prepared
    session = str(report.panel.dates[-1])
    operational_record = market_daily.record_path(store.root, session)
    operational_record.parent.mkdir(parents=True)
    sentinel = operational_record.parent / "existing-evidence.txt"
    sentinel.write_bytes(b"synthetic evidence must remain unchanged")
    original = {
        path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()
    }
    research = tmp_path / "research"
    (research / "desk").mkdir(parents=True)
    (research / "desk" / f"asof={session}").symlink_to(
        operational_record.parent, target_is_directory=True
    )
    calls = []
    real_save = market_daily.save

    # Provide the genuine report so the final session path can be resolved.
    def prepared_run(*args, **kwargs):
        return report

    # Observe the real writer rather than replacing its filesystem side effects.
    def tracked_save(root, data):
        calls.append(root)
        return real_save(root, data)

    monkeypatch.setattr(market_desk.trading_desk, "run", prepared_run)
    monkeypatch.setattr(market_daily, "save", tracked_save)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_desk",
            "--fundamentals",
            "qualified",
            "--data-dir",
            str(store.root),
            "--research-record-root",
            str(research),
        ],
    )
    refused = None
    try:
        market_desk.main()
    except SystemExit as exc:
        refused = exc
    assert calls == [], (
        "CLI reached the record writer through a session alias; "
        f"operational record exists: {operational_record.exists()}"
    )
    assert not operational_record.exists()
    assert {path: path.read_bytes() for path in original} == original
    assert refused is not None
    assert refused.code == 2


# Every nonempty augmentation is refused before the original-source loader runs.
@pytest.mark.parametrize("inputs", [(desk.EXPECTATIONS_GAP,), ("unknown",)])
def test_qualified_mode_cannot_activate_any_augmentation(monkeypatch, inputs):
    # These input-policy checks must not import a loader or request a price panel.
    def refuse(*args, **kwargs):
        raise AssertionError("an unqualified augmentation reached panel construction")

    monkeypatch.setattr(desk, "book_panel", refuse)
    with pytest.raises(ValueError, match="inputs"):
        desk.run(None, ASOF, inputs=inputs, fundamentals="qualified")


# Save the allowed CLI report separately without adding performance or paper data.
def test_qualified_cli_records_real_report_without_augmentations(
    prepared, tmp_path, monkeypatch, capsys
):
    store, report = prepared
    research = tmp_path / "research"
    archives_before = {
        path: path.read_bytes() for path in store.root.rglob("*.parquet")
    }
    called = []

    # Return the genuine prepared report while observing this CLI's requested mode.
    def prepared_run(requested_store, asof, **kwargs):
        called.append((requested_store.root, asof, kwargs))
        return report

    monkeypatch.setattr(market_desk.trading_desk, "run", prepared_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "market_desk",
            "--fundamentals",
            "qualified",
            "--data-dir",
            str(store.root),
            "--research-record-root",
            str(research),
        ],
    )
    market_desk.main()
    assert called == [(store.root, None, {"fundamentals": "qualified", "inputs": ()})]
    output = capsys.readouterr().out
    assert "RESEARCH ONLY" in output
    assert "do not establish" in output
    session = str(report.panel.dates[-1])
    path = market_daily.record_path(research, session)
    record = json.loads(path.read_text())
    assert record["fundamental"]["source"] == fundamental.QUALIFIED_SOURCE
    assert record["provenance"]["rule"]["inputs"] == []
    assert record["paper"] is None
    assert record["curve"] is None
    assert record["provenance"]["ml_forward"] is None
    assert set(record["fundamental"]["qualification"]) == {"TEST", "PEER"}
    for row in record["fundamental"]["qualification"].values():
        assert row["historical_authenticity_verified"] is False
    assert not market_daily.record_path(store.root, session).exists()
    assert {path: path.read_bytes() for path in archives_before} == archives_before
