"""Probability diagnostics preserve paired support and honest loss denominators."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_probabilistic_execution as cli


# Supply two sessions with unequal bar counts to expose accidental bar weighting.
def fixture():
    labels = np.array([[[1.0], [1.0]], [[-1.0], [np.nan]]])
    probabilities = np.array([[[0.8], [0.8]], [[0.8], [0.8]]])
    quantiles = np.broadcast_to([-2.0, 0.0, 2.0], (*labels.shape, 3)).copy()
    return probabilities, quantiles, labels, np.ones(labels.shape, dtype=bool)


# Give each measured session the same total influence despite missing clock labels.
def test_metrics_are_date_balanced_and_keep_missing_labels():
    metrics = cli.probability_metrics(*fixture())
    assert metrics["observations"] == 3
    assert metrics["sessions"] == 2
    assert metrics["brier"] == pytest.approx((0.04 + 0.64) / 2)
    assert metrics["log_loss"] == pytest.approx((-np.log(0.8) - np.log(0.2)) / 2)
    assert metrics["interval_10_90_coverage"] == 1
    assert metrics["reliability"][8]["positive_frequency"] == pytest.approx(0.5)


# An empirical certainty contradicted by an outcome remains infinite, never clipped.
def test_zero_probability_wrong_label_retains_infinite_loss():
    probability, quantiles, labels, valid = fixture()
    probability[0, 0, 0] = 0
    metrics = cli.probability_metrics(probability, quantiles, labels, valid)
    assert metrics["log_loss"] is None
    assert metrics["infinite_log_loss_observations"] == 1
    assert metrics["observations"] == 3


# Use exactly the residual row identities for the raw-price historical reference.
def test_reference_does_not_use_current_outcomes():
    dates = np.array(["2026-01-30", "2026-02-02"], dtype="datetime64[D]")
    labels = np.array([[[1.0], [-1.0]], [[200.0], [200.0]]])
    sample = SimpleNamespace(
        day_indices=np.array([0, 0]),
        clock_indices=np.array([0, 1]),
        weights=np.array([0.5, 0.5]),
    )
    result = SimpleNamespace(
        probability_positive=np.full((2, 2, 1), np.nan),
        quantiles=np.full((2, 2, 1, 3), np.nan),
        dates=dates,
        symbols=("AAA",),
        score_mask=np.ones((2, 2, 1), dtype=bool),
        samples={"2026-02": {"AAA": sample}},
    )
    probability, quantiles = cli.reference(result, labels)
    assert np.isnan(probability[0]).all()
    assert np.all(probability[1] == 0.5)
    np.testing.assert_array_equal(quantiles[1, 0, 0], [-1, -1, 1])


# Keep unavailable forecasts and outcomes visible in the same paired denominator.
def test_summary_keeps_cold_start_and_missing_tail():
    probability, quantiles, labels, valid = fixture()
    probability[0, 0, 0] = np.nan
    result = SimpleNamespace(probability_positive=probability, quantiles=quantiles)
    dates = np.array(["2026-09-29", "2026-09-30"], dtype="datetime64[D]")
    rows = cli.summarize(
        dates, labels, valid, result, np.full_like(probability, 0.5), quantiles
    )
    assert rows[0]["requested_causal_observations"] == 4
    assert rows[0]["probability_available"] == 3
    assert rows[0]["probability_unavailable"] == 1
    assert rows[0]["outcome_available"] == 2
    assert rows[0]["outcome_missing"] == 1


# Refuse forged empirical probabilities instead of repairing them to fit the metric.
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_metrics_refuse_out_of_range_probabilities(value):
    probability, quantiles, labels, valid = fixture()
    probability[0, 0, 0] = value
    with pytest.raises(ValueError, match="Probability"):
        cli.probability_metrics(probability, quantiles, labels, valid)


# Require original receipt bytes before reading untrusted historical contents.
def test_evidence_refuses_changed_bytes_and_symlink(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Original bytes"):
        cli.evidence(path, "0" * 64, json_file=True)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="Regular evidence"):
        cli.evidence(alias, cli.sha256(path), json_file=True)
