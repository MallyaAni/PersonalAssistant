"""Synthetic funded scorecard acceptance; fake forecasts are not model evidence."""

from copy import deepcopy
from functools import lru_cache
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import open_source_forecast_evaluation as evaluation
from backend.market import open_source_forecasts as forecasts
from backend.market.allocation_replay import replay


# Supply fixed dates, a complete causal context and explicitly synthetic prices.
@lru_cache(maxsize=1)
def template():
    calendar = [
        str(day)
        for day in np.arange("2025-08-01", "2026-10-16", dtype="datetime64[D]")
        if np.is_busday(day) and str(day) != "2026-09-07"
    ]
    decisions = [day for day in calendar if evaluation.START <= day <= evaluation.END]
    rows = [
        {
            "symbol": symbol,
            "session": day,
            "available_at": day + "T16:00:00-04:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
        }
        for symbol in evaluation.COHORT
        for day in calendar
        if day <= evaluation.END
    ]
    payload = {
        "calendar": calendar,
        "decisions": decisions,
        "rows": rows,
        "price_basis": "adjusted_ohlcv",
        "volume_basis": "provider_reported",
        "source_revision": "synthetic",
        "availability_mode": "session_close_assumed",
        "data_mode": "reconstructed_snapshot",
        "source_cutoff": evaluation.END,
    }
    dates = np.array(
        [day for day in calendar if day <= evaluation.END], dtype="datetime64[D]"
    )
    prices = np.full((len(dates), 12), 100.0)
    panel = SimpleNamespace(
        dates=dates,
        tickers=evaluation.COHORT,
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    grades = np.full(prices.shape, 3, dtype=np.int8)
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, -2:] = False
    artifact = forecasts.run(
        payload, "chronos2", list(evaluation.COHORT), forecaster=Fake()
    )
    artifact["input_sha256"] = evaluation.SOURCE_SHA256
    return payload, artifact, panel, grades, eligible


# Isolate each case while reusing one explicitly synthetic forecast template.
def fixture():
    return deepcopy(template())


class Fake:
    # Return fixed positive book excess and zero benchmark excess in synthetic units.
    def predict(self, rows, future):
        return np.repeat(
            rows[-1]["close"] * (1 if rows[-1]["symbol"] == "SPY" else 1.02), 10
        )


# Evaluate only synthetic immutable inputs before any real forecast score is read.
def score(data):
    payload, artifact, panel, grades, eligible = data
    return evaluation.evaluate(
        payload,
        [artifact],
        panel,
        grades,
        eligible,
        {"snapshot_sha256": "synthetic"},
        source_sha256=evaluation.SOURCE_SHA256,
    )


# Preserve the fixed cohort, reset phase, deterministic ranking and immature labels.
def test_fixed_targets_and_full_denominators():
    result = score(fixture())
    resets = result["resets"]["chronos2"]
    assert len(resets) == 2
    assert list(resets[0]["weights"]) == ["AAOI", "AAPL", "AMD", "AMZN"]
    assert set(resets[0]["weights"].values()) == {0.25}
    summary = result["forecast_diagnostics"]["chronos2"]
    assert summary["requested_opportunities"] == 228
    assert summary["eligible_opportunities"] == 190
    assert summary["mature_labels"] == 108
    assert summary["immature_labels"] == 120
    assert result["rolling_252_win_rate"] is None
    assert result["adoption_eligible"] is False


# Missing model evidence becomes a complete unavailable basket rather than filtering.
def test_error_retained_and_whole_reset_unavailable():
    data = fixture()
    record = data[1]["records"][0]
    record.update(status="model_error", reason="synthetic_failure")
    result = score(data)
    assert result["resets"]["chronos2"][0]["status"] == "unavailable"
    assert result["resets"]["chronos2"][0]["weights"] == {}
    assert result["forecast_diagnostics"]["chronos2"]["forecast_unavailable"] == 1
    assert len(result["opportunities"]["chronos2"]) == 228


# Refuse missing/duplicate records and mismatched context rather than infer a signal.
@pytest.mark.parametrize(
    "defect",
    ["missing", "duplicate", "context", "horizon", "checkpoint", "excess", "source"],
)
def test_invalid_artifacts_refused(defect):
    data = fixture()
    artifact = data[1]
    if defect == "missing":
        artifact["records"].pop()
    elif defect == "duplicate":
        artifact["records"].append(deepcopy(artifact["records"][0]))
    elif defect in ("context", "horizon", "excess"):
        key = {
            "context": "context_hash",
            "horizon": "horizon_session",
            "excess": "predicted_excess_return",
        }[defect]
        artifact["records"][0][key] = 99 if defect == "excess" else "wrong"
    elif defect == "checkpoint":
        artifact["checkpoint"]["revision"] = "wrong"
    else:
        artifact["source_revision"] = "wrong"
    with pytest.raises(ValueError, match="forecast|Forecast|Checkpoint|SPY"):
        score(data)


# Reject changes to the frozen input file or incompatible adjusted price grids.
def test_hash_and_panel_basis_bindings():
    data = fixture()
    with pytest.raises(ValueError, match="hash"):
        evaluation.evaluate(data[0], [data[1]], *data[2:], {}, source_sha256="wrong")
    data[2].adj_close[-1, 0] *= 10
    with pytest.raises(ValueError, match="price bases"):
        score(data)


# Size from the prior close but spend only real next-open cash across opening gaps.
def test_actual_ledger_gap_funding_and_costs():
    payload, artifact, panel, grades, eligible = fixture()
    panel, grades, eligible = evaluation.common_panel(payload, panel, grades, eligible)
    _, records = evaluation.artifact_records(payload, artifact)
    path, _ = evaluation.instructions(panel, grades, eligible, "chronos2", records)
    panel.open[1] = 200
    panel.close[1] = panel.adj_close[1] = 200
    account = replay(panel, path, first=0, cost_bps=25, start_equity=1)
    assert account["cash"][1] >= 0
    assert np.dot(account["positions"][1], panel.open[1]) <= 1
    assert account["fees"][1] == pytest.approx(
        1 - np.dot(account["positions"][1], panel.open[1])
    )
    assert not np.array_equal(
        account["positions"][1], account["decisions"][0]["submitted_units"]
    )


# Future prices and eligibility cannot alter an earlier target instruction prefix.
def test_target_prefix_invariance():
    payload, artifact, panel, grades, eligible = fixture()
    panel, grades, eligible = evaluation.common_panel(payload, panel, grades, eligible)
    _, records = evaluation.artifact_records(payload, artifact)
    before, _ = evaluation.instructions(panel, grades, eligible, "chronos2", records)
    first_account = replay(panel, before, first=0, cost_bps=25, start_equity=1)
    panel.adj_close[10:] = 999999
    eligible[10:] = False
    after, _ = evaluation.instructions(panel, grades, eligible, "chronos2", records)
    assert before[:10] == after[:10]
    second_account = replay(panel, after, first=0, cost_bps=25, start_equity=1)
    np.testing.assert_array_equal(first_account["nav"][:10], second_account["nav"][:10])
    np.testing.assert_array_equal(
        first_account["positions"][:10], second_account["positions"][:10]
    )


# Existing sell proceeds fund later retries, never buys in the same execution batch.
def test_actual_ledger_does_not_recycle_sale_proceeds_in_batch():
    payload, artifact, panel, grades, eligible = fixture()
    panel, grades, eligible = evaluation.common_panel(payload, panel, grades, eligible)
    _, records = evaluation.artifact_records(payload, artifact)
    second = str(panel.dates[10])
    old = {"AAOI", "AAPL", "AMD", "AMZN"}
    for symbol in evaluation.COHORT[:-2]:
        records[second, symbol]["predicted_excess_return"] = -1 if symbol in old else 1
    path, resets = evaluation.instructions(panel, grades, eligible, "chronos2", records)
    account = replay(panel, path, first=0, cost_bps=10, start_equity=1)
    selected = [evaluation.COHORT.index(symbol) for symbol in resets[1]["weights"]]
    assert not account["positions"][11, selected].any()
    assert account["cash"][11] > 0
    assert account["positions"][12, selected].sum() > 0


# Keep squared-log-return risk labels out of all alpha portfolios.
def test_ttm_risk_units_and_no_alpha_account():
    payload, _, panel, grades, eligible = fixture()
    artifact = forecasts.run(
        payload, "ttm", list(evaluation.COHORT), forecaster=RiskFake()
    )
    artifact["input_sha256"] = evaluation.SOURCE_SHA256
    result = evaluation.evaluate(
        payload,
        [artifact],
        panel,
        grades,
        eligible,
        {},
        source_sha256=evaluation.SOURCE_SHA256,
    )
    assert "ttm" not in result["costs"]
    risk = result["forecast_diagnostics"]["ttm"]
    assert risk["target"] == "mean_squared_log_return"
    assert risk["prediction_mse"] == 0
    assert risk["trailing20_risk_baseline_mse"] == 0


class RiskFake:
    # Return the squared-log-return mean for a constant synthetic price history.
    def predict(self, rows, future):
        return np.zeros(10)


# Refuse existing output before reading anything or overwriting frozen evidence.
def test_cli_refuses_existing_output_before_input_reads(tmp_path, monkeypatch):
    import sys

    from backend.cli.market_open_source_forecast_evaluation import main

    path = tmp_path / "frozen-input.json"
    path.write_text("immutable evidence")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scorecard",
            "missing-source",
            "missing-portfolio",
            "missing-provenance",
            "missing-model",
            "missing-model-2",
            "missing-model-3",
            "missing-model-4",
            "--output",
            str(path),
        ],
    )
    with pytest.raises(FileExistsError, match="overwrite"):
        main()
    assert path.read_text() == "immutable evidence"
# Bind each model output to the same frozen input artifact, not only its prefixes.
def test_model_input_hash_binding():
    data = fixture()
    data[1]["input_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash|source"):
        score(data)


# A changed sampling seed cannot silently become the registered experiment.
def test_fixed_seed_binding():
    data = fixture()
    data[1]["seed"] = 7
    with pytest.raises(ValueError, match="seed|protocol"):
        score(data)


# Final labels published after the declared close remain unavailable at that cutoff.
def test_label_publication_after_cutoff_close():
    payload = fixture()[0]
    source = evaluation.source_rows(payload)
    source[evaluation.END, "AAPL"]["available_at"] = "2026-09-30T16:01:00-04:00"
    assert evaluation.realized_label(
        payload, source, "AAPL", "2026-09-16", evaluation.END, "terminal_close"
    ) is None
