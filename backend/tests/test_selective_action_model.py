"""Real fits, causal fold boundaries and current-state action model checks."""

import json
from dataclasses import replace

import numpy as np
import pytest

from backend.market import selective_action_model as module


# Describe one valid action using current holdings and the signed intervention size.
def _features(daily, action):
    held = 0.0 if action == "Buy" else 0.1
    change = {"Buy": 0.02, "Add": 0.02, "Trim": -0.05, "Sell": -0.1}.get(action, 0.02)
    return module.action_features(
        daily,
        held_weight=held,
        cash_share=0.4,
        target_gap=0.05,
        holding_age=0 if action == "Buy" else 40,
        sessions_to_reset=10,
        signed_incremental_weight=change,
        incumbent_weight=held,
        action=action,
    )


# Build causal-looking synthetic candidates while retaining the last unlabeled rows.
def _data(*, missing_training_actions=False):
    sessions = np.arange(np.datetime64("2016-01-01"), np.datetime64("2020-01-01"))
    sessions = sessions[np.is_busday(sessions)]
    dates = np.repeat(sessions, 4)
    actions = np.tile(module.ACTIONS, len(sessions))
    random = np.random.default_rng(83)
    daily = random.normal(0, 0.03, (len(dates), 22))
    features = np.stack(
        [
            _features(values, action)
            for values, action in zip(daily, actions, strict=True)
        ]
    )
    labels = 0.08 * daily[:, 0] + np.tile([0.001, 0.002, -0.001, -0.002], len(sessions))
    labels += random.normal(0, 0.0001, len(dates))
    label_end = np.full(len(sessions), np.datetime64("NaT", "D"))
    label_end[:-20] = sessions[20:]
    label_end = np.repeat(label_end, 4)
    labels[np.isnat(label_end)] = np.nan
    keep = np.ones(len(dates), dtype=bool)
    if missing_training_actions:
        keep = (dates >= np.datetime64("2019-01-01")) | np.isin(
            actions, ("Buy", "Trim")
        )
    return module.ActionData(
        dates[keep],
        features[keep],
        labels[keep],
        label_end[keep],
        actions[keep],
        tuple(f"daily_{i}" for i in range(22)) + module.STATE_FEATURE_NAMES,
    )


# State columns have one fixed meaning and action encodings preserve intervention signs.
@pytest.mark.parametrize("action", module.ACTIONS)
def test_current_action_feature_contract(action):
    values = _features(np.arange(22, dtype=float), action)
    assert values.shape == (33,)
    np.testing.assert_array_equal(values[:22], np.arange(22))
    np.testing.assert_array_equal(
        values[-4:], np.asarray([action == a for a in module.ACTIONS], dtype=float)
    )
    assert values[23] == 0.4
    assert values[25] == (0 if action == "Buy" else 40)
    assert values[26] == 10
    assert (values[27] > 0) == (action in ("Buy", "Add"))


# Invalid current information cannot become a fabricated valid proposal.
def test_invalid_action_semantics_are_rejected():
    with pytest.raises(ValueError, match="22 finite"):
        _features(np.full(22, np.nan), "Buy")
    with pytest.raises(ValueError, match="action must"):
        _features(np.zeros(22), "Hold")
    with pytest.raises(ValueError, match="requires no holding"):
        module.action_features(
            np.zeros(22),
            held_weight=0.1,
            cash_share=0.4,
            target_gap=0.1,
            holding_age=20,
            sessions_to_reset=10,
            signed_incremental_weight=0.02,
            incumbent_weight=0.1,
            action="Buy",
        )
    with pytest.raises(ValueError, match="signed intervention"):
        module.action_features(
            np.zeros(22),
            held_weight=0.1,
            cash_share=0.4,
            target_gap=0.1,
            holding_age=20,
            sessions_to_reset=10,
            signed_incremental_weight=0.02,
            incumbent_weight=0.1,
            action="Sell",
        )


# The flat dataset owns its inputs and retains unknown outcomes without imputing zero.
def test_dataset_owns_inputs_and_keeps_unlabeled_rows():
    data = _data()
    copied = data.features.copy()
    frozen = replace(data, features=copied)
    copied[:] = 100
    np.testing.assert_array_equal(frozen.features, data.features)
    assert not frozen.features.flags.writeable
    assert np.isnan(frozen.labels[-80:]).all()
    assert np.isnat(frozen.label_end[-80:]).all()
    assert len(frozen.dates) == len(data.dates)


# Every same-date candidate shares a partition and forward endpoints cannot cross it.
def test_rows_purge_whole_counterfactual_horizon():
    data = _data()
    stop = np.datetime64("2018-01-01")
    rows = module._rows(data, np.datetime64("2016-01-01"), stop)
    assert (data.label_end[rows] < stop).all()
    overlaps = (data.dates < stop) & (data.label_end >= stop)
    assert overlaps.any()
    assert not rows[overlaps].any()
    assert np.unique(rows.reshape(-1, 4), axis=1).shape[1] == 1


# Fit real ridge and tree models once for saved-model and causal-state checks.
@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    pytest.importorskip("sklearn")
    data = _data(missing_training_actions=True)
    output = tmp_path_factory.mktemp("selective-model") / "fitted"
    result = module.train(data, output, last_test_year=2019)
    return data, output, result


# Fit eight settings, predict unlabeled rows and save reloadable model state.
def test_real_training_and_saved_models(fitted):
    import joblib

    data, output, result = fitted
    receipt = result.receipts[0]
    assert receipt["status"] == "FITTED"
    assert len(receipt["settings"]) == 8
    assert receipt["fit"]["last_label_end"] < "2018-01-01"
    assert receipt["validation"]["last_label_end"] < "2019-01-01"
    assert receipt["refit"]["last_label_end"] < "2019-01-01"
    for family in ("ridge", "tree"):
        saved = joblib.load(output / "models" / f"2019-{family}.joblib")
        prediction = saved["model"].predict(data.features[-4:])
        np.testing.assert_allclose(prediction, result.predictions[family][-4:])
        assert np.isfinite(result.predictions[family][-80:]).all()
        assert np.isnan(
            result.predictions[family][data.dates < np.datetime64("2019-01-01")]
        ).all()
    evidence = json.loads((output / "training_receipts.json").read_text())
    assert evidence["complete"]
    assert evidence["feature_names"] == list(data.feature_names)


# Preprocessing and action constants use only labels matured before the outer year.
def test_train_only_scaling_and_absent_action_mean(fitted):
    data, _, result = fitted
    rows = module._rows(data, np.datetime64("2016-01-01"), np.datetime64("2019-01-01"))
    scaler = result.models[2019]["ridge"].named_steps["standardscaler"]
    np.testing.assert_allclose(scaler.mean_, data.features[rows].mean(axis=0))
    assert result.means[2019]["Add"] == 0
    assert result.means[2019]["Sell"] == 0
    expected = data.labels[rows & (data.actions == "Buy")].mean()
    assert result.means[2019]["Buy"] == pytest.approx(expected)


# Predict from the candidate account's new features, not a teacher-row lookup.
def test_predict_reads_current_state_and_enforces_year(fitted):
    data, _, result = fitted
    current = data.features[-4:].copy()
    original = result.predict("ridge", "2019-12-31", current, data.actions[-4:])
    current[:, 0] += 1
    changed = result.predict("ridge", "2019-12-31", current, data.actions[-4:])
    assert np.any(np.abs(original - changed) > 0.001)
    with pytest.raises(ValueError, match="no past-fitted"):
        result.predict("ridge", "2018-12-31", current, data.actions[-4:])
    with pytest.raises(ValueError, match="no past-fitted"):
        result.predict("ridge", "2020-01-01", current, data.actions[-4:])
    with pytest.raises(ValueError, match="one-hot"):
        result.predict("ridge", "2019-12-31", current, np.array(["Buy"] * 4))


# Outer-test outcomes cannot change choices, scalers or prior-model predictions.
def test_future_label_mutation_does_not_change_model(fitted, tmp_path):
    data, _, original = fitted
    labels = data.labels.copy()
    labels[(data.dates >= np.datetime64("2019-01-01")) & np.isfinite(labels)] = 1000
    modified = module.train(
        replace(data, labels=labels), tmp_path / "poisoned", last_test_year=2019
    )
    assert original.receipts == modified.receipts
    for family in ("ridge", "tree", "mean"):
        np.testing.assert_allclose(
            original.predictions[family], modified.predictions[family], equal_nan=True
        )


# Reject insufficient folds with incomplete evidence, without a fallback run.
def test_insufficient_labels_and_existing_output_fail(tmp_path):
    pytest.importorskip("sklearn")
    data = _data()
    with pytest.raises(ValueError, match="required fit/validation"):
        module.train(
            replace(data, labels=np.full(len(data.dates), np.nan)),
            tmp_path / "missing",
            last_test_year=2019,
        )
    evidence = json.loads((tmp_path / "missing" / "training_receipts.json").read_text())
    assert not evidence["complete"]
    assert evidence["folds"][0]["status"] == "INVALID_INSUFFICIENT_LABELS"
    with pytest.raises(FileExistsError):
        module.train(data, tmp_path / "missing", last_test_year=2019)


# Known outcomes without future endpoints are malformed, not a permissible training row.
def test_dataset_rejects_inconsistent_endpoints_and_actions():
    data = _data()
    ends = data.label_end.copy()
    ends[0] = data.dates[0]
    with pytest.raises(ValueError, match="later endpoint"):
        replace(data, label_end=ends)
    actions = data.actions.copy()
    actions[0] = "Sell"
    with pytest.raises(ValueError, match="one-hot"):
        replace(data, actions=actions)
