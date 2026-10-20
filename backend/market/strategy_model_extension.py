"""Dated counterfactual inference, separate from actual live publication admission.

The caller authenticates original numeric heads and the risk bank at the REAL
calculation clock. Dated prefixes may then be scored mathematically, without
backdating observe_close or claiming the model was published on those dates.
This adapter deliberately does not inherit an operational reader's admission.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.market import adaptive_growth_policy as growth
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_error_band as errors
from backend.market import direct_feature_arithmetic as feature
from backend.market import market_conditioned_holding as market

VERSION = "counterfactual-forward-extension/1"


# Carry only a verified numerical book across an exact dated, unchanged price anchor.
@dataclass(frozen=True)
class InitialBook:
    through: str
    symbols: tuple
    shares: tuple
    cash: float
    fees: float
    sequence: int
    result_sha256: str

    # Refuse an account-shaped, negative, unbound or nonconsecutive continuation.
    def validate(self, dates, names, first):
        if (self.symbols != names or self.through != str(dates[first - 1])
                or len(self.shares) != len(names)
                or not np.isfinite(self.shares).all() or min(self.shares) < 0
                or not np.isfinite([self.cash, self.fees]).all()
                or self.cash < 0 or self.fees < 0
                or type(self.sequence) is not int or self.sequence < 0
                or len(self.result_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.result_sha256)):
            raise ValueError("Exact original numerical book and preceding session required")


# Convert adjusted fractional units at the boundary while preserving every owned dollar.
def rebase_units(shares, original_prices, revised_prices):
    held, old, new = (np.asarray(value, dtype=np.float64) for value in (shares, original_prices, revised_prices))
    if (held.shape != old.shape or held.shape != new.shape or held.ndim != 1
            or not np.isfinite(held).all() or np.any(held < 0)
            or np.any((held > 0) & (~np.isfinite(old) | ~np.isfinite(new) | (old <= 0) | (new <= 0)))):
        raise ValueError("Positive original and revised marks for every owned unit required")
    revised = np.zeros_like(held)
    selected = held > 0
    revised[selected] = held[selected] * old[selected] / new[selected]
    if not np.allclose(revised[selected] * new[selected], held[selected] * old[selected], rtol=1e-14, atol=1e-14):
        raise ValueError("Mechanical unit conversion must preserve boundary wealth")
    return revised


# Select the same mature simultaneous bank rows for new dated, non-operational forecasts.
class _DatedRisk:
    # Detach the authenticated bank and newly predicted rows without creating a live observation.
    def __init__(self, original, dates, forecasts, support, features, fit_date, identity):
        self.dates, self.symbols = np.asarray(dates).copy(), tuple(original.symbols)
        size, count = len(dates), len(self.symbols)
        if (forecasts.shape != (size, count) or support.shape != (size, count)
                or support.dtype.kind != "b" or features.shape != (size, count, 13)
                or not np.array_equal(dates[:len(original.dates)], original.dates)
                or len(original.dates) >= size
                or np.any(np.diff(dates).astype(int) <= 0)
                or np.datetime64(fit_date, "D") <= original.dates[-1]):
            raise ValueError("Original bank calendar and aligned later predictions required")
        self.fit_date = np.datetime64(fit_date, "D")
        self.identity = {**identity, "adapter": VERSION,
                         "historical_publication_claim": False,
                         "adoption_eligible": False,
                         "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}
        self.bank = {"dates": self.dates, "features": np.array(features, copy=True),
                     "forecasts": np.array(forecasts, copy=True),
                     "support": np.array(support, copy=True),
                     "volatility": np.array(features[:, :, 4], copy=True),
                     "labels": np.full((size, count), np.nan),
                     "endpoints": np.full(size, np.datetime64("NaT", "D"))}
        for key in ("forecasts", "support", "volatility", "features", "labels", "endpoints"):
            self.bank[key][:len(original.dates)] = getattr(original, key)
        for value in self.bank.values():
            value.flags.writeable = False

    # Use only pre-fit and pre-freeze matured outcomes, never the reconstructed day's outcome.
    def distribution(self, day, symbols):
        if (type(day) not in (int, np.int64) or day < 0 or day >= len(self.dates)
                or self.dates[day] < self.fit_date
                or self.dates[day].astype("datetime64[M]") != self.fit_date.astype("datetime64[M]")
                or not symbols or len(set(symbols)) != len(symbols)
                or any(name not in self.symbols or name in ("SPY", "QQQ") for name in symbols)):
            raise ValueError("Unique covered stocks in the original fitted month required")
        indices = np.array([self.symbols.index(name) for name in symbols])
        first = int(np.searchsorted(self.dates, self.fit_date))
        candidates = np.arange(max(0, first - reference.MAX_DAYS), first)
        cutoff = min(self.fit_date, reference.FREEZE)
        bank = self.bank
        mature = candidates[~np.isnat(bank["endpoints"][candidates]) & (bank["endpoints"][candidates] < cutoff)]
        available = (bank["support"][np.ix_(mature, indices)]
                     & np.isfinite(bank["forecasts"][np.ix_(mature, indices)])
                     & np.isfinite(bank["labels"][np.ix_(mature, indices)]))
        rows = mature[available.all(axis=1)]
        receipt = {**self.identity, "status": "unavailable", "symbols": list(symbols),
                   "decision_date": str(self.dates[day]), "fit_date": str(self.fit_date),
                   "label_end_before": str(cutoff), "decision_indices": rows.tolist()}
        if not bank["support"][day, indices].all() or not np.isfinite(bank["forecasts"][day, indices]).all():
            receipt["reason"] = "missing_current_forecast"
        elif len(rows) < 252:
            receipt["reason"] = "insufficient_joint_history"
        else:
            try:
                scenarios = errors.scale_holding_volatility(
                    bank["forecasts"][day, indices], bank["forecasts"][np.ix_(rows, indices)],
                    bank["labels"][np.ix_(rows, indices)], bank["features"][day, indices, 4],
                    bank["volatility"][np.ix_(rows, indices)])
            except ValueError as exc:
                receipt.update(reason="unsupported_volatility_arithmetic", arithmetic_reason=str(exc))
            else:
                receipt["status"] = "available"
                return feature.HoldingScenarios(scenarios, np.full(len(rows), 1 / len(rows)), tuple(symbols), receipt)
        return feature.HoldingScenarios(None, None, tuple(symbols), receipt)


# Reuse native market-calibration mathematics with explicitly counterfactual dated parents.
class CounterfactualMarketRisk(market._MarketCalibration):
    # Preserve original outcome support while adding no synthetic training labels or publications.
    def __init__(self, original, dates, forecasts, support, features, fit_date, identity):
        self._parent = _DatedRisk(original, dates, forecasts, support, features, fit_date, identity)
        self.dates, self.symbols = self._parent.dates, self._parent.symbols
        self._frozen_bank, self._fits = self._parent.bank, {}
        self._market = self._frozen_bank["features"][:, self.symbols.index("SPY")][:, market.CONTEXT_COLUMNS].copy()
        self._market.flags.writeable = False
        self.identity = self._parent.identity

    # Apply the shared native calibration tail without claiming native whole-reader admission.
    def distribution(self, day, symbols):
        return self._distribution(day, symbols)


# Match the zero-held grade-led entry qualification and optimizer without widening live reader types.
def counterfactual_targets(grades, reader, day, cost_bps, blocked):
    if not 0 <= cost_bps < 10000 or set(blocked) - set(grades):
        raise ValueError("Original stock entry restrictions and finite costs required")
    targets = dict.fromkeys(grades, 0.0)
    candidates = sorted(name for name, grade in grades.items() if grade >= 2 and name not in blocked)
    required = tuple(name for name in candidates if reader.distribution(day, (name,)).receipt["status"] == "available")
    if candidates and not required:
        raise ValueError("entry_risk_unavailable")
    if not required:
        return targets, {"status": "no_eligible_entries"}
    sample = reader.distribution(day, required)
    if sample.receipt["status"] != "available":
        raise ValueError("Original current joint-risk evidence unavailable")
    values, receipt = growth.allocate_distribution(
        sample.scenarios, sample.probabilities, np.array([grades[name] for name in required]),
        np.ones(len(required), dtype=bool), np.zeros(len(required)), 1.0, cost_bps,
        np.array([], dtype=np.int64), horizon="next_open_to_following_open_arithmetic_return")
    if receipt["status"] != "optimized":
        raise ValueError("Certified current strategy allocation unavailable")
    targets.update(zip(required, values.tolist(), strict=True))
    if any(not np.isfinite(v) or not 0 <= v <= growth.CAP for v in targets.values()) or sum(targets.values()) > 1 + 1e-10:
        raise ValueError("Certified finite counterfactual model percentages required")
    return targets, receipt
