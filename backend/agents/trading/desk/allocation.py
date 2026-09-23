"""Pure bounded stock/index/cash allocation decision.

This module decides what the desk *wants* to hold, and nothing else: given the
unscaled desired stock weights, the actual held weights, the regime and event
absolute equity ceilings, and the SPY/QQQ price history, it returns the desired
stock/index/cash composition and the reason it is what it is. It makes no
orders, reads no broker, writes nothing, and owns no ledger. Execution is a
separate milestone.

Two fixed, predeclared policies are implemented:

* `vol` — a benchmark-relative volatility budget with residual SPY.
* `vol_trend` — the same budget plus a broad trend ceiling, read with
  hysteresis bands (`TREND_BELOW`/`TREND_ABOVE`) so a close merely crossing
  the 200-session mean does not flip the ceiling.

The incumbent default (no optional policy) is untouched by this module.

The decision is a pure function of its inputs; future rows in the price matrix
are allowed but every calculation slices at the decision index `t`, so
appending or changing future rows cannot change an earlier decision. Repeated
calls with the same unscaled desired composition return stable absolute
targets; yesterday's reduced target is never fed back as today's desired input.

`desired` is stock-only: an index in it is a caller error. SPY is selected as a
residual asset only when the caller passes `index_eligible=True` (it defaults
to False, so broker eligibility is never silently assumed); QQQ is only ever a
risk benchmark. `held` may include SPY or QQQ.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk.paper import ENTRY_NAME_CAP

# The two fixed policies this module implements.
POLICY_VOL = "vol"
POLICY_VOL_TREND = "vol_trend"
POLICIES = (POLICY_VOL, POLICY_VOL_TREND)

SPY = "SPY"
QQQ = "QQQ"

# The trailing windows the risk and trend reads use, and the annualization.
VOL_SHORT = 20
VOL_LONG = 60
TREND_WINDOW = 200
ANNUAL = 252

# Why a decision is what it is.
BINDING_NONE = "none"
BINDING_VOL = "volatility budget"
BINDING_REGIME = "regime equity cap"
BINDING_EVENT = "event cap"
BINDING_TREND = "broad trend ceiling"

_CAP_TOL = 1e-9


@dataclass(frozen=True)
class VolatilityDiagnostics:
    """The risk inputs the decision computed, so callers can audit it."""

    portfolio_risk: float | None  # annualized, or None when unavailable
    spy_risk: float | None
    qqq_risk: float | None
    budget: float | None  # min(SPY, QQQ) risk
    risk_scale: float | None  # min(1, budget / portfolio_risk)
    trend_ceiling: float | None  # 0, 0.5, 1, or None when not computable


@dataclass(frozen=True)
class AllocationDecision:
    """The desired composition for one decision index, and why it is that."""

    version: str
    as_of: str  # the session date at the decision index
    desired_weights: dict[str, float]  # stocks plus SPY when selected
    cash: float  # 1 - sum(desired_weights)
    available: bool  # whether the selected policy's evidence was complete
    reasons: tuple[str, ...]
    missing: tuple[str, ...]  # which inputs were unavailable
    volatility: VolatilityDiagnostics | None
    binding: str  # one of the BINDING_* constants


# The version string of the fixed policy being asked for.
def _version(policy: str) -> str:
    """Return the version identifier for `policy`."""
    return f"portfolio-allocation/{policy}/1"


# Validate the pure decision's inputs before any calculation.
def _validate(  # noqa: C901 - explicit input validation before any portfolio calculation
    dates: np.ndarray,
    prices: np.ndarray,
    tickers: list[str],
    t: int,
    desired: dict[str, float],
    held: dict[str, float],
    regime_cap: float,
    event_cap: float,
    policy: str,
    index_eligible: bool,
) -> tuple[int, int]:
    """Return (SPY column, QQQ column); raise ValueError on bad inputs."""
    dates = np.asarray(dates)
    prices = np.asarray(prices, dtype=float)
    if dates.ndim != 1 or prices.ndim != 2:
        raise ValueError("dates must be one-dimensional and prices two-dimensional")
    if dates.shape[0] != prices.shape[0]:
        raise ValueError("dates and prices must share the number of sessions")
    if len(tickers) != prices.shape[1]:
        raise ValueError("tickers must match the price matrix columns")
    if len(tickers) != len(set(tickers)):
        raise ValueError("tickers must be unique")
    for required in (SPY, QQQ):
        if required not in tickers:
            raise ValueError(f"tickers must include {required}")
    if dates.dtype.kind not in "M":
        raise ValueError("dates must be datetime64")
    if np.isnat(dates).any():
        raise ValueError("dates must not contain NaT")
    if len(dates) > 1 and not np.all(dates[1:] > dates[:-1]):
        raise ValueError("dates must be strictly ascending")
    if not isinstance(t, (int, np.integer)) or not 0 <= t < prices.shape[0]:
        raise ValueError(
            f"decision index t must be an integer in [0, {prices.shape[0] - 1}]"
        )
    if not np.isfinite(regime_cap) or not 0.0 <= regime_cap <= 1.0:
        raise ValueError("regime_cap must be a finite fraction in [0, 1]")
    if not np.isfinite(event_cap) or not 0.0 <= event_cap <= 1.0:
        raise ValueError("event_cap must be a finite fraction in [0, 1]")
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}")
    if not isinstance(index_eligible, bool):
        raise ValueError("index_eligible must be a bool")
    # `desired` is stock-only: an index in it would silently change composition
    # when the residual is computed. `held` may include an index.
    for ticker in desired:
        if ticker in (SPY, QQQ):
            raise ValueError(f"desired must be stock-only; {ticker} is an index")
    for label, weights in (("desired", desired), ("held", held)):
        for ticker, weight in weights.items():
            if ticker not in tickers:
                raise ValueError(
                    f"{label} names a ticker not in the price matrix: {ticker}"
                )
            if not np.isfinite(weight) or weight < 0.0:
                raise ValueError(f"{label}[{ticker}] must be finite and nonnegative")
        if sum(weights.values()) > 1.0 + _CAP_TOL:
            raise ValueError(f"{label} weights must total at most 1")
    return tickers.index(SPY), tickers.index(QQQ)


# Simple returns from adjusted closes: a usable return needs BOTH finite
# strictly positive endpoints, so a zero or negative price is never evidence.
def _simple_returns(prices: np.ndarray) -> np.ndarray:
    """Return (T, N) simple returns, NaN where an endpoint is not usable."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = prices[1:] / prices[:-1] - 1.0
    usable = (
        np.isfinite(prices[1:])
        & (prices[1:] > 0.0)
        & np.isfinite(prices[:-1])
        & (prices[:-1] > 0.0)
    )
    out = np.where(usable, out, np.nan)
    return np.vstack([np.full((1, prices.shape[1]), np.nan), out])


# Whether a completed trailing window of `window` returns through t is finite.
def _window_complete(series: np.ndarray, t: int, window: int) -> bool:
    """Return True when the last `window` rows through t are all finite."""
    if t + 1 < window:
        return False
    return bool(np.isfinite(series[t - window + 1 : t + 1]).all())


# Whether a completed trailing window of `window` prices through t is usable.
def _price_window_complete(prices: np.ndarray, t: int, window: int) -> bool:
    """Return True when the last `window` prices through t are finite and > 0."""
    if t + 1 < window:
        return False
    block = prices[t - window + 1 : t + 1]
    return bool(np.isfinite(block).all() and (block > 0.0).all())


# The annualized population std of a series' last 20 and last 60 returns.
def _risk(series: np.ndarray, t: int) -> float | None:
    """Return max(std20, std60) * sqrt(252) through t, or None when incomplete."""
    if not _window_complete(series, t, VOL_LONG):
        return None
    short = np.std(series[t - VOL_SHORT + 1 : t + 1], ddof=0)
    long = np.std(series[t - VOL_LONG + 1 : t + 1], ddof=0)
    return float(max(short, long) * np.sqrt(ANNUAL))


# The hysteresis bands of the trend read, as fractions of the 200-session
# mean: a benchmark counts as below trend only once its close is more than 3%
# under the mean, and as above again only once it is more than 2% over it.
# Between the bands the most recent decided state holds. A single close
# crossing the mean used to flip the ceiling 1 -> 0.5 -> 0 and back.
TREND_BELOW = -0.03
TREND_ABOVE = 0.02


# Whether one benchmark is above its 200-session price trend at t, with the
# hysteresis bands applied causally: the state is decided by the most recent
# session at or before t whose close sits outside the bands, scanning back
# only through the contiguous run of complete 200-session windows that ends
# at t (a gap in the history is not carried across). Only rows through t are
# read, so appending future rows cannot change an earlier read. When no
# session in that run has ever left the bands there is no decided state to
# hold, and the plain comparison of the close to its mean at t decides.
def _above_trend(series: np.ndarray, t: int) -> bool | None:
    """Return True/False for above/below trend at t, None when unusable."""
    if not _price_window_complete(series, t, TREND_WINDOW):
        return None
    prefix = np.asarray(series[: t + 1], dtype=float)
    usable = np.isfinite(prefix) & (prefix > 0.0)
    # Rolling 200-session means and window completeness from cumulative sums,
    # so the causal scan is one pass over the prefix rather than one window
    # mean per session scanned.
    values = np.where(usable, prefix, 0.0)
    csum = np.concatenate([[0.0], np.cumsum(values)])
    bad = np.concatenate([[0], np.cumsum(~usable)])
    idx = np.arange(TREND_WINDOW - 1, t + 1)
    means = (csum[idx + 1] - csum[idx + 1 - TREND_WINDOW]) / TREND_WINDOW
    complete = (bad[idx + 1] - bad[idx + 1 - TREND_WINDOW]) == 0
    ratio = np.full(t + 1, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio[idx] = np.where(complete, prefix[idx] / means - 1.0, np.nan)
    incomplete = np.flatnonzero(~complete)
    run_start = int(idx[incomplete[-1]]) + 1 if len(incomplete) else int(idx[0])
    decided = np.zeros(t + 1, dtype=int)
    decided[ratio > TREND_ABOVE] = 1
    decided[ratio < TREND_BELOW] = -1
    states = np.flatnonzero(decided[run_start : t + 1])
    if len(states):
        return bool(decided[run_start + int(states[-1])] > 0)
    return bool(prefix[t] > float(means[-1]))


# The broad trend ceiling: the fraction of SPY/QQQ above their trailing
# 200-session adjusted-close PRICE mean, on price levels, never on returns,
# each read with the hysteresis bands of `_above_trend`.
def _trend_ceiling(
    spy_prices: np.ndarray, qqq_prices: np.ndarray, t: int
) -> float | None:
    """Return (above_SPY + above_QQQ) / 2 on price levels, or None when unusable."""
    above = 0
    for series in (spy_prices, qqq_prices):
        state = _above_trend(series, t)
        if state is None:
            return None
        above += int(state)
    return float(above) / 2.0


# The absolute equity ceiling and which of the known ceilings binds it.
def _absolute_ceiling(
    regime_cap: float, event_cap: float, trend: float | None
) -> tuple[float, str]:
    """Return (C, the binding ceiling's name) as the minimum of the known caps."""
    ceilings: dict[str, float] = {BINDING_REGIME: regime_cap, BINDING_EVENT: event_cap}
    if trend is not None:
        ceilings[BINDING_TREND] = trend
    ceiling = min(ceilings.values())
    binding = next(
        name
        for name in (BINDING_REGIME, BINDING_EVENT, BINDING_TREND)
        if name in ceilings and abs(ceilings[name] - ceiling) < _CAP_TOL
    )
    return float(ceiling), binding


# Which constraint the final scalar came from, for the available path.
def _binding(
    final_scalar: float,
    risk_scale: float,
    cap_ratio: float,
    ceiling_binding: str,
    regime_cap: float,
    candidate_sum: float,
) -> str:
    """Return the binding constraint, naming a regime reservation when it holds."""
    if final_scalar < 1.0 - _CAP_TOL:
        if risk_scale <= cap_ratio:
            return BINDING_VOL
        return ceiling_binding
    # The scalar did not move equity; the level was set at composition time. A
    # regime cap below full equity that the candidate met is a reservation: the
    # regime is why the rest sits in cash, not the caller's low target.
    if regime_cap < 1.0 - _CAP_TOL and abs(candidate_sum - regime_cap) < _CAP_TOL:
        return BINDING_REGIME
    return BINDING_NONE


# The plain-language reason for a binding constraint.
def _reason(binding: str, final_scalar: float) -> str:
    """Return the reason string for a binding constraint."""
    if binding == BINDING_VOL:
        return "portfolio volatility scaled down to the SPY/QQQ budget"
    if binding in (BINDING_REGIME, BINDING_EVENT, BINDING_TREND):
        if final_scalar < 1.0 - _CAP_TOL:
            return f"absolute {binding} scaled the candidate down"
        return f"{binding} reserves the remaining equity as cash"
    return "no risk reduction required"


# The pure decision: what the desk should want to hold at index t.
def decide(  # noqa: C901 - explicit composition, evidence and known-risk fallback stages
    dates,
    prices,
    tickers,
    t: int,
    desired: dict[str, float],
    held: dict[str, float],
    regime_cap: float,
    event_cap: float,
    policy: str = POLICY_VOL_TREND,
    index_eligible: bool = False,
) -> AllocationDecision:
    """Return the AllocationDecision for the close of session `t`.

    `dates` is the ordered session calendar, `prices` the (T, N) adjusted-close
    matrix (which must include SPY and QQQ), `tickers` the column names, and `t`
    the decision index. `desired` holds the unscaled desired STOCK weights (an
    index there is a caller error) and `held` the actual held weights (which may
    include an index). `regime_cap` and `event_cap` are the absolute
    total-equity ceilings; `policy` is `vol` or `vol_trend`;
    `index_eligible` says whether SPY may fill residual equity capacity (QQQ is
    only ever a risk benchmark). Only rows through `t` are used. An empty
    candidate targets all cash (a requested exit is never blocked by missing
    evidence, and it authorizes no fill: whether a position can actually be
    sold without an execution price is the execution layer's report). When the
    evidence the chosen policy needs is missing - volatility, or a complete
    200-session trend for `vol_trend` - the decision preserves actual holdings
    and cuts them only to a known absolute ceiling; a missing trend is never
    imputed as bearish.
    """
    spy_col, qqq_col = _validate(
        dates,
        prices,
        tickers,
        t,
        desired,
        held,
        regime_cap,
        event_cap,
        policy,
        index_eligible,
    )
    ticker_list = list(tickers)
    as_of = str(np.asarray(dates)[t])
    price_matrix = np.asarray(prices, dtype=float)

    # 1. Cap stocks at the company cap, then at the regime equity cap.
    capped = {
        name: min(float(weight), ENTRY_NAME_CAP)
        for name, weight in desired.items()
        if weight > 0.0
    }
    stock_sum = sum(capped.values())
    if stock_sum > regime_cap + _CAP_TOL:
        factor = regime_cap / stock_sum
        capped = {name: weight * factor for name, weight in capped.items()}
        stock_sum = regime_cap
    # An explicitly empty stock composition requests cash, not an index entry.
    residual = (
        max(0.0, regime_cap - stock_sum) if index_eligible and stock_sum > 0.0 else 0.0
    )
    candidate = dict(capped)
    if residual > 0.0:
        candidate[SPY] = residual
    candidate_sum = sum(candidate.values())

    # The absolute equity ceiling, from the known caps only. The trend reads
    # price levels, never returns.
    rets = _simple_returns(price_matrix)
    spy_series = rets[:, spy_col]
    qqq_series = rets[:, qqq_col]
    spy_prices = price_matrix[:, spy_col]
    qqq_prices = price_matrix[:, qqq_col]
    trend = (
        _trend_ceiling(spy_prices, qqq_prices, t)
        if policy == POLICY_VOL_TREND
        else None
    )
    ceiling, ceiling_binding = _absolute_ceiling(regime_cap, event_cap, trend)

    # 2. Volatility evidence, tracked as explicit missing inputs: 60 complete
    # returns for every positive-weight component and for each benchmark risk.
    missing_returns: list[str] = []
    missing_prices: list[str] = []
    component_cols: list[int] = []
    component_weights: list[float] = []
    for name, weight in candidate.items():
        if weight <= 0.0:
            continue
        col = ticker_list.index(name)
        if not _window_complete(rets[:, col], t, VOL_LONG):
            missing_returns.append(f"{name} (< {VOL_LONG} returns)")
            continue
        component_cols.append(col)
        component_weights.append(weight)
    if not _window_complete(spy_series, t, VOL_LONG):
        missing_returns.append(f"{SPY} risk (< {VOL_LONG} returns)")
    if not _window_complete(qqq_series, t, VOL_LONG):
        missing_returns.append(f"{QQQ} risk (< {VOL_LONG} returns)")
    if policy == POLICY_VOL_TREND and trend is None:
        missing_prices.append(f"trend ceiling (< {TREND_WINDOW} prices)")

    spy_risk = _risk(spy_series, t)
    qqq_risk = _risk(qqq_series, t)
    budget = (
        min(spy_risk, qqq_risk)
        if spy_risk is not None and qqq_risk is not None
        else None
    )

    # An empty candidate has zero portfolio risk, not missing risk: a requested
    # exit must not be blocked by a stock that lacks a return history.
    portfolio_risk: float | None = 0.0 if candidate_sum <= 0.0 else None
    if candidate_sum > 0.0 and not missing_returns:
        weights = np.array(component_weights, dtype=float)
        joint = rets[: t + 1, component_cols] @ weights
        portfolio_risk = _risk(joint, t)

    # Availability: the volatility evidence, plus a complete trend for the
    # vol_trend policy whenever the target is non-empty. A missing trend is an
    # unavailable absolute ceiling, never imputed as bearish, and it makes the
    # vol_trend decision unavailable; the vol policy only needs volatility. An
    # empty target is risk-free and is never blocked by missing evidence.
    trend_required = policy == POLICY_VOL_TREND and candidate_sum > 0.0
    available = (
        budget is not None
        and portfolio_risk is not None
        and (not trend_required or trend is not None)
    )

    if available:
        risk_scale = (
            min(1.0, budget / portfolio_risk)
            if portfolio_risk is not None and portfolio_risk > 0.0
            else 1.0
        )
        cap_ratio = ceiling / candidate_sum if candidate_sum > 0.0 else 1.0
        final_scalar = min(risk_scale, cap_ratio, 1.0)
        desired_weights = {
            name: weight * final_scalar for name, weight in candidate.items()
        }
        cash = max(0.0, 1.0 - sum(desired_weights.values()))
        binding = _binding(
            final_scalar,
            risk_scale,
            cap_ratio,
            ceiling_binding,
            regime_cap,
            candidate_sum,
        )
        reasons = [_reason(binding, final_scalar)]
        if trend is None and policy == POLICY_VOL_TREND:
            reasons.append("trend ceiling unavailable; excluded from the minimum")
        diag = VolatilityDiagnostics(
            portfolio_risk, spy_risk, qqq_risk, budget, risk_scale, trend
        )
    else:
        # 4. No evidence sufficient for the chosen policy: start from the
        # actual held weights and cut them only to a known absolute ceiling.
        # Never infer a new target from missing data, and never fabricate
        # returns. A deliberate zero-risk target (an empty `desired`) still
        # wants cash: missing diagnostics do not block a requested exit,
        # though whether it can actually be sold without an execution price is
        # the execution layer's report, not a claim this module makes.
        if candidate_sum <= 0.0:
            desired_weights = {}
            binding = BINDING_NONE
            reasons = [
                "insufficient policy evidence; "
                "the requested all-cash target is not blocked by missing diagnostics"
            ]
        else:
            held_positive = {name: float(w) for name, w in held.items() if w > 0.0}
            held_sum = sum(held_positive.values())
            if held_sum > ceiling + _CAP_TOL and held_sum > 0.0:
                cut = ceiling / held_sum
                desired_weights = {name: w * cut for name, w in held_positive.items()}
                binding = ceiling_binding
                reasons = [
                    "insufficient policy evidence; "
                    "held exposure cut to the absolute equity ceiling"
                ]
            else:
                desired_weights = held_positive
                binding = BINDING_NONE
                reasons = [
                    "insufficient policy evidence; "
                    "holdings retained; no risk increase without policy evidence"
                ]
        cash = max(0.0, 1.0 - sum(desired_weights.values()))
        diag = VolatilityDiagnostics(
            portfolio_risk, spy_risk, qqq_risk, budget, None, trend
        )

    return AllocationDecision(
        version=_version(policy),
        as_of=as_of,
        desired_weights=desired_weights,
        cash=cash,
        available=available,
        reasons=tuple(reasons),
        missing=tuple(sorted(missing_returns + missing_prices)),
        volatility=diag,
        binding=binding,
    )
