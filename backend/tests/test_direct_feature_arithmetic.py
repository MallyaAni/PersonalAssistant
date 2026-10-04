"""Actual fixed fits exercise independent feature support and OOS error evidence."""

from copy import deepcopy
from datetime import datetime

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_feature_arithmetic as feature
from backend.market import learned_entry_models as base
from backend.tests.test_direct_daily_arithmetic import fixture as original_fixture


# Reproduce all missing old predictions while retaining original known features.
def fixture(count=570, start="2023-01-03"):
    prepared, parent = original_fixture(count=count, start=start)
    dates = prepared["dates"]
    prices = np.full(parent.labels.shape, 100.0)
    for day in range(count - 2):
        prices[day + 2] = prices[day + 1] * (1 + parent.labels[day])
    prepared["absolute_forecasts"] = np.full(prices.shape, np.nan)
    grades, eligible = np.full(prices.shape, 2), np.ones(prices.shape, bool)
    parent = reference.walk_forward(
        dates,
        prepared["symbols"],
        prices,
        grades,
        eligible,
        prepared["absolute_forecasts"],
        dates,
        data_as_of=datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        ),
    )
    return prepared, parent, grades, eligible


# A real fixed model learns even when the old predictor supplied no forecasts.
def test_actual_head_learns_without_original_predictor():
    prepared, parent, grades, eligible = fixture()
    assert not parent.score_mask.any()
    result = feature.walk_forward(prepared, parent, grades, eligible)
    known = np.isfinite(result.forecasts) & np.isfinite(parent.labels)
    assert known.any()
    assert np.corrcoef(result.forecasts[known], parent.labels[known])[0, 1] > 0.8
    assert result.manifest["support_counts"]["added_opportunities"] == 1140
    assert np.isnan(result.forecasts[:, 2:]).all()
    assert np.isfinite(result.forecasts[-2:, :2]).all()
    for row in result.manifest["months"]:
        if row["status"] == "fitted":
            assert row["training_days"] >= 504
            assert np.datetime64(row["maximum_label_end"]) < np.datetime64(
                row["label_end_before"]
            )
            assert row["model"]["iterations"] == 64


# Build genuinely monthly synthetic forecasts once for joint OOS scenario acceptance.
@pytest.fixture(scope="module")
def joint_forecast():
    prepared, parent, grades, eligible = fixture(count=850, start="2022-01-03")
    result = feature.walk_forward(prepared, parent, grades, eligible, hold_b=True)
    return result, parent


# Same dated gross errors produce aligned joint scenarios without today's labels.
def test_joint_holding_scenarios_preserve_dated_forecast_errors(joint_forecast):
    result, parent = joint_forecast
    reader = feature.HoldingScenarioReader(result, parent)
    day = len(result.dates) - 1
    actual = reader.distribution(day, ("AAA", "BBB"))
    assert actual.receipt["status"] == "available"
    chosen = np.asarray(actual.receipt["decision_indices"])
    expected = (1 + result.forecasts[day, :2]) * (1 + parent.labels[chosen, :2]) / (
        1 + result.forecasts[chosen, :2]
    ) - 1
    np.testing.assert_allclose(actual.scenarios, expected, rtol=1e-13, atol=1e-15)
    assert np.all(
        parent.label_end_dates[chosen]
        < np.datetime64(actual.receipt["label_end_before"])
    )
    assert len(chosen) >= 252
    np.testing.assert_allclose(actual.probabilities, 1 / len(chosen))
    assert not actual.scenarios.flags.writeable
    assert not actual.probabilities.flags.writeable
    assert actual.receipt["confidence_guarantee"] is False


# Cold joint history stays unavailable with its missing opportunity counts retained.
def test_joint_holding_scenarios_do_not_invent_warmup(joint_forecast):
    result, parent = joint_forecast
    day = int(np.flatnonzero(np.isfinite(result.forecasts[:, 0]))[0])
    actual = feature.HoldingScenarioReader(result, parent).distribution(
        day, ("AAA", "BBB")
    )
    assert actual.scenarios is actual.probabilities is None
    assert actual.receipt["status"] == "unavailable"
    assert actual.receipt["reason"] == "insufficient_joint_history"
    assert actual.receipt["joint_dates"] < 252


# An excluded or unknown required stock cannot receive a fabricated marginal forecast.
@pytest.mark.parametrize("symbol", ["SPY", "UNSEEN"])
def test_joint_holding_scenarios_missing_required_stock(joint_forecast, symbol):
    result, parent = joint_forecast
    actual = feature.HoldingScenarioReader(result, parent).distribution(
        len(result.dates) - 1, ("AAA", symbol)
    )
    assert actual.scenarios is None
    assert actual.receipt["status"] == "unavailable"


# Future labels and post-admission caller mutations cannot revise prior scenario bytes.
def test_joint_holding_scenarios_freeze_caller_inputs(joint_forecast):
    result, parent = deepcopy(joint_forecast)
    reader = feature.HoldingScenarioReader(result, parent)
    day = len(result.dates) - 1
    first = reader.distribution(day, ("AAA", "BBB"))
    result.forecasts[:] = np.nan
    parent.labels[:] = np.nan
    second = reader.distribution(day, ("AAA", "BBB"))
    np.testing.assert_array_equal(first.scenarios, second.scenarios)
    assert first.receipt == second.receipt


# A freshly authenticated future label suffix cannot alter the prior month's bank.
def test_joint_holding_scenarios_future_label_prefix_invariance(joint_forecast):
    result, parent = deepcopy(joint_forecast)
    months = result.dates.astype("datetime64[M]")
    day = int(np.flatnonzero(months == months[-1])[0])
    before = feature.HoldingScenarioReader(result, parent).distribution(
        day, ("AAA", "BBB")
    )
    future = (np.arange(len(months)) >= day)[:, None] & np.isfinite(parent.labels)
    parent.labels[future] = 0.05
    parent.manifest["label_sha256"] = reference._hash(parent.labels)
    identity = result.manifest["identity"]
    identity["input_sha256"]["labels"] = reference._hash(parent.labels)
    identity["bridge_manifest_sha256"] = base._json_hash(parent.manifest)
    result.manifest["identity_sha256"] = base._json_hash(identity)
    after = feature.HoldingScenarioReader(result, parent).distribution(
        day, ("AAA", "BBB")
    )
    np.testing.assert_array_equal(before.scenarios, after.scenarios)
    assert before.receipt["row_sha256"] == after.receipt["row_sha256"]


# Returned mutable receipt copies cannot change the cached joint history.
def test_joint_holding_scenarios_return_copies(joint_forecast):
    result, parent = joint_forecast
    reader = feature.HoldingScenarioReader(result, parent)
    day = len(result.dates) - 1
    before = reader.distribution(day, ("AAA", "BBB"))
    expected = before.scenarios.copy()
    before.receipt["decision_indices"].clear()
    before.scenarios.setflags(write=True)
    before.scenarios[:] = 0
    after = reader.distribution(day, ("AAA", "BBB"))
    np.testing.assert_array_equal(after.scenarios, expected)
    assert len(after.receipt["decision_indices"]) >= 252


# The admitted holding scenarios drive the actual funded optimizer without a fit.
def test_joint_holding_scenarios_feed_actual_log_growth_optimizer(joint_forecast):
    from backend.market import adaptive_growth_policy as allocator

    result, parent = joint_forecast
    sample = feature.HoldingScenarioReader(result, parent).distribution(
        len(result.dates) - 1, ("AAA", "BBB")
    )
    target, receipt = allocator.allocate_distribution(
        sample.scenarios,
        sample.probabilities,
        np.array([2, 2]),
        np.ones(2, dtype=bool),
        np.zeros(2),
        1.0,
        10,
        np.array([], dtype=int),
        horizon=sample.receipt["horizon"],
    )
    assert receipt["status"] == "optimized"
    assert receipt["certificate"]["certified"]
    assert target.sum() * 1.001 <= 1.0
    utility = sample.probabilities @ np.log(
        1 + sample.scenarios @ target - 0.001 * target.sum()
    )
    for first in (0, allocator.CAP):
        for second in (0, allocator.CAP):
            alternative = np.array([first, second])
            corner = sample.probabilities @ np.log(
                1 + sample.scenarios @ alternative - 0.001 * alternative.sum()
            )
            assert utility >= corner - allocator.CERTIFICATE_TOLERANCE


# Corrupt monthly lineage is rejected before a scenario reader can be admitted.
def test_joint_holding_scenarios_refuse_forged_monthly_prediction(joint_forecast):
    result, parent = deepcopy(joint_forecast)
    result.manifest["months"][-1]["prediction_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="monthly prediction"):
        feature.HoldingScenarioReader(result, parent)


# Fit one pooled synthetic head while leaving the second stock's grades unknown.
@pytest.fixture(scope="module")
def risk_example(tmp_path_factory):
    return risk_example_factory(tmp_path_factory)


# Reuse fixed synthetic fits with optional distinct stock volatility.
def risk_example_factory(tmp_path_factory, *, with_volatility=False):
    from backend.cli import market_direct_daily_arithmetic as cli

    prepared, bridge, grades, eligible = fixture(count=1200, start="2021-01-04")
    if with_volatility:
        scale = 1 + 0.35 * np.sin(np.arange(len(grades)) / 31)
        prepared["X"][:, :, 4] = scale[:, None] * [0.02, 0.05, 0.015, 0.018]
    grades[:, 1], eligible[:, 1] = -1, False
    prepared["valid"][:252] = False
    prepared["X"][:, 1, 8] = np.nan
    prepared["risk_prices"] = np.full(grades.shape, 100.0, dtype=np.float64)
    parent = feature.walk_forward(prepared, bridge, grades, eligible, hold_b=True)
    folder = tmp_path_factory.mktemp("risk-heads")
    records = cli.save_models(folder, parent.models)
    heads = {}
    for row in parent.manifest["months"]:
        month = row["month"]
        if month not in records:
            heads[month] = None
            continue
        with np.load(folder / records[month]["file"], allow_pickle=False) as bundle:
            heads[month] = feature.direct.numeric_head(dict(bundle), row["model"])
    risk = feature.holding_risk_forecasts(
        parent,
        bridge,
        prepared["X"],
        prepared["valid"],
        heads,
        prices=prepared["risk_prices"],
    )
    return prepared, bridge, parent, heads, risk


# Risk inference covers price histories without fabricating a grade or refitting.
def test_holding_risk_expands_without_trading_permission(risk_example, monkeypatch):
    from backend.market import adaptive_growth_policy as allocator

    prepared, bridge, parent, heads, original = risk_example

    # Inference must never use the training entrypoint to manufacture coverage.
    def forbidden(*args, **kwargs):
        pytest.fail("Saved-head inference attempted a fit")

    monkeypatch.setattr(feature.direct, "_fit", forbidden)
    risk = feature.holding_risk_forecasts(
        parent,
        bridge,
        prepared["X"],
        prepared["valid"],
        heads,
        prices=prepared["risk_prices"],
    )
    assert not parent.score_mask[:, 1].any()
    assert np.isnan(parent.forecasts[:, 1]).all()
    assert np.isfinite(risk.forecasts[:, 1]).sum() > 252
    assert not risk.score_mask[:, 2:].any()
    assert not risk.manifest["identity"]["grade_or_membership_permission"]
    assert risk.parent.models == {}
    np.testing.assert_array_equal(risk.forecasts, original.forecasts)
    sample = feature.HoldingScenarioReader(risk, bridge).distribution(
        len(risk.dates) - 1, ("AAA", "BBB")
    )
    assert sample.receipt["status"] == "available"
    target, _ = allocator.allocate_distribution(
        sample.scenarios,
        sample.probabilities,
        np.array([2, -1]),
        np.array([True, False]),
        np.zeros(2),
        1.0,
        10,
        np.array([], dtype=int),
        horizon=sample.receipt["horizon"],
    )
    assert target[1] == 0


# Expanded artifacts preserve original supported values and unavailable warmup heads.
def test_holding_risk_preserves_original_training_and_forecasts(risk_example):
    _, _, parent, _, risk = risk_example
    np.testing.assert_array_equal(
        risk.forecasts[parent.score_mask], parent.forecasts[parent.score_mask]
    )
    assert risk.parent.manifest == parent.manifest
    months = risk.dates.astype("datetime64[M]")
    for row in risk.manifest["months"]:
        if row["status"] != "fitted":
            assert np.isnan(
                risk.forecasts[months == np.datetime64(row["month"], "M")]
            ).all()


# A substituted feature, validity mask or month's model cannot become risk evidence.
@pytest.mark.parametrize("failure", ["features", "valid", "head", "schedule", "prices"])
def test_holding_risk_refuses_changed_original_inputs(risk_example, failure):
    prepared, bridge, parent, original_heads, _ = risk_example
    x, valid, heads = (
        prepared["X"].copy(),
        prepared["valid"].copy(),
        dict(original_heads),
    )
    prices = prepared["risk_prices"].copy()
    if failure == "features":
        x[-1, 1, 0] += 1
    elif failure == "valid":
        valid[-1, 1] = not valid[-1, 1]
    elif failure == "schedule":
        heads.pop(next(iter(heads)))
    elif failure == "prices":
        prices[-1, 1] = np.inf
    else:
        available = [month for month, head in heads.items() if head is not None]
        heads[available[0]] = heads[available[-1]]
    with pytest.raises(ValueError, match="original"):
        feature.holding_risk_forecasts(parent, bridge, x, valid, heads, prices=prices)


# Refreshing a new feature source's hashes cannot change already observed predictions.
def test_holding_risk_future_feature_prefix_invariance(risk_example):
    prepared, bridge, parent, heads, risk = risk_example
    parent = feature._copy_feature(parent)
    x = prepared["X"].copy()
    x[-1, 1, 0] += 10
    parent.manifest["identity"]["input_sha256"]["features"] = reference._hash(x)
    parent.manifest["identity_sha256"] = base._json_hash(parent.manifest["identity"])
    changed = feature.holding_risk_forecasts(
        parent,
        bridge,
        x,
        prepared["valid"],
        heads,
        prices=prepared["risk_prices"],
    )
    np.testing.assert_array_equal(changed.forecasts[:-1], risk.forecasts[:-1])


# Current-month outcomes cannot alter predictions or earlier joint errors.
def test_holding_risk_future_label_prefix_invariance(risk_example):
    prepared, bridge, parent, heads, risk = risk_example
    parent, bridge = feature._copy_feature(parent), deepcopy(bridge)
    bridge.labels[-3, 1] += 0.4
    bridge.manifest["label_sha256"] = reference._hash(bridge.labels)
    parent.manifest["identity"]["bridge_manifest_sha256"] = base._json_hash(
        bridge.manifest
    )
    parent.manifest["identity"]["input_sha256"]["labels"] = reference._hash(
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
    np.testing.assert_array_equal(changed.forecasts, risk.forecasts)
    day = len(risk.dates) - 1
    original = feature.HoldingScenarioReader(risk, risk_example[1]).distribution(
        day, ("AAA", "BBB")
    )
    actual = feature.HoldingScenarioReader(changed, bridge).distribution(
        day, ("AAA", "BBB")
    )
    np.testing.assert_array_equal(actual.scenarios, original.scenarios)


# Fabricated inference support or training clocks fail before scenario construction.
@pytest.mark.parametrize("failure", ["mask", "monthly", "training"])
def test_holding_risk_reader_refuses_forged_lineage(risk_example, failure):
    _, bridge, _, _, original = risk_example
    risk = deepcopy(original)
    if failure == "mask":
        risk.score_mask[-1, 1] = False
    elif failure == "monthly":
        risk.manifest["months"][-1]["parent_receipt_sha256"] = "0" * 64
    else:
        risk.parent.manifest["months"][-1]["maximum_label_end"] = str(risk.dates[-1])
    with pytest.raises(ValueError, match="lineage|receipt"):
        feature.HoldingScenarioReader(risk, bridge)


# Price history gaps reset causal support even when grade-free features are present.
def test_price_risk_support_requires_complete_prefix_and_spy():
    prices = np.full((600, 2), 100.0, dtype=np.float64)
    x = np.ones((600, 2, 13), dtype=np.float32)
    x[:, :, 8] = np.nan
    whole = feature._price_risk_support(prices, x, ("AAA", "SPY"))
    assert not whole[:252].any()
    assert whole[252:].all()
    prices[275, 0] = np.nan
    missing = feature._price_risk_support(prices, x, ("AAA", "SPY"))
    np.testing.assert_array_equal(missing[:275], whole[:275])
    assert not missing[275:528, 0].any()
    assert missing[528:, 0].all()
    assert missing[275:528, 1].all()
    prices[300, 1] = np.nan
    assert not feature._price_risk_support(prices, x, ("AAA", "SPY"))[300:553].any()
    x[590, 0, 0] = np.nan
    assert feature._price_risk_support(prices, x, ("AAA", "SPY"))[590, 0]
    x[590, 0, 12] = np.nan
    assert not feature._price_risk_support(prices, x, ("AAA", "SPY"))[590, 0]


# Explicit causal grades and membership gate opportunities without future labels.
def test_support_gates_state_and_preserves_missing_outcome_tail():
    prepared, parent, grades, eligible = fixture(count=530)
    grades[-4:, 0] = 1
    eligible[-3:, 1] = False
    prepared["valid"][-5, 0] = False
    result = feature.walk_forward(prepared, parent, grades, eligible)
    assert not result.score_mask[-4:, 0].any()
    assert not result.score_mask[-3:, 1].any()
    assert not result.score_mask[-5, 0]
    assert np.isnan(result.forecasts[-3:, :2]).all()
    assert result.score_mask[-4, 1]


# A changed future feature suffix cannot revise past heads or predictions.
def test_future_features_do_not_change_prior_months():
    prepared, parent, grades, eligible = fixture()
    before = feature.walk_forward(prepared, parent, grades, eligible)
    future = prepared["dates"].astype("datetime64[M]") == prepared["dates"][-1].astype(
        "datetime64[M]"
    )
    prepared["X"][future] *= -5
    after = feature.walk_forward(prepared, parent, grades, eligible)
    np.testing.assert_array_equal(before.forecasts[~future], after.forecasts[~future])
    assert before.manifest["months"][:-1] == after.manifest["months"][:-1]


# The fixed band consumes only genuine matured OOS scores under its new identity.
def test_actual_band_has_new_lineage_and_past_only_residuals():
    prepared, parent, grades, eligible = fixture(count=630)
    result = feature.walk_forward(prepared, parent, grades, eligible)
    bands = feature.calibrate(result, parent)
    assert np.isfinite(bands.radii).any()
    assert (
        bands.manifest["identity"]["policy"] == "direct-feature-error-band/1-research"
    )
    for receipt in bands.manifest["months"]:
        for stock in receipt["stocks"]:
            if stock["status"] == "available":
                assert stock["clusters"] >= 2
                assert np.datetime64(stock["maximum_endpoint"]) < np.datetime64(
                    receipt["label_end_before"]
                )
    future = prepared["dates"].astype("datetime64[M]") == prepared["dates"][-1].astype(
        "datetime64[M]"
    )
    changed = deepcopy(result)
    changed.forecasts[future, :2] += 0.2
    changed.manifest["forecasts_sha256"] = reference._hash(changed.forecasts)
    changed.manifest["months"][-1]["prediction_sha256"] = reference._hash(
        changed.forecasts[future]
    )
    later = feature.calibrate(changed, parent)
    np.testing.assert_array_equal(bands.radii, later.radii)


# Altered forecast or monthly prediction bytes are rejected before calibration.
@pytest.mark.parametrize("change", ["forecast", "clock", "mask", "identity"])
def test_calibration_rejects_changed_lineage(change):
    prepared, parent, grades, eligible = fixture(count=530)
    result = feature.walk_forward(prepared, parent, grades, eligible)
    if change == "forecast":
        result.forecasts[-1, 0] += 0.1
    elif change == "clock":
        result.manifest["months"][-1]["fit_index"] += 1
    elif change == "mask":
        result.score_mask[-1, 0] = False
    else:
        result.manifest["identity"]["policy"] = "old-direct"
    with pytest.raises(ValueError, match="bytes mismatch|support|monthly|identity"):
        feature.calibrate(result, parent)


# Ambiguous eligibility and unrecognized grades cannot become decision support.
@pytest.mark.parametrize("change", ["grade", "membership", "shape"])
def test_support_rejects_invalid_inputs(change):
    prepared, parent, grades, eligible = fixture(count=20)
    if change == "grade":
        grades[0, 0] = 5
    elif change == "membership":
        eligible = eligible.astype(int)
    else:
        eligible = eligible[:-1]
    with pytest.raises(ValueError, match="ordinal grades"):
        feature.walk_forward(prepared, parent, grades, eligible)


# A held-B forecast head learns signed returns without a previous model's scores.
def test_actual_held_b_head_learns_b_rows_and_preserves_default_exclusion():
    prepared, parent, grades, eligible = fixture()
    grades[:, 0] = 1
    default = feature.walk_forward(prepared, parent, grades, eligible)
    held = feature.walk_forward(prepared, parent, grades, eligible, hold_b=True)
    assert not parent.score_mask.any()
    assert not default.score_mask[:, 0].any()
    assert np.isnan(default.forecasts[:, 0]).all()
    known = np.isfinite(held.forecasts[:, 0]) & np.isfinite(parent.labels[:, 0])
    assert known.any()
    assert np.corrcoef(held.forecasts[known, 0], parent.labels[known, 0])[0, 1] > 0.8
    assert held.score_mask[:, 0].all()
    assert np.isfinite(held.forecasts[-2:, 0]).all()
    assert np.isnan(parent.labels[-2:, 0]).all()
    assert held.manifest["identity"]["policy"] == feature.HELD_POLICY
    assert held.manifest["identity"]["hold_b"] is True
    assert held.manifest["identity"]["support_min_grade"] == 1
    assert feature.HELD_PROTOCOL in held.manifest["identity"]["source_sha256"]
    assert "hold_b" not in default.manifest["identity"]
    for receipt in held.manifest["months"]:
        if receipt["status"] == "fitted":
            assert receipt["training_rows"] == receipt["training_days"] * 2
            assert receipt["rows_per_date"] == [2] * receipt["training_days"]
            assert receipt["model"]["iterations"] == 64
            assert np.datetime64(receipt["maximum_label_end"]) < np.datetime64(
                receipt["label_end_before"]
            )


# The explicit off option and unchanged all-A support retain exact default results.
def test_held_b_option_preserves_default_values_and_monthly_receipts():
    prepared, parent, grades, eligible = fixture(count=530)
    implicit = feature.walk_forward(prepared, parent, grades, eligible)
    explicit = feature.walk_forward(prepared, parent, grades, eligible, hold_b=False)
    held = feature.walk_forward(prepared, parent, grades, eligible, hold_b=True)
    np.testing.assert_array_equal(implicit.forecasts, explicit.forecasts)
    assert implicit.manifest == explicit.manifest
    np.testing.assert_array_equal(implicit.forecasts, held.forecasts)
    np.testing.assert_array_equal(implicit.score_mask, held.score_mask)
    assert implicit.manifest["months"] == held.manifest["months"]
    assert implicit.manifest["identity"]["policy"] == feature.POLICY


# B support never turns C, unknown, nonmembers or benchmarks into opportunities.
def test_held_b_support_keeps_every_causal_eligibility_boundary():
    prepared, parent, grades, eligible = fixture(count=530)
    grades[:, :2] = 1
    grades[-5, 0] = 0
    grades[-4, 0] = -1
    eligible[-3, 0] = False
    prepared["valid"][-2, 0] = False
    _, _, _, mask, _ = feature.support(prepared, parent, grades, eligible, hold_b=True)
    assert not mask[-5:-1, 0].any()
    assert mask[-1, 0]
    assert not mask[:, 2:].any()


# Held-B error evidence is stock-specific genuine OOS under its own named lineage.
def test_actual_held_b_band_has_explicit_matching_mode_identity():
    prepared, parent, grades, eligible = fixture(count=630)
    grades[:, 0] = 1
    result = feature.walk_forward(prepared, parent, grades, eligible, hold_b=True)
    bands = feature.calibrate(result, parent)
    assert bands.manifest["identity"]["policy"] == feature.HELD_BAND_POLICY
    assert bands.manifest["identity"]["hold_b"] is True
    assert bands.manifest["identity"]["support_min_grade"] == 1
    assert np.isfinite(bands.radii[-2:, 0]).all()
    assert np.isnan(bands.radii[:, 2:]).all()
    for receipt in bands.manifest["months"]:
        for row in receipt["stocks"]:
            if row["status"] == "available":
                assert row["clusters"] >= 2
                assert row["maximum_endpoint"] < receipt["label_end_before"]


# A refreshed JSON hash cannot disguise a holding model as another support mode.
@pytest.mark.parametrize(
    "change", ["policy", "option", "grade", "protocol", "boolean_grade"]
)
def test_held_b_calibration_rejects_forged_mode(change):
    prepared, parent, grades, eligible = fixture(count=530)
    grades[:, 0] = 1
    result = feature.walk_forward(prepared, parent, grades, eligible, hold_b=True)
    identity = result.manifest["identity"]
    if change == "policy":
        identity["policy"] = feature.POLICY
    elif change == "option":
        identity["hold_b"] = False
    elif change == "grade":
        identity["support_min_grade"] = 2
    elif change == "boolean_grade":
        identity["support_min_grade"] = True
    else:
        identity["source_sha256"][feature.HELD_PROTOCOL] = "0" * 64
    result.manifest["identity_sha256"] = base._json_hash(identity)
    with pytest.raises(ValueError, match="mode identity mismatch"):
        feature.calibrate(result, parent)


# Future B features cannot alter a previous frozen model or its forecasts.
def test_held_b_future_prefix_and_holdout_outcomes_are_causal():
    prepared, parent, grades, eligible = fixture(count=700, start="2024-01-02")
    grades[:, 0] = 1
    original = feature.walk_forward(prepared, parent, grades, eligible, hold_b=True)
    future = prepared["dates"] >= np.datetime64("2026-08-17")
    prepared["X"][future, 0] *= -5
    labels = parent.labels.copy()
    unavailable = parent.label_end_dates >= np.datetime64("2026-08-17")
    parent.labels[unavailable & np.isfinite(parent.labels[:, 0]), 0] += 0.25
    parent.manifest["label_sha256"] = reference._hash(parent.labels)
    actual = feature.walk_forward(prepared, parent, grades, eligible, hold_b=True)
    np.testing.assert_array_equal(
        original.forecasts[~future], actual.forecasts[~future]
    )
    for before, after in zip(
        original.manifest["months"], actual.manifest["months"], strict=True
    ):
        assert (
            before["model"] == after["model"]
            if "model" in before
            else "model" not in after
        )
        if before["month"] >= "2026-08":
            assert before["maximum_label_end"] < "2026-08-17"
    assert np.isnan(labels[-2:]).all()


# Missing grade-option intent cannot be coerced from a string or integer flag.
@pytest.mark.parametrize("option", [1, "true", None])
def test_held_b_option_requires_an_actual_boolean(option):
    prepared, parent, grades, eligible = fixture(count=20)
    with pytest.raises(ValueError, match="boolean held-B support"):
        feature.walk_forward(prepared, parent, grades, eligible, hold_b=option)


# An unpublished future decision cannot enter B support despite known feature values.
def test_held_b_requires_completed_decision_and_known_label_publication():
    prepared, parent, grades, eligible = fixture(count=20, start="2026-01-02")
    dates = prepared["dates"]
    grades[:, 0] = 1
    observed = 10
    as_of = datetime.combine(
        dates[observed].astype(object),
        exchange.session_close(dates[observed].astype(object)),
        exchange.NEW_YORK,
    )
    parent.manifest["data_as_of"] = as_of.isoformat()
    future_end = parent.label_end_dates > dates[observed]
    parent.labels[future_end] = np.nan
    parent.manifest["label_sha256"] = reference._hash(parent.labels)
    _, _, _, mask, completed = feature.support(
        prepared, parent, grades, eligible, hold_b=True
    )
    assert mask[: observed + 1, 0].all()
    assert not mask[observed + 1 :].any()
    assert not completed[observed + 1 :].any()
    future_label = np.flatnonzero(future_end)[0]
    parent.labels[future_label, 0] = 0.001
    parent.manifest["label_sha256"] = reference._hash(parent.labels)
    with pytest.raises(ValueError, match="endpoint is not yet known"):
        feature.support(prepared, parent, grades, eligible, hold_b=True)
