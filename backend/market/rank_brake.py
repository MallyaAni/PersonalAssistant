"""Adaptive exposure and hard brake for the experimental ranker's book.

A deterministic, causal rule that turns one session's regime state and the
ranker's predicted book into (a) an exposure multiplier in [0,1] applied to
the sized book and (b) a hard-brake decision. Everything it reads is known at
the decision-session close: nothing here is ever a future value.

Exposure semantics follow the desk: exposure is a multiplier on the book in
[0,1] (compare the regime analyst's 0.75 hype exposure in
`backend/agents/trading/desk/regime.py` and the 0.5 event reduction in
`backend/agents/trading/desk/event_risk.py`). A full brake drives it to 0.
Drawdown is a negative loss, the desk's own convention (the regime analyst's
`ai_drawdown` and the desk curve both fall to negative on a decline); a
`market_drawdown_63` of -0.20 means the market is 20% below its 63-session
high.

The rule is a set of piecewise-linear factors, not a fitted black box, so a
reviewer can read exactly why exposure moved. This component does not train
anything: it consumes precomputed causal features on synthetic or real inputs
and returns a decision. It is the step-2 brake/exposure half of the
experimental ML ranker, evaluated honestly out-of-sample by the other agent.
"""

from dataclasses import dataclass

import numpy as np


# Reject any non-finite feature or parameter value; a brake must never
# silently pass bad data through to a decision.
def _require_finite(value: float, name: str) -> None:
    if not np.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


# Reject a value outside its declared bounds after the finiteness check.
# `lower_open`/`upper_open` mark exclusive bounds, e.g. realised volatility
# must be strictly above zero.
def _require_bounds(
    value: float,
    name: str,
    lower: float,
    upper: float,
    *,
    lower_open: bool = False,
    upper_open: bool = False,
) -> None:
    _require_finite(value, name)
    below = value <= lower if lower_open else value < lower
    above = value >= upper if upper_open else value > upper
    if below or above:
        left = "(" if lower_open else "["
        right = ")" if upper_open else "]"
        raise ValueError(
            f"{name} out of declared range {left}{lower}, {upper}{right}, got {value!r}"
        )


# Validate every causal feature a decision reads: finite and inside its
# declared range, whatever object supplies them.
def _validate_regime(regime) -> None:
    _require_bounds(regime.market_drawdown_63, "market_drawdown_63", -np.inf, 0.0)
    _require_bounds(
        regime.realized_vol_21, "realized_vol_21", 0.0, np.inf, lower_open=True
    )
    _require_bounds(regime.ai_participation, "ai_participation", 0.0, 1.0)
    _require_bounds(
        regime.participation_percentile, "participation_percentile", 0.0, 1.0
    )
    _require_bounds(
        regime.avg_prediction_strength, "avg_prediction_strength", 0.0, np.inf
    )
    _require_bounds(regime.top_name_concentration, "top_name_concentration", 0.0, 1.0)


@dataclass(frozen=True)
class RegimeFeatures:
    """The causal inputs known at a decision-session close (nothing future).

    Ranges are enforced at construction and again by every `AdaptiveBrake`
    method, so a brake can never decide on data it was not given.
    """

    # <=0: drawdown of the market from its 63-session high, negative loss.
    market_drawdown_63: float
    # >0: realised volatility over the last 21 sessions (decimal, same scale
    # as the desk's volatility target near 0.25-0.30).
    realized_vol_21: float
    # [0,1]: the AI basket's participation level, normalised; carried for
    # context, not separately consumed (the percentile below already ranks it).
    ai_participation: float
    # [0,1]: participation rank against its own trailing history; drives the
    # crowding/participation cut, mirroring the desk's participation_percentile.
    participation_percentile: float
    # >=0: mean absolute ranker prediction across the candidate book; weak
    # predictions scale the book down even when the market is calm.
    avg_prediction_strength: float
    # [0,1]: fraction of the predicted book value sitting in the top name.
    # Validated and carried; the current rule reserves it for a future
    # single-name concentration channel rather than double-counting a risk.
    top_name_concentration: float

    # Reject bad data at construction so a decision is never made on it.
    def __post_init__(self) -> None:
        _validate_regime(self)


class AdaptiveBrake:
    """Adaptive exposure plus hard brake, deterministic and explainable."""

    def __init__(
        self,
        *,
        seed: int = 0,
        max_exposure: float = 1.0,
        vol_floor: float = 0.12,
        vol_ceiling: float = 0.30,
        drawdown_brake: float = -0.15,
        participation_floor: float = 0.10,
        drawdown_hard: float = -0.25,
        participation_low: float = 0.25,
        prediction_strength_floor: float = 0.05,
        prediction_strength_full: float = 0.15,
    ) -> None:
        # Validate every parameter up front so a misconfigured brake fails at
        # construction rather than making odd decisions later.
        for name, value in (
            ("max_exposure", max_exposure),
            ("vol_floor", vol_floor),
            ("vol_ceiling", vol_ceiling),
            ("drawdown_brake", drawdown_brake),
            ("drawdown_hard", drawdown_hard),
            ("participation_floor", participation_floor),
            ("participation_low", participation_low),
            (
                "prediction_strength_floor",
                prediction_strength_floor,
            ),
            ("prediction_strength_full", prediction_strength_full),
        ):
            _require_finite(value, f"parameter {name}")
        if not 0.0 < max_exposure <= 1.0:
            raise ValueError("parameter max_exposure must be in (0, 1]")
        if not 0.0 < vol_floor < vol_ceiling:
            raise ValueError(
                "parameter vol_floor must be positive and below vol_ceiling"
            )
        if not drawdown_hard < drawdown_brake <= 0.0:
            raise ValueError(
                "parameter drawdown_hard must be below drawdown_brake, "
                "and drawdown_brake must be <= 0"
            )
        if not 0.0 <= participation_floor < participation_low <= 1.0:
            raise ValueError(
                "parameter participation_floor must be below participation_low, "
                "both in [0, 1]"
            )
        if not 0.0 <= prediction_strength_floor < prediction_strength_full:
            raise ValueError(
                "parameter prediction_strength_floor must be below "
                "prediction_strength_full"
            )
        # Reserved for reproducibility of any future stochastic element; the
        # deterministic rule never consumes it, so identical inputs always
        # give identical outputs.
        self._seed = int(seed)
        self.max_exposure = max_exposure
        self.vol_floor = vol_floor
        self.vol_ceiling = vol_ceiling
        self.drawdown_brake = drawdown_brake
        self.drawdown_hard = drawdown_hard
        self.participation_floor = participation_floor
        self.participation_low = participation_low
        self.prediction_strength_floor = prediction_strength_floor
        self.prediction_strength_full = prediction_strength_full

    # Linear exposure factor from realised volatility: 1 at or below the floor,
    # 0 at or above the ceiling, monotone non-increasing in between.
    def _vol_factor(self, vol: float) -> float:
        if vol <= self.vol_floor:
            return 1.0
        if vol >= self.vol_ceiling:
            return 0.0
        return float((self.vol_ceiling - vol) / (self.vol_ceiling - self.vol_floor))

    # Linear exposure factor from market drawdown (negative): 1 at or above the
    # brake level, 0 at or below the hard threshold, monotone non-increasing as
    # the drawdown deepens.
    def _dd_factor(self, drawdown: float) -> float:
        if drawdown >= self.drawdown_brake:
            return 1.0
        if drawdown <= self.drawdown_hard:
            return 0.0
        return float(
            (drawdown - self.drawdown_hard) / (self.drawdown_brake - self.drawdown_hard)
        )

    # Linear exposure factor from participation percentile: 1 at or above the
    # low level, 0 at or below the floor, monotone non-decreasing in the
    # percentile.
    def _part_factor(self, percentile: float) -> float:
        if percentile >= self.participation_low:
            return 1.0
        if percentile <= self.participation_floor:
            return 0.0
        return float(
            (percentile - self.participation_floor)
            / (self.participation_low - self.participation_floor)
        )

    # Confidence scaling from mean absolute prediction strength, bounded in
    # [0.5, 1]: weak signal halves the book but never alone brakes it, so a
    # zero exposure always means the brake fired, never low confidence.
    def _conf_factor(self, strength: float) -> float:
        if strength >= self.prediction_strength_full:
            return 1.0
        if strength <= self.prediction_strength_floor:
            return 0.5
        scaled = (strength - self.prediction_strength_floor) / (
            self.prediction_strength_full - self.prediction_strength_floor
        )
        return float(0.5 + 0.5 * scaled)

    # Decide exposure, the brake flag and the human-readable reasons in one
    # pass so the three public views can never disagree.
    def decide(self, regime: RegimeFeatures) -> dict:
        _validate_regime(regime)
        vol = float(regime.realized_vol_21)
        drawdown = float(regime.market_drawdown_63)
        percentile = float(regime.participation_percentile)
        strength = float(regime.avg_prediction_strength)
        vol_factor = self._vol_factor(vol)
        dd_factor = self._dd_factor(drawdown)
        part_factor = self._part_factor(percentile)
        conf_factor = self._conf_factor(strength)
        brake = bool(
            vol >= self.vol_ceiling
            or drawdown <= self.drawdown_hard
            or percentile <= self.participation_floor
        )
        reasons: list[str] = []
        if vol >= self.vol_ceiling:
            reasons.append(
                f"brake: realized_vol_21 {vol:.4f} at/above ceiling "
                f"{self.vol_ceiling:.4f}"
            )
        elif vol > self.vol_floor:
            reasons.append(
                f"vol: realized_vol_21 {vol:.4f} above floor "
                f"{self.vol_floor:.4f}; factor {vol_factor:.3f}"
            )
        if drawdown <= self.drawdown_hard:
            reasons.append(
                f"brake: market_drawdown_63 {drawdown:.4f} at/below hard "
                f"{self.drawdown_hard:.4f}"
            )
        elif drawdown < self.drawdown_brake:
            reasons.append(
                f"drawdown: market_drawdown_63 {drawdown:.4f} below brake "
                f"{self.drawdown_brake:.4f}; factor {dd_factor:.3f}"
            )
        if percentile <= self.participation_floor:
            reasons.append(
                "brake: participation_percentile "
                f"{percentile:.4f} at/below floor {self.participation_floor:.4f}"
            )
        elif percentile < self.participation_low:
            reasons.append(
                "participation: participation_percentile "
                f"{percentile:.4f} below {self.participation_low:.4f}; "
                f"factor {part_factor:.3f}"
            )
        if strength < self.prediction_strength_full:
            reasons.append(
                "confidence: avg_prediction_strength "
                f"{strength:.4f} below full {self.prediction_strength_full:.4f}; "
                f"factor {conf_factor:.3f}"
            )
        exposure = float(
            np.clip(
                self.max_exposure * vol_factor * dd_factor * part_factor * conf_factor,
                0.0,
                1.0,
            )
        )
        if brake:
            exposure = 0.0
        return {"exposure": exposure, "brake": brake, "reasons": reasons}

    # The exposure multiplier in [0,1]: the full book in a calm regime, scaled
    # down as risk rises and zeroed by a hard brake.
    def exposure(self, regime: RegimeFeatures) -> float:
        return float(self.decide(regime)["exposure"])

    # Whether the hard brake fires: severe volatility, a deep drawdown, or a
    # collapsed participation percentile.
    def brake(self, regime: RegimeFeatures) -> bool:
        return bool(self.decide(regime)["brake"])
