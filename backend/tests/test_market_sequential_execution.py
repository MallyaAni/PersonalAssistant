"""Authenticate saved evidence and run the CLI's actual paired funded replay."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_sequential_execution as cli
from backend.market import learned_entry_models as original
from backend.market.sip_cube import SessionCube


# Build a price book with current-gate and learned actions at distinct clocks.
def _case():
    dates = np.array(
        ["2018-01-31", "2018-02-01", "2018-02-02", "2026-09-29", "2026-09-30"],
        dtype="datetime64[D]",
    )
    prices = np.full((5, 3), 10.0)
    panel = SimpleNamespace(
        dates=dates,
        tickers=("ONE", "SPY", "QQQ"),
        adj_close=prices,
        open=prices.copy(),
        close=prices.copy(),
    )
    shape = (5, 25, 3)
    dataset = {
        "dates": dates,
        "current_close": np.full(shape, 10.0),
        "next_open": np.full(shape, 10.0),
        "provenance": {"fixture": "synthetic"},
    }
    dataset["current_close"][:, 4, 0] = 9.9
    dataset["next_open"][:, 0, 0] = 12
    dataset["next_open"][:, 4, 0] = 8
    forecasts = np.zeros(shape + (2,), dtype=np.float32)
    grades = np.full(prices.shape, 3)
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, 1:] = False
    cube = SessionCube(
        ticker="ONE",
        dates=dates,
        open=np.full((5, 26), 100.0),
        high=np.full((5, 26), 100.0),
        low=np.full((5, 26), 100.0),
        close=np.full((5, 26), 100.0),
        volume=np.ones((5, 26)),
        prior_close=np.full(5, 100.0),
        excluded={},
        auction_open=np.full(5, 100.0),
        auction_volume=np.ones(5),
    )
    return (
        panel,
        grades,
        eligible,
        {name: cube for name in panel.tickers},
        dataset,
        forecasts,
    )


# Write saved benchmark curves using the known closed-form NAV1 cash and fee contract.
def _baseline(tmp_path, panel, monkeypatch):
    rows = []
    for cost in cli.COSTS:
        value = 1 / (1 + cost / 1e4)
        curves = {
            "nav": [1, value, value, value, value],
            "cash": [1, 0, 0, 0, 0],
            "exposure": [0, 1, 1, 1, 1],
            "turnover": [0, value, 0, 0, 0],
            "fees": [0, 1 - value, 0, 0, 0],
        }
        rows.append(
            {
                "cost_bps": cost,
                "curves": {
                    "SPY": curves,
                    "QQQ": curves,
                    "old_control": {"intentionally": "unused"},
                },
            }
        )
    path = tmp_path / "baseline.json"
    cli.write_json(
        path,
        {"common_start": str(cli.START), "common_end": str(cli.END), "costs": rows},
    )
    monkeypatch.setattr(cli, "BASELINE_SHA256", cli.sha256(path))
    return path


# Refuse absent prepared evidence before the shared loader can initialize an archive.
def test_existing_prepared_inputs_required_without_fallback(tmp_path):
    args = SimpleNamespace(prepared=tmp_path)
    with pytest.raises(ValueError, match="Existing original prepared"):
        cli.load_inputs(args)
    assert list(tmp_path.iterdir()) == []


# Scale every opening reference once and leave absent ticker cubes unavailable.
def test_session_open_conversion_preserves_crossing_ratio():
    panel, _, _, cubes, dataset, _ = _case()
    opens = cli.session_opens(panel, cubes)
    np.testing.assert_array_equal(opens, np.full((5, 3), 10.0))
    assert dataset["current_close"][1, 4, 0] / opens[1, 0] == pytest.approx(0.99)
    del cubes["QQQ"]
    assert np.isnan(cli.session_opens(panel, cubes)[:, 2]).all()


# Verify benchmark bytes, common dates, NAV1 scale and costs before reusing references.
def test_baseline_authentication_and_units_reject_wrong_curve(tmp_path, monkeypatch):
    panel, *_ = _case()
    path = _baseline(tmp_path, panel, monkeypatch)
    refs = cli.references(panel, 1, path)
    assert refs[25]["SPY"]["nav"][0] == 1
    assert refs[25]["SPY"]["nav"][1] == pytest.approx(1 / 1.0025)
    report = json.loads(path.read_text())
    report["costs"][0]["curves"]["SPY"]["nav"][2] *= 2
    cli.write_json(path, report)
    with pytest.raises(ValueError, match="baseline report SHA"):
        cli.references(panel, 1, path)
    monkeypatch.setattr(cli, "BASELINE_SHA256", cli.sha256(path))
    with pytest.raises(ValueError, match="NAV1 units"):
        cli.references(panel, 1, path)


# Run actual funded phases while forbidding model fitting and ETF replay.
def test_actual_evaluation_retains_all_phases_traces_and_never_refits(
    tmp_path, monkeypatch
):
    panel, grades, eligible, cubes, dataset, forecasts = _case()
    baseline = _baseline(tmp_path, panel, monkeypatch)
    output = tmp_path / "run"
    output.mkdir()
    cli.write_json(output / "fit-complete.json", {"fixture": True})
    monkeypatch.setattr(
        cli, "fitted", lambda *_: (forecasts, {}, {"forecast_sha256": "synthetic-test"})
    )
    monkeypatch.setattr(cli.models, "walk_forward", _forbidden)
    monkeypatch.setattr(cli.scoring, "benchmark_account", _forbidden)
    report = cli.evaluate(panel, grades, eligible, cubes, dataset, output, baseline)
    assert len(report["phases"]) == 60
    assert [(row["cost_bps"], row["phase"]) for row in report["phases"]] == [
        (c, p) for c in (0, 10, 25) for p in range(20)
    ]
    phase = report["phases"][0]
    assert phase["candidate"]["intent_trace"][0]["attempt_clock"] == 0
    assert phase["control"]["intent_trace"][0]["attempt_clock"] == 4
    assert phase["paired_gain_initial_nav_units"] < 0
    assert phase["candidate"]["score"]["stocks"] == phase["candidate"]["stocks"]
    assert len(phase["candidate"]["curves"]["nav"]) == 5
    assert report["adoption_eligible"] is False
    report_hash = cli.sha256(output / "evaluation.json")
    monkeypatch.setattr(cli.replay, "account", _forbidden)
    again = cli.evaluate(panel, grades, eligible, cubes, dataset, output, baseline)
    assert again == report
    assert cli.sha256(output / "evaluation.json") == report_hash
    (output / "evaluation.json").write_text("{}")
    with pytest.raises(ValueError, match="refusing overwrite"):
        cli.evaluate(panel, grades, eligible, cubes, dataset, output, baseline)


# Fail if an acceptance path refits or reruns a completed account.
def _forbidden(*args, **kwargs):
    raise AssertionError("forbidden fit, ETF replay or completed-account repetition")


# Authenticate fit source and bytes before invoking the saved-model reader.
def test_fitted_source_and_archive_guards(tmp_path, monkeypatch):
    (tmp_path / "models").mkdir()
    (tmp_path / "models/manifest.json").write_text("{}")
    (tmp_path / "models/predictions.npz").write_bytes(b"receipt-bound-archive")
    source = {"source_revision": "frozen", "files": {"file": "digest"}}
    monkeypatch.setattr(cli, "source_identity", lambda: source)
    receipt = {
        "status": "fitted",
        "source": source,
        "manifest_sha256": cli.sha256(tmp_path / "models/manifest.json"),
        "forecast_sha256": cli.sha256(tmp_path / "models/predictions.npz"),
    }
    cli.write_json(tmp_path / "fit-complete.json", receipt)
    source["files"]["file"] = "changed"
    with pytest.raises(ValueError, match="execution source changed"):
        cli.fitted({}, tmp_path)
    source["files"]["file"] = "digest"
    (tmp_path / "models/predictions.npz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact changed"):
        cli.fitted({}, tmp_path)


# Reject selected or duplicated phase progress instead of restarting scores.
def test_progress_sequence_and_bytes_are_authenticated(tmp_path):
    identity = {"input": "same"}
    cli._report(
        tmp_path,
        "evaluation-progress",
        {"identity": identity, "phases": [{"cost_bps": 0, "phase": 1}]},
    )
    with pytest.raises(ValueError, match="phase sequence"):
        cli._progress(tmp_path, identity)
    (tmp_path / "evaluation-progress.json").write_text("{}")
    with pytest.raises(ValueError, match="progress bytes"):
        cli._progress(tmp_path, identity)


# Exercise actual fitting and authenticate its completed receipt without repeating fits.
def test_real_cli_fit_then_saved_forecasts_no_refit(tmp_path, monkeypatch):
    monkeypatch.setattr(original, "MIN_TRAIN_DAYS", 20)
    dates = np.busday_offset("2026-05-01", np.arange(70)).astype("datetime64[D]")
    rng = np.random.default_rng(132)
    x = rng.normal(size=(70, 25, 2, 2)).astype(np.float32)
    data = {
        "X": x,
        "y": np.full((70, 25, 2, 3), np.nan, dtype=np.float32),
        "valid": np.ones((70, 25, 2), dtype=bool),
        "dates": dates,
        "feature_names": ["structure", "volatility"],
        "next_open": (10 + 0.1 * x[..., 0]).astype(np.float32),
        "current_close": np.full((70, 25, 2), 10, dtype=np.float32),
    }
    before, _ = cli.fit(data, tmp_path)
    assert np.isfinite(before[-1, :24]).all()
    monkeypatch.setattr(cli.models, "walk_forward", _forbidden)
    loaded, _ = cli.fit(data, tmp_path)
    np.testing.assert_array_equal(before, loaded)
