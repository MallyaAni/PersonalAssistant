"""Forward-only, cash-funded target tracking from archived research decisions.

This compares target trackers, not the full scheduled strategy with its exits.
An allocation is filled only at a later observed candle, after it was recorded.
"""

import math
from datetime import datetime, timedelta

ARMS = ("baseline_targets", "technical_targets", "targets")


# Reject malformed weights before any simulated account changes.
def validate_weights(weights: dict) -> None:
    if (
        any(not math.isfinite(w) or w < 0 for w in weights.values())
        or sum(weights.values()) > 1.000001
    ):
        raise ValueError("Invalid funded target weights")


# Compare funded accounts using prices observed after each recommendation.
def evaluate(decisions: list[dict], cost_bps: float = 10) -> dict:
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 100:
        raise ValueError("Cost must be between zero and 100 basis points")
    decisions = sorted(decisions, key=lambda row: row["bar"])
    if len({row["bar"] for row in decisions}) != len(decisions):
        raise ValueError("Duplicate decision bars")
    accounts = {
        arm: {
            "cash": 100000.0,
            "shares": {},
            "peak": 100000.0,
            "drawdown": 0.0,
            "traded": 0.0,
            "equity": 100000.0,
        }
        for arm in ARMS
    }
    fills = 0
    for previous, current in zip(decisions, decisions[1:], strict=False):
        fill_time = datetime.fromisoformat(current["bar"]) + timedelta(minutes=15)
        if fill_time <= datetime.fromisoformat(
            previous["as_of"]
        ) or datetime.fromisoformat(current["bar"]) > datetime.fromisoformat(
            previous["valid_until"]
        ):
            continue
        prices = current["prices"]
        needed = set().union(
            *(previous[arm] for arm in ARMS),
            *(account["shares"] for account in accounts.values()),
        )
        if any(
            name not in prices or not math.isfinite(prices[name]) or prices[name] <= 0
            for name in needed
        ):
            raise ValueError("Missing next-candle valuation; comparison withheld")
        for arm, account in accounts.items():
            shares = account["shares"]
            equity = account["cash"] + sum(
                qty * prices[name] for name, qty in shares.items()
            )
            weights = previous[arm]
            validate_weights(weights)
            if not previous.get("event_paused"):
                targets = {
                    name: math.floor(equity * weights.get(name, 0) / prices[name])
                    for name in needed
                }
                for name in sorted(needed):
                    sold = max(0, shares.get(name, 0) - targets[name])
                    account["cash"] += sold * prices[name] * (1 - cost_bps / 10000)
                    account["traded"] += sold * prices[name]
                    shares[name] = shares.get(name, 0) - sold
                wanted = {name: max(0, targets[name] - shares[name]) for name in needed}
                requested = sum(
                    qty * prices[name] * (1 + cost_bps / 10000)
                    for name, qty in wanted.items()
                )
                scale = min(1, account["cash"] / requested) if requested else 0
                for name in sorted(needed):
                    bought = math.floor(wanted[name] * scale)
                    account["cash"] -= bought * prices[name] * (1 + cost_bps / 10000)
                    account["traded"] += bought * prices[name]
                    shares[name] += bought
            account["equity"] = account["cash"] + sum(
                qty * prices[name] for name, qty in shares.items()
            )
            account["peak"] = max(account["peak"], account["equity"])
            account["drawdown"] = min(
                account["drawdown"], account["equity"] / account["peak"] - 1
            )
        fills += 1
    return {
        "status": "observations_available"
        if fills >= 2
        else "insufficient_forward_data",
        "decision_count": len(decisions),
        "fill_intervals": fills,
        "cost_bps": cost_bps,
        "limitation": "Target trackers only; not the full scheduled strategy. "
        "No automatic promotion.",
        "arms": {
            arm: {
                "return": account["equity"] / 100000 - 1,
                "drawdown": account["drawdown"],
                "cash": account["cash"],
                "traded_dollars": account["traded"],
            }
            for arm, account in accounts.items()
        },
    }
