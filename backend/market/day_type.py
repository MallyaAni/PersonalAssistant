"""Day type: can tomorrow's red day for the volatile book be seen today?

The operator's objective includes being in the volatile names on green days
and out of them before red ones. The desk's own learned brake (QQQ drawdown
within 20 sessions, `learned_policy.walk_forward_brake`) lost CAGR for the
drawdown it saved, and every market-timing line in the repo's history did
the same. So this module does not trade. It asks the narrower question the
gate needs answered first: does a calibrated probability of a large
down-move in the *book's own basket* over the next 1 or 5 sessions carry
any skill over climatology, out of sample, on 2016-2023? The kill criterion
is written here, before the first run: Brier skill below `SKILL_FLOOR` on
the choosing window means the day-type idea is recorded as insufficient
evidence and stays a banner at most.

What is predicted. The equal-weight point-in-time basket's forward return
over H sessions, from tomorrow's open (the first return a decision made at
today's close can earn) to the open H sessions later, below a threshold
that is itself set from the trailing distribution (the bottom `TAIL`
fraction of the past 250 basket returns of that horizon), so the label is
a bad day *for that regime*, not a fixed number that is rare in calm years
and common in wild ones.

What it sees. Only the close of day t and before: the basket's and the
index's recent returns and realised volatility at several horizons and
their ratios (a volatility-of-volatility regime read), how the index's
daily candle was built (close location in the range, range against its own
average, the overnight gap), breadth (share of members above their 20- and
50-session averages, share up on the day), the index's drawdown and
distance from its 250-session high, calendar structure (day of week,
sessions to and since an FOMC decision) and the regime analyst's context.
Everything is a trailing statistic that is NaN until its window is full.

How it is judged. A logistic model and a gradient-boosted model, refit
every `REFIT` sessions on rows whose labels matured before the fit,
scored out of sample on the rest, against climatology (the trailing base
rate) on Brier score. Brier skill = 1 - Brier / Brier_climatology. The
study also reports how an exposure scalar built from the probability
(scale to `1 - p` above the threshold) would have changed the basket's
CAGR and drawdown, purely as a diagnostic beside the insurance budget.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

HORIZONS = (1, 5)
TAIL = 0.10
TRAILING = 250
REFIT = 63
MIN_TRAIN = 750
SKILL_FLOOR = 0.02
FEATURE_NAMES: tuple[str, ...] = (
    "basket_ret_1", "basket_ret_5", "basket_ret_20",
    "index_ret_1", "index_ret_5", "index_ret_20",
    "basket_vol_5", "basket_vol_20", "basket_vol_60", "basket_vol_ratio_5_60",
    "index_vol_5", "index_vol_20", "index_vol_ratio_5_20",
    "index_close_location", "index_range_ratio", "index_gap",
    "breadth_above_20", "breadth_above_50", "breadth_up_today",
    "index_drawdown_250", "index_high_250_distance",
    "day_of_week", "sessions_to_fomc", "sessions_since_fomc",
    "regime_participation", "regime_correlation_z", "regime_novelty_z",
    "regime_exposure", "regime_tightening",
)


@dataclass(frozen=True)
class Study:
    """Inputs the walk-forward evaluation runs on, aligned per session."""

    dates: np.ndarray
    features: np.ndarray  # (T, F) known at the close of each session
    basket_open_return: dict[int, np.ndarray]  # horizon -> (T,) forward return, NaN if unknown
    labels: dict[int, np.ndarray]  # horizon -> (T,) 1.0 / 0.0 / NaN
    thresholds: dict[int, np.ndarray]


# Trailing standard deviation over `n` rows, NaN until the window is full.
def _trailing_std(values: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for t in range(n - 1, len(values)):
        block = values[t - n + 1 : t + 1]
        if np.isfinite(block).all():
            out[t] = float(block.std(ddof=1))
    return out


# Trailing sum over `n` rows, NaN until the window is full.
def _trailing_sum(values: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for t in range(n - 1, len(values)):
        block = values[t - n + 1 : t + 1]
        if np.isfinite(block).all():
            out[t] = float(block.sum())
    return out


# The equal-weight basket's daily log return across the names in `mask`
# (members with a price yesterday and today), NaN when none qualify.
def basket_returns(adj_close: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Return (T,) equal-weight close-to-close log returns of the masked book."""
    rows = len(adj_close)
    out = np.full(rows, np.nan)
    with np.errstate(all="ignore"):
        log = np.log(adj_close)
    for t in range(1, rows):
        ok = mask[t] & np.isfinite(log[t]) & np.isfinite(log[t - 1])
        if ok.any():
            out[t] = float((log[t, ok] - log[t - 1, ok]).mean())
    return out


# Forward open-to-open basket return over `h` sessions from a decision at
# the close of t: open[t+1] to open[t+1+h], equal weight over members at t.
def forward_open_returns(adj_open: np.ndarray, mask: np.ndarray, h: int) -> np.ndarray:
    """Return (T,) forward returns, NaN where the window is not complete."""
    rows = len(adj_open)
    out = np.full(rows, np.nan)
    with np.errstate(all="ignore"):
        log = np.log(adj_open)
    for t in range(rows - h - 1):
        ok = mask[t] & np.isfinite(log[t + 1]) & np.isfinite(log[t + 1 + h])
        if ok.any():
            out[t] = float((log[t + 1 + h, ok] - log[t + 1, ok]).mean())
    return out


# Labels: 1 when the forward return falls below the trailing `TAIL` quantile
# of the same horizon's past returns (known at t), 0 otherwise, NaN when
# either side is unknown. The threshold series is returned for the record.
def tail_labels(forward: np.ndarray, trailing: int = TRAILING, tail: float = TAIL):
    """Return (labels, thresholds), both (T,)."""
    rows = len(forward)
    labels = np.full(rows, np.nan)
    thresholds = np.full(rows, np.nan)
    for t in range(trailing, rows):
        # Past forward returns known by t: those that started at s with
        # s + h + 1 <= t, i.e. whose window has closed. Using rows
        # [t - trailing - h, t - h) is conservative for every h <= 20.
        past = forward[max(0, t - trailing - 21) : max(0, t - 21)]
        past = past[np.isfinite(past)]
        if len(past) < trailing // 2 or not np.isfinite(forward[t]):
            continue
        thresholds[t] = float(np.quantile(past, tail))
        labels[t] = float(forward[t] < thresholds[t])
    return labels, thresholds


# The per-session feature matrix from the panel's daily data, the book mask
# and the regime states; every column is a trailing statistic.
def features(panel, mask: np.ndarray, regime_states, fomc_ahead: np.ndarray, fomc_since: np.ndarray) -> np.ndarray:
    """Return the (T, F) matrix in FEATURE_NAMES order."""
    rows = len(panel.dates)
    bench = panel.index(panel.benchmark)
    basket = basket_returns(panel.adj_close, mask)
    with np.errstate(all="ignore"):
        index_log = np.log(panel.adj_close[:, bench])
        index_ret = np.r_[np.nan, np.diff(index_log)]
        basis = np.where(panel.close[:, bench] > 0, panel.adj_close[:, bench] / panel.close[:, bench], np.nan)
        high = panel.high[:, bench] * basis
        low = panel.low[:, bench] * basis
        open_ = panel.open[:, bench] * basis
        close = panel.adj_close[:, bench]
        rng = high - low
        location = np.where(rng > 0, (close - low) / rng, np.nan)
        range_ratio = rng / _trailing_sum(rng, 20) * 20
        gap = np.r_[np.nan, np.log(open_[1:] / close[:-1])]
        ma20 = np.full_like(panel.adj_close, np.nan)
        ma50 = np.full_like(panel.adj_close, np.nan)
        for t in range(49, rows):
            ma20[t] = panel.adj_close[t - 19 : t + 1].mean(axis=0)
            ma50[t] = panel.adj_close[t - 49 : t + 1].mean(axis=0)
        above20 = _breadth(panel.adj_close > ma20, mask)
        above50 = _breadth(panel.adj_close > ma50, mask)
        up = np.vstack([np.full((1, panel.adj_close.shape[1]), False), panel.adj_close[1:] > panel.adj_close[:-1]])
        up_today = _breadth(up, mask)
        drawdown = np.full(rows, np.nan)
        high250 = np.full(rows, np.nan)
        for t in range(249, rows):
            window = close[t - 249 : t + 1]
            if np.isfinite(window).all():
                drawdown[t] = window[-1] / window.max() - 1.0
                high250[t] = np.log(window[-1] / window.max())
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    weekday = ((days.astype("datetime64[D]").astype(int) + 3) % 7).astype(float)
    context = np.array(
        [
            [s.participation_percentile, s.correlation_z, s.novelty_z, s.exposure, float(s.tightening)]
            for s in regime_states
        ],
        dtype=float,
    )
    columns = [
        basket, _trailing_sum(basket, 5), _trailing_sum(basket, 20),
        index_ret, _trailing_sum(index_ret, 5), _trailing_sum(index_ret, 20),
        _trailing_std(basket, 5), _trailing_std(basket, 20), _trailing_std(basket, 60),
        _trailing_std(basket, 5) / _trailing_std(basket, 60),
        _trailing_std(index_ret, 5), _trailing_std(index_ret, 20),
        _trailing_std(index_ret, 5) / _trailing_std(index_ret, 20),
        location, range_ratio, gap,
        above20, above50, up_today,
        drawdown, high250,
        weekday, np.asarray(fomc_ahead, dtype=float), np.asarray(fomc_since, dtype=float),
        context[:, 0], context[:, 1], context[:, 2], context[:, 3], context[:, 4],
    ]
    out = np.column_stack(columns)
    assert out.shape[1] == len(FEATURE_NAMES)
    return out


# Share of members for which `condition` holds on each session.
def _breadth(condition: np.ndarray, mask: np.ndarray) -> np.ndarray:
    count = mask.sum(axis=1).astype(float)
    with np.errstate(all="ignore"):
        return np.where(count > 0, (condition & mask).sum(axis=1) / count, np.nan)


# Assemble the study from a restricted report and its mask.
def build(report, mask: np.ndarray, fomc_ahead: np.ndarray, fomc_since: np.ndarray) -> Study:
    """Return the Study for the point-in-time book."""
    from backend.agents.trading.desk import simulate

    panel = report.panel
    opens = simulate.adjusted_open(panel)
    book = mask.copy()
    book[:, panel.index(panel.benchmark)] = False
    x = features(panel, book, report.regime.states, fomc_ahead, fomc_since)
    forward = {h: forward_open_returns(opens, book, h) for h in HORIZONS}
    labels, thresholds = {}, {}
    for h in HORIZONS:
        labels[h], thresholds[h] = tail_labels(forward[h])
    return Study(panel.dates, x, forward, labels, thresholds)


@dataclass(frozen=True)
class Verdict:
    """Out-of-sample probabilities and their skill for one horizon and model."""

    horizon: int
    model: str
    probability: np.ndarray  # (T,) NaN before the first fit
    climatology: np.ndarray  # (T,) trailing base rate
    brier: float
    brier_climatology: float
    skill: float
    sessions: int


# Walk-forward probabilities: refit every REFIT sessions on rows whose
# labels matured before the fit session (purge of horizon + 21, the label's
# own look-back), scored on the next block. `model` is "logistic" or "hgb".
def walk_forward(study: Study, horizon: int, model: str = "logistic", window=None) -> Verdict:
    """Return the Verdict for `horizon` under `model`, scored inside `window` if given."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    y = study.labels[horizon]
    x = study.features
    rows = len(y)
    prob = np.full(rows, np.nan)
    clim = np.full(rows, np.nan)
    purge = horizon + 22
    for start in range(MIN_TRAIN, rows, REFIT):
        end = min(start + REFIT, rows)
        train = np.arange(0, start - purge)
        ok = train[np.isfinite(y[train]) & np.isfinite(x[train]).all(axis=1)]
        if len(ok) < MIN_TRAIN // 2 or len(np.unique(y[ok])) < 2:
            continue
        if model == "logistic":
            mean = x[ok].mean(axis=0)
            scale = x[ok].std(axis=0)
            scale[scale == 0] = 1.0
            fit = LogisticRegression(C=0.1, max_iter=500).fit((x[ok] - mean) / scale, y[ok])
            predict = lambda block: fit.predict_proba((block - mean) / scale)[:, 1]  # noqa: E731
        elif model == "hgb":
            # A rare label on about a thousand rows: shallow trees, few of
            # them, big leaves and an L2 penalty, or the model learns the
            # training years' accidents.
            fit = HistGradientBoostingClassifier(
                max_iter=60, learning_rate=0.05, max_leaf_nodes=7,
                min_samples_leaf=100, l2_regularization=1.0,
                early_stopping=False, random_state=0,
            ).fit(x[ok], y[ok])
            predict = lambda block: fit.predict_proba(block)[:, 1]  # noqa: E731
        else:
            raise ValueError(f"unknown model {model!r}")
        block = np.arange(start, end)
        usable = block[np.isfinite(x[block]).all(axis=1)]
        if len(usable):
            prob[usable] = predict(x[usable])
        clim[block] = float(y[ok].mean())
    scored = np.isfinite(prob) & np.isfinite(y) & np.isfinite(clim)
    if window is not None:
        scored &= window
    if scored.sum() < 2:
        return Verdict(horizon, model, prob, clim, math.nan, math.nan, math.nan, int(scored.sum()))
    brier = float(np.mean((prob[scored] - y[scored]) ** 2))
    base = float(np.mean((clim[scored] - y[scored]) ** 2))
    skill = 1.0 - brier / base if base > 0 else math.nan
    return Verdict(horizon, model, prob, clim, brier, base, skill, int(scored.sum()))


# The diagnostic beside the budget: scale exposure to 1 - p whenever p is
# above the climatology, hold the basket otherwise, and compare CAGR and
# drawdown with always invested. Returns (cagr_scaled, cagr_always,
# drawdown_scaled, drawdown_always) over the scored sessions.
def exposure_diagnostic(study: Study, verdict: Verdict, window=None) -> dict[str, float]:
    """Return the CAGR and drawdown of the scaled and the always-invested basket."""
    r = study.basket_open_return[1]
    p = verdict.probability
    ok = np.isfinite(r) & np.isfinite(p) & np.isfinite(verdict.climatology)
    if window is not None:
        ok &= window
    if ok.sum() < 2:
        return {k: math.nan for k in ("cagr_scaled", "cagr_always", "drawdown_scaled", "drawdown_always")}
    scale = np.where(p[ok] > verdict.climatology[ok], 1.0 - p[ok], 1.0)
    always = np.expm1(r[ok])
    scaled = scale * always
    out = {}
    for name, series in (("scaled", scaled), ("always", always)):
        curve = np.cumprod(1.0 + series)
        out[f"cagr_{name}"] = float(curve[-1] ** (252.0 / len(series)) - 1.0)
        out[f"drawdown_{name}"] = float((curve / np.maximum.accumulate(curve) - 1.0).min())
    return out
