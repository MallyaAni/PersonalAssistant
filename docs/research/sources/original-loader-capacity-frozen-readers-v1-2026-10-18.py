"""UNEXECUTED capacity reader identities; constructors only, no policy admission.

Two constructor frames preserve the first feature graph's release boundary.
Inherited select/distribution/clock and calibration methods are NOT admitted;
the future exact phase fence must exclude every such call. No model is fitted.
"""
from copy import deepcopy

import numpy as np

from backend.market import direct_daily_arithmetic, forward_arithmetic, learned_retention_models
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.market_conditioned_holding import ForwardMarketConditionedHoldingReader

SCHEMA = 'capacity-original-frozen-readers/1'


# Retain original counterfactual constructor allocations in a separate returning frame.
class CapacityCounterfactualRiskBaseV1(forward_arithmetic.ForwardVolatilityHoldingReader):
    # Preserve first features, first prediction, current observation and original bank copies.
    def __init__(
        self, original, panel, grades, eligible, head, model, actual_observed_at
    ):
        prepared = learned_retention_models.completed_features(
            panel,
            grades,
            eligible,
            panel.dates,
            {
                "data_as_of": actual_observed_at.isoformat(),
                "basis": "counterfactual_current_vintage",
            },
        )
        if tuple(prepared["symbols"]) != tuple(original.symbols):
            raise ValueError(
                "Counterfactual cohort differs from authenticated original risk"
            )
        common = min(len(panel.dates), len(original.dates))
        if not np.array_equal(panel.dates[:common], original.dates[:common]):
            raise ValueError("Counterfactual calendar differs from original bank")
        values, _ = direct_daily_arithmetic.predict(
            head, prepared["X"][-1:], prepared["risk_valid"][-1:]
        )
        identity = {
            "model_fit_date": model["training"]["fit_date"],
            "model_published_at": model["identity"]["published_at"],
            "actual_observed_at": actual_observed_at.isoformat(),
            "assumption": "installed heads available at historical decision",
            "prefix_sha256": {
                "dates": _hash(panel.dates),
                "prices": _hash(panel.adj_close),
            },
        }
        self.current = forward_arithmetic.CloseObservation(
            panel.dates.copy(),
            tuple(panel.tickers),
            prepared["X"][-1].copy(),
            prepared["prices"][-1].copy(),
            values[-1].copy(),
            prepared["risk_valid"][-1].copy(),
            panel.adj_close.copy(),
            grades.copy(),
            head,
            {"identity": identity},
        )
        self.dates, self.symbols = self.current.dates, self.current.symbols
        self._bank = {
            key: getattr(original, key).copy()
            for key in (
                "dates",
                "forecasts",
                "labels",
                "endpoints",
                "support",
                "volatility",
                "features",
            )
        }
        for value in self._bank.values():
            value.flags.writeable = False
        self.identity = {
            "policy": "counterfactual-holding-risk/1",
            "original_identity": deepcopy(original.identity),
            "assumption": identity["assumption"],
            "real_orders": False,
        }


# Freeze the second complete feature graph only after the first constructor returns.
class CapacityFrozenRiskReaderV1(CapacityCounterfactualRiskBaseV1):
    # Preserve the second prediction, frozen copies, readonly flags and original numeric receipt.
    def __init__(self, original, panel, grades, eligible, head, model, observed_at):
        super().__init__(original, panel, grades, eligible, head, model, observed_at)
        prepared = learned_retention_models.completed_features(
            panel,
            grades,
            eligible,
            panel.dates,
            {
                "data_as_of": observed_at.isoformat(),
                "basis": "current-model-retrospective",
            },
        )
        forecasts, _ = direct_daily_arithmetic.predict(
            head, prepared["X"], prepared["risk_valid"]
        )
        self._frozen_dates = panel.dates.copy()
        self._features = prepared["X"].copy()
        self._forecasts = forecasts.copy()
        self._support = prepared["risk_valid"].copy()
        self._prices = prepared["prices"].copy()
        self._history_prices = panel.adj_close.copy()
        self._history_grades = grades.copy()
        self._model_identity = deepcopy(self.current.receipt["identity"])
        self._head = head
        for value in (
            self._frozen_dates,
            self._features,
            self._forecasts,
            self._support,
            self._prices,
            self._history_prices,
            self._history_grades,
        ):
            value.flags.writeable = False
        self.identity.update(
            basis="fixed_current_models_applied_retrospectively",
            model_published_at=model["identity"]["published_at"],
            model_fit_date=model["training"]["fit_date"],
            feature_rows_sha256=_hash(self._features),
            current_model_forecasts_sha256=_hash(self._forecasts),
        )


# Preserve real market-calibration MRO, deepcopy and self-file identities under a new type.
class CapacityFrozenMarketReaderV1(ForwardMarketConditionedHoldingReader):
    # Accept only the exact new capacity parent before unchanged original market binding.
    def __init__(self, parent):
        if type(parent) is not CapacityFrozenRiskReaderV1:
            raise ValueError("Explicit frozen current-model parent required")
        self._bind(parent)
