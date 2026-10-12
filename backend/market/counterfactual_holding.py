"""Explicit as-if-available research inference; never installed live admission.

Original publication times remain in the receipt. The user's retrospective
assumption applies only to this private ReplayBroker account, not to production.
"""

from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np

from backend.market import (
    calendar,
    direct_daily_arithmetic,
    forward_arithmetic,
    joint_funded_policy,
    learned_retention_models,
)
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.market_conditioned_holding import (
    ForwardMarketConditionedHoldingReader,
)
from backend.market.replay_broker import ReplayBroker


# Reuse the volatility calculation with an explicit retrospective assumption.
class CounterfactualRiskReader(forward_arithmetic.ForwardVolatilityHoldingReader):
    # Freeze original risk and a past prefix scored by authenticated heads.
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

    # Permit only the declared past close; keep original publication receipts.
    def validate_clock(self, instant):
        day = self.dates[-1].astype(object)
        expected = datetime.combine(
            day, calendar.session_close(day), calendar.NEW_YORK
        ) + timedelta(minutes=1)
        if instant != expected:
            raise ValueError(
                "Counterfactual reader belongs only to its historical close"
            )


# Apply the existing market calibration to the explicit counterfactual risk observation.
class CounterfactualMarketReader(ForwardMarketConditionedHoldingReader):
    # Keep this adapter unavailable to the installed forward-policy factory.
    def __init__(self, parent):
        if type(parent) is not CounterfactualRiskReader:
            raise ValueError("Explicit counterfactual parent required")
        self._bind(parent)

    # Validate the private historical clock without backdating publication.
    def validate_clock(self, instant):
        self._parent.validate_clock(instant)

    # Preserve the same original monthly calibration and retained-stock scenarios.
    def distribution(self, day, symbols):
        return self._distribution(day, symbols)


# Restrict the as-if-available policy structurally to an isolated synthetic broker.
class CounterfactualPolicy(joint_funded_policy.RetainedMarketConditionedFundedPolicy):
    # Admit this private reader without widening any installed-policy constructor.
    def __init__(self, reader, cost_bps):
        if type(reader) is not CounterfactualMarketReader:
            raise ValueError("Explicit private counterfactual market reader required")
        joint_funded_policy.JointFundedPolicy.__init__(self, reader, cost_bps)
        self.identity.update(self._timing_identity())
        self.identity.update(counterfactual=True, real_orders=False)

    # Refuse production brokers even if this research policy is imported.
    def admit_broker(self, client, decision_at):
        if type(client) is not ReplayBroker:
            raise ValueError("Counterfactual strategy never admits a real broker")
        self.reader._parent.validate_clock(decision_at)
