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
# Which measure plays the stretch role while the theme falls. "support" is
# the original nearest-swing-low distance, which sawtooths as levels drop in
# and out; "signed" keeps the level through the crossing; "band" is the
# close's position in its own twenty-session band; "none" drops the leg.
#
# Measured over 2018-06 to 2026-09 through the desk's own harness before
# adoption, and "support" lost on every dimension that matters:
#
#   leg        CAGR    Sharpe   max DD   quiet-session flips > 40 pts
#   support   26.70%    1.448  -21.98%   14.6%   <- the shipped sawtooth
#   signed    27.07%    1.470  -19.02%   10.8%   <- adopted
#   band      26.07%    1.407  -20.42%    2.6%
#   none      27.83%    1.493  -20.59%   -
#
# "none" edges the return and the Sharpe, but by a margin well inside the
# noise of eight years, and dropping the leg would leave the desk with no
# mean-reversion reading at all: a name resting on support below its
# averages would be scored on trend alone forever. "signed" fixes the
# discontinuity, takes the best drawdown of the four, and keeps that read.
# See docs/research/stretch-leg-2026-09-18.md.
STRETCH_LEG = "signed"
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


# A name the stretch measure cannot read takes the session's largest value,
# because having no level beneath you is the stretched end of the scale
# rather than the supported end. A session where nothing is finite stays at
# zero rather than warning, and a name with no price at all keeps its NaN so
# it is absent from the cross-section instead of ranking in it.
def _fill_with_the_most_stretched(
    measure: np.ndarray, close: np.ndarray
) -> np.ndarray:
    """Return `measure` with unreadable names set to the session's largest."""
    with np.errstate(all="ignore"):
        worst = np.max(np.where(np.isfinite(measure), measure, -np.inf), axis=1)
    worst = np.where(np.isfinite(worst), worst, 0.0)
    return np.where(
        np.isfinite(measure) | ~np.isfinite(close), measure, worst[:, None]
    )


# Score every name by the playbook the theme's trend selects; cite the rest.
def opine(panel: Panel, ai_trend: np.ndarray | None = None) -> Opinion:
    """Return the technical analyst's Opinion for the panel."""
    feats = technical.technical_features(panel)
    idx = {n: i for i, n in enumerate(technical.TECHNICAL_NAMES)}
    loc = levels.level_features(panel)
    lidx = {n: i for i, n in enumerate(levels.LEVEL_NAMES)}
    momentum = baselines.residual_momentum(panel, MOMENTUM_SESSIONS, MOMENTUM_SKIP)
    weekly = loc[:, :, lidx["weekly_trend"]]
    daily = loc[:, :, lidx["daily_trend"]]
    range_position = loc[:, :, lidx["range_position_60"]]
    # Falling theme: the stretch fade is the best leg and joins the trends.
    # Whichever measure plays that role, a name it cannot read has nothing
    # under it and is the most stretched name of the session, not the
    # least, so it takes the session's largest value rather than dropping
    # out of the blend. `support_distance` floors on the 50, 200 and weekly
    # 21 averages as well as the swing lows, so it is rarely absent;
    # `support_gap` reads swing lows alone, so a name that has climbed for
    # a year without printing one is absent every session and would score
    # on three legs while the rest of the book scored on four.
    stretch = _fill_with_the_most_stretched(
        loc[:, :, lidx["support_distance"]], panel.adj_close
    )
    if STRETCH_LEG == "signed":
        fade = -_fill_with_the_most_stretched(
            loc[:, :, lidx["support_gap"]], panel.adj_close
        )
    elif STRETCH_LEG == "band":
        fade = -_fill_with_the_most_stretched(
            loc[:, :, lidx["band_position"]], panel.adj_close
        )
    else:
        fade = -stretch
    falling = (
        baselines.rank_blend(weekly, daily, momentum)
        if STRETCH_LEG == "none"
        else baselines.rank_blend(weekly, daily, momentum, fade)
    )
    if ai_trend is None:
        scores = falling
    else:
        # Rising theme: strength in the range replaces the fade.
        rising = baselines.rank_blend(weekly, daily, momentum, range_position)
        up = np.isfinite(ai_trend) & (ai_trend > 0)
        scores = np.where(up[:, None], rising, falling)
    # The benchmark is the yardstick, never a candidate: residual momentum
    # against itself is float noise that ranked it top of the book.
    if panel.benchmark in panel.tickers:
        scores = np.array(scores, dtype=float, copy=True)
        scores[:, panel.index(panel.benchmark)] = np.nan
    evidence = {n: feats[:, :, idx[n]].astype(float) for n in CITED}
    evidence.update({n: loc[:, :, lidx[n]] for n in LOCATION_CITED})
    evidence["residual_momentum_120"] = momentum
    # What the nearest support and resistance are, so a read can name them
    # as a swing point or an average rather than only a distance.
    support_level, support_kind, resistance_level, resistance_kind = (
        levels.level_identity(panel)
    )
    evidence["support_level"] = support_level
    evidence["support_kind"] = support_kind
    evidence["resistance_level"] = resistance_level
    evidence["resistance_kind"] = resistance_kind
    return Opinion(NAME, scores, evidence)
