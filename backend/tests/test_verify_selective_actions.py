"""Bounded read-back checks for labels, account state and real saved models."""

import shutil
from copy import deepcopy

import numpy as np
import pytest

from backend.cli import verify_selective_actions as verifier
from backend.market import selective_action_model as model


# Build one explicit Sell label whose state and terminal arithmetic are hand-checkable.
def _label_fixture():
    dates = np.busday_offset(np.datetime64("2016-01-04"), np.arange(21))
    inputs = {
        "dates": dates,
        "tickers": np.asarray(["A", "SPY"]),
        "adj_close": np.full((21, 2), 100.0),
        "features": np.zeros((21, 2, 22)),
        "membership": np.tile([True, False], (21, 1)),
        "grades": np.tile([2, 0], (21, 1)),
    }
    features = np.r_[np.zeros(22), 0.1, 0.9, 0.1, 0, 20, -0.1, 0.1, 0, 0, 0, 1]
    data = {
        "dates": dates[:1],
        "label_end": dates[-1:],
        "actions": np.asarray(["Sell"]),
        "features": features[None, :],
        "labels": np.asarray([0.1]),
    }
    evidence = [
        {
            "row": 0,
            "t": 0,
            "symbol": "A",
            "action": "Sell",
            "units": 0.0,
            "held_units": 0.001,
            "incumbent_units": 0.001,
            "nav": 1.0,
            "cash": 0.9,
            "last_rebalance": 0,
            "next_rebalance": 20,
            "baseline_endpoint_nav": 1.1,
            "action_endpoint_nav": 1.2,
            "label": 0.1,
        }
    ]
    states = {
        0: {
            "positions": np.array([0.001, 0.0]),
            "cash": 0.9,
            "nav": 1.0,
            "opened": {0: 0},
        }
    }
    plans = {0: (np.array([0.001, 0.0]), 0, 20)}
    forks = {
        "baseline": [{"t": 0, "stop": 20, "nav": 1.1}],
        "full_prefix": [{"t": 0, "symbol": "A", "action": "Sell"}],
    }
    return inputs, data, evidence, states, plans, {20: 1.1}, forks


# Changing a saved label or a state feature must fail the reopened arithmetic check.
def test_label_arithmetic_and_state_tampering():
    args = _label_fixture()
    result = verifier._verify_labels(*args)
    assert result["label_rows"] == 1
    modified = deepcopy(args)
    modified[1]["labels"][0] = 0.2
    with pytest.raises(AssertionError):
        verifier._verify_labels(*modified)
    modified = deepcopy(args)
    modified[1]["features"][0, 25] = 5
    with pytest.raises(AssertionError):
        verifier._verify_labels(*modified)


# A zero-to-positive fill starts age; adding keeps it, and a full exit clears it.
def test_teacher_ages_and_reset_clock_follow_actual_fills():
    events = [
        {"type": "open_account", "session_index": 0},
        {
            "type": "decision",
            "session_index": 0,
            "submitted_units": [1.0],
            "metadata": {"scheduled": True},
        },
        {
            "type": "fill_batch",
            "session_index": 1,
            "positions_before": [0.0],
            "positions_after": [1.0],
        },
        {
            "type": "mark",
            "session_index": 1,
            "positions": [1.0],
            "cash": 0.0,
            "nav": 1.0,
        },
        {
            "type": "fill_batch",
            "session_index": 2,
            "positions_before": [1.0],
            "positions_after": [2.0],
        },
        {
            "type": "mark",
            "session_index": 2,
            "positions": [2.0],
            "cash": 0.0,
            "nav": 2.0,
        },
        {
            "type": "fill_batch",
            "session_index": 3,
            "positions_before": [2.0],
            "positions_after": [0.0],
        },
        {
            "type": "mark",
            "session_index": 3,
            "positions": [0.0],
            "cash": 2.0,
            "nav": 2.0,
        },
    ]
    states, plans = verifier._teacher_states(events)
    assert states[1]["opened"][0] == 1
    assert states[2]["opened"][0] == 1
    assert states[3]["opened"] == {}
    assert plans[0][1:] == (0, 20)


# Fit synthetic models once, then exercise the verifier against real retained states.
@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    pytest.importorskip("sklearn")
    from backend.tests.test_selective_action_model import _data

    data = _data(missing_training_actions=True)
    root = tmp_path_factory.mktemp("selective-verification")
    model.train(data, root / "training", last_test_year=2019)
    arrays = {
        name: getattr(data, name)
        for name in (
            "dates",
            "features",
            "labels",
            "label_end",
            "actions",
            "feature_names",
        )
    }
    return root, arrays


# Reopen real fitted states and independently reconstruct every training partition.
def test_model_receipts_scalers_and_predictions(fitted):
    root, arrays = fitted
    result = verifier._verify_models(root, arrays)
    assert result["models_reloaded"] == 2
    assert result["prediction_samples"] == 6
    modified = dict(arrays)
    modified["label_end"] = arrays["label_end"].copy()
    modified["label_end"][0] = np.datetime64("2019-01-01")
    with pytest.raises(AssertionError):
        verifier._verify_models(root, modified)


# Refuse changed model bytes before the unsafe deserializer can run.
def test_model_hash_is_checked_before_loading(fitted, tmp_path, monkeypatch):
    import joblib

    root, arrays = fitted
    copied = tmp_path / "changed"
    shutil.copytree(root, copied)
    path = copied / "training/models/2019-ridge.joblib"
    path.write_bytes(path.read_bytes() + b"tampered")
    calls = []
    monkeypatch.setattr(joblib, "load", lambda source: calls.append(source))
    with pytest.raises(ValueError, match="model hash mismatch"):
        verifier._verify_models(copied, arrays)
    assert not calls


# The CLI never implicitly trusts an arbitrary user-supplied joblib archive.
def test_cli_requires_explicit_local_model_trust(tmp_path):
    with pytest.raises(SystemExit) as error:
        verifier.main(["--run", str(tmp_path)])
    assert error.value.code == 2
