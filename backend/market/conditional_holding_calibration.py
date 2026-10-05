"""Past-only conditional log-return calibration on authenticated joint risk banks.

The empirical scenarios and regression leverage are not calibrated probabilities.
This option never changes the underlying numeric head or selects a live broker.
"""

import hashlib
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_feature_arithmetic as feature
from backend.market import learned_entry_models as base
from backend.market.direct_error_band import VolatilityHoldingReader
from backend.market.forward_arithmetic import ForwardVolatilityHoldingReader

POLICY = "joint-holding-log-calibration/1-research"
PROTOCOL = "docs/research/conditional-holding-calibration-plan-2026-10-05.md"


# Keep the fitted conditional mean separate from actual default observations.
@dataclass(frozen=True)
class LogFit:
    center: float
    scale: float
    slope: float
    mean: float
    sum_squared_predictor: float
    observations: int
    defaults: int
    parameters: int

    # Predict the conditional log mean and its regression uncertainty adjustment.
    def predict(self, forecast):
        if (
            isinstance(forecast, (bool, np.bool_))
            or not isinstance(forecast, (int, float, np.integer, np.floating))
            or not np.isfinite(forecast)
            or forecast <= -1
        ):
            raise ValueError("Possible finite current forecast required")
        z = (np.log1p(forecast) - self.center) / self.scale if self.scale else 0.0
        leverage = 1 / self.observations + (
            z * z / self.sum_squared_predictor if self.parameters == 2 else 0
        )
        mean = self.mean + self.slope * z
        factor = np.sqrt(
            self.observations / (self.observations - self.parameters) * (1 + leverage)
        )
        if not np.isfinite([mean, factor]).all():
            raise ValueError("Unsupported calibration arithmetic")
        return float(mean), float(factor)


# Fit one supplied mature stock bank without clipping losses or selecting a sign.
def fit_log(forecasts, outcomes):
    raw, observed = np.asarray(forecasts), np.asarray(outcomes)
    if (
        raw.ndim != 1
        or observed.shape != raw.shape
        or raw.dtype.kind not in "fiu"
        or observed.dtype.kind not in "fiu"
        or not np.isfinite(raw).all()
        or not np.isfinite(observed).all()
        or np.any(raw <= -1)
        or np.any(observed < -1)
    ):
        raise ValueError("Aligned possible finite forecasts and outcomes required")
    default = observed == -1
    x, y = np.log1p(raw[~default]), np.log1p(observed[~default])
    if len(x) < 3:
        raise ValueError("Insufficient nondefault calibration history")
    center, mean = float(x.mean()), float(y.mean())
    scale = 0.0 if np.all(x == x[0]) else float(np.max(np.abs(x - center)))
    z = (x - center) / scale if scale else np.zeros_like(x)
    squared = float(z @ z)
    slope = float(z @ (y - mean) / squared) if scale else 0.0
    fit = LogFit(
        center,
        scale,
        slope,
        mean,
        squared,
        len(x),
        int(default.sum()),
        2 if scale else 1,
    )
    if not np.isfinite([center, mean, scale, squared, slope]).all():
        raise ValueError("Unsupported calibration fit arithmetic")
    return fit


# Retain the same-date error vectors and true defaults under current stock volatility.
def calibrated_scenarios(current, past, outcomes, current_vol, past_vol, fits):
    arrays = tuple(
        np.asarray(v) for v in (current, past, outcomes, current_vol, past_vol)
    )
    current, past, outcomes, current_vol, past_vol = arrays
    if (
        any(v.dtype.kind not in "fiu" or not np.isfinite(v).all() for v in arrays)
        or current.ndim != 1
        or not len(current)
        or past.ndim != 2
        or not past.shape[0]
        or outcomes.shape != past.shape
        or past.shape[1] != len(current)
        or current_vol.shape != current.shape
        or past_vol.shape != past.shape
        or len(fits) != len(current)
        or not all(isinstance(fit, LogFit) for fit in fits)
        or np.any(current <= -1)
        or np.any(past <= -1)
        or np.any(outcomes < -1)
        or np.any(current_vol <= 0)
        or np.any(past_vol <= 0)
    ):
        raise ValueError("Aligned calibrated stocks and positive volatility required")
    result = np.empty(past.shape, dtype=np.float64)
    predictions = []
    for stock, fit in enumerate(fits):
        mean, adjustment = fit.predict(current[stock])
        default = outcomes[:, stock] == -1
        x = np.log1p(past[~default, stock])
        z = (x - fit.center) / fit.scale if fit.scale else np.zeros_like(x)
        residual = np.log1p(outcomes[~default, stock]) - (fit.mean + fit.slope * z)
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            log_values = (
                mean
                + residual * adjustment * current_vol[stock] / past_vol[~default, stock]
            )
            values = np.expm1(log_values)
        if not np.isfinite(values).all() or np.any(values <= -1):
            raise ValueError("Calibration overflows or manufactures total loss")
        result[default, stock], result[~default, stock] = -1.0, values
        predictions.append(
            {"conditional_log_mean": mean, "residual_multiplier": adjustment}
        )
    result.flags.writeable = False
    return result, predictions


# Share monthly calibration while retaining the original reader's publication guards.
class _Calibration:
    # Detach all caller buffers before binding a historical or published forward reader.
    def _bind(self, parent):
        self._parent = deepcopy(parent)
        self.dates, self.symbols = self._parent.dates, self._parent.symbols
        forward = isinstance(parent, ForwardVolatilityHoldingReader)
        if forward:
            self.current = self._parent.current
            self._frozen_bank = self._parent._bank
        else:
            self._frozen_bank = {
                key: getattr(self._parent, key)
                for key in (
                    "dates",
                    "forecasts",
                    "labels",
                    "endpoints",
                    "support",
                    "volatility",
                )
            }
        for value in self._frozen_bank.values():
            value.flags.writeable = False
        self.dates.flags.writeable = False
        self._fits = {}
        root = Path(__file__).resolve().parents[2]
        self.identity = {
            "policy": POLICY,
            "parent_identity_sha256": base._json_hash(parent.identity),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "protocol_sha256": hashlib.sha256(
                (root / PROTOCOL).read_bytes()
            ).hexdigest(),
            "calibration_residuals": "in_sample_on_genuine_OOS_base_forecasts",
            "confidence_guarantee": False,
            "adoption_eligible": False,
        }

    # Fit each stock once per original month, independently of requested peers.
    def _stock_fit(self, day, symbol):
        sample = self._parent.distribution(day, (symbol,))
        if sample.receipt["status"] != "available":
            raise ValueError("Original individual risk is unavailable")
        key = (sample.receipt["fit_date"], symbol)
        if key not in self._fits:
            rows = np.asarray(sample.receipt["decision_indices"], dtype=np.int64)
            bank = self._frozen_bank
            cutoff = np.datetime64(sample.receipt["label_end_before"], "D")
            if (
                len(rows) < 252
                or np.isnat(bank["endpoints"][rows]).any()
                or np.any(bank["endpoints"][rows] >= cutoff)
            ):
                raise ValueError("Strictly mature original calibration dates required")
            stock = self.symbols.index(symbol)
            past, observed = bank["forecasts"][rows, stock], bank["labels"][rows, stock]
            fit = fit_log(past, observed)
            proof = {
                "symbol": symbol,
                "fit_date": key[0],
                "label_end_before": str(cutoff),
                "decision_indices_sha256": reference._hash(rows),
                "calibration_dates": len(rows),
                "maximum_endpoint": str(bank["endpoints"][rows].max()),
                "fit": asdict(fit),
                "forecasts_sha256": reference._hash(past),
                "labels_sha256": reference._hash(observed),
                "endpoints_sha256": reference._hash(bank["endpoints"][rows]),
            }
            self._fits[key] = fit, proof
        return self._fits[key]

    # Transform an admitted common bank without reading current or future outcomes.
    def _distribution(self, day, symbols):
        original = self._parent.distribution(day, symbols)
        receipt = {
            **deepcopy(original.receipt),
            "policy": POLICY,
            "calibration_identity": deepcopy(self.identity),
            "parent_receipt_sha256": base._json_hash(original.receipt),
            "parent_volatility_identity": deepcopy(
                original.receipt.get("volatility_identity")
            ),
        }
        for key in (
            "volatility_identity",
            "original_mean_sha256",
            "corrected_mean_sha256",
        ):
            receipt.pop(key, None)
        if receipt["status"] != "available":
            return feature.HoldingScenarios(None, None, original.symbols, receipt)
        rows = np.asarray(receipt["decision_indices"], dtype=np.int64)
        stocks = np.asarray([self.symbols.index(name) for name in original.symbols])
        bank = self._frozen_bank
        forward = isinstance(self._parent, ForwardVolatilityHoldingReader)
        current = (
            self.current.forecasts[stocks]
            if forward
            else bank["forecasts"][day, stocks]
        )
        volatility = (
            self.current.features[stocks, 4]
            if forward
            else bank["volatility"][day, stocks]
        )
        try:
            pairs = [self._stock_fit(day, name) for name in original.symbols]
            scenarios, predictions = calibrated_scenarios(
                current,
                bank["forecasts"][np.ix_(rows, stocks)],
                bank["labels"][np.ix_(rows, stocks)],
                volatility,
                bank["volatility"][np.ix_(rows, stocks)],
                [pair[0] for pair in pairs],
            )
        except ValueError as exc:
            receipt.update(
                status="unavailable",
                reason="unsupported_log_calibration",
                calibration_reason=str(exc),
            )
            receipt.pop("scenarios_sha256", None)
            return feature.HoldingScenarios(None, None, original.symbols, receipt)
        receipt.update(
            calibration=[deepcopy(pair[1]) for pair in pairs],
            predictions=predictions,
            scenarios_sha256=reference._hash(scenarios),
            probabilities_sha256=reference._hash(original.probabilities),
        )
        return feature.HoldingScenarios(
            scenarios, original.probabilities, original.symbols, receipt
        )


# Expose calibrated historical scenarios through the existing trusted reader contract.
class CalibratedHoldingReader(_Calibration, VolatilityHoldingReader):
    # Admit exactly the unchanged original volatility reader, not stacked corrections.
    def __init__(self, parent):
        if type(parent) is not VolatilityHoldingReader:
            raise ValueError("Original historical volatility reader required")
        self._bind(parent)

    # Preserve the historical reader's original eligibility and completed-close checks.
    def distribution(self, day, symbols):
        return self._distribution(day, symbols)


# Apply identical calibration to explicitly published current close observations.
class ForwardCalibratedHoldingReader(_Calibration, ForwardVolatilityHoldingReader):
    # Keep current-clock and report validation on the original published forward path.
    def __init__(self, parent):
        if type(parent) is not ForwardVolatilityHoldingReader:
            raise ValueError("Original forward volatility reader required")
        self._bind(parent)

    # Preserve forward current-index, publication and stock-identity checks.
    def distribution(self, day, symbols):
        return self._distribution(day, symbols)
