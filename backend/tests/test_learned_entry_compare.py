"""Independent clock and missing-outcome acceptance for model comparison."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli.market_learned_entry_compare import (
    common_clock,
    learned_forecasts,
    pretrained_forecasts,
    sha256,
    source_identity,
)
from backend.market.learned_entry_evaluation import learned_account
from backend.market.learned_entry_models import _array_hash
from backend.market.pretrained_entry_model import ARTIFACT_HASHES, MODEL_REVISION


# Preserve unlabeled future outcomes while selecting only the fixed holdout clock.
def test_common_clock_does_not_select_outcomes():
    dates = np.arange("2026-08-14", "2026-08-20", dtype="datetime64[D]")
    shape = (len(dates), 25, 2, 3)
    values = np.full(shape, 0.01, dtype=np.float32)
    valid = np.ones(shape[:-1], dtype=bool)
    dataset = {"dates": dates, "valid": valid}
    selected = common_clock(values, dataset)
    assert np.isnan(selected[dates < np.datetime64("2026-08-17")]).all()
    assert np.isfinite(selected[dates >= np.datetime64("2026-08-17"), 9]).all()
    assert np.isnan(selected[:, :9]).all()
    assert np.isnan(selected[:, 10:]).all()


# Reject forecasts on unusable prefixes instead of inventing opportunities.
def test_common_clock_rejects_invalid_observation():
    dates = np.array(["2026-08-17"], dtype="datetime64[D]")
    values = np.ones((1, 25, 1, 3), dtype=np.float32)
    dataset = {"dates": dates, "valid": np.zeros((1, 25, 1), dtype=bool)}
    with pytest.raises(ValueError, match="invalid shared"):
        common_clock(values, dataset)


# A learned-funded account reconciles its cash, costs, shares and per-stock gain.
def test_learned_account_real_sizing_and_funding():
    days = 256
    dates = np.datetime64("2025-01-01") + np.arange(days).astype("timedelta64[D]")
    prices = np.full((days, 3), 10.0)
    panel = SimpleNamespace(dates=dates, tickers=("A", "SPY", "QQQ"), adj_close=prices)
    dataset = {
        "current_close": np.broadcast_to(prices[:, None, :], (days, 25, 3)),
        "next_open": np.broadcast_to(prices[:, None, :], (days, 25, 3)),
        "prior_grades": np.full((days, 3), 3),
        "prior_eligible": np.tile([True, False, False], (days, 1)),
    }
    forecasts = np.full((days, 25, 3, 3), np.nan)
    forecasts[:, 9, 0] = [0.03, 0.05, 0]
    result = learned_account(panel, dataset, forecasts, 253, 10)
    assert result["nav"][0] == 1
    assert result["counts"]["fills"] >= 1
    assert result["fees"].sum() > 0
    assert (result["cash"] >= 0).all()
    assert result["nav"][-1] < 1
    assert sum(
        row["net_gain_initial_nav_units"] for row in result["stocks"].values()
    ) == pytest.approx(result["nav"][-1] - 1)
    assert result["stocks"]["SPY"]["fills"] == 0
    assert result["stocks"]["QQQ"]["fills"] == 0


# Publish a minimal valid forecast receipt to exercise actual immutable-array checks.
def artifact_dataset(tmp_path):
    import json

    shape = (2, 25, 1)
    dataset = {
        "dates": np.array(["2026-08-17", "2026-09-01"], dtype="datetime64[D]"),
        "X": np.zeros((*shape, 1), dtype=np.float32),
        "y": np.zeros((*shape, 3), dtype=np.float32),
        "valid": np.ones(shape, dtype=bool),
        "feature_names": ("feature",),
        "training_symbols": np.ones(1, dtype=bool),
        "tickers": ("AAA",),
        "provenance": {
            "snapshot_sha256": "a",
            "provenance_sha256": "b",
            "cubes": {"AAA": "c"},
            "feature_source_sha256": "d",
        },
    }
    predictions = np.zeros_like(dataset["y"])
    path = tmp_path / "predictions.npz"
    np.savez(path, predictions=predictions, dates=dataset["dates"])
    receipt = {
        "artifact_sha256": sha256(path),
        "prediction_array_sha256": _array_hash(predictions),
        "source": source_identity(),
        "manifest": {
            "identity": {
                "method": "boosting",
                "holdout_label_end_before": "2026-08-17",
                "source_provenance": dataset["provenance"],
                "arrays": {
                    key: _array_hash(dataset[key])
                    for key in ("X", "y", "valid", "dates")
                },
                "feature_names": list(dataset["feature_names"]),
                "training_symbols_sha256": _array_hash(dataset["training_symbols"]),
            },
            "months": [],
        },
    }
    (tmp_path / "complete.json").write_text(json.dumps(receipt))
    return dataset


# Same original hashes cannot conceal an altered prepared feature matrix.
def test_artifact_rejects_changed_causal_arrays(tmp_path):
    dataset = artifact_dataset(tmp_path)
    actual, _ = learned_forecasts(tmp_path, dataset, "boosting")
    assert actual.dtype == np.float32
    dataset["X"][0, 9, 0, 0] = 1
    with pytest.raises(ValueError, match="causal array"):
        learned_forecasts(tmp_path, dataset, "boosting")


# Identical forecast bytes reinterpreted as integers cannot pass a bytes-only digest.
def test_pretrained_rejects_integer_reinterpretation(tmp_path):
    import hashlib
    import json

    dataset = artifact_dataset(tmp_path)
    values = np.ones_like(dataset["y"]).view(np.uint32)
    metadata = {
        "source_identity": dataset["provenance"],
        "forecast_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "model_provenance": {
            "revision": MODEL_REVISION,
            "artifact_hashes": ARTIFACT_HASHES,
        },
        "input_clock": 9,
        "holdout_start": "2026-08-17",
        "holdout_end": "2026-09-30",
    }
    path = tmp_path / "pretrained.npz"
    np.savez(
        path,
        predictions=values,
        dates=dataset["dates"],
        tickers=dataset["tickers"],
        metadata=json.dumps(metadata),
    )
    with pytest.raises(ValueError, match="contract"):
        pretrained_forecasts(path, dataset)
