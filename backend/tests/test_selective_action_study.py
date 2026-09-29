"""Exact-label study integration, missing future rows and fixed screening floors."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import selective_action_study as study


# Supply all registered offsets with intentionally passing synthetic summary statistics.
def passing_runs():
    return [
        {
            "cost_bps": 25.0,
            "offset": offset,
            "accounts": {
                name: {
                    "all": {
                        "cagr": 0.12 if name in ("ridge", "tree") else 0.1,
                        "drawdown": -0.2,
                    }
                }
                for name in ("ridge", "tree", "original_v4", "momentum")
            },
            "paired": {
                name: {
                    control: {
                        "mean_daily_bp": 2.0,
                        "hac_t": 2.1,
                        "recent_mean_daily_bp": 0.1,
                    }
                    for control in ("original_v4", "momentum")
                }
                for name in ("ridge", "tree")
            },
        }
        for offset in study.OFFSETS
    ]


# A research pass is not promotion, and the matched unlearned control can veto it.
def test_fixed_screens_require_both_comparators():
    runs = passing_runs()
    assert study.verdict(runs)["ridge"]["status"] == "RESEARCH_PASS_ONLY"
    runs[0]["paired"]["ridge"]["momentum"]["hac_t"] = 1.99
    assert study.verdict(runs)["ridge"]["status"] == "DO_NOT_PROMOTE"
    runs = passing_runs()
    runs[2]["accounts"]["tree"]["all"]["drawdown"] = -0.231
    assert study.verdict(runs)["tree"]["status"] == "DO_NOT_PROMOTE"


# Missing or duplicate offsets must not masquerade as a complete registered evaluation.
@pytest.mark.parametrize("offsets", [(0, 5, 10), (0, 5, 10, 10)])
def test_incomplete_screen_fails(offsets):
    rows = passing_runs()[: len(offsets)]
    for row, offset in zip(rows, offsets, strict=True):
        row["offset"] = offset
    with pytest.raises(ValueError, match="exactly four"):
        study.verdict(rows)


# Input-cache integrity must be checked before the unsafe deserializer is reachable.
def test_trusted_cache_hash_precedes_deserialization(tmp_path, monkeypatch):
    cache = tmp_path / "cache.pickle"
    cache.write_bytes(b"not a pickle")
    calls = []
    monkeypatch.setattr(study.pickle, "load", lambda stream: calls.append(stream))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        study.load_inputs(cache, "0" * 64)
    assert not calls


# Round-trip only the explicitly trusted and hash-matched public-input schema.
def test_input_cache_round_trip_and_invalid_schema(tmp_path):
    cache = tmp_path / "cache.pickle"
    bundle = dict(report=None, membership=None, indexes=None, spy=None, qqq=None)
    with cache.open("wb") as stream:
        study.pickle.dump(bundle, stream)
    assert study.load_inputs(cache, study.file_hash(cache)) == bundle
    with cache.open("wb") as stream:
        study.pickle.dump({"wrong": True}, stream)
    with pytest.raises(ValueError, match="schema"):
        study.load_inputs(cache, study.file_hash(cache))


# Enforce current opportunity timing without using any future label availability.
def test_teacher_collector_keeps_unmatured_present_candidates(monkeypatch):
    from backend.market import selective_action_execution as execution

    choices = [SimpleNamespace(symbol="A", action="Trim")]
    monkeypatch.setattr(execution, "candidates", lambda context, row: choices)
    data = SimpleNamespace(features=np.ones((8, 2, 22)))
    collector = study.TeacherCollector(data)
    collector.capture(SimpleNamespace(t=5))
    assert collector(SimpleNamespace(t=5, last_rebalance=0)) is None
    assert len(collector.opportunities) == 1
    collector.capture(SimpleNamespace(t=6))
    collector(SimpleNamespace(t=6, last_rebalance=0))
    assert len(collector.opportunities) == 1
    with pytest.raises(ValueError, match="checkpoint"):
        collector(SimpleNamespace(t=5, last_rebalance=0))


# Actual stateful forks produce finite labels while late candidate rows remain missing.
def test_synthetic_counterfactual_labels_and_parity(tmp_path):
    from backend.agents.trading.desk import simulate
    from backend.market import daily_action_model, profit_taking
    from backend.market.selective_action_model import STATE_FEATURE_NAMES
    from backend.tests.funded_simulator_fixtures import _report

    rows, names = 70, 7
    closes = np.full((rows, names), 100.0)
    closes[:, 0] = 100 * np.exp(np.arange(rows) * -0.004)
    grades = np.zeros_like(closes, dtype=int)
    grades[:, :2] = 3
    report = _report(close=closes, grades=grades)
    # The fixture starts after 2016, retaining all its actual close-state history.
    mask = np.ones_like(closes, dtype=bool)
    feature_names = (
        "stock_log_return_1",
        "stock_log_return_5",
        "stock_log_return_20",
        "stock_log_return_60",
        "stock_volatility_20",
        "stock_log_close_mean_20",
        "stock_log_close_mean_60",
        "stock_peak_drawdown_20",
        "stock_log_open_gap",
        "stock_log_high_low",
        "stock_log_close_open",
        "stock_log_relative_volume_20",
        "spy_log_return_1",
        "spy_log_return_5",
        "spy_log_return_20",
        "spy_log_return_60",
        "spy_volatility_20",
        "qqq_log_return_1",
        "qqq_log_return_5",
        "qqq_log_return_20",
        "qqq_log_return_60",
        "qqq_volatility_20",
    )
    data = daily_action_model.DailyData(
        report.panel.dates,
        report.panel.tickers,
        np.zeros((rows, names, 22)),
        np.full((rows, names), np.nan),
        mask,
        feature_names,
        np.full(rows, np.datetime64("NaT", "D")),
    )
    options = profit_taking.control_options(report.panel)
    prepared = simulate.prepare_research(report, **options)
    labels = study.generate_labels(
        report, mask, data, tmp_path / "labels", prepared=prepared, options=options
    )
    assert np.isfinite(labels.labels).any()
    assert np.isnan(labels.labels).any()
    assert labels.feature_names == feature_names + STATE_FEATURE_NAMES
    assert len(labels.dates) == len(labels.features)
    assert np.isnat(labels.label_end[np.isnan(labels.labels)]).all()
    # Labels are net account differences, not the raw stock's forward return.
    assert np.max(np.abs(labels.labels[np.isfinite(labels.labels)])) < 0.2
    evidence = study.json.loads(
        (tmp_path / "labels" / "label-evidence.json").read_text()
    )
    for row in evidence:
        if row["label"] is not None:
            assert row["label"] == pytest.approx(
                (row["action_endpoint_nav"] - row["baseline_endpoint_nav"]) / row["nav"]
            )
    before = deepcopy(labels.features)
    assert np.isfinite(before).all()
