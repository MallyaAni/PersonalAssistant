"""The requested research objective: maximize net compounded account wealth."""

import math

VERSION = "net-compounded-growth/1"


# Reward net portfolio NAV without a volatility divisor or a second fee charge.
def reward(previous_equity, next_equity):
    if not all(math.isfinite(v) and v > 0 for v in (previous_equity, next_equity)):
        raise ValueError("Positive finite, flow-adjusted net equity required")
    return math.log(next_equity / previous_equity)


# Report the same terminal wealth objective with drawdown as a separate diagnostic.
def evaluate(equities):
    if len(equities) < 2:
        raise ValueError("At least two validated net equity observations required")
    rewards = [reward(a, b) for a, b in zip(equities[:-1], equities[1:], strict=True)]
    peak = equities[0]
    drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    return {
        "objective": VERSION,
        "log_growth": sum(rewards),
        "total_return": equities[-1] / equities[0] - 1,
        "drawdown": drawdown,
        "terminal_equity": equities[-1],
        "transitions": len(rewards),
    }
