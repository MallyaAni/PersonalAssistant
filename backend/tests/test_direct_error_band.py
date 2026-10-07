"""Supplied OOS errors prove causal stock-specific monthly resolution bands."""

import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as bridge_module
from backend.market import direct_daily_arithmetic as direct
from backend.market import direct_error_band as bands
from backend.market import learned_entry_models as base

pytest_plugins = ["backend.tests.test_direct_feature_arithmetic"]


# Supply genuine causal bridge receipts and a caller-authenticated numeric archive.
def fixture(count=660, start="2023-01-03"):
    _, actual = exchange.reviewed_sessions()
    first = np.datetime64(start)
    candidates = np.arange(first, first + np.timedelta64(count * 3, "D"))
    dates = candidates[np.is_busday(candidates, busdaycal=actual)][:count]
    names = ("AAA", "BBB", "SPY", "QQQ")
    opens = np.full((count, 4), 100.0)
    for day in range(count - 2):
        opens[day + 2] = opens[day + 1] * (1 + np.array([0.002, 0.004, 0.001, 0.001]))
    parent = bridge_module.walk_forward(
        dates,
        names,
        opens,
        np.full(opens.shape, 2),
        np.ones(opens.shape, bool),
        np.full(opens.shape, 0.02),
        dates,
        data_as_of=datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        ),
    )
    forecasts = np.full(opens.shape, np.nan)
    months = dates.astype("datetime64[M]")
    for receipt in parent.manifest["months"]:
        if receipt["status"] == "fitted":
            scored = months == np.datetime64(receipt["month"], "M")
            forecasts[scored, 0] = 0.001
            forecasts[scored, 1] = -0.002
    return dates, names, forecasts, manifest(dates, names, forecasts, parent), parent


# Authenticate supplied synthetic forecast bytes exactly as the public archive does.
def manifest(dates, names, forecasts, parent):
    identity = {
        "policy": direct.POLICY,
        "symbols": list(names),
        "target": parent.manifest["target"],
        "config": dict(base.MODEL_CONFIG["boosting"]),
        "minimum_days": bridge_module.MIN_DAYS,
        "label_end": 2,
        "holdout_end_before": str(bridge_module.FREEZE),
        "maximum_days": bridge_module.MAX_DAYS,
        "bridge_manifest_sha256": base._json_hash(parent.manifest),
        "dates_sha256": bridge_module._hash(dates),
        "labels_sha256": bridge_module._hash(parent.labels),
        "label_end_dates_sha256": bridge_module._hash(parent.label_end_dates),
        "score_mask_sha256": bridge_module._hash(parent.score_mask),
        "source_sha256": {
            str(
                path.relative_to(Path(direct.__file__).resolve().parents[2])
            ): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(direct.__file__).resolve(),
                Path(base.__file__).resolve(),
                Path(bridge_module.__file__).resolve(),
                Path(direct.__file__).resolve().parents[2] / direct.PROTOCOL,
            )
        },
    }
    months = dates.astype("datetime64[M]")
    receipts = deepcopy(parent.manifest["months"])
    for receipt in receipts:
        receipt["prediction_sha256"] = bridge_module._hash(
            forecasts[months == np.datetime64(receipt["month"], "M")]
        )
    return {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "forecasts_sha256": bridge_module._hash(forecasts),
        "score_mask_sha256": bridge_module._hash(parent.score_mask),
        "months": receipts,
    }


# Refresh an intentional synthetic source mutation without weakening hash checks.
def changed_labels(parent, labels):
    receipt = deepcopy(parent.manifest)
    receipt["label_sha256"] = bridge_module._hash(labels)
    return replace(parent, labels=labels, manifest=receipt)


# Find one named stock's receipt in the final month for readable assertions.
def stock_receipt(result, name="AAA", month=-1):
    return next(
        row
        for row in result.manifest["months"][month]["stocks"]
        if row["symbol"] == name
    )


# Constant stock errors yield distinct biases without fictitious sampling precision.
def test_constant_stock_errors_zero_standard_error_and_distinct_radii():
    args = fixture()
    result = bands.calibrate(*args)
    a, b = stock_receipt(result), stock_receipt(result, "BBB")
    assert a["radius"] == pytest.approx(0.001, abs=1e-14)
    assert b["radius"] == pytest.approx(0.006, abs=1e-14)
    assert a["standard_error"] < 1e-14
    assert b["standard_error"] < 1e-14
    assert np.isnan(result.radii[:, 2:]).all()
    assert stock_receipt(result, "SPY")["status"] == "excluded_benchmark"
    assert len(result.manifest["months"][-1]["stocks"]) == 4


# Unequal-sized clusters implement the registered sum-based standard error.
def test_cluster_formula_preserves_unequal_month_sizes():
    errors = np.array([0.01, 0.02, 0.03, -0.01, 0.04, 0.05])
    clusters = np.array(
        ["2025-01"] * 2 + ["2025-02"] + ["2025-03"] * 3, dtype="datetime64[M]"
    )
    actual = bands._statistics(errors, clusters)
    bias = errors.mean()
    sums = np.array(
        [(errors[clusters == month] - bias).sum() for month in np.unique(clusters)]
    )
    expected = np.sqrt(3 / 2 * np.sum(sums**2)) / len(errors)
    assert actual["bias"] == pytest.approx(bias)
    np.testing.assert_allclose(actual["cluster_sums"], sums, atol=1e-16)
    assert actual["standard_error"] == pytest.approx(expected)
    assert actual["radius"] == pytest.approx(abs(bias) + expected)


# Neither one observation nor many observations in one month supplies a radius.
@pytest.mark.parametrize(
    ("errors", "clusters", "status"),
    [
        ([0.1], ["2025-01"], "insufficient_observations"),
        ([0.1, 0.2], ["2025-01", "2025-01"], "insufficient_clusters"),
        ([], [], "insufficient_observations"),
    ],
)
def test_observation_and_cluster_minimum_are_distinct(errors, clusters, status):
    result = bands._statistics(
        np.array(errors), np.array(clusters, dtype="datetime64[M]")
    )
    assert result["status"] == status
    assert result["radius"] is None


# Zero observed errors produce exactly zero resolution with two real clusters.
def test_zero_errors_produce_exact_zero_not_unavailable():
    receipt = bands._statistics(
        np.zeros(5), np.array(["2025-01"] * 2 + ["2025-02"] * 3, dtype="datetime64[M]")
    )
    assert receipt["status"] == "available"
    assert receipt["radius"] == receipt["standard_error"] == receipt["bias"] == 0


# A scoring row with an unknown future outcome keeps its previously fitted radius.
def test_future_missing_labels_do_not_remove_causal_opportunities():
    args = fixture()
    result = bands.calibrate(*args)
    assert np.isnan(args[-1].labels[-2:, :2]).all()
    assert args[-1].score_mask[-2:, :2].all()
    assert np.isfinite(result.radii[-2:, :2]).all()
    assert result.manifest["counts"]["opportunities"] == int(args[-1].score_mask.sum())
    assert (
        result.manifest["counts"]["available"]
        + result.manifest["counts"]["unavailable"]
        == result.manifest["counts"]["opportunities"]
    )


# Calibration remains frozen within a month despite different daily forecast errors.
def test_monthly_radius_uses_only_strictly_mature_previous_rows():
    args = fixture()
    result = bands.calibrate(*args)
    dates, _, forecasts, _, parent = args
    for month in result.manifest["months"]:
        scored = dates.astype("datetime64[M]") == np.datetime64(month["month"], "M")
        for index, stock in enumerate(month["stocks"][:2]):
            available = result.radii[scored, index]
            finite = available[np.isfinite(available)]
            assert not len(finite) or np.all(finite == finite[0])
            if stock["observations"]:
                assert np.datetime64(stock["maximum_endpoint"]) < np.datetime64(
                    month["label_end_before"]
                )
                first = month["fit_index"]
                indices = np.arange(max(0, first - 756), first, dtype=np.int64)
                indices = indices[
                    (
                        parent.label_end_dates[indices]
                        < np.datetime64(month["label_end_before"])
                    )
                    & np.isfinite(forecasts[indices, index])
                    & np.isfinite(parent.labels[indices, index])
                ]
                assert stock["row_sha256"]["decision_indices"] == bridge_module._hash(
                    indices
                )


# A later scoring month's labels and forecasts cannot change earlier bands.
def test_future_suffix_mutation_preserves_prefix_calibration():
    dates, names, forecasts, direct_manifest, parent = fixture()
    original = bands.calibrate(dates, names, forecasts, direct_manifest, parent)
    future = dates.astype("datetime64[M]") == dates.astype("datetime64[M]")[-1]
    labels = parent.labels.copy()
    labels[future & np.isfinite(labels[:, 0]), 0] += 0.25
    changed = changed_labels(parent, labels)
    forecasts = forecasts.copy()
    forecasts[future, :2] += 0.05
    updated = manifest(dates, names, forecasts, changed)
    actual = bands.calibrate(dates, names, forecasts, updated, changed)
    np.testing.assert_array_equal(original.radii, actual.radii)
    assert original.manifest["months"] == actual.manifest["months"]


# August and September calibrations cannot see endpoints on or beyond August17.
def test_august_september_frozen_outcomes_are_never_used():
    dates, names, forecasts, direct_manifest, parent = fixture(
        count=700, start="2024-01-02"
    )
    original = bands.calibrate(dates, names, forecasts, direct_manifest, parent)
    labels = parent.labels.copy()
    forbidden = parent.label_end_dates >= np.datetime64("2026-08-17")
    labels[forbidden & np.isfinite(labels[:, 0]), 0] += 0.5
    updated_parent = changed_labels(parent, labels)
    actual = bands.calibrate(
        dates,
        names,
        forecasts,
        manifest(dates, names, forecasts, updated_parent),
        updated_parent,
    )
    holdout = dates >= np.datetime64("2026-08-01")
    np.testing.assert_array_equal(original.radii[holdout], actual.radii[holdout])
    for receipt in actual.manifest["months"]:
        if receipt["month"] >= "2026-08":
            assert receipt["label_end_before"] <= "2026-08-17"
            for stock in receipt["stocks"]:
                if stock["observations"]:
                    assert stock["maximum_endpoint"] < "2026-08-17"


# Original numeric and parent-manifest mutations fail before calibration.
@pytest.mark.parametrize(
    "field", ["forecast", "labels", "identity", "monthly", "score_mask", "dates"]
)
def test_typed_lineage_tampering_is_rejected(field):
    dates, names, forecasts, direct_manifest, parent = fixture()
    if field == "forecast":
        forecasts[-1, 0] += 0.1
    elif field == "labels":
        parent.labels[0, 0] += 0.1
    elif field == "identity":
        direct_manifest["identity"]["target"] = "wrong"
    elif field == "monthly":
        direct_manifest["months"][-1]["fit_date"] = "2026-01-01"
    elif field == "score_mask":
        parent.score_mask[-1, 0] = False
    else:
        dates = dates.astype("datetime64[ns]")
    with pytest.raises(ValueError, match="mismatch|required|disagree"):
        bands.calibrate(dates, names, forecasts, direct_manifest, parent)


# Extreme finite errors remain representable without overflow in squared cluster sums.
def test_scaled_formula_avoids_intermediate_overflow_and_reports_true_overflow():
    months = np.array(
        ["2025-01", "2025-01", "2025-02", "2025-02"], dtype="datetime64[M]"
    )
    huge = bands._statistics(np.array([1e200, 1e200, -1e200, -1e200]), months)
    assert huge["status"] == "available"
    assert huge["radius"] == pytest.approx(1e200)
    invalid = bands._statistics(np.array([np.inf, 1.0, 2.0, 3.0]), months)
    assert invalid["status"] == "nonfinite_residual"
    assert invalid["radius"] is None
    assert invalid["nonfinite_residuals"] == 1


# Repeated calibration is deterministic and never changes caller-owned arrays.
def test_inputs_remain_unchanged_and_receipts_repeat_exactly():
    args = fixture()
    snapshots = [
        value.copy()
        for value in (args[0], args[2], args[-1].labels, args[-1].score_mask)
    ]
    first, second = bands.calibrate(*args), bands.calibrate(*args)
    assert first.manifest == second.manifest
    np.testing.assert_array_equal(first.radii, second.radii)
    for actual, expected in zip(
        (args[0], args[2], args[-1].labels, args[-1].score_mask), snapshots, strict=True
    ):
        np.testing.assert_array_equal(actual, expected)


# A stock with no past forecasts keeps its current opportunities but no error radius.
def test_missing_stock_history_is_not_pooled_or_given_zero():
    dates, names, forecasts, _, parent = fixture()
    months = dates.astype("datetime64[M]")
    forecasts[months < months[-1], 1] = np.nan
    result = bands.calibrate(
        dates, names, forecasts, manifest(dates, names, forecasts, parent), parent
    )
    missing = stock_receipt(result, "BBB")
    assert missing["observations"] == missing["clusters"] == 0
    assert missing["status"] == "insufficient_observations"
    assert np.isnan(result.radii[:, 1]).all()
    assert np.isfinite(result.radii[-1, 0])
    assert parent.score_mask[-1, 1]


# A source digest must be explicit even when the parent JSON itself is self-consistent.
def test_missing_direct_source_identity_is_rejected():
    dates, names, forecasts, receipt, parent = fixture()
    del receipt["identity"]["source_sha256"]
    receipt["identity_sha256"] = base._json_hash(receipt["identity"])
    with pytest.raises(ValueError, match="source hashes required"):
        bands.calibrate(dates, names, forecasts, receipt, parent)


# Unequal weights match pairwise CRPS and empirical quantiles.
def test_holding_scores_match_two_point_probability_arithmetic():
    values, weights = np.array([-0.02, 0.04]), np.array([0.25, 0.75])
    original = values.copy(), weights.copy()
    actual = bands.score_holding_distribution(values, weights, 0.01, 0)
    assert actual["crps"] == pytest.approx(0.01875)
    assert actual["brier"] == pytest.approx(0.0625)
    assert actual["probability_gain"] == 0.75
    assert actual["realized_gain"] == 1
    assert actual["predicted_mean"] == pytest.approx(0.025)
    assert actual["mean_error"] == pytest.approx(0.015)
    np.testing.assert_allclose(actual["quantiles_10_50_90"], [-0.02, 0.04, 0.04])
    assert actual["interval80_covered"] == 1
    assert actual["interval80_width"] == pytest.approx(0.06)
    assert actual["pit_left"] == actual["pit_right"] == 0.25
    np.testing.assert_array_equal(values, original[0])
    np.testing.assert_array_equal(weights, original[1])


# Strict gains, equal outcomes and bankruptcy retain their distinct probability meaning.
def test_holding_scores_preserve_ties_and_total_loss():
    actual = bands.score_holding_distribution([0, 0.01], [0.5, 0.5], 0, 0)
    assert actual["probability_gain"] == 0.5
    assert actual["realized_gain"] == 0
    assert actual["brier"] == 0.25
    assert actual["pit_left"] == 0
    assert actual["pit_right"] == 0.5
    loss = bands.score_holding_distribution([-1], [1], -1, 25)
    assert loss["realized_return"] == loss["predicted_mean"] == -1
    assert loss["brier"] == loss["crps"] == 0
    assert loss["quantiles_10_50_90"] == [-1, -1, -1]


# Per-side costs change gain classification once and preserve proper score arithmetic.
@pytest.mark.parametrize("cost", [0, 10, 25])
def test_holding_scores_match_independent_pairwise_definition(cost):
    values = np.array([-0.04, 0.001, 0.001, 0.005, 0.03])
    weights = np.array([0.1, 0.2, 0.15, 0.35, 0.2])
    actual = bands.score_holding_distribution(values, weights, 0.001, cost)
    rate = cost / 10000
    net = ((1 + values) * (1 - rate) / (1 + rate)) - 1
    observed = (1.001 * (1 - rate) / (1 + rate)) - 1
    expected = weights @ np.abs(net - observed) - 0.5 * np.sum(
        weights[:, None] * weights[None, :] * np.abs(net[:, None] - net[None, :])
    )
    assert actual["crps"] == pytest.approx(expected, abs=2e-15)
    assert actual["realized_gain"] == int(cost == 0)
    assert actual["probability_gain"] == pytest.approx(weights[net > 0].sum())
    assert actual["realized_return"] == pytest.approx(observed, abs=2e-15)


# Invalid distributions and impossible outcomes cannot manufacture usable risk scores.
@pytest.mark.parametrize(
    ("values", "weights", "actual", "cost"),
    [
        ([-1.01], [1], 0, 0),
        ([0], [1], -1.01, 0),
        ([0], [0.9], 0, 0),
        ([0], [0], 0, 0),
        ([np.nan], [1], 0, 0),
        ([0], [1], np.nan, 0),
        ([0], [1], True, 0),
        ([0], [1], 0, True),
        ([0], [1], 0, -1),
        ([0], [1], 0, 10000),
        ([0], [1], 0, np.inf),
    ],
)
def test_holding_scores_refuse_invalid_probability_domains(
    values, weights, actual, cost
):
    with pytest.raises(ValueError, match="required"):
        bands.score_holding_distribution(values, weights, actual, cost)


# Actual saved heads retain cold starts and unpublished outcomes without permission.
def test_holding_diagnostic_retains_actual_reader_opportunities(risk_example):
    from backend.market import direct_feature_arithmetic as feature

    _, bridge, _, _, risk = risk_example
    reader = feature.HoldingScenarioReader(risk, bridge)
    last = len(reader.dates) - 1
    rows = list(bands.holding_diagnostic_rows(reader, [0, last - 2, last - 1, last]))
    assert len(rows) == 8
    assert {row["symbol"] for row in rows} == {"AAA", "BBB"}
    assert all(row["scores"] is None for row in rows[:2])
    assert all(row["outcome_status"] == "known_outcome" for row in rows[:4])
    assert all(row["scores"] is not None for row in rows[2:4])
    assert all(row["prediction_status"] == "available" for row in rows[2:])
    assert all(row["outcome_status"] == "immature_outcome" for row in rows[4:])
    assert all(row["scores"] is None for row in rows[4:])
    for row in rows[2:4]:
        assert [score["cost_bps"] for score in row["scores"]] == [0, 10, 25]
        assert np.datetime64(row["bank"]["maximum_endpoint"]) < np.datetime64(
            row["bank"]["label_end_before"]
        )


# Missing current labels change scoring availability without censoring predictions.
def test_holding_diagnostic_keeps_missing_known_outcome(risk_example):
    from backend.market import direct_feature_arithmetic as feature

    prepared, bridge, parent, heads, original = risk_example
    bridge, parent = deepcopy(bridge), feature._copy_feature(parent)
    day = len(original.dates) - 3
    bridge.labels[day, 1] = np.nan
    bridge.manifest["label_sha256"] = bridge_module._hash(bridge.labels)
    parent.manifest["identity"]["bridge_manifest_sha256"] = base._json_hash(
        bridge.manifest
    )
    parent.manifest["identity"]["input_sha256"]["labels"] = bridge_module._hash(
        bridge.labels
    )
    parent.manifest["identity_sha256"] = base._json_hash(parent.manifest["identity"])
    risk = feature.holding_risk_forecasts(
        parent,
        bridge,
        prepared["X"],
        prepared["valid"],
        heads,
        prices=prepared["risk_prices"],
    )
    rows = list(
        bands.holding_diagnostic_rows(
            feature.HoldingScenarioReader(risk, bridge), [day]
        )
    )
    assert rows[0]["scores"] is not None
    assert rows[1]["prediction_status"] == "available"
    assert rows[1]["outcome_status"] == "missing_known_outcome"
    assert rows[1]["scores"] is None


# Calendar close separates missing and future outcomes, including early closes.
def test_holding_outcome_uses_calendar_maturity_and_unknown_endpoints():
    reader = SimpleNamespace(
        dates=np.array(
            ["2026-11-23", "2026-11-24", "2026-11-25"], dtype="datetime64[D]"
        ),
        endpoints=np.array(["2026-11-25", "NaT", "NaT"], dtype="datetime64[D]"),
        labels=np.full((3, 1), np.nan),
        as_of=datetime(2026, 11, 27, 12, 59, tzinfo=exchange.NEW_YORK),
    )
    assert bands._holding_outcome(reader, 1, 0) == "immature_outcome"
    reader.as_of = datetime(2026, 11, 27, 13, 0, tzinfo=exchange.NEW_YORK)
    assert bands._holding_outcome(reader, 1, 0) == "missing_known_outcome"
    assert bands._holding_outcome(reader, 2, 0) == "immature_outcome"
    reader.as_of = datetime(2026, 12, 2, 16, 0, tzinfo=exchange.NEW_YORK)
    assert bands._holding_outcome(reader, 2, 0) == "missing_known_outcome"
    reader.dates = np.array(
        ["2100-12-28", "2100-12-29", "2100-12-30"], dtype="datetime64[D]"
    )
    assert bands._holding_outcome(reader, 2, 0) == "unknown_outcome_endpoint"


# Malformed requests cannot silently repeat or select opportunities.
@pytest.mark.parametrize("days", [[], [True], [1, 1], [2, 1], [-1], [1200], [1.0]])
def test_holding_diagnostic_refuses_malformed_days(risk_example, days):
    from backend.market import direct_feature_arithmetic as feature

    reader = feature.HoldingScenarioReader(risk_example[-1], risk_example[1])
    with pytest.raises(ValueError, match="chronological"):
        list(bands.holding_diagnostic_rows(reader, days))


# Different stock volatility adjusts dispersion without manufacturing expected gain.
def test_volatility_scaling_matches_power_formula_and_preserves_mean():
    current = np.array([0.01, 0.02])
    past = np.array([[0.01, 0.02], [0.02, -0.01], [-0.01, 0.01]])
    truth = np.array([[-0.04, 0.08], [0.02, -0.04], [0.05, 0.01]])
    now = np.array([0.04, 0.015])
    previous = np.array([[0.02, 0.03], [0.03, 0.02], [0.015, 0.02]])
    actual = bands.scale_holding_volatility(current, past, truth, now, previous)
    g = (1 + truth) / (1 + past)
    h = g ** (now / previous)
    expected = (1 + current) * h * g.mean(axis=0) / h.mean(axis=0) - 1
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-15)
    original = (1 + current) * g - 1
    np.testing.assert_allclose(actual.mean(axis=0), original.mean(axis=0), atol=1e-15)
    assert np.std(actual[:, 0]) > np.std(original[:, 0])
    assert np.std(actual[:, 1]) < np.std(original[:, 1])
    assert not actual.flags.writeable


# Equal current/bank volatility preserves original arrays exactly without input writes.
def test_volatility_scaling_identity_is_exact_and_detached():
    current, past = np.array([0.01]), np.array([[0.005], [-0.02], [0.01]])
    truth = np.array([[-0.03], [0.01], [0.04]])
    now, previous = np.array([0.02]), np.full(past.shape, 0.02)
    saved = [value.copy() for value in (current, past, truth, now, previous)]
    actual = bands.scale_holding_volatility(current, past, truth, now, previous)
    np.testing.assert_array_equal(
        actual, (1 + current) * ((1 + truth) / (1 + past)) - 1
    )
    for value, original in zip(
        (current, past, truth, now, previous), saved, strict=True
    ):
        np.testing.assert_array_equal(value, original)


# Preserve true bankruptcy mass, including an all-default bank.
def test_volatility_scaling_preserves_true_total_loss():
    actual = bands.scale_holding_volatility(
        [0.01, 0.02],
        np.zeros((3, 2)),
        np.array([[-1, -1], [0.03, -1], [-0.02, -1]]),
        [0.04, 0.03],
        np.full((3, 2), 0.02),
    )
    assert actual[0, 0] == -1
    np.testing.assert_array_equal(actual[:, 1], -1)
    assert np.all(actual[1:, 0] > -1)


# Invalid volatility cannot silently remove historical dates.
@pytest.mark.parametrize("bad", [0, -0.01, np.nan, np.inf, True, "0.02"])
def test_volatility_scaling_refuses_unsupported_context(bad):
    with pytest.raises(ValueError, match="required"):
        bands.scale_holding_volatility([0.01], [[0]], [[0.02]], [bad], [[0.02]])


# Finite inputs that would invent total loss or lose a positive ratio are refused.
@pytest.mark.parametrize(
    ("current", "past", "truth", "now", "previous"),
    [
        ([0], [[0], [0]], [[-0.5], [0.5]], [1e200], [[1e-200], [1e-200]]),
        ([0], [[0], [0]], [[-0.5], [0.5]], [1], [[0.001], [0.001]]),
        ([0], [[1e30]], [[0]], [0.02], [[0.02]]),
        ([0], [[0]], [[0.02]], [1e-300], [[1e300]]),
    ],
)
def test_volatility_scaling_refuses_numeric_tail_loss(
    current, past, truth, now, previous
):
    with pytest.raises(ValueError, match="Volatility arithmetic"):
        bands.scale_holding_volatility(current, past, truth, now, previous)


# Supply actual saved heads with distinct positive stock-volatility paths.
@pytest.fixture(scope="module")
def volatility_risk(tmp_path_factory):
    from backend.tests.test_direct_feature_arithmetic import risk_example_factory

    return risk_example_factory(tmp_path_factory, with_volatility=True)


# Preserve authenticated joint dates, probabilities and means without model calls.
def test_volatility_reader_preserves_joint_provenance(volatility_risk, monkeypatch):
    from backend.market import direct_feature_arithmetic as feature

    _, bridge, _, _, risk = volatility_risk
    day = len(risk.dates) - 1
    original = feature.HoldingScenarioReader(risk, bridge).distribution(
        day, ("AAA", "BBB")
    )

    # Runtime conditional dispersion never fits or runs a numeric forecast head.
    def forbidden(*args, **kwargs):
        pytest.fail("Saved risk reader must not fit or run models")

    monkeypatch.setattr(feature, "holding_risk_forecasts", forbidden)
    monkeypatch.setattr(feature.direct.NumericHead, "predict", forbidden)
    actual = bands.VolatilityHoldingReader(risk, bridge).distribution(
        day, ("AAA", "BBB")
    )
    assert actual.receipt["status"] == "available"
    assert actual.receipt["decision_indices"] == original.receipt["decision_indices"]
    np.testing.assert_array_equal(actual.probabilities, original.probabilities)
    np.testing.assert_allclose(
        actual.scenarios.mean(axis=0), original.scenarios.mean(axis=0), atol=1e-15
    )
    assert actual.receipt["original_scenario_receipt_sha256"] == base._json_hash(
        original.receipt
    )
    assert actual.receipt["volatility_identity"]["confidence_guarantee"] is False
    assert not actual.scenarios.flags.writeable


# Zero volatility retains the unavailable request and its original bank.
def test_volatility_reader_retains_unsupported_context(risk_example):
    reader = bands.VolatilityHoldingReader(risk_example[-1], risk_example[1])
    sample = reader.distribution(len(reader.dates) - 1, ("AAA", "BBB"))
    assert sample.receipt["status"] == "unavailable"
    assert sample.receipt["reason"] == "unsupported_current_or_bank_volatility"
    assert sample.receipt["joint_dates"] >= 252
    assert sample.scenarios is None
    assert sample.probabilities is None
    assert "scenarios_sha256" not in sample.receipt


# Future volatility changes cannot alter an earlier authenticated request.
def test_volatility_reader_future_feature_prefix_invariance(volatility_risk):
    from backend.market import direct_feature_arithmetic as feature

    prepared, bridge, parent, heads, risk = volatility_risk
    parent = feature._copy_feature(parent)
    x = prepared["X"].copy()
    x[-1, :2, 4] *= 100
    parent.manifest["identity"]["input_sha256"]["features"] = bridge_module._hash(x)
    parent.manifest["identity_sha256"] = base._json_hash(parent.manifest["identity"])
    changed = feature.holding_risk_forecasts(
        parent, bridge, x, prepared["valid"], heads, prices=prepared["risk_prices"]
    )
    day = len(risk.dates) - 2
    old = bands.VolatilityHoldingReader(risk, bridge).distribution(day, ("AAA", "BBB"))
    new = bands.VolatilityHoldingReader(changed, bridge).distribution(
        day, ("AAA", "BBB")
    )
    np.testing.assert_array_equal(old.scenarios, new.scenarios)
    assert (
        old.receipt["volatility_context_sha256"]
        == new.receipt["volatility_context_sha256"]
    )


# Mutable caller buffers cannot change admitted context or scenarios.
def test_volatility_reader_detaches_original_inputs(volatility_risk):
    risk, bridge = deepcopy(volatility_risk[-1]), deepcopy(volatility_risk[1])
    reader = bands.VolatilityHoldingReader(risk, bridge)
    day = len(reader.dates) - 1
    before = reader.distribution(day, ("AAA", "BBB"))
    risk.features[:, :, 4] = np.nan
    risk.forecasts[:] = np.nan
    bridge.labels[:] = np.nan
    after = reader.distribution(day, ("AAA", "BBB"))
    np.testing.assert_array_equal(before.scenarios, after.scenarios)
    assert before.receipt == after.receipt


# Keep corrected predictions for unpublished labels and common cost scoring.
def test_volatility_reader_diagnostic_retains_mature_and_future_cases(volatility_risk):
    reader = bands.VolatilityHoldingReader(volatility_risk[-1], volatility_risk[1])
    rows = list(
        bands.holding_diagnostic_rows(
            reader, [len(reader.dates) - 3, len(reader.dates) - 1]
        )
    )
    assert len(rows) == 4
    assert all(row["prediction_status"] == "available" for row in rows)
    assert all(row["scores"] is not None for row in rows[:2])
    assert all(row["scores"] is None for row in rows[2:])
    assert all(row["outcome_status"] == "immature_outcome" for row in rows[2:])


# Current outcomes cannot change the preceding admitted distribution or its joint bank.
def test_volatility_reader_current_label_does_not_change_prediction(volatility_risk):
    from backend.market import direct_feature_arithmetic as feature

    prepared, bridge, parent, heads, risk = volatility_risk
    bridge, parent = deepcopy(bridge), feature._copy_feature(parent)
    day = len(risk.dates) - 3
    bridge.labels[day, 1] += 0.4
    bridge.manifest["label_sha256"] = bridge_module._hash(bridge.labels)
    parent.manifest["identity"]["bridge_manifest_sha256"] = base._json_hash(
        bridge.manifest
    )
    parent.manifest["identity"]["input_sha256"]["labels"] = bridge_module._hash(
        bridge.labels
    )
    parent.manifest["identity_sha256"] = base._json_hash(parent.manifest["identity"])
    changed = feature.holding_risk_forecasts(
        parent,
        bridge,
        prepared["X"],
        prepared["valid"],
        heads,
        prices=prepared["risk_prices"],
    )
    old = bands.VolatilityHoldingReader(risk, volatility_risk[1]).distribution(
        day, ("AAA", "BBB")
    )
    new = bands.VolatilityHoldingReader(changed, bridge).distribution(
        day, ("AAA", "BBB")
    )
    np.testing.assert_array_equal(old.scenarios, new.scenarios)
    assert old.receipt["decision_indices"] == new.receipt["decision_indices"]
    assert (
        old.receipt["volatility_context_sha256"]
        == new.receipt["volatility_context_sha256"]
    )


# Substituted volatility fails admission before scenario creation.
def test_volatility_reader_refuses_unbound_context(volatility_risk):
    risk = deepcopy(volatility_risk[-1])
    risk.features[-1, 0, 4] *= 2
    with pytest.raises(ValueError, match="Exact original holding feature"):
        bands.VolatilityHoldingReader(risk, volatility_risk[1])
