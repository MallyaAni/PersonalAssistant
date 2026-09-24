"""Behavioural tests for the adaptive exposure / brake model.

Pure synthetic numpy inputs, no database, no Redis, no network: each test
builds a `RegimeFeatures` directly and asserts on a property of the rule
(range, monotonicity, determinism, explainability, edge cases) rather than
on any fitted number.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.rank_brake import AdaptiveBrake, RegimeFeatures


# A benign regime: every field inside its calm band.
def _regime(**overrides) -> RegimeFeatures:
    base = dict(
        market_drawdown_63=-0.05,
        realized_vol_21=0.10,
        ai_participation=0.5,
        participation_percentile=0.5,
        avg_prediction_strength=0.5,
        top_name_concentration=0.2,
    )
    base.update(overrides)
    return RegimeFeatures(**base)


def test_exposure_stays_in_unit_interval_and_finite():
    brake = AdaptiveBrake()
    for vol in np.linspace(0.02, 0.60, 60):
        exposure = brake.exposure(_regime(realized_vol_21=float(vol)))
        assert 0.0 <= exposure <= 1.0
        assert np.isfinite(exposure)


def test_exposure_is_non_increasing_in_vol():
    brake = AdaptiveBrake()
    previous = 1.0
    for vol in (0.05, 0.10, 0.14, 0.20, 0.28, 0.30, 0.35, 0.45):
        exposure = brake.exposure(_regime(realized_vol_21=vol))
        assert exposure <= previous + 1e-12, f"exposure rose as vol rose to {vol}"
        previous = exposure


def test_exposure_is_non_increasing_in_drawdown_severity():
    brake = AdaptiveBrake()
    previous = 1.0
    for drawdown in (0.0, -0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.50):
        exposure = brake.exposure(_regime(market_drawdown_63=drawdown))
        assert exposure <= previous + 1e-12, (
            f"exposure rose as drawdown deepened to {drawdown}"
        )
        previous = exposure


def test_calm_regime_yields_full_exposure_with_no_reasons():
    brake = AdaptiveBrake()
    decision = brake.decide(_regime())
    assert decision["exposure"] == pytest.approx(brake.max_exposure)
    assert decision["brake"] is False
    assert decision["reasons"] == []
    capped = AdaptiveBrake(max_exposure=0.8)
    assert capped.exposure(_regime()) == pytest.approx(0.8)


@pytest.mark.parametrize(
    "overrides",
    [
        {"realized_vol_21": 0.35},
        {"market_drawdown_63": -0.30},
        {"participation_percentile": 0.05},
    ],
)
def test_severe_regime_brakes_to_zero_exposure(overrides):
    brake = AdaptiveBrake()
    regime = _regime(**overrides)
    assert brake.brake(regime) is True
    decision = brake.decide(regime)
    assert decision["brake"] is True
    assert decision["exposure"] == 0.0


def test_same_input_yields_same_output_with_no_hidden_state():
    brake = AdaptiveBrake(seed=7)
    regime = _regime(
        realized_vol_21=0.22,
        market_drawdown_63=-0.18,
        participation_percentile=0.20,
    )
    first = brake.decide(regime)
    for _ in range(5):
        brake.decide(_regime(realized_vol_21=0.40))
    second = brake.decide(regime)
    assert first == second
    assert brake.exposure(regime) == first["exposure"]
    assert brake.brake(regime) == first["brake"]


def test_reasons_nonempty_whenever_exposure_is_cut():
    brake = AdaptiveBrake()
    cases = [
        {"realized_vol_21": 0.20},
        {"market_drawdown_63": -0.20},
        {"participation_percentile": 0.15},
        {"avg_prediction_strength": 0.05},
        {"realized_vol_21": 0.40},
    ]
    for overrides in cases:
        decision = brake.decide(_regime(**overrides))
        assert decision["exposure"] < brake.max_exposure, overrides
        assert decision["reasons"], overrides


def test_reasons_match_the_actual_cause():
    brake = AdaptiveBrake()
    vol_decision = brake.decide(_regime(realized_vol_21=0.40))
    assert any("vol" in r for r in vol_decision["reasons"])
    assert any(
        "drawdown" in r
        for r in brake.decide(_regime(market_drawdown_63=-0.30))["reasons"]
    )
    assert any(
        "participation" in r
        for r in brake.decide(_regime(participation_percentile=0.05))["reasons"]
    )
    assert any(
        "confidence" in r
        for r in brake.decide(_regime(avg_prediction_strength=0.05))["reasons"]
    )
    modest = brake.decide(_regime(realized_vol_21=0.20))
    assert any(r.startswith("vol") for r in modest["reasons"])
    assert not any(r.startswith("brake") for r in modest["reasons"])


def test_random_sweep_stays_bounded_and_finite():
    rng = np.random.default_rng(1234)
    brake = AdaptiveBrake(seed=4321)
    for _ in range(2000):
        regime = RegimeFeatures(
            market_drawdown_63=float(-rng.random() * 0.5),
            realized_vol_21=float(rng.random() * 0.8 + 0.01),
            ai_participation=float(rng.random()),
            participation_percentile=float(rng.random()),
            avg_prediction_strength=float(rng.random() * 0.5),
            top_name_concentration=float(rng.random()),
        )
        decision = brake.decide(regime)
        exposure = decision["exposure"]
        assert np.isfinite(exposure)
        assert 0.0 <= exposure <= 1.0
        assert isinstance(decision["brake"], bool)
        assert isinstance(decision["reasons"], list)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("market_drawdown_63", float("nan")),
        ("realized_vol_21", float("inf")),
        ("ai_participation", float("nan")),
        ("participation_percentile", float("-inf")),
        ("avg_prediction_strength", float("nan")),
        ("top_name_concentration", float("inf")),
    ],
)
def test_non_finite_feature_raises(field, bad):
    with pytest.raises(ValueError, match="must be finite"):
        _regime(**{field: bad})


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("market_drawdown_63", 0.05),
        ("realized_vol_21", 0.0),
        ("realized_vol_21", -0.1),
        ("ai_participation", -0.01),
        ("ai_participation", 1.01),
        ("participation_percentile", -0.01),
        ("participation_percentile", 1.01),
        ("avg_prediction_strength", -0.01),
        ("top_name_concentration", -0.01),
        ("top_name_concentration", 1.01),
    ],
)
def test_out_of_range_feature_raises(field, bad):
    with pytest.raises(ValueError, match="out of declared range"):
        _regime(**{field: bad})


def test_brake_rejects_bad_data_even_when_post_init_is_bypassed():
    brake = AdaptiveBrake()
    bad = SimpleNamespace(
        market_drawdown_63=-0.05,
        realized_vol_21=float("nan"),
        ai_participation=0.5,
        participation_percentile=0.5,
        avg_prediction_strength=0.5,
        top_name_concentration=0.2,
    )
    with pytest.raises(ValueError, match="must be finite"):
        brake.exposure(bad)
    with pytest.raises(ValueError, match="must be finite"):
        brake.brake(bad)
    with pytest.raises(ValueError, match="must be finite"):
        brake.decide(bad)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_exposure": 0.0},
        {"max_exposure": 1.5},
        {"vol_floor": 0.30, "vol_ceiling": 0.12},
        {"vol_floor": -0.1},
        {"drawdown_hard": -0.10, "drawdown_brake": -0.15},
        {"drawdown_brake": 0.05},
        {"participation_floor": 0.5, "participation_low": 0.25},
        {"participation_low": 1.5},
        {"prediction_strength_floor": 0.2, "prediction_strength_full": 0.1},
    ],
)
def test_invalid_parameters_raise(kwargs):
    with pytest.raises(ValueError, match="must be"):
        AdaptiveBrake(**kwargs)


def test_brake_fires_at_the_boundary_values():
    brake = AdaptiveBrake()
    assert brake.brake(_regime(realized_vol_21=0.30)) is True
    assert brake.exposure(_regime(realized_vol_21=0.30)) == 0.0
    assert brake.brake(_regime(market_drawdown_63=-0.25)) is True
    assert brake.brake(_regime(participation_percentile=0.10)) is True
    assert brake.brake(_regime(realized_vol_21=0.29)) is False
    assert brake.brake(_regime(market_drawdown_63=-0.24)) is False
    assert brake.brake(_regime(participation_percentile=0.11)) is False
