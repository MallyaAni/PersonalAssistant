"""The technical analyst: where price sits, and whether the timeframes agree.

Measured on the AI-and-software names, beta-adjusted, 20 sessions, among
names that already qualify on fundamentals and release tone (the trade
the desk actually takes):

* Weekly trend up (close above a rising weekly 21 EMA): +1.0% against
  -2.0% when the weekly trend is flat (t 4.2). Daily trend up (21 EMA
  above the 50 and rising): +0.9% (t 3.3). Multi-timeframe agreement is
  the strongest location fact.
* Strength beats dips: the top of the 60-session range +1.3% (t 3.7, hit
  0.56), the bottom -0.5%. Slow momentum (120 sessions skipping the latest
  month) holds in every regime.
* Stretch is the risk term: more than 15% above the nearest support earns
  nothing and carries the worst drawdown inside the window (-12%); at
  support the drawdown is -7.6%. Support proximity cuts adverse excursion
  without raising the return, so it enters as the negative of stretch.
* Reward-to-risk from swing levels inverts on these names (resistance
  close overhead means breakout, not rejection), so it is cited, not
  scored. The 21/50 convergence, candles and buying near the 200 EMA
  measured nothing or lost in every regime.

The regime analyst's basket trend still picks the weight of the fade:
while the AI basket falls the stretch fade is the best single leg (+0.082,
t 2.5); while it rises it is worth nothing, and the range position takes
its place.
"""

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.market import baselines, levels, technical
from backend.market.panel import Panel

NAME = "technical"
MOMENTUM_SESSIONS = 120
MOMENTUM_SKIP = 21
LOCATION_CITED = (
    "support_distance",
    "resistance_distance",
    "reward_risk",
    "range_position_60",
    "weekly_trend",
    "daily_trend",
    "confluence",
)
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
    loc = levels.level_features(panel)
    lidx = {n: i for i, n in enumerate(levels.LEVEL_NAMES)}
    momentum = baselines.momentum(panel, MOMENTUM_SESSIONS, MOMENTUM_SKIP)
    weekly = loc[:, :, lidx["weekly_trend"]]
    daily = loc[:, :, lidx["daily_trend"]]
    range_position = loc[:, :, lidx["range_position_60"]]
    stretch = loc[:, :, lidx["support_distance"]]
    # A name below every level has nothing under it to stretch from.
    stretch = np.where(
        np.isfinite(stretch) | ~np.isfinite(panel.adj_close), stretch, 0.0
    )
    # Falling theme: the stretch fade is the best leg and joins the trends.
    falling = baselines.rank_blend(weekly, daily, momentum, -stretch)
    if ai_trend is None:
        scores = falling
    else:
        # Rising theme: strength in the range replaces the fade.
        rising = baselines.rank_blend(weekly, daily, momentum, range_position)
        up = np.isfinite(ai_trend) & (ai_trend > 0)
        scores = np.where(up[:, None], rising, falling)
    evidence = {n: feats[:, :, idx[n]].astype(float) for n in CITED}
    evidence.update({n: loc[:, :, lidx[n]] for n in LOCATION_CITED})
    evidence["momentum_120"] = momentum
    return Opinion(NAME, scores, evidence)
