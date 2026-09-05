"""The technical analyst: what the tape says, given where the theme is.

Measured on the AI-and-software names, beta-adjusted, 20 sessions, over
2015-2026 and split by the AI basket's own 60-session trend:

* Basket falling: stretch above the 21-day EMA fades (IC +0.082, t 2.5)
  and slow momentum (120 sessions skipping the latest month) holds
  (+0.055). Nothing to buy for strength.
* Basket rising: the fade is worth nothing (-0.006) and proximity to the
  52-week high pays (+0.042, t 2.3); momentum still holds (+0.020).

So the analyst has two playbooks and the regime analyst's basket trend
picks one per session: fade stretch in a falling theme, buy strength in
a rising one, momentum in both. Without a trend series it falls back to
momentum plus the fade, which is the falling-theme playbook.

The EMA reads the operator uses by eye (21 and 50 slopes, the stack, the
21/50 convergence) measured nothing over the decade and paid only in the
low-correlation regime of 2026 (35 windows, t 2.0). They are cited as
evidence, not scored, until that regime has enough history to judge.
"""

import numpy as np

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


# Score every name by the playbook the theme's trend selects; cite the rest.
def opine(panel: Panel, ai_trend: np.ndarray | None = None) -> Opinion:
    """Return the technical analyst's Opinion for the panel."""
    feats = technical.technical_features(panel)
    idx = {n: i for i, n in enumerate(technical.TECHNICAL_NAMES)}
    momentum = baselines.momentum(panel, MOMENTUM_SESSIONS, MOMENTUM_SKIP)
    stretch = feats[:, :, idx["ema21_distance"]].astype(float)
    near_high = feats[:, :, idx["high_52w_distance"]].astype(float)
    falling = baselines.rank_blend(momentum, -stretch)
    if ai_trend is None:
        scores = falling
    else:
        rising = baselines.rank_blend(momentum, near_high)
        up = np.isfinite(ai_trend) & (ai_trend > 0)
        scores = np.where(up[:, None], rising, falling)
    evidence = {n: feats[:, :, idx[n]].astype(float) for n in CITED}
    evidence["momentum_120"] = momentum
    return Opinion(NAME, scores, evidence)
