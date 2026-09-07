"""Position sizing: from a score to a book that can actually be held.

A score orders names. A position is a decision about how much of each, and
that decision has to survive three things the score knows nothing about:
volatility (a name that moves 6% a day cannot carry the same weight as one
that moves 1%), concentration (a book that is 60% one theme is a bet on
the theme, whatever the scores say), and turnover (a signal that changes
every day is traded away in costs). This module makes those decisions
explicitly and measures the book that results.

Per rebalance session:

1. **Select**: the names in the top `top_fraction` by score (the long
   book), and, when `short_fraction` is set, the bottom fraction (short).
2. **Inverse-volatility weights**: each selected name gets weight
   proportional to 1 / its trailing realised volatility, so each carries a
   similar risk.
3. **Caps**: no name above `name_cap`, no theme above `theme_cap`; excess
   is redistributed to the uncapped names until nothing is over.
4. **Volatility target**: the book is scaled so its estimated volatility
   (from the names' own volatilities, correlations ignored, which is
   conservative for a long book) meets `target_volatility`, never above
   `max_gross`.
5. **Turnover control**: the held book moves a fraction `speed` of the way
   toward the target each rebalance, and changes smaller than `min_trade`
   are not traded.

`simulate` runs that through the panel's own returns with a per-unit
turnover cost and reports what a person would have experienced: return,
volatility, Sharpe, drawdown, turnover, and the benchmark's own figures.
`size_today` gives the sizes the book would hold now, per name, with why
each was capped or scaled — the answer to "how much CRWV".
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from backend.market.alpha import _rolling_std
from backend.market.panel import Panel

SESSIONS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class SizingConfig:
    """Every knob of the book."""

    top_fraction: float = 0.2
    short_fraction: float = 0.0  # 0 for a long-only book
    volatility_lookback: int = 60
    # A name whose price is pinned (a pending takeover) reads as nearly
    # riskless; the floor keeps it from absorbing the whole budget.
    min_volatility: float = 0.10
    target_volatility: float = 0.15  # annualised, for the whole book
    max_gross: float = 1.0  # long-only: fully invested at most
    name_cap: float = 0.10
    theme_cap: float = 0.40
    rebalance_every: int = 20
    speed: float = 0.5  # fraction of the way to the target per rebalance
    min_trade: float = 0.005  # weight changes below this are not traded
    cost_bps: float = 10.0


# Bring every weight under `cap`, handing what comes off to the names still
# below it, until `gross` is restored or nothing can take more.
#
# A step that renormalises after the cap has been applied can undo it. The
# tightening tilt does exactly that: it raises the weight of the calmest
# names and rescales to the original gross, which carried a position to
# 0.1626 against a 0.15 cap. A cap a later step can undo is not a cap, so
# both the paper path and the simulator call this after tilting.
#
# A book already at the cap in every name keeps the remainder as cash. The
# alternative is breaching the cap to stay fully invested, which is the
# thing being prevented.
def apply_name_cap(weights: np.ndarray, cap: float, gross: float) -> np.ndarray:
    """Return `weights` with none above `cap`, summing to at most `gross`."""
    if not cap or cap <= 0:
        return weights
    out = np.minimum(weights, cap)
    for _pass in range(8):
        spare = gross - float(out.sum())
        if spare <= 1e-12:
            break
        room = np.where(out > 0, np.maximum(cap - out, 0.0), 0.0)
        available = float(room.sum())
        if available <= 1e-12:
            break
        out = np.minimum(out + room / available * min(spare, available), cap)
    return out


# Every limit the book has, made true at the same time.
#
# `apply_name_cap` guarantees one constraint. Guaranteeing one at a time is
# not enough when they interact: scaling a theme down to its cap changes no
# name cap, but redistributing a name's excess to its neighbours raises
# every theme those neighbours belong to. With a name in two themes, the
# book came back inside every name cap and 0.4376 into a theme capped at
# 0.40.
#
# So the redistribution runs first, to use the budget where it can, and
# then this reduces - and only reduces - until nothing is over. Clipping a
# name and scaling a theme both move weights down, so the passes converge
# rather than trading one breach for another. Where a limit cannot be met
# while spending the gross, the gross is what gives way: the remainder
# stays in cash, because a limit that yields to a target exposure is not a
# limit.
def apply_limits(
    weights: np.ndarray,
    themes: Mapping[str, tuple[str, ...]],
    tickers: tuple[str, ...],
    name_cap: float,
    theme_cap: float,
    gross: float,
) -> np.ndarray:
    """Return `weights` inside every name and theme cap, spending at most `gross`."""
    out = apply_name_cap(weights, name_cap, gross) if name_cap else weights.copy()
    if not theme_cap or theme_cap <= 0:
        return out
    members: dict[str, list[int]] = {}
    for column, ticker in enumerate(tickers):
        for theme in themes.get(ticker, ()):
            members.setdefault(theme, []).append(column)
    for _pass in range(60):
        moved = False
        for columns in members.values():
            total = float(out[columns].sum())
            if total > theme_cap + 1e-12:
                out[columns] *= theme_cap / total
                moved = True
        over = out > name_cap + 1e-12 if name_cap else np.zeros(len(out), bool)
        if over.any():
            out = np.minimum(out, name_cap)
            moved = True
        if not moved:
            break
    return out


@dataclass(frozen=True, slots=True)
class BookResult:
    """What holding the book would have been like."""

    weights: np.ndarray  # (T, N) held weights, applied to the next session
    returns: np.ndarray  # (T,) daily book return net of cost
    benchmark_returns: np.ndarray  # (T,)
    turnover: np.ndarray  # (T,) absolute weight traded on rebalance sessions
    rebalances: int

    @property
    def annual_return(self) -> float:
        return float(np.nanmean(self.returns) * SESSIONS_PER_YEAR)

    @property
    def annual_volatility(self) -> float:
        return float(np.nanstd(self.returns, ddof=1) * math.sqrt(SESSIONS_PER_YEAR))

    @property
    def sharpe(self) -> float:
        vol = self.annual_volatility
        return self.annual_return / vol if vol > 0 else float("nan")

    @property
    def max_drawdown(self) -> float:
        curve = np.cumprod(1.0 + np.nan_to_num(self.returns))
        peak = np.maximum.accumulate(curve)
        return float(np.min(curve / peak - 1.0))

    @property
    def benchmark_sharpe(self) -> float:
        vol = float(
            np.nanstd(self.benchmark_returns, ddof=1) * math.sqrt(SESSIONS_PER_YEAR)
        )
        mean = float(np.nanmean(self.benchmark_returns) * SESSIONS_PER_YEAR)
        return mean / vol if vol > 0 else float("nan")

    @property
    def information_ratio(self) -> float:
        excess = self.returns - self.benchmark_returns
        vol = float(np.nanstd(excess, ddof=1) * math.sqrt(SESSIONS_PER_YEAR))
        return (
            float(np.nanmean(excess) * SESSIONS_PER_YEAR) / vol
            if vol > 0
            else float("nan")
        )

    @property
    def mean_turnover(self) -> float:
        traded = self.turnover[self.turnover > 0]
        return float(traded.mean()) if len(traded) else 0.0


@dataclass(frozen=True, slots=True)
class Position:
    """One name's size today and how it got there."""

    ticker: str
    weight: float
    score_rank: float
    volatility: float
    themes: tuple[str, ...]
    note: str


# Annualised trailing volatility per (session, name) from daily log returns.
# A better forecast here does not make a better book, and it was worth
# finding that out before replacing this.
#
# The desk sizes every position by the inverse of this number, so it is
# read more often than any signal, and a trailing window is the crudest
# estimator there is. Eleven models were run against the next twenty
# sessions' realised volatility, walk-forward with the label horizon
# purged, scored by QLIKE on 147,376 name-sessions:
#
#   trailing-60, what this returns          0.4361
#   HAR in levels                           0.4055   -7.0%
#   a small network on the QLIKE loss       0.3686  -15.5%
#   the same network on squared error       0.4486   +2.9%
#   gradient boosting, random forest,
#   k-nearest neighbours, ridge, EWMA       all worse than trailing-60
#
# The network wins clearly - and only when trained on the loss it is
# scored on. On squared error the identical network is worse than the
# window it was meant to replace, which is a fact about objectives rather
# than about model classes.
#
# Then it was put behind this function and the desk's own full-rule
# simulation was run against it: same scores, grades, regime, costs and
# constraints, only the volatility different. Sharpe 1.85 to 1.85, worst
# drawdown -19.0% to -19.1%, 31.8% a year to 31.6%. Nothing.
#
# Not because the estimates agree - the cross-sectional rank correlation
# between a sixty-session window and a twenty-session one is 0.854, and
# swapping them moves about 8.4% of the book. The book is simply not
# sensitive to this input at the margin: the name and theme caps bind, the
# volatility target rescales whatever comes out, and which tenth of the
# universe is held is decided by the scores. So a materially different
# ordering of volatilities produces the same portfolio.
#
# The conclusion is not "networks do not work". It is that this input is
# not where the book's risk-adjusted return is decided, so improving it
# buys nothing, and the trailing window stays because it is simpler and
# just as good here.
def realised_volatility(panel: Panel, lookback: int) -> np.ndarray:
    """Return (T, N) annualised realised volatility, NaN until the window fills."""
    return _rolling_std(panel.log_returns(), lookback) * math.sqrt(SESSIONS_PER_YEAR)


# The target weights for one session from its scores and volatilities.
#
# Returns (N,) weights: positive for the long book, negative for the short
# book, zero elsewhere. Names without a finite score or volatility are
# never selected.
def target_weights(
    scores: np.ndarray,
    volatility: np.ndarray,
    themes: Mapping[str, tuple[str, ...]],
    tickers: tuple[str, ...],
    config: SizingConfig,
    history: np.ndarray | None = None,
) -> np.ndarray:
    """Return capped, volatility-targeted weights for one session.

    `history` is (L, N) recent simple returns; when given, the book's
    volatility is measured on them under the candidate weights, which
    counts the correlation a long book is mostly made of.
    """
    n = len(tickers)
    weights = np.zeros(n)
    volatility = np.maximum(volatility, config.min_volatility)
    usable = np.isfinite(scores) & np.isfinite(volatility) & (volatility > 0)
    if usable.sum() < 2:
        return weights
    order = np.flatnonzero(usable)[np.argsort(scores[usable])]
    k_long = max(1, int(math.floor(len(order) * config.top_fraction)))
    long_names = order[-k_long:]
    weights[long_names] = 1.0 / volatility[long_names]
    if config.short_fraction > 0:
        k_short = max(1, int(math.floor(len(order) * config.short_fraction)))
        short_names = order[:k_short]
        weights[short_names] = -1.0 / volatility[short_names]
    weights = _normalise_sides(weights)
    weights = _apply_caps(weights, themes, tickers, config)
    # Volatility target: scale the whole book so its estimated volatility
    # meets the target, within the gross limit.
    estimated = book_volatility(weights, volatility, history)
    if estimated > 0:
        scale = min(config.target_volatility / estimated, 1.0)
        weights = weights * scale
    gross = float(np.abs(weights).sum())
    if gross > config.max_gross:
        weights = weights * (config.max_gross / gross)
    return weights


# The annualised volatility of a book: measured on recent returns under
# the weights when a history is given, else from the names' own
# volatilities with correlations ignored (an underestimate for a long
# book, used only when no history exists yet).
def book_volatility(
    weights: np.ndarray, volatility: np.ndarray, history: np.ndarray | None
) -> float:
    """Return the book's annualised volatility estimate."""
    if history is not None and len(history) >= 20:
        clean = np.where(np.isfinite(history), history, 0.0)
        series = clean @ weights
        realised = float(series.std(ddof=1)) * math.sqrt(SESSIONS_PER_YEAR)
        if realised > 0:
            return realised
    return math.sqrt(float(np.nansum((weights * volatility) ** 2)))


# Scale the long side to sum to one and the short side to minus one.
def _normalise_sides(weights: np.ndarray) -> np.ndarray:
    out = weights.copy()
    long_sum = out[out > 0].sum()
    short_sum = -out[out < 0].sum()
    if long_sum > 0:
        out[out > 0] /= long_sum
    if short_sum > 0:
        out[out < 0] /= short_sum
    return out


# Enforce per-name and per-theme caps on one side of the book by clipping
# and redistributing the excess to the names still under their caps, a few
# rounds at most - and then make the name cap true whatever those rounds
# managed.
#
# The rounds alone were not enough. Clipping a name and handing its excess
# to the others can push those others over, and with few names there is
# nowhere for the excess to go: the loop shuffles it until it runs out of
# passes and returns a book that breaches. Measured with a 15% cap, a
# two-name book came back holding 42.5% of one name, a three-name book
# 35%, a four-name book 16.4%. None of them were fully invested - the
# two-name book held 57.5% gross - so this was never the engine choosing
# full investment over the cap. It was the cap not being enforced.
#
# `apply_name_cap` finishes the job. Where the cap cannot be met while
# keeping the gross, the gross gives way and the remainder stays in cash,
# because a cap that yields to a target exposure is not a cap.
def _apply_caps(
    weights: np.ndarray,
    themes: Mapping[str, tuple[str, ...]],
    tickers: tuple[str, ...],
    config: SizingConfig,
) -> np.ndarray:
    out = weights.copy()
    for sign in (1.0, -1.0):
        side = out * sign > 0
        if not side.any():
            continue
        magnitude = out * sign
        for _ in range(8):
            changed_names = _cap_names(magnitude, side, config.name_cap)
            changed_themes = _cap_themes(
                magnitude, side, themes, tickers, config.theme_cap
            )
            if not (changed_names or changed_themes):
                break
        held = magnitude.copy()
        held[~side] = 0.0
        held = apply_limits(
            held,
            themes,
            tickers,
            config.name_cap,
            config.theme_cap,
            float(magnitude[side].sum()),
        )
        magnitude[side] = held[side]
        out[side] = magnitude[side] * sign
    return out


# Clip names over the cap and hand the excess to the names under it.
def _cap_names(magnitude: np.ndarray, side: np.ndarray, cap: float) -> bool:
    over = side & (magnitude > cap)
    if not over.any():
        return False
    excess = float((magnitude[over] - cap).sum())
    magnitude[over] = cap
    free = side & ~over
    if free.any() and excess > 0:
        magnitude[free] += excess * magnitude[free] / magnitude[free].sum()
    return True


# Scale any theme over its cap down and hand the excess to names outside it.
def _cap_themes(
    magnitude: np.ndarray,
    side: np.ndarray,
    themes: Mapping[str, tuple[str, ...]],
    tickers: tuple[str, ...],
    cap: float,
) -> bool:
    by_theme: dict[str, list[int]] = {}
    for column, ticker in enumerate(tickers):
        if side[column]:
            for theme in themes.get(ticker, ()):
                by_theme.setdefault(theme, []).append(column)
    changed = False
    for members in by_theme.values():
        total = float(magnitude[members].sum())
        if total <= cap + 1e-12:
            continue
        excess = total - cap
        magnitude[members] *= cap / total
        others = side.copy()
        others[members] = False
        if others.any():
            magnitude[others] += excess * magnitude[others] / magnitude[others].sum()
        changed = True
    return changed


# Move the held book toward the target with the configured speed and
# minimum trade size; returns (new weights, turnover).
def rebalance(
    held: np.ndarray, target: np.ndarray, config: SizingConfig
) -> tuple[np.ndarray, float]:
    """Return the book after one turnover-controlled rebalance and what it traded."""
    step = held + config.speed * (target - held)
    trade = step - held
    # An exit is always a full trade: a name the score no longer wants
    # is sold whatever its size, or small stale positions accumulate
    # into leverage. Speed and the minimum apply to entries and resizes.
    exit_ = (np.abs(target) < 1e-12) & (np.abs(held) > 0)
    trade[exit_] = -held[exit_]
    small = (np.abs(trade) < config.min_trade) & ~exit_
    trade[small] = 0.0
    new = held + trade
    gross = float(np.abs(new).sum())
    if gross > config.max_gross:
        scaled = new * (config.max_gross / gross)
        trade = trade + (scaled - new)
        new = scaled
    return new, float(np.abs(trade).sum())


# Run the book through the panel: rebalance every `rebalance_every`
# sessions on the score known that session, hold in between, charge cost
# on what was traded, and earn the next sessions' simple returns.
def simulate(scores: np.ndarray, panel: Panel, config: SizingConfig) -> BookResult:
    """Return the BookResult of holding the sized book through the panel."""
    rows, n = scores.shape
    volatility = realised_volatility(panel, config.volatility_lookback)
    simple = np.expm1(panel.log_returns())
    simple = np.where(np.isfinite(simple), simple, 0.0)
    bench = simple[:, panel.index(panel.benchmark)]
    weights = np.zeros((rows, n))
    returns = np.full(rows, np.nan)
    turnover = np.zeros(rows)
    held = np.zeros(n)
    rebalances = 0
    unit_cost = config.cost_bps / 10_000.0
    started = False
    for t in range(rows):
        cost = 0.0
        if t % config.rebalance_every == 0 and np.isfinite(scores[t]).sum() >= 10:
            window = simple[max(0, t - config.volatility_lookback + 1) : t + 1]
            target = target_weights(
                scores[t],
                volatility[t],
                panel.themes,
                panel.tickers,
                config,
                history=window,
            )
            target[panel.index(panel.benchmark)] = 0.0
            held, traded = rebalance(held, target, config)
            turnover[t] = traded
            cost = traded * unit_cost
            rebalances += 1
            started = True
        weights[t] = held
        if started and t + 1 < rows:
            returns[t + 1] = float((held * simple[t + 1]).sum()) - cost
    # Charge each rebalance's cost on the session that follows it.
    first = int(np.argmax(np.isfinite(returns))) if np.isfinite(returns).any() else rows
    return BookResult(
        weights=weights,
        returns=returns[first:] if first < rows else returns,
        benchmark_returns=bench[first:] if first < rows else bench,
        turnover=turnover,
        rebalances=rebalances,
    )


# The book the system would hold on the last session, per name, with notes.
def size_today(
    scores_today: np.ndarray,
    panel: Panel,
    config: SizingConfig,
    held: np.ndarray | None = None,
) -> list[Position]:
    """Return the positions the book takes now, largest first."""
    from backend.market.baselines import percentile_rank

    last = len(panel.dates) - 1
    volatility = realised_volatility(panel, config.volatility_lookback)[last]
    simple = np.expm1(panel.log_returns())
    window = simple[max(0, last - config.volatility_lookback + 1) : last + 1]
    target = target_weights(
        scores_today,
        volatility,
        panel.themes,
        panel.tickers,
        config,
        history=window,
    )
    target[panel.index(panel.benchmark)] = 0.0
    if held is not None:
        target, _ = rebalance(held, target, config)
    ranks = percentile_rank(scores_today[None, :])[0]
    positions: list[Position] = []
    for column, ticker in enumerate(panel.tickers):
        if abs(target[column]) < 1e-9:
            continue
        note = []
        if abs(target[column]) >= config.name_cap - 1e-9:
            note.append("at name cap")
        for theme in panel.themes.get(ticker, ()):
            members = [
                c
                for c, tk in enumerate(panel.tickers)
                if theme in panel.themes.get(tk, ())
            ]
            if abs(target[members]).sum() >= config.theme_cap - 1e-6:
                note.append(f"theme {theme} at cap")
        positions.append(
            Position(
                ticker=ticker,
                weight=float(target[column]),
                score_rank=(
                    float(ranks[column]) if np.isfinite(ranks[column]) else float("nan")
                ),
                volatility=float(volatility[column]),
                themes=tuple(panel.themes.get(ticker, ())),
                note="; ".join(note) or "inverse-volatility weight",
            )
        )
    positions.sort(key=lambda p: -abs(p.weight))
    return positions
