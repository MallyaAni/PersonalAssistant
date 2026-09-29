"""Causal features, purged fits and real saved-model tests for daily actions."""

import json
from dataclasses import replace

import numpy as np
import pytest

from backend.market import daily_action_model as module
from backend.market.panel import Panel


# Make a deterministic daily market with enough actual rows for the fixed fold floor.
def _panel():
    dates = np.arange(np.datetime64("2015-01-01"), np.datetime64("2020-01-01"))
    dates = dates[np.is_busday(dates)]
    random = np.random.default_rng(71)
    returns = random.normal(0.0005, 0.015, (len(dates), 3))
    close = 100 * np.exp(np.cumsum(returns, axis=0))
    open_ = close * np.exp(random.normal(0, 0.003, close.shape))
    panel = Panel(
        dates=dates,
        tickers=("AAA", "BBB", "SPY"),
        open=open_,
        high=np.maximum(close, open_) * 1.01,
        low=np.minimum(close, open_) * 0.99,
        close=close,
        adj_close=close.copy(),
        volume=random.integers(1000, 10000, close.shape).astype(float),
        themes={},
        benchmark="SPY",
    )
    return panel


# Supply the incumbent eligibility gate with no future-dependent filtering.
def _data(panel=None):
    panel = _panel() if panel is None else panel
    return module.build_dataset(
        panel,
        np.ones(panel.close.shape, dtype=bool),
        np.full(panel.close.shape, 2),
        panel.close[:, 2],
    )


# Future observations cannot affect today's features or row existence.
def test_features_ignore_future_tampering():
    panel = _panel()
    original = _data(panel)
    cut = 650
    changed = {}
    for field in ("open", "high", "low", "close", "adj_close", "volume"):
        values = getattr(panel, field).copy()
        values[cut + 1 :] *= 19
        changed[field] = values
    modified = _data(replace(panel, **changed))
    np.testing.assert_allclose(
        original.features[: cut + 1], modified.features[: cut + 1], equal_nan=True
    )
    np.testing.assert_array_equal(
        original.eligible[: cut + 1], modified.eligible[: cut + 1]
    )
    assert original.features.shape[-1] == 22


# Labels use next open through the sixth future open and keep the newest input rows.
def test_label_horizon_and_unavailable_targets():
    panel = _panel()
    data = _data(panel)
    np.testing.assert_allclose(
        data.labels[100], np.log(panel.open[106] / panel.open[101])
    )
    assert data.label_end[100] == data.dates[106]
    assert np.isnan(data.labels[-6:]).all()
    assert np.isnat(data.label_end[-6:]).all()
    assert data.eligible[-6:, :2].all()
    assert not data.eligible[:, 2].any()


# Future missing prices change labels, not the earlier feature-row selection.
def test_missing_future_endpoint_never_drops_current_row():
    panel = _panel()
    original = _data(panel)
    open_ = panel.open.copy()
    open_[506, 0] = np.nan
    data = _data(replace(panel, open=open_))
    assert original.eligible[500, 0]
    assert data.eligible[500, 0]
    assert np.isfinite(original.labels[500, 0])
    assert np.isnan(data.labels[500, 0])


# Invalid prices and volume remain missing while genuine large moves are preserved.
def test_invalid_inputs_and_real_extremes():
    panel = _panel()
    fields = {}
    for field in ("open", "high", "low", "close", "adj_close"):
        values = getattr(panel, field).copy()
        values[500:, 0] *= 5
        fields[field] = values
    extreme = _data(replace(panel, **fields))
    assert extreme.eligible[500, 0]
    assert extreme.features[500, 0, 0] > 1
    assert extreme.labels[494, 0] > 1
    volume = panel.volume.copy()
    volume[500, 0] = 0
    invalid = _data(replace(panel, volume=volume))
    assert not invalid.eligible[500, 0]
    assert np.isnan(invalid.features[500, 0, 0])


# Member and A-grade gates are enforced without adding grade information to features.
def test_membership_and_grade_gate():
    panel = _panel()
    member = np.ones(panel.close.shape, dtype=bool)
    grades = np.full(panel.close.shape, 2)
    member[100, 0] = False
    grades[101, 0] = 1
    data = module.build_dataset(panel, member, grades, panel.close[:, 2])
    assert not data.eligible[100, 0]
    assert not data.eligible[101, 0]
    assert data.eligible[102, 0]
    assert not any("grade" in name for name in data.feature_names)


# Label-end purging separates every date's entire cross-section at both boundaries.
def test_fold_rows_purge_label_overlap():
    data = _data()
    fit = module._rows(data, np.datetime64("2016-01-01"), np.datetime64("2018-01-01"))
    selected = fit.any(axis=1)
    assert (data.label_end[selected] < np.datetime64("2018-01-01")).all()
    boundary = (data.dates < np.datetime64("2018-01-01")) & (
        data.label_end >= np.datetime64("2018-01-01")
    )
    assert boundary.any()
    assert not fit[boundary].any()
    assert not fit[data.dates < np.datetime64("2016-01-01")].any()


# Fit real models once so saved states and predictions can be checked independently.
@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    pytest.importorskip("sklearn")
    data = _data()
    output = tmp_path_factory.mktemp("daily-action") / "fitted"
    result = module.train(data, output, last_test_year=2019)
    return data, output, result


# Fit all eight settings and predict rows whose future labels are unavailable.
def test_real_fit_and_saved_prediction_state(fitted):
    import joblib

    data, output, result = fitted
    assert len(result.receipts) == 1
    receipt = result.receipts[0]
    assert receipt["status"] == "FITTED"
    assert len(receipt["settings"]) == 8
    assert receipt["selected_tree_iterations"] in (25, 50, 100)
    assert receipt["fit"]["last_label_end"] < "2018-01-01"
    assert receipt["refit"]["last_label_end"] < "2019-01-01"
    for family in ("ridge", "tree"):
        saved = joblib.load(output / "models" / f"2019-{family}.joblib")
        predicted = saved["model"].predict(data.features[-1, :2])
        np.testing.assert_allclose(predicted, result.predictions[family][-1, :2])
        assert np.isnan(
            result.predictions[family][data.dates < np.datetime64("2019-01-01")]
        ).all()
    assert np.isfinite(result.predictions["mean"][-1, :2]).all()


# Ridge preprocessing and the mean baseline are fitted strictly before the test year.
def test_train_only_preprocessing(fitted):
    import joblib

    data, output, result = fitted
    rows = module._rows(data, np.datetime64("2016-01-01"), np.datetime64("2019-01-01"))
    pipeline = joblib.load(output / "models" / "2019-ridge.joblib")["model"]
    np.testing.assert_allclose(
        pipeline.named_steps["standardscaler"].mean_, data.features[rows].mean(axis=0)
    )
    assert result.receipts[0]["refit_mean"] == pytest.approx(data.labels[rows].mean())


# Changing every outer-test outcome cannot affect fitted state or any prediction.
def test_outer_labels_never_choose_or_fit_models(fitted, tmp_path):
    data, _, original = fitted
    labels = data.labels.copy()
    labels[data.dates >= np.datetime64("2019-01-01")] = -1000
    modified = module.train(
        replace(data, labels=labels), tmp_path / "poisoned", last_test_year=2019
    )
    for family in original.predictions:
        np.testing.assert_allclose(
            original.predictions[family], modified.predictions[family], equal_nan=True
        )
    assert original.receipts == modified.receipts


# Insufficient labels produce a recorded invalid fold instead of a relaxed split.
def test_insufficient_fold_is_explicit(tmp_path):
    pytest.importorskip("sklearn")
    data = _data()
    with pytest.raises(ValueError, match="required fit/validation"):
        module.train(
            replace(data, eligible=np.zeros_like(data.eligible)),
            tmp_path / "invalid",
            last_test_year=2019,
        )
    evidence = json.loads((tmp_path / "invalid" / "training_receipts.json").read_text())
    assert not evidence["complete"]
    assert evidence["folds"][0]["status"] == "INVALID_INSUFFICIENT_LABELS"


# An empty outer cross-section cannot become a successful all-fallback experiment.
def test_empty_prediction_fold_is_rejected(tmp_path):
    pytest.importorskip("sklearn")
    data = _data()
    eligible = data.eligible.copy()
    eligible[data.dates >= np.datetime64("2019-01-01")] = False
    with pytest.raises(ValueError, match="no eligible prediction"):
        module.train(
            replace(data, eligible=eligible), tmp_path / "empty", last_test_year=2019
        )
    evidence = json.loads((tmp_path / "empty" / "training_receipts.json").read_text())
    assert not evidence["complete"]
    assert evidence["folds"][0]["status"] == "INVALID_NO_ELIGIBLE_TEST_ROWS"


# Misaligned benchmarks and overwritten evidence are rejected before fitting.
def test_bad_alignment_and_existing_output_are_rejected(tmp_path):
    panel = _panel()
    with pytest.raises(ValueError, match="QQQ"):
        module.build_dataset(
            panel, np.ones(panel.close.shape), np.full(panel.close.shape, 2), np.ones(7)
        )
    pytest.importorskip("sklearn")
    with pytest.raises(FileExistsError):
        module.train(_data(), tmp_path, last_test_year=2019)
