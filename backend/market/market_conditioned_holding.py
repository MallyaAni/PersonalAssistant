"""Authenticated market-conditioned scenarios for private funded research.

This preserves the original dated simultaneous risk bank and publication guards.
Empirical residuals and regression leverage do not certify forecast probabilities.
"""

import hashlib
from copy import deepcopy
from pathlib import Path

import numpy as np

from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_feature_arithmetic as feature
from backend.market import learned_entry_models as base
from backend.market import market_conditioned_calibration as numerical
from backend.market.conditional_holding_calibration import _Calibration
from backend.market.direct_error_band import VolatilityHoldingReader
from backend.market.forward_arithmetic import ForwardVolatilityHoldingReader

POLICY = "market-conditioned-joint-holding/1-research"
CONTEXT_COLUMNS = (1, 5, 4, 12)


# Keep one monthly stock fit independent of request order and requested peers.
class _MarketCalibration(_Calibration):
    # Detach authenticated full features alongside the unchanged original risk bank.
    def _bind(self, parent):
        if isinstance(parent, VolatilityHoldingReader) and (
            reference._hash(parent.features) != parent.identity["features_sha256"]
            or reference._hash(parent.volatility)
            != parent.identity["volatility_sha256"]
            or any(
                reference._hash(getattr(parent, name))
                != reference._hash(getattr(parent._reader, name))
                for name in ("dates", "forecasts", "labels", "endpoints", "support")
            )
        ):
            raise ValueError("Original reader feature binding differs")
        super()._bind(parent)
        if "SPY" not in self.symbols:
            raise ValueError("Authenticated SPY feature context required")
        if "features" not in self._frozen_bank:
            self._frozen_bank["features"] = self._parent.features
        self._frozen_bank["features"].flags.writeable = False
        self._market = self._frozen_bank["features"][:, self.symbols.index("SPY")][
            :, CONTEXT_COLUMNS
        ].copy()
        self._market.flags.writeable = False
        self.identity.update(
            policy=POLICY,
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            numerical_source_sha256=hashlib.sha256(
                Path(numerical.__file__).read_bytes()
            ).hexdigest(),
            protocol_sha256=hashlib.sha256(
                (Path(__file__).resolve().parents[2] / numerical.PROTOCOL).read_bytes()
            ).hexdigest(),
            context=list(numerical.CONTEXT),
            context_sha256=reference._hash(self._market),
            features_sha256=reference._hash(self._frozen_bank["features"]),
        )

    # Retain original admitted dates and independently recheck outcome maturity.
    def _stock_fit(self, day, symbol):
        sample = self._parent.distribution(day, (symbol,))
        if sample.receipt["status"] != "available":
            raise ValueError("Original individual risk is unavailable")
        key = (sample.receipt["fit_date"], symbol)
        if key not in self._fits:
            bank = self._frozen_bank
            rows = np.asarray(sample.receipt["decision_indices"], dtype=np.int64)
            dates = (
                bank["dates"] if len(bank["dates"]) >= len(self.dates) else self.dates
            )
            count, stock = len(dates), self.symbols.index(symbol)
            support = np.zeros(count, dtype=bool)
            support[rows] = True
            endpoints = np.full(count, np.datetime64("NaT", "D"))
            forecast, outcome = np.full((2, count), np.nan)
            market = np.full((count, len(numerical.CONTEXT)), np.nan)
            size = len(bank["dates"])
            endpoints[:size] = bank["endpoints"]
            forecast[:size] = bank["forecasts"][:, stock]
            outcome[:size] = bank["labels"][:, stock]
            market[:size] = self._market
            fit = numerical.fit_market_log(
                dates,
                endpoints,
                forecast,
                outcome,
                market,
                support,
                fit_date=np.datetime64(key[0], "D"),
            )
            if not np.array_equal(fit.selected, rows):
                raise ValueError("Market fit differs from original admitted dates")
            self._fits[key] = fit, {"symbol": symbol, **fit.receipt()}
        return self._fits[key]

    # Transform only the admitted simultaneous rows under the authentic current context.
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
            "scenarios_sha256",
            "original_mean_sha256",
            "corrected_mean_sha256",
            "volatility_identity",
        ):
            receipt.pop(key, None)
        if receipt["status"] != "available":
            return feature.HoldingScenarios(None, None, original.symbols, receipt)
        bank = self._frozen_bank
        rows = np.asarray(receipt["decision_indices"], dtype=np.int64)
        stocks = np.asarray([self.symbols.index(name) for name in original.symbols])
        forward = isinstance(self._parent, ForwardVolatilityHoldingReader)
        current = self.current.forecasts if forward else bank["forecasts"][day]
        features = self.current.features if forward else bank["features"][day]
        try:
            context = numerical._context(
                features[self.symbols.index("SPY"), CONTEXT_COLUMNS][None]
            )[0]
            pairs = [self._stock_fit(day, name) for name in original.symbols]
            scenarios = np.empty((len(rows), len(stocks)), dtype=np.float64)
            predictions = []
            for column, (stock, (fit, _)) in enumerate(zip(stocks, pairs, strict=True)):
                if not np.isin(rows, fit.selected).all():
                    raise ValueError(
                        "Joint residual date is outside original stock fit"
                    )
                mean, multiplier = fit.predict(current[stock], context)
                observed = bank["labels"][rows, stock]
                default = observed == -1
                predictors = np.c_[
                    np.log1p(bank["forecasts"][rows[~default], stock]),
                    self._market[rows[~default]],
                ]
                active = fit.scale > 0
                design = np.zeros((len(predictors), 6))
                design[:, 0] = 1
                design[:, 1 + np.flatnonzero(active)] = (
                    predictors[:, active] - fit.center[active]
                ) / fit.scale[active]
                residual = np.log1p(observed[~default]) - design @ fit.coefficients
                current_vol, past_vol = (
                    features[stock, 4],
                    bank["volatility"][rows, stock],
                )
                if (
                    not np.isfinite(current_vol)
                    or current_vol <= 0
                    or not np.isfinite(past_vol).all()
                    or np.any(past_vol <= 0)
                ):
                    raise ValueError(
                        "Positive finite original stock volatility required"
                    )
                with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                    values = np.expm1(
                        mean + residual * multiplier * current_vol / past_vol[~default]
                    )
                if not np.isfinite(values).all() or np.any(values <= -1):
                    raise ValueError("Calibration overflows or manufactures total loss")
                scenarios[default, column], scenarios[~default, column] = -1, values
                predictions.append(
                    {"conditional_log_mean": mean, "residual_multiplier": multiplier}
                )
        except ValueError as exc:
            receipt.update(
                status="unavailable",
                reason="unsupported_market_calibration",
                calibration_reason=str(exc),
            )
            return feature.HoldingScenarios(None, None, original.symbols, receipt)
        scenarios.flags.writeable = False
        receipt.update(
            calibration=[deepcopy(pair[1]) for pair in pairs],
            predictions=predictions,
            current_context=context.tolist(),
            current_context_sha256=reference._hash(context),
            scenarios_sha256=reference._hash(scenarios),
            probabilities_sha256=reference._hash(original.probabilities),
        )
        return feature.HoldingScenarios(
            scenarios, original.probabilities, original.symbols, receipt
        )


# Expose the same transformation through the historical authenticated reader contract.
class MarketConditionedHoldingReader(_MarketCalibration, VolatilityHoldingReader):
    # Admit the original reader rather than stacking an earlier learned correction.
    def __init__(self, parent):
        if type(parent) is not VolatilityHoldingReader:
            raise ValueError("Original historical volatility reader required")
        self._bind(parent)

    # Keep original historical eligibility and completed-close checks.
    def distribution(self, day, symbols):
        return self._distribution(day, symbols)


# Retain genuine forward publication and report guards around the identical scenarios.
class ForwardMarketConditionedHoldingReader(
    _MarketCalibration, ForwardVolatilityHoldingReader
):
    # Admit only an original published current close and its fixed historic bank.
    def __init__(self, parent):
        if type(parent) is not ForwardVolatilityHoldingReader:
            raise ValueError("Original forward volatility reader required")
        self._bind(parent)

    # Keep the original current-index and publication validation before any calibration.
    def distribution(self, day, symbols):
        return self._distribution(day, symbols)
