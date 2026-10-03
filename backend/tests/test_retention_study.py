"""Pin actual funded benchmark accounting and fixed-window report arithmetic."""

import json
from dataclasses import replace

import numpy as np
import pytest

from backend.market import retention_study as study
from backend.market.research_journal_replay import verify_snapshot
from backend.tests.test_learned_retention_simulator_hook import report_fixture


# Next-open budget conversion cannot earn the prior gap or spend unavailable cash.
@pytest.mark.parametrize("cost", [0, 10, 25])
@pytest.mark.parametrize("opening", [80, 120])
def test_benchmark_is_cash_funded_next_open_hold(cost, opening):
    panel = report_fixture().panel
    one = replace(
        panel,
        tickers=("SPY",),
        benchmark="SPY",
        **{
            key: getattr(panel, key)[:, -1:]
            for key in ("open", "high", "low", "close", "adj_close", "volume")
        },
    )
    prices = one.open.copy()
    prices[1] = opening
    one = replace(one, open=prices)
    journal = study._journal(one, cost, "SPY-fixture", {"test": "next-open"})
    nav = study.benchmark(one, "SPY", 0, cost, journal)
    assert nav[0] == 1
    assert nav[1] == pytest.approx(100 / (opening * (1 + cost / 1e4)))
    np.testing.assert_array_equal(nav[1:], np.full(len(nav) - 1, nav[1]))
    proof = verify_snapshot(journal.snapshot())
    assert proof["ok"], proof
    assert proof["total_fees"] == pytest.approx(cost / (10000 + cost))


# Preserve missing returns and measure fees from actual fills.
def test_score_preserves_missing_and_actual_fill_flows(monkeypatch):
    dates = np.array(["2026-09-28", "2026-09-29", "2026-09-30"], dtype="datetime64[D]")
    monkeypatch.setattr(study, "WINDOWS", {"fixture": (dates[0], dates[-1])})
    nav = np.array([1, 1.1, 1.21])
    actual = study.score(
        dates,
        nav,
        np.array([0, 0.5, 0.55]),
        np.array([0, 0.001, 0.002]),
        {"SPY": np.array([1, 1.01, 1.02])},
    )["fixture"]
    assert actual["metrics"]["total"] == pytest.approx(0.21)
    assert actual["fees_nav1"] == pytest.approx(0.003)
    assert actual["turnover_per_year"] == pytest.approx(126)
    assert actual["benchmarks"]["SPY"]["excess_total"] == pytest.approx(0.19)
    nav[-1] = np.nan
    missing = study.score(dates, nav, np.zeros(3), np.zeros(3), {"SPY": np.ones(3)})[
        "fixture"
    ]
    assert missing["metrics"] is None
    assert missing["missing_returns"] == 1
    assert missing["benchmarks"]["SPY"]["excess_total"] is None


# Exercise actual accounts and archives separately from model correctness tests.
def test_runner_exercises_actual_accounts_and_archives(tmp_path, monkeypatch):
    panel = report_fixture().panel
    panel = replace(
        panel,
        tickers=(*panel.tickers, "QQQ"),
        **{
            key: np.column_stack((getattr(panel, key), getattr(panel, key)[:, -1]))
            for key in ("open", "high", "low", "close", "adj_close", "volume")
        },
    )
    grades = np.column_stack(
        (report_fixture().graded.grades, np.zeros(len(panel.dates)))
    )
    eligible = np.ones(panel.close.shape, dtype=bool)
    eligible[:, -2:] = False
    monkeypatch.setattr(
        study.retention_inputs,
        "load",
        lambda *args: (panel, grades, eligible, {"test": "real-account-fixture"}),
    )
    monkeypatch.setattr(study, "START", panel.dates[0])
    monkeypatch.setattr(study, "END", panel.dates[-1])
    monkeypatch.setattr(study, "COSTS", (10,))
    monkeypatch.setattr(study, "OFFSETS", (0,))
    monkeypatch.setattr(
        study, "WINDOWS", {"fixture": (panel.dates[0], panel.dates[-1])}
    )
    monkeypatch.setattr(
        study,
        "fit",
        lambda *args: study.heads.DailyForecasts(
            np.full(panel.close.shape, 0.01), np.zeros(len(panel.dates)), {}, {}
        ),
    )

    # Keep this account workflow test independent of fitting tests.
    def fixture_hash(path):
        return "fixture" if path.name == "fit.json" else original_hash(path)

    original_hash = study.file_hash
    monkeypatch.setattr(study, "SNAPSHOT_SHA256", "fixture")
    monkeypatch.setattr(study, "authenticate_source", lambda *args: {"fixture": True})
    monkeypatch.setattr(
        study,
        "file_hash",
        lambda path: "fixture" if str(path) == "unused" else fixture_hash(path),
    )
    result = study.run(
        "unused",
        "unused",
        "unused",
        tmp_path / "result",
        "fixture-sha",
        "fixture-manifest",
    )
    assert len(result["accounts"]) == 3
    assert len(result["benchmarks"]) == 2
    assert all(row["journal"]["proof"]["ok"] for row in result["accounts"])
    assert result["adoption"] is False


# Authenticate source bytes and refuse false revisions and module tampering.
def test_source_guard_checks_revision_and_required_bytes(tmp_path):
    hashes = study.source_hashes()
    manifest = tmp_path / "identity.json"
    manifest.write_text(json.dumps({"git_commit": "a" * 40, "files": hashes}))
    proof = study.authenticate_source("a" * 40, manifest)
    assert proof["files"] == len(hashes)
    with pytest.raises(ValueError, match="SHA"):
        study.authenticate_source("fixture-sha", manifest)
    with pytest.raises(ValueError, match="declared"):
        study.authenticate_source("b" * 40, manifest)
    hashes[next(iter(hashes))] = "0" * 64
    manifest.write_text(json.dumps({"git_commit": "a" * 40, "files": hashes}))
    with pytest.raises(ValueError, match="differ"):
        study.authenticate_source("a" * 40, manifest)


# Reject alternative snapshots before fitting or creating an apparently valid output.
def test_fixed_snapshot_guard_runs_before_any_fit(tmp_path, monkeypatch):
    path = tmp_path / "wrong.npz"
    path.write_bytes(b"different snapshot")
    monkeypatch.setattr(study, "authenticate_source", lambda *args: {})
    with pytest.raises(ValueError, match="preregistered snapshot"):
        study.run(path, "unused", "unused", tmp_path / "out", "a" * 40, "unused")
    assert not (tmp_path / "out").exists()
