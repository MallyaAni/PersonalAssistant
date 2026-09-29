"""Each stage-two prediction head needs its own matured training supervision."""

from dataclasses import replace

import numpy as np
import pytest

from backend.market import deep_intraday as stage1
from backend.market import deep_stage2 as stage2


# Build small sequence arrays on the unchanged production fit/purge/session schedule.
def _dataset(*, rows=None):
    rows = stage2.MIN_TRAIN + 3 if rows is None else rows
    sessions = np.arange("2020-01-01", "2025-01-01", dtype="datetime64[D]")
    sessions = sessions[np.is_busday(sessions)][:rows]
    return stage2.Dataset2(
        dates=sessions.copy(),
        tickers=np.full(rows, "AAA"),
        x_seq=np.zeros((rows, stage2.SLOTS, 3), dtype=np.float32),
        x_scalar=np.zeros((rows, 1)),
        scalar_names=("synthetic",),
        y_return=np.full(rows, 0.01),
        y_rank=np.full(rows, 0.5),
        y_downgrade20=np.full(rows, 0.0),
        y_drawdown20=np.full(rows, -0.1),
        y_vol20=np.full(rows, -5.0),
        trailing_vol20=np.full(rows, -5.0),
        fwd20=np.full(rows, 0.02),
        grade=np.full(rows, stage2.A_MIN_GRADE),
        sessions=sessions,
        session_index=np.arange(rows),
        k=1,
        benchmarks=(),
        benchmark_fill=0,
        row_selection=stage1.ROW_SELECTION,
    )


# Return finite, read-only head outputs to isolate the public walk-forward boundary.
def _finite_fitter(monkeypatch):
    calls = []

    # Retain the actual fitter arguments and masks without running a training job.
    def factory(dataset, model, targets, labels, device):
        # Simulate a network's finite raw output, even for heads with no supervision.
        def fit(train, test):
            prediction = np.tile(
                np.arange(1, len(targets) + 1, dtype=float), (int(test.sum()), 1)
            )
            prediction.setflags(write=False)
            calls.append(
                {
                    "model": model,
                    "targets": targets,
                    "labels": labels.copy(),
                    "train": train.copy(),
                    "test": test.copy(),
                    "output": prediction,
                    "device": device,
                }
            )
            return prediction, 321

        return fit

    monkeypatch.setattr(stage2, "_fitter", factory)
    return calls


# Every model family must suppress missing and undersupported heads independently.
@pytest.mark.parametrize("model", stage2.MODELS)
@pytest.mark.parametrize("reverse_targets", [False, True])
def test_each_head_requires_existing_minimum_supervision(
    monkeypatch, model, reverse_targets
):
    dataset = _dataset()
    absent = np.full(len(dataset), np.nan)
    scarce = absent.copy()
    scarce[: stage2.MIN_NAMES - 1] = -0.1
    scarce[stage2.MIN_NAMES - 1] = np.inf
    boundary = absent.copy()
    boundary[: stage2.MIN_NAMES] = -5.0
    dataset = replace(
        dataset,
        y_downgrade20=absent,
        y_drawdown20=scarce,
        y_vol20=boundary,
    )
    targets = tuple(reversed(stage2.TARGETS)) if reverse_targets else stage2.TARGETS
    calls = _finite_fitter(monkeypatch)
    forecasts = stage2.walk_forward(dataset, model, targets, device="cpu")
    assert len(calls) == 1
    train, test = calls[0]["train"], calls[0]["test"]
    assert np.array_equal(
        train, dataset.session_index < stage2.MIN_TRAIN - stage2.PURGE
    )
    assert np.array_equal(test, dataset.session_index >= stage2.MIN_TRAIN)
    assert calls[0]["model"] == model
    assert calls[0]["device"] == "cpu"
    assert np.isfinite(calls[0]["output"]).all(), "Do not mutate fitter-owned output"
    counts = {
        "rank": int(train.sum()),
        "downgrade20": 0,
        "drawdown20": stage2.MIN_NAMES - 1,
        "vol20": stage2.MIN_NAMES,
    }
    for target, forecast in forecasts.items():
        assert np.isnan(forecast.values[~test]).all()
        if counts[target] < stage2.MIN_NAMES:
            assert np.isnan(forecast.values[test]).all(), target
        else:
            np.testing.assert_array_equal(
                forecast.values[test], targets.index(target) + 1
            )
        assert forecast.parameters == 321
    for forecast in forecasts.values():
        assert forecast.fits[0]["n_train_by_target"] == counts
        assert forecast.fits[0]["supervised_targets"] == [
            name for name in targets if counts[name] >= stage2.MIN_NAMES
        ]


# A later label crosses eligibility only at the next unchanged purged refit boundary.
def test_head_becomes_available_only_after_its_third_label_matures(monkeypatch):
    dataset = _dataset(rows=stage2.MIN_TRAIN + stage2.REFIT + 3)
    label = np.full(len(dataset), np.nan)
    label[: stage2.MIN_NAMES - 1] = 0.0
    label[stage2.MIN_TRAIN - stage2.PURGE] = 1.0
    dataset = replace(dataset, y_downgrade20=label)
    calls = _finite_fitter(monkeypatch)
    forecasts = stage2.walk_forward(dataset, "cnn")
    assert len(calls) == 2
    score = forecasts["downgrade20"]
    first = (dataset.session_index >= stage2.MIN_TRAIN) & (
        dataset.session_index < stage2.MIN_TRAIN + stage2.REFIT
    )
    second = dataset.session_index >= stage2.MIN_TRAIN + stage2.REFIT
    assert np.isnan(score.values[first]).all()
    assert np.isfinite(score.values[second]).all()
    assert [fit["n_train_by_target"]["downgrade20"] for fit in score.fits] == [
        stage2.MIN_NAMES - 1,
        stage2.MIN_NAMES,
    ]
    assert score.fits[0]["test_start"] == str(dataset.sessions[stage2.MIN_TRAIN])
    assert score.fits[1]["test_start"] == str(
        dataset.sessions[stage2.MIN_TRAIN + stage2.REFIT]
    )


# Unknown test outcomes cannot suppress a head trained on sufficient past labels.
def test_test_label_missingness_does_not_determine_prediction_coverage(monkeypatch):
    dataset = _dataset()
    labels = dataset.y_downgrade20.copy()
    labels[dataset.session_index >= stage2.MIN_TRAIN] = np.nan
    dataset = replace(dataset, y_downgrade20=labels)
    calls = _finite_fitter(monkeypatch)
    forecast = stage2.walk_forward(dataset, "patchtst", ("downgrade20",))["downgrade20"]
    assert len(calls) == 1
    test = dataset.session_index >= stage2.MIN_TRAIN
    assert np.isfinite(forecast.values[test]).all()
    assert forecast.fits[0]["n_train_by_target"] == {
        "downgrade20": stage2.MIN_TRAIN - stage2.PURGE
    }


# Global multi-head row eligibility cannot substitute for a head's own label count.
def test_union_of_sparse_heads_does_not_qualify_any_one_head(monkeypatch):
    dataset = _dataset()
    changes = {}
    for index, target in enumerate(stage2.TARGETS):
        labels = np.full(len(dataset), np.nan)
        labels[index] = 0.0
        changes[f"y_{target}"] = labels
    dataset = replace(dataset, **changes)
    calls = _finite_fitter(monkeypatch)
    forecasts = stage2.walk_forward(dataset, "cnn")
    assert len(calls) == 1, "Preserve the existing aggregate training schedule"
    assert int(calls[0]["train"].sum()) == len(stage2.TARGETS)
    for forecast in forecasts.values():
        assert np.isnan(forecast.values).all()
        assert forecast.fits[0]["supervised_targets"] == []
