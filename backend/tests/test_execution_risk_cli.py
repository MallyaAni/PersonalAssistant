"""Actual artifact readback and immutable boundaries for execution-risk research."""

import hashlib
import json

import numpy as np
import pytest

from backend.cli import market_execution_risk as runner
from backend.cli.market_execution_risk import fit, load_risk, verify_months
from backend.tests.test_learned_execution_risk import _dataset
from backend.tests.test_learned_execution_timing import sample


# Fit one actual risk model set once and exercise its complete published CLI artifacts.
@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    directory = tmp_path_factory.mktemp("execution-risk-cli")
    data = _dataset()
    receipt = fit(data, directory)
    return data, directory, receipt


# Read actual fitted bytes and prove missing future labels never erased forecasts.
def test_actual_risk_artifact_readback(fitted):
    data, directory, receipt = fitted
    values, actual = load_risk(directory, data)
    assert values.shape == data["valid"].shape
    assert np.isfinite(values[-10:]).all()
    assert actual["prediction_array_sha256"] == receipt["prediction_array_sha256"]
    assert len(actual["manifest"]["months"]) > 1


# A completed fit cannot be accidentally started a second time.
def test_completed_risk_fit_cannot_be_repeated(fitted):
    data, directory, _ = fitted
    with pytest.raises(FileExistsError, match="completed risk fit"):
        fit(data, directory)


# Changed causal observations invalidate a risk artifact even if its dimensions match.
def test_changed_causal_arrays_reject_risk(fitted):
    data, directory, _ = fitted
    changed = {**data, "X": data["X"].copy()}
    changed["X"][0, 0, 0, 0] += 0.01
    with pytest.raises(ValueError, match="original inputs differ"):
        load_risk(directory, changed)


# Validate real calendar ordering and label maturity independently of estimator outputs.
def test_wrong_month_and_immature_labels_reject(fitted):
    data, directory, receipt = fitted
    months = json.loads(json.dumps(receipt["manifest"]["months"]))
    months.reverse()
    with pytest.raises(ValueError, match="month schedule"):
        verify_months(directory, months, data["dates"])
    months = json.loads(json.dumps(receipt["manifest"]["months"]))
    month = next(row for row in months if row["status"] == "fitted")
    month["maximum_label_end"] = month["label_end_before"]
    with pytest.raises(ValueError, match="immature or holdout"):
        verify_months(directory, months, data["dates"])


# A tampered prediction archive fails before its arrays can enter trading decisions.
def test_risk_artifact_byte_tampering_rejects(fitted, tmp_path):
    import shutil

    data, directory, _ = fitted
    copy = tmp_path / "altered"
    shutil.copytree(directory, copy)
    archive = copy / "predictions.npz"
    archive.write_bytes(archive.read_bytes() + b"altered")
    with pytest.raises(ValueError, match="risk artifact bytes"):
        load_risk(copy, data)


# Write and read the complete synthetic evidence path without a fit or old baseline run.
def test_synthetic_evaluation_persists_all_costs_phases_counts_and_sources(
    tmp_path, monkeypatch
):
    panel, grades, eligible, data, forecasts, variance, closing = sample()
    panel.dates = np.array(["2026-08-14", "2026-08-17"], dtype="datetime64[D]")
    data["dates"] = panel.dates
    data.update(
        {
            "provenance": {"fixture": "private synthetic acceptance"},
            "valid": np.ones((2, 25, 3), bool),
            "y": np.zeros((2, 25, 3, 3)),
            "training_symbols": np.array([True, False, False]),
        }
    )
    curves = {
        name: {
            "nav": [1, 1],
            "cash": [1, 1],
            "exposure": [0, 0],
            "fees": [0, 0],
            "turnover": [0, 0],
        }
        for name in ["SPY", "QQQ"] + [f"control_phase_{i}" for i in range(20)]
    }
    baseline = {
        "data": data["provenance"],
        "common_start": "2026-08-17",
        "costs": [
            {
                "cost_bps": cost,
                "curves": curves,
                "controls": [{"frozen_control_phase": i} for i in range(20)],
            }
            for cost in (0, 10, 25)
        ],
    }
    reference = tmp_path / "original-synthetic-baseline.json"
    reference.write_text(json.dumps(baseline))
    expected_reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
    monkeypatch.setattr(runner, "CONTROL_REPORT", expected_reference_hash)
    output = tmp_path / "timing-only-report.json"

    # Supply the synthetic auction without changing the production hash guard.
    def fixture_closing(supplied_panel, supplied_cubes):
        assert supplied_panel is panel
        assert supplied_cubes == {}
        return closing

    monkeypatch.setattr(runner.timing, "closing_prices", fixture_closing)
    receipts = {
        "risk": {"identity": "synthetic-risk-receipt"},
        "boosting": {"identity": "synthetic-original-mean"},
        "ridge": {"identity": "synthetic-original-mean"},
    }
    result = runner.evaluate(
        panel,
        grades,
        eligible,
        {},
        data,
        {"boosting": forecasts, "ridge": forecasts},
        variance,
        receipts,
        reference,
        output,
    )
    persisted = json.loads(output.read_text())
    assert result == persisted
    assert persisted["baseline_report_sha256"] == expected_reference_hash
    assert persisted["adoption_eligible"] is False
    assert persisted["forecast_receipts"] == receipts
    assert persisted["source"] == runner.execution_source()
    assert persisted["start"] == persisted["end"] == "2026-08-17"
    assert [cost["cost_bps"] for cost in persisted["costs"]] == [0, 10, 25]
    for cost in persisted["costs"]:
        assert set(cost["methods"]) == {"boosting", "ridge"}
        for phases in cost["methods"].values():
            assert len(phases) == 20
            assert [phase["offset"] for phase in phases] == list(range(20))
            for phase in phases:
                assert phase["paired_control"] == {
                    "frozen_control_phase": phase["offset"]
                }
                assert phase["curve"]["dates"] == ["2026-08-14", "2026-08-17"]
                assert phase["curve"]["nav"][0] == 1
                assert len(phase["curve"]["nav"]) == 2
                statistics = phase["statistics"]
                assert "counts" in statistics
                assert "stocks" in statistics
                counts = statistics["counts"]
                assert counts["intents"] == sum(
                    counts[k]
                    for k in (
                        "completed_intents",
                        "expired_partial",
                        "expired_unfilled",
                    )
                )
                assert set(statistics["stocks"]) == {"STOCK", "SPY", "QQQ"}
                assert sum(
                    stock["net_gain_initial_nav_units"]
                    for stock in statistics["stocks"].values()
                ) == pytest.approx(phase["curve"]["nav"][-1] - 1)
    proof = json.loads(output.with_suffix(".proof.json").read_text())
    assert proof["artifact_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert proof["source"] == persisted["source"]
    assert json.loads(output.with_suffix(".progress.json").read_text()) == persisted
    with pytest.raises(FileExistsError, match="completed"):
        runner.evaluate(
            panel,
            grades,
            eligible,
            {},
            data,
            {"boosting": forecasts, "ridge": forecasts},
            variance,
            receipts,
            reference,
            output,
        )
