"""Current installed models on past observations, confined to a private broker.

Model publication dates remain real. Retrospective availability is explicit;
these readers cannot be selected by the installed production factory.
"""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from backend.market import (
    direct_daily_arithmetic,
    forward_arithmetic,
    joint_funded_policy,
    learned_retention_models,
)
from backend.market.counterfactual_holding import CounterfactualRiskReader
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.market_conditioned_holding import (
    ForwardMarketConditionedHoldingReader,
)
from backend.market.replay_broker import ReplayBroker


# Cache causal feature rows and current-head inference without fitting any base model.
class FrozenCurrentRiskReader(CounterfactualRiskReader):
    # Authenticate the private contract before freezing current model rows.
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

    # Bind one historical prefix while retaining frozen model metadata.
    def select(self, day):
        if type(day) is not int or not 0 <= day < len(self._frozen_dates):
            raise ValueError("Explicit historical model row required")
        self.dates = self._frozen_dates[: day + 1]
        identity = {
            **deepcopy(self._model_identity),
            "prefix_sha256": {
                "dates": _hash(self.dates),
                "prices": _hash(self._history_prices[: day + 1]),
            },
        }
        self.current = forward_arithmetic.CloseObservation(
            self.dates,
            self.symbols,
            self._features[day],
            self._prices[day],
            self._forecasts[day],
            self._support[day],
            self._history_prices[: day + 1],
            self._history_grades[: day + 1],
            self._head,
            {"identity": identity},
        )

    # Reuse live residual arithmetic with the frozen current bank.
    def distribution(self, day, symbols):
        if (
            isinstance(day, (bool, np.bool_))
            or not isinstance(day, (int, np.integer))
            or day != len(self.dates) - 1
        ):
            raise ValueError("Selected historical close index required")
        frozen = SimpleNamespace(
            dates=self._frozen_dates,
            symbols=self.symbols,
            current=self.current,
            _bank=self._bank,
            identity=self.identity,
        )
        sample = forward_arithmetic.ForwardVolatilityHoldingReader.distribution(
            frozen, len(self._frozen_dates) - 1, symbols
        )
        receipt = {
            **sample.receipt,
            "decision_date": str(self.dates[-1]),
            "retrospective_current_model": True,
            "original_model_published_at": self.identity["model_published_at"],
        }
        return replace(sample, receipt=receipt)


# Reuse the live market calibration while retaining its fixed current-model stock fits.
class FrozenCurrentMarketReader(ForwardMarketConditionedHoldingReader):
    # Keep retrospective readers structurally separate from installed-policy admission.
    def __init__(self, parent):
        if type(parent) is not FrozenCurrentRiskReader:
            raise ValueError("Explicit frozen current-model parent required")
        self._bind(parent)

    # Select an observation while preserving the frozen bank and its fits.
    def select(self, day):
        self._parent.select(day)
        self.current, self.dates = self._parent.current, self._parent.dates

    # Require the same private historical decision clock as the selected model row.
    def validate_clock(self, instant):
        self._parent.validate_clock(instant)


# Apply live grade-led decisions and timing only to an isolated synthetic account.
class FrozenCurrentGradePolicy(joint_funded_policy.GradeLedFundedPolicy):
    # Preserve policy identity and fees without widening production admission.
    def __init__(self, reader, cost_bps):
        if type(reader) is not FrozenCurrentMarketReader:
            raise ValueError("Explicit frozen current-model market reader required")
        joint_funded_policy.JointFundedPolicy.__init__(self, reader, cost_bps)
        self.identity.update(self._timing_identity())
        self.identity.update(
            counterfactual=True,
            real_orders=False,
            model_basis="current-model-retrospective",
        )

    # Refuse real or environment brokers even when this private policy is imported.
    def admit_broker(self, client, decision_at):
        if type(client) is not ReplayBroker:
            raise ValueError("Historical current models never admit a real broker")
        self.reader.validate_clock(decision_at)
