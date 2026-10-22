"""Restrict a desk report to the names the book could have held on each session.

`desk.run` grades the book as it stands today over the whole history, so a
backtest on its report holds names the desk could not have known about:
2024-25 listings, this year's overlay, names chosen because they won. This
module applies the dated membership history (`universe.as_of`) to a report:
on every session, a name outside its membership interval is graded C and
given no score, so the rules cannot select it, size it or rank it. Nothing
else about the report changes, and the panel keeps every column, so prices
and benchmarks line up exactly with the unrestricted run.

The masked report is what a point-in-time backtest runs on, and the same
mask defines the equal-weight book that is the survivorship hurdle.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk.grading import ORDINAL, C
from backend.market import membership, universe


# (T, N) True where the name was a book member on the session, from the
# dated intervals. A name with no interval at all is never eligible.
def eligibility(
    dates: np.ndarray,
    tickers: tuple[str, ...],
    history_path: Path = universe.MEMBERSHIP_HISTORY_PATH,
) -> np.ndarray:
    """Return the (T, N) Boolean membership mask."""
    records = membership.load_history(history_path)
    days = np.asarray(dates, dtype="datetime64[D]")
    mask = np.zeros((len(days), len(tickers)), dtype=bool)
    column = {t: i for i, t in enumerate(tickers)}
    for row in records:
        j = column.get(row.ticker)
        if j is None:
            continue
        start = np.datetime64(max(row.entered, row.entry_announced), "D")
        lo = int(np.searchsorted(days, start, side="left"))
        hi = len(days)
        if row.exited is not None:
            hi = int(np.searchsorted(days, np.datetime64(row.exited, "D"), side="left"))
        if lo < hi:
            mask[lo:hi, j] = True
    return mask


# The report with every non-member (session, name) graded C and unscored.
def restrict(report, mask: np.ndarray):
    """Return a copy of `report` restricted to `mask`; the panel is untouched."""
    graded = report.graded
    if mask.shape != graded.grades.shape:
        raise ValueError("mask must match the report's (T, N) shape")
    grades = np.where(mask, graded.grades, ORDINAL[C])
    conviction = None
    if graded.conviction is not None:
        conviction = np.where(mask, graded.conviction, np.nan)
    scores = np.where(mask, report.scores, np.nan)
    restricted = replace(graded, grades=grades, conviction=conviction)
    return replace(report, graded=restricted, scores=scores)


# One call: mask from the history, then restrict.
def point_in_time(report, history_path: Path = universe.MEMBERSHIP_HISTORY_PATH):
    """Return (restricted report, mask)."""
    mask = eligibility(report.panel.dates, tuple(report.panel.tickers), history_path)
    benchmark = report.panel.index(report.panel.benchmark)
    mask[:, benchmark] = False
    return restrict(report, mask), mask


# An allocator for `simulate.run(allocator=...)`: equal weight across every
# member of the book on the decision session, the benchmark excluded, at
# `gross` of equity. It reads only the mask at `t`, so it cannot see the
# future through the unsliced panel the hook receives.
def equal_weight_allocator(mask: np.ndarray, gross: float = 1.0):
    """Return a callable (report, panel, config, t) -> target weights."""

    def allocate(report, panel, config, t: int) -> np.ndarray:
        eligible = mask[t].copy()
        eligible[panel.index(panel.benchmark)] = False
        # A name with no price on the decision day cannot be bought.
        eligible &= np.isfinite(panel.adj_close[t])
        targets = np.zeros(len(panel.tickers))
        count = int(eligible.sum())
        if count:
            targets[eligible] = gross / count
        return targets

    return allocate


# Sessions on or after `start` and before `end`, as a Boolean mask over dates.
def window(dates: np.ndarray, start: date | None, end: date | None) -> np.ndarray:
    """Return the (T,) mask of sessions inside [start, end)."""
    days = np.asarray(dates, dtype="datetime64[D]")
    out = np.ones(len(days), dtype=bool)
    if start is not None:
        out &= days >= np.datetime64(start, "D")
    if end is not None:
        out &= days < np.datetime64(end, "D")
    return out


# Arm P1.2 of the volatile-book plan: capped equal weight across every name
# the desk grades A or better on the decision session, within the book's
# membership, at most `cap` of equity each, never more than `gross` in
# total. With ten or more qualifying names the book is fully invested and
# equal weight; with fewer, each takes `cap` and the rest stays in cash
# (the plan's rule: leftover cash stays in cash). No volatility target, no
# regime multiplier and no grade ladder: those are exactly what the arm
# removes, and each is measured by the scorecard rather than assumed.
def graded_equal_weight_allocator(
    mask: np.ndarray, min_grade: int, cap: float = 0.10, gross: float = 1.0
):
    """Return a callable (report, panel, config, t) -> target weights."""
    if not 0 < cap <= gross <= 1.0:
        raise ValueError("need 0 < cap <= gross <= 1")

    def allocate(report, panel, config, t: int) -> np.ndarray:
        eligible = mask[t] & (report.graded.grades[t] >= min_grade)
        eligible[panel.index(panel.benchmark)] = False
        eligible &= np.isfinite(panel.adj_close[t])
        targets = np.zeros(len(panel.tickers))
        count = int(eligible.sum())
        if count:
            targets[eligible] = min(gross / count, cap)
        return targets

    return allocate


# Equal risk instead of equal weight: every A-or-better name within the
# book's membership, sized inversely to its own trailing volatility so that a
# wild name takes less of the book than a quiet one, fully invested (or up
# to `gross`), each name at most `cap`. The volatility is the standard
# deviation of the last `window` daily log returns of adjusted close ending
# on the decision session, so nothing after that session is read. A name
# without `window` prior returns, or with zero variance, is not sized rather
# than given a guessed risk. Registered as an arm beside equal weight so the
# scorecard measures what the risk weighting buys, if anything; the only
# parameters are the window and the operator's hold limit.
def graded_inverse_volatility_allocator(
    mask: np.ndarray,
    min_grade: int,
    window: int = 63,
    cap: float = 1.0,
    gross: float = 1.0,
):
    """Return a callable (report, panel, config, t) -> inverse-volatility weights."""
    if not 0 < cap <= gross <= 1.0:
        raise ValueError("need 0 < cap <= gross <= 1")
    if window < 2:
        raise ValueError("need at least two returns for a volatility")

    def allocate(report, panel, config, t: int) -> np.ndarray:
        eligible = mask[t] & (report.graded.grades[t] >= min_grade)
        eligible[panel.index(panel.benchmark)] = False
        eligible &= np.isfinite(panel.adj_close[t])
        targets = np.zeros(len(panel.tickers))
        if t < window or not eligible.any():
            return targets
        closes = np.asarray(panel.adj_close[t - window : t + 1], dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = np.diff(np.log(closes), axis=0)
        volatility = np.nanstd(returns, axis=0, ddof=1)
        known = (
            np.isfinite(returns).all(axis=0)
            & np.isfinite(volatility)
            & (volatility > 0)
        )
        eligible &= known
        if not eligible.any():
            return targets
        inverse = np.where(eligible, 1.0 / volatility, 0.0)
        weights = gross * inverse / inverse.sum()
        # A name over the hold limit is trimmed to it; the excess is left in
        # cash rather than pushed onto the others, so the limit never makes
        # another name larger than its risk says.
        targets[eligible] = np.minimum(weights[eligible], cap)
        return targets

    return allocate


# Exposure control without a forecast: the equal-weight A-or-better book,
# scaled down as a whole when its own recent volatility is high. The basket's
# realised volatility is the standard deviation of the equal-weight basket's
# last `window` daily log returns (the names eligible on the decision
# session, so nothing after it is read), annualised; the book holds
# min(1, target / realised) of equity and the rest stays in cash. The 0.30
# target is the one the frozen rule already used, kept rather than tuned.
def graded_volatility_targeted_allocator(
    mask: np.ndarray,
    min_grade: int,
    window: int = 63,
    target: float = 0.30,
    cap: float = 1.0,
):
    """Return a callable (report, panel, config, t) -> equal weights at a volatility target."""
    if not 0 < cap <= 1.0 or not target > 0 or window < 2:
        raise ValueError(
            "need 0 < cap <= 1, a positive target and a window of two or more"
        )
    equal = graded_equal_weight_allocator(mask, min_grade, cap=cap, gross=1.0)

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = equal(report, panel, config, t)
        held = targets > 0
        if t < window or not held.any():
            return targets
        closes = np.asarray(panel.adj_close[t - window : t + 1], dtype=float)[:, held]
        with np.errstate(divide="ignore", invalid="ignore"):
            returns = np.diff(np.log(closes), axis=0)
        basket = np.nanmean(returns, axis=1)
        if not np.isfinite(basket).all() or len(basket) < 2:
            return targets
        realised = float(np.std(basket, ddof=1)) * np.sqrt(252.0)
        if not realised > 0:
            return targets
        return targets * min(1.0, target / realised)

    return allocate


# Per-name price tilts on the equal-weight book. The owner asked whether the
# size of a name should depend on where its price is, so each tilt turns one
# reading of the name's own past prices into a multiplier on its equal-weight
# slot; the slots are renormalised to the gross and then scaled to the
# volatility target like the untilted book, so a tilt changes how the book is
# shared out, not how much of the book is invested. Every reading ends on the
# decision session. The three tilts are the three honest answers to "buy more
# when...": the name is trending (price above its trailing average), the name
# has pulled back (price below its trailing high), the name has led its peers
# (trailing return rank). Each has one parameter beyond the window so the
# scorecard measures the idea, not a fit.
def _tilt_trend(closes: np.ndarray, strength: float) -> np.ndarray:
    """(window+1, n) closes -> 1 above the window's mean close, 1-strength below."""
    mean = np.nanmean(closes[:-1], axis=0)
    return np.where(closes[-1] > mean, 1.0, 1.0 - strength)


def _tilt_pullback(closes: np.ndarray, strength: float) -> np.ndarray:
    """(window+1, n) closes -> 1 at the window high, up to 1+strength at a full retreat."""
    high = np.nanmax(closes, axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        retreat = 1.0 - closes[-1] / high
    return 1.0 + strength * np.clip(np.nan_to_num(retreat), 0.0, 1.0)


def _tilt_leader(closes: np.ndarray, strength: float) -> np.ndarray:
    """(window+1, n) closes -> 1-strength for the weakest trailing return,
    1+strength for the strongest."""
    with np.errstate(divide="ignore", invalid="ignore"):
        trailing = closes[-1] / closes[0] - 1.0
    order = np.argsort(np.argsort(np.nan_to_num(trailing)))
    if len(order) < 2:
        return np.ones(len(order))
    return 1.0 + strength * (2.0 * order / (len(order) - 1) - 1.0)


TILTS = {"trend": _tilt_trend, "pullback": _tilt_pullback, "leader": _tilt_leader}


def graded_tilted_allocator(
    mask: np.ndarray,
    min_grade: int,
    tilt: str,
    strength: float = 0.5,
    window: int = 63,
    target: float = 0.25,
    cap: float = 1.0,
    vol_window: int = 63,
):
    """Return a callable (report, panel, config, t) -> tilted, vol-targeted weights."""
    if tilt not in TILTS:
        raise ValueError(f"unknown tilt {tilt!r}; one of {sorted(TILTS)}")
    if not 0 <= strength <= 1 or window < 2 or not 0 < cap <= 1.0:
        raise ValueError(
            "need 0 <= strength <= 1, a window of two or more and 0 < cap <= 1"
        )
    read = TILTS[tilt]
    scaled = graded_volatility_targeted_allocator(
        mask, min_grade, window=vol_window, target=target, cap=1.0
    )

    def allocate(report, panel, config, t: int) -> np.ndarray:
        base = scaled(report, panel, config, t)
        held = base > 0
        if t < window or not held.any():
            return base
        gross = float(base.sum())
        closes = np.asarray(panel.adj_close[t - window : t + 1], dtype=float)[:, held]
        multipliers = read(closes, strength)
        if not np.isfinite(multipliers).all() or not multipliers.sum() > 0:
            return base
        targets = np.zeros(len(base))
        targets[held] = gross * multipliers / multipliers.sum()
        return np.minimum(targets, cap)

    return allocate


# Sector concentration control. The A/A+ names cluster in one or two GICS
# sectors, and the equal-risk arm showed that reweighting among names that
# move together buys no drawdown; the only lever left is how much of the book
# one sector may hold. A group's weights are scaled down together to the cap
# (a share of the book's gross) and the excess stays in cash, so the control
# changes nothing about which names are held or how they rank, only how far
# one sector can carry the book. `groups` maps a ticker to its label; a name
# without a label is its own group.
def group_capped_allocator(inner, groups: dict, group_cap: float):
    """Return a callable (report, panel, config, t) -> inner weights, each group capped."""
    if not 0 < group_cap <= 1:
        raise ValueError("need 0 < group_cap <= 1")

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = np.array(inner(report, panel, config, t), dtype=float)
        gross = float(targets.sum())
        if not gross > 0:
            return targets
        labels = np.array([groups.get(name, name) for name in panel.tickers])
        for label in np.unique(labels[targets > 0]):
            members = labels == label
            share = float(targets[members].sum())
            if share > group_cap * gross:
                targets[members] *= group_cap * gross / share
        return targets

    return allocate


# Price-structure gates on top of a sizing arm. The owner's question is
# whether the desk should act on trend structure, not only grade on it: an
# exit when a name's own trend breaks, or no new entry while it is under
# distribution. Each gate reads the name's trailing adjusted closes through
# the decision session and either removes the name from the sized set every
# session the structure is broken (an exit gate) or only blocks names not
# held the session before (an entry gate, which keeps a small amount of
# state: the previous session's targets, reset whenever the clock does not
# advance). The levels are the desk's own: the 21- and 50-session averages
# and a 105-session exponential average standing in for the 21-week one.
def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _structure(panel, t: int, held: np.ndarray, kind: str) -> np.ndarray:
    """True where the name's structure passes `kind` on session t."""
    closes = np.asarray(panel.adj_close[: t + 1], dtype=float)[:, held]
    n = len(closes)
    ok = np.ones(held.sum(), dtype=bool)
    with np.errstate(invalid="ignore"):
        if kind == "daily_trend":
            if n < 50:
                return ok
            ok &= closes[-1] > np.nanmean(closes[-50:], axis=0)
        elif kind == "weekly_trend":
            if n < 110:
                return ok
            for j in range(closes.shape[1]):
                series = closes[-260:, j]
                if not np.isfinite(series).all():
                    continue
                ema = _ema(series, 105)
                ok[j] = series[-1] > ema[-1] and ema[-1] > ema[-6]
        elif kind == "not_distributing":
            if n < 30:
                return ok
            for j in range(closes.shape[1]):
                series = closes[-120:, j]
                if not np.isfinite(series).all():
                    continue
                ema = _ema(series, 21)
                ok[j] = not (series[-1] < ema[-1] and ema[-1] < ema[-6])
        else:
            raise ValueError(f"unknown structure gate {kind!r}")
    return np.where(np.isfinite(closes[-1]), ok, False)


def structure_gated_allocator(
    inner, kind: str, entries_only: bool = False, reshare: bool = False
):
    """Return a callable (report, panel, config, t) -> inner weights with a structure gate."""
    state = {"t": -1, "previous": None}

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = np.array(inner(report, panel, config, t), dtype=float)
        held = targets > 0
        if held.any():
            passing = _structure(panel, t, held, kind)
            blocked = np.zeros(len(targets), dtype=bool)
            blocked[np.flatnonzero(held)[~passing]] = True
            if entries_only and state["previous"] is not None and t > state["t"]:
                blocked &= ~(state["previous"] > 0)
            gross = float(targets.sum())
            targets[blocked] = 0.0
            kept = float(targets.sum())
            # By default a gated name's slot goes to cash, so the gate is also
            # an exposure cut in a selloff; with `reshare` the survivors take
            # it and the book stays as invested as the inner arm chose.
            if reshare and kept > 0 and gross > 0:
                targets *= gross / kept
        state["t"], state["previous"] = t, targets.copy()
        return targets

    return allocate


# Exposure from a volatility forecast instead of the trailing realised figure.
# The deep studies of September found the one thing a model predicted on
# this book was risk, not return, so the natural place for a learner is the
# volatility target: scale the book by what the next twenty sessions'
# basket volatility is forecast to be. The forecast here is a walk-forward
# ridge on the book's own price features (realised volatility over 5, 20
# and 63 sessions, the retreat from the 63-session high, cross-sectional
# dispersion, the benchmark's volatility), refit every `refit` sessions on
# a purged training set that ends `horizon` sessions before the decision,
# so the target is never read from the future. An EWMA forecast stands
# beside it as the naive learner the ridge must beat.
VOL_HORIZON = 20
_VOL_WINDOWS = (5, 20, 63)


def _basket_log_returns(panel, held: np.ndarray, t: int) -> np.ndarray:
    closes = np.asarray(panel.adj_close[: t + 1], dtype=float)[:, held]
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.diff(np.log(closes), axis=0)
    return np.nanmean(returns, axis=1)


def _vol_features(basket: np.ndarray, bench: np.ndarray, closes: np.ndarray, end: int):
    """Feature row for a decision at index `end` (inclusive) of the return series."""
    if end < 63:
        return None
    row = []
    for window in _VOL_WINDOWS:
        piece = basket[end - window + 1 : end + 1]
        row.append(np.log(np.std(piece, ddof=1) * np.sqrt(252.0) + 1e-6))
    piece = bench[end - 20 + 1 : end + 1]
    row.append(np.log(np.std(piece, ddof=1) * np.sqrt(252.0) + 1e-6))
    level = np.cumsum(basket[: end + 1])
    row.append(level[-1] - level[-63:].max())
    row.append(np.log(np.nanmean(np.nanstd(closes[end - 19 : end + 1], axis=0)) + 1e-6))
    return np.array(row, dtype=float)


def _vol_target_value(basket: np.ndarray, end: int, horizon: int) -> float | None:
    piece = basket[end + 1 : end + 1 + horizon]
    if len(piece) < horizon:
        return None
    return float(np.log(np.std(piece, ddof=1) * np.sqrt(252.0) + 1e-6))


def forecast_targeted_allocator(
    inner,
    forecaster: str = "ridge",
    target: float = 0.25,
    horizon: int = VOL_HORIZON,
    refit: int = 63,
    min_train: int = 500,
    ridge_lambda: float = 1.0,
    ewma_span: int = 20,
):
    """Return a callable (report, panel, config, t) -> inner weights at a forecast-vol target.

    `inner` must return unscaled slots (equal or tilted, cap applied) whose gross is
    what the book would hold at full exposure; the forecast decides the fraction.
    """
    if forecaster not in ("ridge", "ewma", "trailing"):
        raise ValueError(f"unknown forecaster {forecaster!r}")
    state = {"fit_at": None, "coef": None, "held_key": None}

    def allocate(report, panel, config, t: int) -> np.ndarray:
        slots = np.array(inner(report, panel, config, t), dtype=float)
        held = slots > 0
        if not held.any() or t < 64:
            return slots
        bench = panel.index(panel.benchmark)
        basket = _basket_log_returns(panel, held, t)
        if not np.isfinite(basket).all():
            return slots
        with np.errstate(divide="ignore", invalid="ignore"):
            bench_returns = np.diff(
                np.log(np.asarray(panel.adj_close[: t + 1, bench], dtype=float))
            )
        bench_returns = np.nan_to_num(bench_returns)
        end = len(basket) - 1
        if forecaster == "trailing":
            forecast = float(np.std(basket[-63:], ddof=1) * np.sqrt(252.0))
        elif forecaster == "ewma":
            alpha = 2.0 / (ewma_span + 1.0)
            variance = basket[-250:] ** 2
            weights = (1 - alpha) ** np.arange(len(variance))[::-1]
            forecast = float(
                np.sqrt(np.sum(weights * variance) / weights.sum() * 252.0)
            )
        else:
            closes = np.asarray(panel.adj_close[: t + 1], dtype=float)[:, held]
            # Refit on the schedule, on examples whose targets end before the
            # decision session, so no example contains tomorrow.
            if state["coef"] is None or t - state["fit_at"] >= refit:
                rows, targets = [], []
                for e in range(63, end - horizon):
                    x = _vol_features(basket, bench_returns, closes, e)
                    y = _vol_target_value(basket, e, horizon)
                    if x is not None and y is not None and np.isfinite(x).all():
                        rows.append(x)
                        targets.append(y)
                if len(rows) >= min_train:
                    X = np.c_[np.ones(len(rows)), np.array(rows)]
                    y = np.array(targets)
                    penalty = ridge_lambda * np.eye(X.shape[1])
                    penalty[0, 0] = 0.0
                    state["coef"] = np.linalg.solve(X.T @ X + penalty, X.T @ y)
                    state["fit_at"] = t
            x = _vol_features(basket, bench_returns, closes, end)
            if state["coef"] is None or x is None or not np.isfinite(x).all():
                forecast = float(np.std(basket[-63:], ddof=1) * np.sqrt(252.0))
            else:
                forecast = float(np.exp(np.r_[1.0, x] @ state["coef"]))
        if not forecast > 0:
            return slots
        return slots * min(1.0, target / forecast)

    return allocate


# A learned tilt. The learned rankers failed as selectors (ten names at 10%
# concentrated the book and lost to equal weight), but the question the
# owner asks is narrower: within the graded book, should a name's slot
# follow a walk-forward forecast of its relative return rather than its
# trailing-return rank? The tilt reshares the inner slots by the rank of
# the out-of-sample forecast among the held names, the same 1-strength to
# 1+strength mapping as the leader tilt, and leaves a name untouched on a
# session the forecast has no fitted model for.
def forecast_tilted_allocator(inner, forecast, strength: float = 0.5):
    """Return a callable (report, panel, config, t) -> inner slots tilted by forecast rank."""
    if not 0 <= strength <= 1:
        raise ValueError("need 0 <= strength <= 1")

    def allocate(report, panel, config, t: int) -> np.ndarray:
        slots = np.array(inner(report, panel, config, t), dtype=float)
        held = np.flatnonzero(slots > 0)
        if (
            len(held) < 2
            or np.isnat(forecast.fit_session[t])
            or forecast.last_training_label_end[t] >= t
        ):
            return slots
        scores = np.asarray(forecast.values[t], dtype=float)[held]
        if not np.isfinite(scores).all():
            return slots
        order = np.argsort(np.argsort(scores))
        multipliers = 1.0 + strength * (2.0 * order / (len(held) - 1) - 1.0)
        gross = float(slots[held].sum())
        tilted = slots[held] * multipliers
        slots[held] = tilted * gross / tilted.sum()
        return slots

    return allocate


# Three overlays on an allocator's targets, each a question the owner asks
# about the installed rule rather than a new rule: does trading only when a
# target has moved enough keep more of the return after costs; does standing
# aside when the benchmark is under its trend cut the drawdown; does a
# trailing stop on each name do what a trader expects of it. Each keeps the
# session state it needs in the closure, read forward only.
def banded_allocator(inner, band: float = 0.01):
    """Return a callable keeping a target until the new one moves by `band`."""
    state = {"t": -1, "previous": None}

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = np.array(inner(report, panel, config, t), dtype=float)
        previous = state["previous"]
        if previous is not None and t > state["t"] and len(previous) == len(targets):
            # A name leaving the book (target zero) always trades; a small
            # move on a held name waits.
            hold = (np.abs(targets - previous) < band) & (targets > 0) & (previous > 0)
            targets[hold] = previous[hold]
        state["t"], state["previous"] = t, targets.copy()
        return targets

    return allocate


def index_regime_allocator(inner, span: int = 50, scale: float = 0.5):
    """Return a callable scaling targets by `scale` under the benchmark EMA."""

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = np.array(inner(report, panel, config, t), dtype=float)
        if t < span:
            return targets
        bench = np.asarray(
            panel.adj_close[: t + 1, panel.index(panel.benchmark)], dtype=float
        )
        if not np.isfinite(bench[-span:]).all():
            return targets
        if bench[-1] < _ema(bench, span)[-1]:
            targets *= scale
        return targets

    return allocate


def trailing_stop_allocator(inner, stop: float = 0.15, cooldown: int = 10):
    """Return a callable exiting a name `stop` under its peak, out for `cooldown`."""
    state = {"t": -1, "peak": None, "blocked_until": None}

    def allocate(report, panel, config, t: int) -> np.ndarray:
        targets = np.array(inner(report, panel, config, t), dtype=float)
        n = len(targets)
        if state["peak"] is None or len(state["peak"]) != n:
            state["peak"] = np.full(n, np.nan)
            state["blocked_until"] = np.full(n, -1)
        closes = np.asarray(panel.adj_close[t], dtype=float)
        peak, blocked_until = state["peak"], state["blocked_until"]
        held = targets > 0
        # A name entering the book starts its peak at today's close; a held
        # name's peak ratchets up; a name leaving forgets its peak.
        entering = held & ~np.isfinite(peak)
        peak[entering] = closes[entering]
        peak[held] = np.fmax(peak[held], closes[held])
        peak[~held] = np.nan
        stopped = held & np.isfinite(peak) & (closes < peak * (1.0 - stop))
        blocked_until[stopped] = t + cooldown
        peak[stopped] = np.nan
        out = (blocked_until >= t) & held
        targets[out] = 0.0
        state["t"] = t
        return targets

    return allocate


# Enter on one grade, hold on a lower one. The installed rule exits a name
# the session its grade slips below A, and the replay's own audit found the
# exited names went on to beat the benchmark: the downgrade sells too soon.
# This keeps a held name while it still grades at least `hold_grade` and
# admits a new one only at `enter_grade`, so the book is the same names with
# a slower hand on the exit. `build(mask)` makes the inner allocator from a
# mask; the mask it is given admits a name on the entry grade, or on the hold
# grade when the previous session's targets held it.
def grade_hysteresis_allocator(
    build, mask: np.ndarray, report, enter_grade: int, hold_grade: int
):
    """Return a callable (report, panel, config, t) -> targets, exiting lower."""
    if hold_grade > enter_grade:
        raise ValueError("the hold grade must not be above the entry grade")
    state = {"held": None}

    class _Mask:
        def __getitem__(self, t):
            base = np.asarray(mask[t], dtype=bool)
            grades = report.graded.grades[t]
            keep = grades >= enter_grade
            if state["held"] is not None and len(state["held"]) == len(keep):
                keep |= state["held"] & (grades >= hold_grade)
            return base & keep

    inner = build(_Mask())

    def allocate(report_, panel, config, t: int) -> np.ndarray:
        targets = np.array(inner(report_, panel, config, t), dtype=float)
        state["held"] = targets > 0
        return targets

    return allocate
