"""Research-only learned timing and growth sizing; no broker or live activation.

Forecast columns are ten-session log return, its second moment, and the
buy-side log-price advantage of waiting. The same pure decision is reusable
by a future live adapter; execution and missing observations remain separate.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

POLICY = "learned-entry-risk/1-research"
CAP = 0.25


class OptimizationUnavailableError(RuntimeError):
    """No certified feasible optimum; a caller must preserve the funded account."""


# Estimate correlation only from fully observed preceding adjusted daily prices.
def correlation(history):
    history = np.asarray(history, dtype=float)
    if history.ndim != 2 or len(history) != 253:
        raise ValueError("253 preceding closes required for 252 return observations")
    if not np.isfinite(history).all() or np.any(history <= 0):
        raise ValueError("missing correlation evidence")
    returns = np.diff(np.log(history), axis=0)
    covariance = LedoitWolf().fit(returns).covariance_
    scale = np.sqrt(np.maximum(np.diag(covariance), 1e-16))
    result = covariance / np.outer(scale, scale)
    # Constant series have no observed variation, not evidence of zero future risk.
    np.fill_diagonal(result, 1.0)
    return (result + result.T) / 2


# Maximize second-order growth from arithmetic-mean and cross-moment approximations.
def growth_weights(mean, covariance, current, upper, cost):
    mean, current, upper = [np.asarray(a, dtype=float) for a in (mean, current, upper)]
    covariance = np.asarray(covariance, dtype=float)
    n = len(mean)
    if (
        n == 0
        or current.shape != (n,)
        or upper.shape != (n,)
        or covariance.shape != (n, n)
        or not all(np.isfinite(a).all() for a in (mean, covariance, current, upper))
        or not np.isfinite(cost)
        or cost < 0
        or np.any(current < 0)
        or current.sum() > 1 + 1e-8
        or np.any(upper < 0)
        or np.any(upper > CAP + 1e-12)
        or not np.allclose(covariance, covariance.T, atol=1e-10)
        or np.linalg.eigvalsh(covariance).min() < -1e-10
    ):
        raise ValueError("invalid funded growth optimization inputs")
    # A convex objective with a supporting gradient directed into every upper
    # bound is globally minimized there. Certify it directly instead of asking
    # SLSQP to line-search through near-zero fixed-position bounds.
    at_upper = covariance @ upper - mean + cost * np.where(upper <= current, -1, 1)
    if upper.sum() <= 1 and np.all(at_upper[upper > 0] <= 0):
        return upper.copy()
    at_zero = -mean + cost * np.where(current > 0, -1, 1)
    if np.all(at_zero[upper > 0] >= 0):
        return np.zeros(n)

    # The second half bounds absolute trades, making the objective differentiable.
    def objective(x):
        w, trades = x[:n], x[n:]
        return 0.5 * w @ covariance @ w - mean @ w + cost * trades.sum()

    # Supply exact gradients rather than finite-difference repeated portfolio solves.
    def gradient(x):
        return np.r_[covariance @ x[:n] - mean, np.full(n, cost)]

    matrix = np.vstack(
        [
            np.r_[-np.ones(n), np.zeros(n)],
            np.c_[-np.eye(n), np.eye(n)],
            np.c_[np.eye(n), np.eye(n)],
        ]
    )
    offset = np.r_[1.0, current, -current]
    initial = np.minimum(current, upper)
    solved = minimize(
        objective,
        np.r_[initial, np.abs(initial - current)],
        jac=gradient,
        method="SLSQP",
        bounds=[(0.0, float(v)) for v in upper] + [(0.0, 1.0)] * n,
        constraints={
            "type": "ineq",
            "fun": lambda x: matrix @ x + offset,
            "jac": lambda x: matrix,
        },
        options={"ftol": 1e-10, "maxiter": 100},
    )
    w = solved.x[:n]
    if (
        not solved.success
        or not np.isfinite(w).all()
        or np.any(w < -1e-8)
        or np.any(w > upper + 1e-8)
        or w.sum() > 1 + 1e-8
        or np.min(matrix @ solved.x + offset) < -1e-8
        or objective(solved.x)
        > objective(np.r_[initial, np.abs(initial - current)]) + 1e-8
    ):
        raise OptimizationUnavailableError(
            "growth optimizer did not establish a feasible improvement"
        )
    w = np.clip(w, 0, upper)
    if w.sum() > 1:
        w /= w.sum()
    return w


# Convert joint forecasts to funded targets, preserving the account on missing evidence.
def decide(forecasts, history, current, may_add, cost_bps):
    forecasts = np.asarray(forecasts, dtype=float)
    current = np.asarray(current, dtype=float)
    may_add = np.asarray(may_add, dtype=bool)
    history = np.asarray(history, dtype=float)
    n = len(current)
    if forecasts.shape != (n, 3) or may_add.shape != (n,) or history.shape != (253, n):
        raise ValueError("aligned forecast, prior-history and account vectors required")
    if (
        not np.isfinite(current).all()
        or np.any(current < 0)
        or current.sum() > 1 + 1e-8
    ):
        raise ValueError("invalid current funded weights")
    known = (
        np.isfinite(forecasts).all(axis=1)
        & np.isfinite(history).all(axis=0)
        & (history > 0).all(axis=0)
    )
    if np.any((current > 0) & ~known):
        return current.copy(), {
            "status": "hold_missing_held_evidence",
            "unknown": int((~known).sum()),
        }
    selected = known & (may_add | (current > 0))
    if not selected.any():
        return current.copy(), {
            "status": "hold_no_evidence",
            "unknown": int((~known).sum()),
        }
    f = forecasts[selected]
    corr = correlation(history[:, selected])
    mean, second_moment, inconsistent = growth_parameters(f, corr)
    previous = current[selected]
    upper = np.where(may_add[selected], CAP, np.minimum(CAP, previous))
    try:
        weights = growth_weights(mean, second_moment, previous, upper, cost_bps / 1e4)
    except OptimizationUnavailableError:
        return current.copy(), {"status": "hold_optimizer_unavailable"}
    delta = weights - previous
    waiting = ((delta > 0) & (f[:, 2] > 0)) | ((delta < 0) & (f[:, 2] < 0))
    target = current.copy()
    target[selected] = np.where(waiting, previous, weights)
    # Delayed sells may retain capital the optimizer assigned to buys; resize those
    # buys without inventing financing or silently canceling the delayed holding.
    increases = np.maximum(target - current, 0)
    available = max(0.0, 1 - float(np.minimum(target, current).sum()))
    if increases.sum() > available:
        target = np.minimum(target, current) + increases * available / increases.sum()
    return target, {
        "status": "decided",
        "known": int(selected.sum()),
        "unknown": int((~known).sum()),
        "waiting": int(waiting.sum()),
        "inconsistent_moments": int(inconsistent.sum()),
    }


# Convert log-return moments without subtracting the same risk penalty twice.
def growth_parameters(forecasts, corr):
    mean_log = forecasts[:, 0]
    predicted_second = forecasts[:, 1]
    inconsistent = predicted_second < mean_log**2
    variance = np.maximum(predicted_second, mean_log**2) - mean_log**2
    variance[inconsistent] = np.maximum(
        predicted_second[inconsistent], mean_log[inconsistent] ** 2
    )
    variance = np.maximum(variance, 1e-8)
    second = variance + mean_log**2
    covariance = corr * np.outer(np.sqrt(variance), np.sqrt(variance))
    cross_moment = covariance + np.outer(mean_log, mean_log)
    return mean_log + 0.5 * second, cross_moment, inconsistent
