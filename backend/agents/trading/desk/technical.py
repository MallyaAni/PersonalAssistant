"""The technical analyst: what the tape says.

Two things measured on the AI-and-software names beta-adjusted: slow
momentum (120 sessions, skipping the latest month) is positive at one to
three months, and stretch above the 21-day EMA fades over the next weeks.
The EMA structure the operator reads by eye (stack, slopes, 21/50
convergence, weekly EMAs, 52-week distance) measured nothing on its own on
this universe, so it is cited as context rather than scored.
"""

from backend.agents.trading.desk.opinions import Opinion
from backend.market import baselines, technical
from backend.market.panel import Panel

NAME = "technical"
MOMENTUM_SESSIONS = 120
MOMENTUM_SKIP = 21
CITED = (
    "ema21_distance",
    "ema50_distance",
    "ema200_distance",
    "sma200_distance",
    "ema21_slope",
    "ema50_slope",
    "stack_order",
    "spread_21_50",
    "spread_21_50_slope",
    "converging_21_50",
    "weekly_stack",
    "high_52w_distance",
    "low_52w_distance",
)


# Score every name from slow momentum and the 21-EMA fade; cite the rest.
def opine(panel: Panel) -> Opinion:
    """Return the technical analyst's Opinion for the panel."""
    feats = technical.technical_features(panel)
    idx = {n: i for i, n in enumerate(technical.TECHNICAL_NAMES)}
    momentum = baselines.momentum(panel, MOMENTUM_SESSIONS, MOMENTUM_SKIP)
    stretch = feats[:, :, idx["ema21_distance"]].astype(float)
    scores = baselines.rank_blend(momentum, -stretch)
    evidence = {n: feats[:, :, idx[n]].astype(float) for n in CITED}
    evidence["momentum_120"] = momentum
    return Opinion(NAME, scores, evidence)
