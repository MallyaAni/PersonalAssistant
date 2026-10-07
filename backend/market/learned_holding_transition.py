"""Conservative capital accounting for retained, uncalibrated long holdings."""

import math
from dataclasses import dataclass

POLICY = "joint-stock-risk-funded/6-retained-holdings-probability-timing-research"
PROTOCOL = "docs/research/learned-held-transition-2026-10-07.md"


# Keep the original account and its calibrated capital in explicitly separate units.
@dataclass(frozen=True)
class Capital:
    equity: float
    cash: float
    modeled_equity: float
    modeled_holdings: dict[str, int]
    retained_weights: dict[str, float]

    # Convert modeled weights to full-account weights without spending retained capital.
    def lift(self, weights):
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in weights.values()
            )
            or sum(weights.values()) > 1 + 1e-10
        ):
            raise ValueError("Valid modeled target weights required")
        if any(weights.get(name, 0) > 0 for name in self.retained_weights):
            raise ValueError("Retained capital cannot become a modeled purchase")
        factor = self.modeled_equity / self.equity
        return {
            **{name: float(value) * factor for name, value in weights.items()},
            **self.retained_weights,
        }

    # Record the lower-bound capital basis rather than an invented return distribution.
    def receipt(self, unavailable):
        return {
            "policy": POLICY,
            "observed_equity": self.equity,
            "observed_cash": self.cash,
            "modeled_equity": self.modeled_equity,
            "modeled_fraction": self.modeled_equity / self.equity,
            "reserved_capital": self.equity - self.modeled_equity,
            "retained_weights": dict(self.retained_weights),
            "risk_unavailable": unavailable,
            "unknown_future_value_lower_bound": 0.0,
            "sale_proceeds_are_funding": False,
        }


# Reserve uncalibrated positions and unobserved wealth while retaining actual cash.
def partition(equity, cash, held, prices, retained):
    from backend.market.joint_funded_policy import _account

    current, _, reason = _account(equity, held, prices, cash)
    if reason is not None:
        raise ValueError(reason)
    if not isinstance(retained, (set, frozenset)) or not retained.issubset(current):
        raise ValueError("Only marked existing holdings may be retained")
    known = {
        name: int(qty) for name, qty in held.items() if qty > 0 and name not in retained
    }
    modeled = float(cash) + sum(
        qty * float(prices[name]) for name, qty in known.items()
    )
    if modeled > float(equity) + 1e-10 * float(equity):
        raise ValueError("Calibrated capital exceeds observed equity")
    return Capital(
        float(equity),
        float(cash),
        min(modeled, float(equity)),
        known,
        {name: current[name] for name in sorted(retained)},
    )


# Validate retained paper accounting before using it in another account.
def recorded(record):
    if (record.get("targets") or {}).get("policy") != POLICY:
        return None
    receipt = ((record.get("paper") or {}).get("joint_funded") or {}).get(
        "receipt"
    ) or {}
    transition = receipt.get("transition")
    if transition is None:
        return None
    expected = {
        "policy",
        "observed_equity",
        "observed_cash",
        "modeled_equity",
        "modeled_fraction",
        "reserved_capital",
        "retained_weights",
        "risk_unavailable",
        "unknown_future_value_lower_bound",
        "sale_proceeds_are_funding",
    }
    if not isinstance(transition, dict) or set(transition) != expected:
        raise ValueError("Exact retained-capital receipt required")
    numeric = [
        transition[name]
        for name in (
            "observed_equity",
            "observed_cash",
            "modeled_equity",
            "modeled_fraction",
            "reserved_capital",
            "unknown_future_value_lower_bound",
        )
    ]
    weights = transition["retained_weights"]
    if (
        any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in numeric
        )
        or transition["observed_equity"] <= 0
        or transition["policy"] != POLICY
        or transition["unknown_future_value_lower_bound"] != 0
        or transition["sale_proceeds_are_funding"] is not False
        or not isinstance(weights, dict)
        or not isinstance(transition["risk_unavailable"], dict)
        or set(weights) != set(transition["risk_unavailable"])
        or any(
            not isinstance(risk, dict)
            or risk.get("status") != "unavailable"
            or risk.get("symbols") != [name]
            or risk.get("decision_date") != record.get("session")
            for name, risk in transition["risk_unavailable"].items()
        )
        or any(
            not isinstance(name, str)
            or not name
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 < value <= 1
            for name, value in weights.items()
        )
        or sum(weights.values()) > 1 + 1e-10
        or not math.isclose(
            transition["modeled_equity"] + transition["reserved_capital"],
            transition["observed_equity"],
            rel_tol=1e-10,
        )
        or not math.isclose(
            transition["modeled_fraction"],
            transition["modeled_equity"] / transition["observed_equity"],
            rel_tol=1e-10,
            abs_tol=1e-12,
        )
        or transition["modeled_equity"] < transition["observed_cash"]
        or transition["reserved_capital"] + 1e-10 * transition["observed_equity"]
        < sum(weights.values()) * transition["observed_equity"]
    ):
        raise ValueError("Invalid retained-capital accounting")
    return transition


# Rebase modeled weights onto the person's own capital, retaining only their own shares.
def personal_weights(boundary, weights, shares, prices, equity, cash):
    retained = set(boundary["retained_weights"])
    protected = (set(shares) - set(weights)) | (set(shares) & retained)
    current = {name: qty * prices[name] / equity for name, qty in shares.items()}
    if cash is None or boundary["modeled_fraction"] == 0:
        return {name: current.get(name, 0.0) for name in set(weights) | set(shares)}
    capital = partition(equity, cash, shares, prices, protected)
    factor = capital.modeled_equity / equity / boundary["modeled_fraction"]
    result = {
        name: float(value) * factor if name not in retained else current.get(name, 0.0)
        for name, value in weights.items()
    }
    result.update({name: current[name] for name in protected})
    if (
        any(value > 1 + 1e-10 for value in result.values())
        or sum(result.values()) > 1 + 1e-10
    ):
        raise ValueError("Personal modeled and retained targets exceed equity")
    return result
