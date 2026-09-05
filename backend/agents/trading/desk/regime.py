"""The regime analyst: what kind of market this is, and whether it has
changed shape.

Three things it measures every session, from the book's own names:

* Participation: the AI basket's dollar volume against its own trailing
  year. Measured on the book, beta-adjusted: the release-tone and rotation
  signals pay only when participation is above its historical median (tone
  IC 0.033 vs -0.004; rotation 0.086 vs -0.007). After the top quintile of
  participation the AI basket lags the market by about 1.2% over the next
  20 sessions. So participation sets how far to trust the selection and
  how much market to carry.
* Rotation: which side, AI or software, has led over the last 60 sessions.
  Following the leader measured positive (IC 0.040 at 20 sessions) and is
  what pays when participation is high.
* Novelty: how far the current co-movement between the theme baskets sits
  from its own history. The 2026 inversion between software and AI is the
  example: the two baskets had a residual correlation near +0.35 for a
  decade and -0.5 this year. A pattern nobody named yet shows up here as a
  distance, which is the point: the desk is told the map changed before
  anyone knows what the new map is.

Calendar and macro facts (FOMC distance, expiry days, VIX) are reported as
context. None of them changes a size: the measured calendar effects are
one-day and the volatility target already answers a rising VIX.
"""

from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk.opinions import Opinion
from backend.market import baselines
from backend.market.panel import Panel
from backend.market.universe import AI_SIDE, SOFTWARE_SIDE, THEMES

NAME = "regime"
PARTICIPATION_SHORT = 20
PARTICIPATION_LONG = 250
ROTATION_SESSIONS = 60
CORRELATION_SESSIONS = 60
# Novelty compares the current correlation window with non-overlapping
# past windows; it needs this many of them before it has an opinion.
MIN_HISTORY_WINDOWS = 6
# History for the participation percentiles: the trailing two years.
HISTORY_SESSIONS = 500
LOW_CONFIDENCE = 0.5
HYPE_EXPOSURE = 0.75


@dataclass(frozen=True)
class RegimeState:
    """The regime on one session, and what the desk does about it."""

    ai_participation: float
    software_participation: float
    participation_percentile: float
    ai_vs_software_correlation: float
    correlation_z: float
    novelty_z: float
    rotation_leader: str
    rotation_spread: float
    ai_drawdown: float
    # How far to trust the analysts' selection this session (0.5 or 1).
    selection_confidence: float
    # How much of the sized book to carry (0.75 in a hype phase, else 1).
    exposure: float
    flags: tuple[str, ...]
    # The AI basket's own 60-session log return (with the market): the
    # technical analyst switches playbook on its sign.
    ai_trend_60: float = float("nan")


@dataclass(frozen=True)
class RegimeView:
    """Per-session regime states plus the rotation opinion."""

    states: list[RegimeState]
    rotation: Opinion
    # (T,) the AI basket's trailing 60-session return, for the technical
    # analyst's switch.
    ai_trend: np.ndarray | None = None

    # The state on the last session.
    def today(self) -> RegimeState:
        """Return the latest session's RegimeState."""
        return self.states[-1]


# Equal-weight daily log return of the names in `mask`, minus the benchmark.
def residual_basket(panel: Panel, mask: np.ndarray) -> np.ndarray:
    """Return (T,) residual basket returns for the masked columns."""
    rets = panel.log_returns()
    bench = panel.benchmark_returns()
    bench = np.where(np.isfinite(bench), bench, 0.0)
    block = rets[:, mask]
    known = np.isfinite(block)
    if not mask.any():
        return np.zeros(len(panel.dates))
    total = np.where(known, block, 0.0).sum(axis=1)
    return total / np.maximum(known.sum(axis=1), 1) - bench


# Trailing mean over `n` sessions, NaN-aware, per column.
def _trailing_mean(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    for t in range(n - 1, len(x)):
        window = x[t - n + 1 : t + 1]
        with np.errstate(all="ignore"):
            out[t] = np.nanmean(window, axis=0)
    return out


# Each name's log dollar volume over the last 20 sessions against its last
# 250: above zero means more money is moving through it than usual.
def participation(panel: Panel) -> np.ndarray:
    """Return (T, N) volume-trend per name."""
    volume = np.where(panel.volume > 0, panel.volume, np.nan)
    dollar = np.log(volume * panel.close)
    return _trailing_mean(dollar, PARTICIPATION_SHORT) - _trailing_mean(
        dollar, PARTICIPATION_LONG
    )


# The rank of the latest value within the trailing history, in [0, 1].
def _trailing_percentile(x: np.ndarray, t: int, history: int) -> float:
    past = x[max(0, t - history) : t]
    past = past[np.isfinite(past)]
    if len(past) < 20 or not np.isfinite(x[t]):
        return float("nan")
    return float((past < x[t]).mean())


# Rolling correlation between two series over `n` sessions ending at t-1.
def _rolling_corr(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(a), np.nan)
    for t in range(n, len(a)):
        x, y = a[t - n : t], b[t - n : t]
        if x.std() > 0 and y.std() > 0:
            out[t] = float(np.corrcoef(x, y)[0, 1])
    return out


# The theme baskets' pairwise correlations over a window, as one vector.
def _structure(baskets: np.ndarray, start: int, stop: int) -> np.ndarray:
    block = baskets[start:stop]
    k = block.shape[1]
    with np.errstate(all="ignore"):
        corr = np.corrcoef(block.T)
    corr = np.where(np.isfinite(corr), corr, 0.0)
    return corr[np.triu_indices(k, 1)]


# How far this session's co-movement structure sits from the history of
# non-overlapping past windows, as a z-score of the distance; NaN until
# there are enough windows. Reads only sessions before t.
def novelty(baskets: np.ndarray, window: int = CORRELATION_SESSIONS) -> np.ndarray:
    """Return (T,) novelty z-scores of the correlation structure."""
    count = baskets.shape[0]
    out = np.full(count, np.nan)
    if baskets.shape[1] < 2:
        return out
    ends = list(range(window, count, window))
    past = [_structure(baskets, e - window, e) for e in ends]
    for t in range(window, count):
        usable = [s for e, s in zip(ends, past, strict=True) if e <= t - window]
        if len(usable) < MIN_HISTORY_WINDOWS:
            continue
        history = np.stack(usable)
        mean = history.mean(axis=0)
        distances = np.linalg.norm(history - mean, axis=1)
        current = np.linalg.norm(_structure(baskets, t - window, t) - mean)
        spread = distances.std()
        if spread > 0:
            out[t] = float((current - distances.mean()) / spread)
    return out


# Run the regime analyst over the panel for the names in `sides`.
def opine(panel: Panel, sides: dict[str, str]) -> RegimeView:
    """Return the RegimeView: per-session states and the rotation Opinion."""
    count = len(panel.dates)
    is_ai = np.array([sides.get(t) == AI_SIDE for t in panel.tickers])
    is_sw = np.array([sides.get(t) == SOFTWARE_SIDE for t in panel.tickers])
    ai = residual_basket(panel, is_ai)
    sw = residual_basket(panel, is_sw)
    part = participation(panel)
    with np.errstate(all="ignore"):
        ai_part = np.nanmedian(np.where(is_ai[None, :], part, np.nan), axis=1)
        sw_part = np.nanmedian(np.where(is_sw[None, :], part, np.nan), axis=1)
    corr = _rolling_corr(ai, sw, CORRELATION_SESSIONS)
    spread = (
        baselines.trailing_sum(ai[:, None], ROTATION_SESSIONS)[:, 0]
        - baselines.trailing_sum(sw[:, None], ROTATION_SESSIONS)[:, 0]
    )
    theme_masks = [
        np.array([theme in panel.themes.get(t, ()) for t in panel.tickers])
        for theme in THEMES
    ]
    baskets = np.stack(
        [residual_basket(panel, m) for m in theme_masks if m.any()], axis=1
    )
    nov = novelty(baskets)
    bench = panel.benchmark_returns()
    bench = np.where(np.isfinite(bench), bench, 0.0)
    cum = np.cumsum(ai + bench)
    ai_trend = baselines.trailing_sum((ai + bench)[:, None], ROTATION_SESSIONS)[:, 0]
    drawdown = np.array(
        [
            cum[t] - cum[max(0, t - PARTICIPATION_LONG) : t + 1].max()
            for t in range(count)
        ]
    )
    side = np.where(is_ai, 1.0, np.where(is_sw, -1.0, np.nan))
    rotation_scores = spread[:, None] * side[None, :]
    states: list[RegimeState] = []
    for t in range(count):
        pct = _trailing_percentile(ai_part, t, HISTORY_SESSIONS)
        corr_z = _z_within(corr, t)
        flags: list[str] = []
        confidence = 1.0
        exposure = 1.0
        if np.isfinite(pct) and pct < 0.5:
            confidence = LOW_CONFIDENCE
            flags.append("participation below its two-year median")
        if np.isfinite(pct) and pct >= 0.8:
            exposure = HYPE_EXPOSURE
            flags.append("participation in its top quintile (hype)")
        if np.isfinite(corr_z) and abs(corr_z) >= 2.0:
            flags.append("AI-vs-software co-movement far from its history")
        if np.isfinite(nov[t]) and nov[t] >= 2.0:
            flags.append("theme co-movement structure has changed shape")
        if np.isfinite(drawdown[t]) and drawdown[t] <= -0.25:
            flags.append("AI basket more than 25% off its yearly high")
        if not np.isfinite(pct):
            confidence = LOW_CONFIDENCE
            flags.append("not enough history to judge participation")
        # Rotation only pays when the crowd is present.
        if confidence < 1.0:
            rotation_scores[t] = np.nan
        leader = "ai" if spread[t] > 0 else "software"
        if not np.isfinite(spread[t]):
            leader = "unknown"
        states.append(
            RegimeState(
                ai_participation=float(ai_part[t]),
                software_participation=float(sw_part[t]),
                participation_percentile=pct,
                ai_vs_software_correlation=float(corr[t]),
                correlation_z=corr_z,
                novelty_z=float(nov[t]),
                rotation_leader=leader,
                rotation_spread=float(spread[t]),
                ai_drawdown=float(drawdown[t]),
                selection_confidence=confidence,
                exposure=exposure,
                flags=tuple(flags),
                ai_trend_60=float(ai_trend[t]),
            )
        )
    rotation = Opinion(
        "rotation", rotation_scores, {"rotation_spread_60": rotation_scores}
    )
    return RegimeView(states, rotation, ai_trend)


# z-score of x[t] against the finite values of x before t (at least a year).
def _z_within(x: np.ndarray, t: int) -> float:
    past = x[:t]
    past = past[np.isfinite(past)]
    if len(past) < PARTICIPATION_LONG or not np.isfinite(x[t]):
        return float("nan")
    spread = past.std()
    if spread == 0:
        return float("nan")
    return float((x[t] - past.mean()) / spread)
