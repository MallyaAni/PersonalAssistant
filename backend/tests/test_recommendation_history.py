"""Pin original recommendation history and distinguish stock marks from trade P/L."""

import json
from pathlib import Path

import pytest

from backend.market import forward_actions, recommendation_history
from backend.tests.test_forward_evidence import observations


# Write the exact observations that the history reader must preserve.
def archive(root, rows):
    folder = root / "desk/intraday-research"
    folder.mkdir(parents=True)
    for index, row in enumerate(rows):
        (folder / f"decision-{index}.json").write_text(json.dumps(row))
    return {str(path): path.read_bytes() for path in folder.glob("*.json")}


# Paused sizes stay withheld and later policy changes do not rewrite an earlier grade.
def test_original_grades_sizes_and_pauses_are_immutable(tmp_path, monkeypatch):
    rows = observations()
    rows[1]["targets"]["AAPL"] = 0.2
    rows[2]["event_paused"] = True
    rows[2]["policy_sha256"] = "new"
    rows[2]["grades"]["AAPL"]["grade_live"] = "C"
    before = archive(tmp_path, rows)
    monkeypatch.setattr(
        forward_actions, "load", lambda root, symbols: ({}, "2026-09-11")
    )
    result = recommendation_history.load(tmp_path, "AAPL")
    assert result["observations"][0]["allocation"] is None
    assert result["observations"][0]["model_weight"] == 0.1
    assert result["observations"][0]["grade"] == "C"
    assert result["observations"][1]["allocation_change"] == pytest.approx(0.1)
    assert result["observations"][-1]["grade"] == "A+"
    assert all(row["stock_total_return"] is None for row in result["observations"])
    assert result["outcomes"]["status"] == "awaiting_daily_validation"
    assert {path: Path(path).read_bytes() for path in before} == before


# A split-adjusted observed mark is not a loss or a simulated execution result.
def test_stock_mark_accounts_for_split_and_keeps_latest_outcome_unknown(
    tmp_path, monkeypatch
):
    rows = observations()
    rows[-1]["prices"]["AAPL"] = 5
    archive(tmp_path, rows)
    actions = {"AAPL": [{"date": "2026-09-16", "kind": "split", "value": 2}]}
    monkeypatch.setattr(
        forward_actions, "load", lambda root, symbols: (actions, "2026-09-21")
    )
    result = recommendation_history.load(tmp_path, "AAPL")
    assert result["observations"][-1]["stock_total_return"] == pytest.approx(0)
    assert result["observations"][0]["stock_total_return"] is None
    assert result["outcomes"]["mark_at"] == "2026-09-21T14:30:00+00:00"
    assert "not a trade fill" in result["method"]


# Two policies observing the same candle do not establish a later price outcome.
def test_duplicate_candle_does_not_invent_outcomes(tmp_path, monkeypatch):
    rows = observations()[:1]
    rows.append(
        {**rows[0], "as_of": "2026-09-14T14:16:00+00:00", "policy_sha256": "two"}
    )
    archive(tmp_path, rows)
    monkeypatch.setattr(
        forward_actions, "load", lambda root, symbols: ({}, "2026-09-14")
    )
    assert all(
        row["stock_total_return"] is None
        for row in recommendation_history.load(tmp_path, "AAPL")["observations"]
    )


# Corrupt archive evidence is counted instead of silently presented as complete history.
def test_invalid_archive_is_reported(tmp_path, monkeypatch):
    archive(tmp_path, observations())
    (tmp_path / "desk/intraday-research/decision-broken.json").write_text("{")
    monkeypatch.setattr(
        forward_actions, "load", lambda root, symbols: ({}, "2026-09-11")
    )
    assert recommendation_history.load(tmp_path, "AAPL")["invalid_archives"] == 1
