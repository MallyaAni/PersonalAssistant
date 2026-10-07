"""Authenticate saved forecasts and exercise causal sizing through the real CLI."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_adaptive_timing_sizing as cli
from backend.market import adaptive_growth_policy


# Construct a compact chronological grid with the fixed comparison endpoints.
def panel_fixture():
    dates = np.array(
        ["2018-01-31", "2018-02-01", "2026-08-17", "2026-09-30"], dtype="datetime64[D]"
    )
    prices = np.full((len(dates), 3), 10.0)
    panel = SimpleNamespace(
        dates=dates,
        tickers=("ONE", "SPY", "QQQ"),
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices,
    )
    shape = (len(dates), 25, len(panel.tickers))
    provenance = {
        "snapshot_sha256": "snapshot",
        "provenance_sha256": "provenance",
        "snapshot_contract": {"eligibility_mode": "recomputed-current-vintage"},
    }
    dataset = {
        "X": np.zeros((*shape, 21), dtype=np.float32),
        "y": np.zeros((*shape, 3)),
        "valid": np.ones(shape, dtype=bool),
        "dates": dates,
        "provenance": provenance,
    }
    return panel, dataset


# Create saved, unchanged account evidence without invoking an account replay.
def saved_account(length):
    return {
        "curves": {
            "nav": [1.0] * length,
            "cash": [1.0] * length,
            "exposure": [0.0] * length,
            "turnover": [0.0] * length,
            "fees": [0.0] * length,
        },
        "counts": {"intents": 0},
        "stocks": {"ONE": {"net_gain_initial_nav_units": 0.0}},
        "intent_trace": [],
    }


# Preserve the known historical hook and simulator bytes in synthetic receipts.
def historical_files(current):
    files = dict(current)
    files.update(cli.OLD_HOOKS)
    files[cli.SIMULATOR] = cli.OLD_SIMULATOR_SHA
    files[cli.CALENDAR_FILE] = cli.OLD_CALENDAR_SHA
    return files


# Only the inspected calendar extension may accompany reused original controls.
@pytest.mark.parametrize("changed", ["old", "new"])
def test_calendar_lineage_rejects_an_unreviewed_transition(changed):
    current = cli.primary.source_identity()["files"]
    old = historical_files(current)
    if changed == "old":
        old[cli.CALENDAR_FILE] = "unreviewed"
    else:
        current[cli.CALENDAR_FILE] = "unreviewed"
    with pytest.raises(ValueError, match="calendar transition"):
        cli.historical_source(old, current, Path(cli.__file__).resolve().parents[2])


# Pin synthetic normalized artifacts for an actual saved-evidence loader test.
def timing_fixture(tmp_path, monkeypatch, *, dtype=np.float32):
    panel, dataset = panel_fixture()
    output = tmp_path / "timing"
    (output / "models").mkdir(parents=True)
    predictions = np.zeros((*dataset["valid"].shape, 2), dtype=dtype)
    forecast_path = output / "models/predictions.npz"
    np.savez(forecast_path, dates=panel.dates, predictions=predictions)
    forecast_sha = cli.sha256(forecast_path)
    identity = {
        "arrays": {
            key: cli.original._array_hash(dataset[key])
            for key in ("X", "y", "valid", "dates")
        },
        "source_provenance": dataset["provenance"],
    }
    manifest = {
        "identity": identity,
        "identity_sha256": cli.original._json_hash(identity),
        "forecast": {
            "file": "predictions.npz",
            "sha256": forecast_sha,
            "arrays": {
                "dates": cli.original._array_hash(panel.dates),
                "predictions": cli.original._array_hash(predictions),
            },
        },
    }
    cli.write_json(output / "models/manifest.json", manifest)
    report_identity = {
        "model_identity": manifest["identity_sha256"],
        "forecast_sha256": forecast_sha,
        "primary_sha256": cli.saved.PRIMARY_SHA256,
        "dates": panel.dates.astype(str).tolist(),
        "data": dataset["provenance"],
        "source": {
            "files": historical_files(cli.normalized.source_identity()["files"])
        },
    }
    report = {
        "identity": report_identity,
        "status": "complete_conditional_research",
        "adoption_eligible": False,
        "phases": [
            {
                "cost_bps": cost,
                "phase": phase,
                "candidate": saved_account(len(panel.dates)),
            }
            for cost in cli.primary.COSTS
            for phase in range(20)
        ],
    }
    cli.write_json(output / "normalized-evaluation.json", report)
    report_sha = cli.sha256(output / "normalized-evaluation.json")
    cli.write_json(
        output / "normalized-evaluation-proof.json",
        {"report_sha256": report_sha, "identity": report_identity},
    )
    monkeypatch.setattr(cli, "NORMALIZED_REPORT_SHA", report_sha)
    monkeypatch.setattr(
        cli, "NORMALIZED_MANIFEST_SHA", cli.sha256(output / "models/manifest.json")
    )
    monkeypatch.setattr(cli, "NORMALIZED_FORECAST_SHA", forecast_sha)
    return panel, dataset, output


# Write synthetic daily arrays with authenticated symbol, calendar and model lineage.
def daily_fixture(tmp_path, monkeypatch):
    panel, dataset = panel_fixture()
    output = tmp_path / "daily"
    output.mkdir()
    relative = np.zeros(panel.adj_close.shape)
    market = np.full(panel.dates.shape, 0.01)
    np.savez(output / "forecasts.npz", dates=panel.dates, relative=relative, spy=market)
    forecast_sha = cli.sha256(output / "forecasts.npz")
    inputs = {
        "original_inputs": {
            "snapshot_sha256": "snapshot",
            "provenance_sha256": "provenance",
            "snapshot_provenance": dataset["provenance"]["snapshot_contract"],
            "symbols": list(panel.tickers),
            "arrays_sha256": {"dates": cli.original._array_hash(panel.dates)},
        }
    }
    cli.write_json(output / "inputs.json", inputs)
    identity = {
        "symbols": list(panel.tickers),
        "provenance": inputs,
        "policy": "learned-held-b-forecast/1",
        "label_end": 11,
        "holdout_end_before": "2026-08-17",
    }
    fit = {
        "identity": identity,
        "identity_sha256": cli.original._json_hash(identity),
        "artifact_hashes": {"forecasts.npz": forecast_sha},
        "relative_forecast_sha256": cli.original._array_hash(relative),
        "spy_forecast_sha256": cli.original._array_hash(market),
    }
    cli.write_json(output / "fit.json", fit)
    monkeypatch.setattr(cli, "DAILY_INPUT_SHA", cli.sha256(output / "inputs.json"))
    monkeypatch.setattr(cli, "DAILY_FIT_SHA", cli.sha256(output / "fit.json"))
    monkeypatch.setattr(cli, "DAILY_FORECAST_SHA", forecast_sha)
    return panel, dataset, output


# Recover all saved timing accounts and forecasts without invoking the replay engine.
def test_original_timing_bytes_dates_and_all_sixty_controls(tmp_path, monkeypatch):
    panel, dataset, output = timing_fixture(tmp_path, monkeypatch)
    predictions, _, accounts = cli.load_timing(output, panel, dataset)
    assert predictions.dtype == np.float32
    assert len(accounts) == 60
    assert accounts[(25, 19)]["nav"][0] == 1


# Refuse numeric-equivalent forecast casting instead of laundering a changed artifact.
def test_timing_forecast_precision_is_part_of_identity(tmp_path, monkeypatch):
    panel, dataset, output = timing_fixture(tmp_path, monkeypatch, dtype=np.float64)
    with pytest.raises(ValueError, match="forecast representation"):
        cli.load_timing(output, panel, dataset)


# Require original forecast bytes even when a replacement would have the same calendar.
def test_timing_file_corruption_rejected_before_loading(tmp_path, monkeypatch):
    panel, dataset, output = timing_fixture(tmp_path, monkeypatch)
    with (output / "models/predictions.npz").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="forecast bytes changed"):
        cli.load_timing(output, panel, dataset)


# Refuse a matching-sized learned grid derived from different causal inputs.
def test_timing_prepared_array_identity_cannot_change(tmp_path, monkeypatch):
    panel, dataset, output = timing_fixture(tmp_path, monkeypatch)
    dataset["X"][0, 0, 0, 0] = 1
    with pytest.raises(ValueError, match="prepared array changed"):
        cli.load_timing(output, panel, dataset)


# Load relative and SPY heads only from their original dated and typed artifacts.
def test_daily_forecasts_share_exact_ticker_and_date_contract(tmp_path, monkeypatch):
    panel, dataset, output = daily_fixture(tmp_path, monkeypatch)
    relative, spy, receipt = cli.load_daily(output, panel, dataset)
    assert relative.shape == panel.adj_close.shape
    assert spy[-1] == 0.01
    assert receipt["forecast_sha256"] == cli.sha256(output / "forecasts.npz")
    changed = SimpleNamespace(**vars(panel))
    changed.tickers = ("SPY", "ONE", "QQQ")
    with pytest.raises(ValueError, match="symbol identity"):
        cli.load_daily(output, changed, dataset)


# Reject a calendar selected from available predictions rather than source sessions.
def test_daily_model_cannot_drop_a_missing_session(tmp_path, monkeypatch):
    panel, dataset, output = daily_fixture(tmp_path, monkeypatch)
    panel.dates = panel.dates[:-1]
    with pytest.raises(ValueError, match="forecast calendar"):
        cli.load_daily(output, panel, dataset)


# Authenticate the original funded class and refuse any unrelated dependency drift.
def test_exact_historical_book_and_two_hook_lineage():
    current = cli.primary.source_identity()["files"]
    old = historical_files(current)
    root = Path(cli.__file__).resolve().parents[2]
    cli.historical_source(old, current, root)
    old["backend/market/entry_timing.py"] = "0" * 64
    with pytest.raises(ValueError, match="Unreviewed historical source"):
        cli.historical_source(old, current, root)


# Refuse an unknown historical hook rather than widening lineage automatically.
def test_unregistered_old_hook_refused():
    current = cli.primary.source_identity()["files"]
    old = historical_files(current)
    old[next(iter(cli.OLD_HOOKS))] = "0" * 64
    with pytest.raises(ValueError, match="Unknown historical target hook"):
        cli.historical_source(old, current, Path(cli.__file__).resolve().parents[2])


# Authenticate the prior report and ETF fee-funded prices without rerunning books.
def test_primary_saved_gate_controls_and_funded_etfs(tmp_path, monkeypatch):
    panel, dataset = panel_fixture()
    benchmarks = {}
    for cost in cli.primary.COSTS:
        gross = 1 / (1 + cost / 1e4)
        curves = {
            "nav": [1.0, gross, gross, gross],
            "cash": [1.0, 0.0, 0.0, 0.0],
            "exposure": [0.0, 1.0, 1.0, 1.0],
            "turnover": [0.0, gross, 0.0, 0.0],
            "fees": [0.0, 1 - gross, 0.0, 0.0],
        }
        benchmarks[str(cost)] = {name: {"curves": curves} for name in ("SPY", "QQQ")}
    identity = {
        "source": {"files": historical_files(cli.primary.source_identity()["files"])},
        "data": dataset["provenance"],
        "baseline_sha256": cli.primary.BASELINE_SHA256,
    }
    report = {
        "identity": identity,
        "dates": panel.dates.astype(str).tolist(),
        "status": "complete_reused_conditional_research",
        "adoption_eligible": False,
        "benchmarks": benchmarks,
        "phases": [
            {
                "cost_bps": cost,
                "phase": phase,
                "control": saved_account(len(panel.dates)),
            }
            for cost in cli.primary.COSTS
            for phase in range(20)
        ],
    }
    path = tmp_path / "primary.json"
    proof = tmp_path / "primary-proof.json"
    cli.write_json(path, report)
    digest = cli.sha256(path)
    cli.write_json(proof, {"report_sha256": digest, "identity": identity})
    monkeypatch.setattr(cli.saved, "PRIMARY_SHA256", digest)
    _, controls, references = cli.load_primary(panel, dataset, path, proof)
    assert len(controls) == 60
    assert references[25]["SPY"]["nav"][1] == pytest.approx(1 / 1.0025)
    assert references[25]["QQQ"]["fees"][1] == pytest.approx(0.0025 / 1.0025)
    dataset["provenance"] = {"changed": "source"}
    with pytest.raises(ValueError, match="input/calendar changed"):
        cli.load_primary(panel, dataset, path, proof)


# Bind a mock allocator to one preceding row and observe its causal arguments.
def provider_fixture(monkeypatch):
    dates = np.busday_offset("2026-08-03", np.arange(10))
    prices = np.arange(30).reshape(10, 3).astype(float) + 10
    panel = SimpleNamespace(
        dates=dates, tickers=("ONE", "SPY", "QQQ"), adj_close=prices
    )
    relative = np.repeat(np.arange(10)[:, None], 3, axis=1).astype(float) / 100
    market = np.arange(10).astype(float) / 1000
    observed = []

    # Capture allocator evidence without fitting or replaying any account.
    def allocate(history, grades, eligible, means, current, cash, cost, benchmark):
        observed.append(
            {"history": history.copy(), "means": means.copy(), "benchmark": benchmark}
        )
        return np.asarray(current).copy(), {"status": "optimized"}

    monkeypatch.setattr(adaptive_growth_policy, "allocate", allocate)
    arguments = {
        "history": prices[:4].copy(),
        "grades": np.array([3, -1, -1]),
        "eligible": np.array([True, False, False]),
        "current_weights": np.zeros(3),
        "cash_weight": 1.0,
        "cost_bps": 10,
        "as_of": dates[3],
    }
    return panel, relative, market, observed, arguments


# Ensure same-session and future forecasts never influence the prior-close plan.
def test_provider_uses_previous_completed_row_and_future_prefix_invariance(monkeypatch):
    panel, relative, market, observed, args = provider_fixture(monkeypatch)
    provide = cli.target_provider(panel, relative, market)
    _, receipt = provide(**args)
    first = observed[-1]["means"].copy()
    assert first == pytest.approx(relative[3] + market[3])
    assert observed[-1]["benchmark"] == (1, 2)
    assert receipt["as_of"] == str(panel.dates[3])
    assert receipt["forecast_horizon_sessions"] == 10
    relative[4:] = 999
    market[4:] = -999
    panel.adj_close[4:] = 9999
    provide(**args)
    assert observed[-1]["means"] == pytest.approx(first)


# Refuse even a single forward close in the allocator's observable history.
def test_provider_rejects_future_or_stale_history(monkeypatch):
    panel, relative, market, _, args = provider_fixture(monkeypatch)
    provide = cli.target_provider(panel, relative, market)
    args["history"] = panel.adj_close[:5]
    with pytest.raises(ValueError, match="causal history prefix"):
        provide(**args)
    args["history"] = panel.adj_close[:4].copy()
    args["history"][0, 0] += 1
    with pytest.raises(ValueError, match="causal history prefix"):
        provide(**args)


# Missing market forecasts remain unavailable instead of substituting zero alpha.
def test_missing_spy_forecast_is_not_fabricated(monkeypatch):
    panel, relative, market, observed, args = provider_fixture(monkeypatch)
    market[3] = np.nan
    cli.target_provider(panel, relative, market)(**args)
    assert np.isnan(observed[-1]["means"]).all()


# Exercise the actual allocator through the dated wrapper on finite prior evidence.
def test_real_allocation_wrapper_funds_prior_only_risk_sensitive_weights():
    dates = np.busday_offset("2025-01-02", np.arange(260))
    rows = np.arange(260)
    history = np.column_stack(
        [
            20 * np.exp(0.001 * rows + 0.002 * np.sin(rows)),
            30 * np.exp(0.0005 * rows + 0.001 * np.cos(rows)),
            25 * np.exp(0.0007 * rows + 0.002 * np.cos(rows)),
        ]
    )
    panel = SimpleNamespace(
        dates=dates, tickers=("ONE", "SPY", "QQQ"), adj_close=history
    )
    relative = np.full(history.shape, 0.02)
    market = np.full(len(dates), 0.001)
    weights, receipt = cli.target_provider(panel, relative, market)(
        history=history.copy(),
        grades=np.array([3, -1, -1]),
        eligible=np.array([True, False, False]),
        current_weights=np.zeros(3),
        cash_weight=0.20,
        cost_bps=25,
        as_of=dates[-1],
    )
    assert receipt["status"] == "optimized"
    assert 0 < weights[0] <= 0.20 / 1.0025 + 1e-8
    assert weights[1:] == pytest.approx([0, 0])


# Construct every phase with all four arms and common positive-loss gain metrics.
def summary_rows():
    rows = []
    for cost in cli.primary.COSTS:
        for phase in range(20):
            scores = {}
            for index, name in enumerate((*cli.ARMS, "SPY", "QQQ")):
                scores[name] = {
                    "windows": [
                        {
                            "window": window,
                            "status": "measured",
                            "total_net_gain": 0.20 + index / 100,
                            "cagr": 0.1,
                            "max_drawdown_loss": 0.05,
                            "sharpe": 1.0,
                            "gross_traded_weight_per_year": 2.0,
                            "fees_initial_nav_units": 0.01,
                        }
                        for window in ("all", "2018-20", "2021-26", "reused_recent")
                    ]
                }
            rows.append({"cost_bps": cost, "phase": phase, "scores": scores})
    return rows


# Summarize wealth against every arm and ETF without choosing favorable reset phases.
def test_four_arm_all_phase_wealth_summary():
    result = cli.summarize(summary_rows())
    assert [row["cost_bps"] for row in result] == [0, 10, 25]
    for cost in result:
        for window in cost["windows"]:
            assert set(window["arms"]) == set(cli.ARMS)
            for arm in cli.ARMS:
                assert len(window["arms"][arm]["paired_gain"]) == 5
                assert (
                    window["arms"][arm]["median_metrics"]["max_drawdown_loss"] == 0.05
                )
    comparison = result[1]["windows"][0]["arms"]["growth_adaptive"]["paired_gain"][
        "equal_gate"
    ]
    assert comparison["median_gain_difference"] == pytest.approx(0.03)
    assert comparison["positive_phases"] == 20


# Refuse omitted phases and unavailable windows instead of dropping bad outcomes.
def test_missing_phase_or_window_cannot_be_reported_as_complete():
    rows = summary_rows()
    with pytest.raises(ValueError, match="All sixty"):
        cli.summarize(rows[:-1])
    rows[0]["scores"]["growth_gate"]["windows"][3]["status"] = "unavailable"
    with pytest.raises(ValueError, match="cannot be dropped"):
        cli.summarize(rows)


# Annualize already normalized turnover once and label reused windows explicitly.
def test_annual_turnover_not_divided_by_nav_twice():
    dates = np.array(["2026-09-28", "2026-09-29", "2026-09-30"], dtype="datetime64[D]")
    account = {
        "dates": dates,
        "nav": np.array([1.0, 2.0, 2.0]),
        "turnover": np.array([0.0, 0.0, 0.1]),
    }
    score = {
        "windows": [
            {
                "window": "frozen_holdout",
                "status": "measured",
                "start": "2026-09-29",
                "end": "2026-09-30",
                "sessions": 2,
            }
        ]
    }
    result = cli.named_score(score, account)
    assert result["windows"][0]["window"] == "reused_recent"
    assert result["windows"][0]["gross_traded_weight_per_year"] == pytest.approx(
        0.1 * 252 / 2
    )


# Ensure the CLI creates only 120 new books and reuses both sixty-book controls.
def test_new_account_schedule_only_and_separate_trace_persistence(
    tmp_path, monkeypatch
):
    panel, dataset = panel_fixture()
    dates = panel.dates.copy()
    account = {
        **{
            key: np.asarray(value)
            for key, value in saved_account(len(dates))["curves"].items()
        },
        "dates": dates,
        "counts": {"intents": 0},
        "stocks": {"ONE": {"net_gain_initial_nav_units": 0.0}},
        "intent_trace": [],
    }
    controls = {
        (cost, phase): copy.deepcopy(account)
        for cost in cli.primary.COSTS
        for phase in range(20)
    }
    etfs = {
        cost: {name: copy.deepcopy(account) for name in ("SPY", "QQQ")}
        for cost in cli.primary.COSTS
    }
    calls = []

    # Record new replay requests and preserve a synthetic allocation receipt.
    def replay_account(*args, method, supported_days, target_provider):
        calls.append((args[7], args[8], method))
        result = copy.deepcopy(account)
        result["allocation_trace"] = [
            {"receipt": {"status": "optimized", "as_of": str(dates[0])}}
        ]
        return result

    # Provide fixed complete score windows without introducing extra account replay.
    def score(value, references, spy):
        row = summary_rows()[0]["scores"]["equal_gate"]
        return {
            **copy.deepcopy(row),
            "counts": value["counts"],
            "stocks": value["stocks"],
        }

    monkeypatch.setattr(cli.replay, "account", replay_account)
    monkeypatch.setattr(
        cli.primary, "execution_support", lambda *args: np.ones(len(dates), dtype=bool)
    )
    monkeypatch.setattr(
        cli.primary, "session_opens", lambda *args: panel.adj_close.copy()
    )
    monkeypatch.setattr(
        cli, "source_identity", lambda *args, **kwargs: {"files": {"fixed": "source"}}
    )
    monkeypatch.setattr(cli.primary.scoring, "score", score)
    monkeypatch.setattr(cli, "named_score", lambda value, account: value)
    args = SimpleNamespace(
        output=tmp_path / "new-study", source_manifest=None, source_revision=None
    )
    source = {
        "identity": {
            "session_open_sha256": cli.original._array_hash(panel.adj_close),
            "supported_sessions_sha256": cli.original._array_hash(
                np.ones(len(dates), dtype=bool)
            ),
        }
    }
    report = cli.evaluate(
        args,
        (panel, np.zeros((4, 3)), np.zeros((4, 3), dtype=bool), {}, dataset),
        np.zeros((4, 25, 3, 2), dtype=np.float32),
        np.zeros((4, 3)),
        np.zeros(4),
        source,
        controls,
        controls,
        etfs,
        {},
        {"identity_sha256": "fixed"},
    )
    assert len(calls) == 120
    assert set(method for _, _, method in calls) == {"control", "candidate"}
    assert report["adoption_eligible"] is False
    assert len(report["phases"]) == 60
    assert len(list(args.output.glob("growth_*.json"))) == 120
    saved_trace = json.loads((args.output / "growth_gate-10-3.json").read_text())
    assert saved_trace["allocation_trace"][0]["receipt"]["status"] == "optimized"
    proof = json.loads((args.output / "evaluation-proof.json").read_text())
    assert proof["report_sha256"] == cli.sha256(args.output / "evaluation.json")
    with pytest.raises(ValueError, match="no account restart"):
        cli.evaluate(
            args,
            (panel, None, None, {}, dataset),
            np.zeros((4, 25, 3, 2), dtype=np.float32),
            np.zeros((4, 3)),
            np.zeros(4),
            source,
            controls,
            controls,
            etfs,
            {},
            {"identity_sha256": "fixed"},
        )
