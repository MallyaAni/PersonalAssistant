"""Independent numerical, causal-reader and real private-account acceptance."""

from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.cli import market_daily
from backend.market import calendar
from backend.market import conditional_holding_calibration as calibrated
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_feature_arithmetic as feature
from backend.market import learned_entry_models as base
from backend.market.direct_error_band import VolatilityHoldingReader
from backend.market.joint_funded_accounts import candidate_grid
from backend.market.joint_funded_policy import (
    CALIBRATED_POLICY,
    POLICY,
    CalibratedMaturityFundedPolicy,
)
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_direct_feature_arithmetic import risk_example_factory
from backend.tests.test_joint_funded_policy import report


# Compare the scaled implementation with an independently solved raw affine regression.
def test_affine_prediction_and_leverage_match_independent_matrix_oracle():
    x = np.linspace(-0.015, 0.021, 21)
    y = 0.003 + 0.4 * x + 0.001 * np.cos(np.arange(len(x)))
    fit = calibrated.fit_log(np.expm1(x), np.expm1(y))
    design = np.c_[np.ones(len(x)), x]
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    query = np.array([1.0, 0.011])
    mean, factor = fit.predict(np.expm1(query[1]))
    expected_leverage = query @ np.linalg.inv(design.T @ design) @ query
    assert mean == pytest.approx(query @ coefficients, abs=1e-14)
    assert factor == pytest.approx(
        np.sqrt(len(x) / (len(x) - 2) * (1 + expected_leverage))
    )


# Constant forecasts learn the observed conditional mean with one parameter.
def test_constant_predictor_and_extrapolation_uncertainty():
    outcome = np.expm1(np.linspace(-0.02, 0.03, 20))
    fit = calibrated.fit_log(np.full(20, -0.01), outcome)
    assert fit.parameters == 1
    assert fit.slope == 0
    assert fit.scale == 0
    mean, multiplier = fit.predict(0.2)
    assert mean == pytest.approx(np.log1p(outcome).mean())
    assert multiplier == pytest.approx(np.sqrt(20 / 19 * 1.05))
    varying = calibrated.fit_log(np.linspace(-0.01, 0.02, 20), outcome)
    assert varying.predict(0.5)[1] > varying.predict(0.005)[1]


# Total-loss point masses remain in their original joint dates after calibration.
def test_true_defaults_volatility_and_joint_row_order():
    past = np.c_[np.linspace(-0.01, 0.02, 20), np.linspace(-0.02, 0.01, 20)]
    outcomes = past * 0.3 + np.sin(np.arange(20))[:, None] * [0.01, 0.02]
    outcomes[3, 0], outcomes[8, 1] = -1, -1
    fits = [calibrated.fit_log(past[:, i], outcomes[:, i]) for i in range(2)]
    actual, _ = calibrated.calibrated_scenarios(
        np.array([0.01, 0.005]), past, outcomes, np.ones(2), np.ones_like(past), fits
    )
    assert np.array_equal(actual == -1, outcomes == -1)
    permuted, _ = calibrated.calibrated_scenarios(
        np.array([0.005, 0.01]),
        past[:, ::-1],
        outcomes[:, ::-1],
        np.ones(2),
        np.ones_like(past),
        fits[::-1],
    )
    np.testing.assert_array_equal(actual, permuted[:, ::-1])
    assert not actual.flags.writeable


# Current volatility changes risk dispersion without a fixed dip or profit target.
def test_stock_volatility_changes_log_dispersion():
    past = np.linspace(-0.01, 0.02, 30)[:, None]
    outcomes = past * 0.2 + 0.01 * np.cos(np.arange(30))[:, None]
    fit = calibrated.fit_log(past[:, 0], outcomes[:, 0])
    low, _ = calibrated.calibrated_scenarios(
        np.array([0.01]), past, outcomes, np.ones(1), np.ones_like(past), [fit]
    )
    high, _ = calibrated.calibrated_scenarios(
        np.array([0.01]), past, outcomes, np.full(1, 2.0), np.ones_like(past), [fit]
    )
    assert np.var(np.log1p(high)) == pytest.approx(4 * np.var(np.log1p(low)))
    assert np.mean(np.log1p(high)) == pytest.approx(np.mean(np.log1p(low)), abs=1e-14)


# Invalid fitting domains cannot become calibrated risk or fabricated total losses.
@pytest.mark.parametrize("bad", [np.nan, np.inf, -1.01, True, 1j])
def test_invalid_scalar_prediction_is_refused(bad):
    fit = calibrated.fit_log(np.zeros(4), np.array([0.01, 0.02, -0.01, 0.0]))
    with pytest.raises(ValueError, match="finite current forecast"):
        fit.predict(bad)


# Extreme volatility refuses the complete request rather than clipping generated tails.
@pytest.mark.parametrize("sign", [-1, 1])
def test_numeric_overflow_and_total_loss_fabrication_are_refused(sign):
    past = np.zeros((4, 1))
    outcome = np.array([-0.2, 0.2, -0.1, 0.1])[:, None]
    fit = calibrated.fit_log(past[:, 0], outcome[:, 0])
    with pytest.raises(ValueError, match="overflows|total loss"):
        calibrated.calibrated_scenarios(
            np.array([0.0]),
            past,
            outcome * sign,
            np.array([1e300]),
            np.full_like(past, 1e-300),
            [fit],
        )


# Bind genuine synthetic saved heads once for the actual reader and planning paths.
@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    return risk_example_factory(tmp_path_factory, with_volatility=True)


# Each stock's monthly fit is unchanged by requested peers, order and repeated calls.
def test_reader_preserves_dates_peers_monthly_identity_and_original(evidence):
    original = VolatilityHoldingReader(evidence[-1], evidence[1])
    before = original.distribution(len(original.dates) - 1, ("AAA", "BBB"))
    reader = calibrated.CalibratedHoldingReader(original)
    day = len(reader.dates) - 1
    single = reader.distribution(day, ("AAA",))
    joint = reader.distribution(day, ("AAA", "BBB"))
    reverse = reader.distribution(day, ("BBB", "AAA"))
    assert joint.receipt["status"] == "available"
    assert single.receipt["calibration"][0] == joint.receipt["calibration"][0]
    assert len(reader._fits) == 2
    np.testing.assert_array_equal(joint.scenarios, reverse.scenarios[:, ::-1])
    assert joint.receipt == reader.distribution(day, ("AAA", "BBB")).receipt
    assert joint.receipt["decision_indices"] == before.receipt["decision_indices"]
    np.testing.assert_array_equal(joint.probabilities, before.probabilities)
    np.testing.assert_array_equal(
        before.scenarios, original.distribution(day, ("AAA", "BBB")).scenarios
    )
    assert joint.receipt["calibration_identity"]["confidence_guarantee"] is False
    assert "volatility_identity" not in joint.receipt


# A newly bound valid artifact with altered current outcomes preserves prior decisions.
def test_current_and_future_outcomes_do_not_change_calibration(evidence):
    prepared, old_bridge, parent, heads, risk = evidence
    bridge, parent = deepcopy(old_bridge), feature._copy_feature(parent)
    day = len(risk.dates) - 3
    bridge.labels[day, 1] += 0.4
    bridge.manifest["label_sha256"] = reference._hash(bridge.labels)
    identity = parent.manifest["identity"]
    identity["bridge_manifest_sha256"] = base._json_hash(bridge.manifest)
    identity["input_sha256"]["labels"] = reference._hash(bridge.labels)
    parent.manifest["identity_sha256"] = base._json_hash(identity)
    changed = feature.holding_risk_forecasts(
        parent,
        bridge,
        prepared["X"],
        prepared["valid"],
        heads,
        prices=prepared["risk_prices"],
    )
    old = calibrated.CalibratedHoldingReader(VolatilityHoldingReader(risk, old_bridge))
    new = calibrated.CalibratedHoldingReader(VolatilityHoldingReader(changed, bridge))
    a, b = old.distribution(day, ("AAA", "BBB")), new.distribution(day, ("AAA", "BBB"))
    np.testing.assert_array_equal(a.scenarios, b.scenarios)
    assert a.receipt["calibration"] == b.receipt["calibration"]


# Later volatility inputs cannot change an earlier valid calibrated request.
def test_future_feature_prefix_does_not_change_calibration(evidence):
    prepared, bridge, original, heads, risk = evidence
    parent = feature._copy_feature(original)
    x = prepared["X"].copy()
    x[-1, :2, 4] *= 100
    parent.manifest["identity"]["input_sha256"]["features"] = reference._hash(x)
    parent.manifest["identity_sha256"] = base._json_hash(parent.manifest["identity"])
    changed = feature.holding_risk_forecasts(
        parent, bridge, x, prepared["valid"], heads, prices=prepared["risk_prices"]
    )
    day = len(risk.dates) - 2
    old = calibrated.CalibratedHoldingReader(VolatilityHoldingReader(risk, bridge))
    new = calibrated.CalibratedHoldingReader(VolatilityHoldingReader(changed, bridge))
    a, b = old.distribution(day, ("AAA", "BBB")), new.distribution(day, ("AAA", "BBB"))
    np.testing.assert_array_equal(a.scenarios, b.scenarios)
    assert a.receipt["calibration"] == b.receipt["calibration"]


# Missing original risk retains its refusal rather than inventing evidence.
def test_unavailable_original_request_stays_unavailable(evidence):
    original = VolatilityHoldingReader(evidence[-1], evidence[1])
    reader = calibrated.CalibratedHoldingReader(original)
    result = reader.distribution(0, ("AAA",))
    assert result.receipt["status"] == "unavailable"
    assert result.scenarios is None
    assert not reader._fits
    with pytest.raises(ValueError, match="Original historical"):
        calibrated.CalibratedHoldingReader(reader)


# The predeclared calibration screen cannot expand into another sixty-account job.
def test_screen_grid_keeps_each_cost_and_the_first_original_start():
    _, sessions = calendar.reviewed_sessions()
    dates = np.arange("2018-01-01", "2026-10-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates, busdaycal=sessions)]
    rows = candidate_grid(dates, policy=CALIBRATED_POLICY)
    assert [r["id"] for r in rows] == [
        "calibrated-0-0",
        "calibrated-10-0",
        "calibrated-25-0",
    ]
    assert len(candidate_grid(dates, policy=POLICY)) == 60


# Private nightly plans persist the new identity and settle actual ledger fills.
def test_calibrated_private_nightly_cash_repeat_and_settlement(evidence, tmp_path):
    original = VolatilityHoldingReader(evidence[-1], evidence[1])
    policy = CalibratedMaturityFundedPolicy(original, 10)
    shown = report(original, day=len(original.dates) - 2, grades=(0, 3))
    session = str(shown.panel.dates[-1])
    now = datetime.combine(
        shown.panel.dates[-1].astype(object),
        calendar.session_close(shown.panel.dates[-1].astype(object)),
        calendar.NEW_YORK,
    ) + timedelta(minutes=1)
    broker = ReplayBroker(
        100000.0, 10, initial_holdings={"AAA": 10}, initial_average_prices={"AAA": 90.0}
    )
    broker.observe(now, {"AAA": 100.0, "BBB": 100.0}, False)

    # Keep event and permission dependencies explicit on the private journey.
    def features(kind, ignored):
        return (
            {"calendar_known": True, "factor": 1.0}
            if kind == "event"
            else (set(), {})
            if kind == "blocked"
            else {}
        )

    kwargs = dict(
        client_factory=lambda: broker,
        decision_at=now,
        feature_reader=features,
        holding_policy=policy,
    )
    entry = market_daily.paper_trade(shown, tmp_path, session, True, **kwargs)
    state = paper.load_state(tmp_path)
    assert entry["policy"] == state.policy_version == CALIBRATED_POLICY
    assert state.allocation_state["receipt"]["scenario"]["calibration"]
    assert any(r["symbol"] == "AAA" and r["side"] == "sell" for r in state.pending)
    assert state.allocation_state["receipt"]["execution"]["projected_liquid_cash"] >= 0
    attempts = broker.attempt_history
    market_daily.paper_trade(shown, tmp_path, session, True, **kwargs)
    assert broker.attempt_history == attempts
    assert paper.load_state(tmp_path).pending == state.pending
    opening = datetime.combine(
        original.dates[-1].astype(object), calendar.REGULAR_OPEN, calendar.NEW_YORK
    )
    broker.observe(opening, {"AAA": 100.0, "BBB": 100.0}, True)
    broker.flush(opening, {"AAA": 100.0, "BBB": 100.0}, phase="open")
    settled, receipts = market_daily._reconcile(broker, state, tmp_path, True)
    assert receipts
    assert not settled.pending
    assert "AAA" not in {p.symbol for p in broker.positions()}
    assert paper.load_state(tmp_path).journal == settled.journal
    assert broker.account().cash >= 0
