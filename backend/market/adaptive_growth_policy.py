"""Research-only, cash-constrained allocation from authenticated causal inputs.

The caller owns forecast maturity, symbol identities and completed-close clocks.
This module neither fits a return model nor reads prices, accounts or orders.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linprog, minimize
from sklearn.covariance import LedoitWolf

POLICY = "adaptive-funded-growth/1-research"
CAP = 0.25
HORIZON = 10
CERTIFICATE_TOLERANCE = 1e-8


# Refuse ambiguous or nonnumeric symbol vectors rather than coercing evidence.
def _vector(value, size, name, *, missing=False):
    array = np.asarray(value)
    if array.shape != (size,) or array.dtype.kind not in "iuf":
        raise ValueError(f"{name} requires an aligned numeric vector")
    array = array.astype(np.float64, copy=True)
    if np.isinf(array).any() or (not missing and not np.isfinite(array).all()):
        raise ValueError(f"{name} contains unavailable numeric evidence")
    return array


# Estimate historical risk at the declared one- or ten-session forecast horizon.
def covariance(history, *, horizon_sessions=HORIZON):
    if (
        isinstance(horizon_sessions, (bool, np.bool_))
        or not isinstance(horizon_sessions, (int, np.integer))
        or horizon_sessions not in (1, HORIZON)
    ):
        raise ValueError("Declared one- or ten-session risk horizon required")
    values = np.asarray(history, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < 253 or values.shape[1] == 0:
        raise ValueError("At least 253 completed closes required")
    values = values[-253:]
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError("Covariance needs complete positive prior prices")
    returns = np.diff(np.log(values), axis=0)
    result = LedoitWolf().fit(returns).covariance_ * horizon_sessions
    if not np.isfinite(result).all() or np.any(np.diag(result) <= 0):
        raise ValueError("Historical variation is unavailable")
    return (result + result.T) / 2


# Prove a feasible point's global convex optimality through its linearized gap.
def _certificate(solution, gradient, matrix, limits, bounds):
    x = np.asarray(solution, dtype=np.float64)
    lower = np.array([item[0] for item in bounds])
    upper = np.array([item[1] for item in bounds])
    violation = max(
        0.0,
        float(np.max(matrix @ x - limits)),
        float(np.max(lower - x)),
        float(np.max(x - upper)),
    )
    if (
        not np.isfinite(x).all()
        or np.any(x < lower)
        or np.any(x > upper)
        or violation > CERTIFICATE_TOLERANCE
    ):
        return {"certified": False, "reason": "infeasible", "violation": violation}
    g = gradient(x)
    linear = linprog(g, A_ub=matrix, b_ub=limits, bounds=bounds, method="highs")
    if not linear.success or not np.isfinite(linear.fun):
        return {"certified": False, "reason": "certificate_unavailable"}
    gap = max(0.0, float(g @ x - linear.fun))
    return {
        "certified": gap <= CERTIFICATE_TOLERANCE,
        "reason": "global_convex_gap",
        "gap": gap,
        "violation": violation,
    }


# Solve absolute trades and purchases jointly, retaining fixed-position cross-risk.
def _solve(mean, second, current, lower, upper, cash, cost):
    size = len(current)
    eye = np.eye(size)
    zero = np.zeros((size, size))
    matrix = np.vstack(
        (
            np.r_[np.ones(size), np.zeros(2 * size)],
            np.c_[eye, -eye, zero],
            np.c_[-eye, -eye, zero],
            np.c_[eye, zero, -eye],
            np.r_[np.zeros(2 * size), np.full(size, 1 + cost)],
        )
    )
    limits = np.r_[1.0, current, -current, current, cash]
    bounds = list(zip(lower, upper, strict=True)) + [(0.0, 1.0)] * (2 * size)
    initial = np.minimum(np.maximum(current, lower), upper)
    start = np.r_[initial, np.abs(initial - current), np.maximum(initial - current, 0)]

    # Evaluate the preregistered approximate growth loss and actual trade penalty.
    def objective(x):
        return (
            0.5 * x[:size] @ second @ x[:size]
            - mean @ x[:size]
            + cost * x[size : 2 * size].sum()
        )

    # Give the solver exact derivatives of weights and auxiliary trade variables.
    def gradient(x):
        return np.r_[second @ x[:size] - mean, np.full(size, cost), np.zeros(size)]

    solved = minimize(
        objective,
        start,
        jac=gradient,
        method="SLSQP",
        bounds=bounds,
        constraints={
            "type": "ineq",
            "fun": lambda x: limits - matrix @ x,
            "jac": lambda x: -matrix,
        },
        options={"ftol": 1e-14, "maxiter": 300},
    )
    proof = _certificate(solved.x, gradient, matrix, limits, bounds)
    proof["solver_success"] = bool(solved.success)
    proof["iterations"] = int(solved.nit)
    proof["objective"] = float(objective(solved.x))
    return solved.x[:size].copy(), proof


# Validate the complete observation and account contract before optimizing capital.
def _validated(
    history,
    grades,
    eligible,
    means,
    current_weights,
    cash_weight,
    cost_bps,
    benchmark_indices,
):
    raw = np.asarray(history)
    if raw.ndim != 2 or raw.shape[0] < 253 or raw.dtype.kind not in "iuf":
        raise ValueError("At least 253 aligned completed-close rows required")
    size = raw.shape[1]
    if not size:
        raise ValueError("Nonempty symbol grid required")
    history = raw[-253:].astype(np.float64, copy=True)
    if np.isinf(history).any():
        raise ValueError("Infinite history is invalid")
    grades = _vector(grades, size, "grades")
    if np.any(~np.isin(grades, (-1, 0, 1, 2, 3))):
        raise ValueError("Ordinal grades -1 through 3 required")
    eligible = np.asarray(eligible)
    if eligible.shape != (size,) or eligible.dtype.kind != "b":
        raise ValueError("Explicit boolean eligibility required")
    means = _vector(means, size, "means", missing=True)
    current = _vector(current_weights, size, "current_weights")
    for value, name, upper in (
        (cash_weight, "cash_weight", 1),
        (cost_bps, "cost_bps", 10000),
    ):
        if (
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, float, np.integer, np.floating))
            or not np.isfinite(value)
            or not 0 <= value <= upper
        ):
            raise ValueError(f"Invalid {name}")
    if (
        cost_bps == 10000
        or np.any(current < 0)
        or current.sum() + cash_weight > 1 + 1e-10
    ):
        raise ValueError("Invalid funded weights or fees")
    benchmarks = np.asarray(benchmark_indices)
    if (
        benchmarks.ndim != 1
        or benchmarks.dtype.kind not in "iu"
        or np.any(benchmarks < 0)
        or np.any(benchmarks >= size)
        or len(np.unique(benchmarks)) != len(benchmarks)
    ):
        raise ValueError("Unique benchmark indices required")
    return history, grades, eligible.copy(), means, current, benchmarks


# Allocate known stocks with matching forecast units, risk horizon and funded limits.
def allocate(
    history,
    grades,
    eligible,
    means,
    current_weights,
    cash_weight,
    cost_bps,
    benchmark_indices,
    *,
    mean_units="log",
    horizon_sessions=HORIZON,
):
    """Return target weights and evidence; desired sales never become buying cash."""
    if (
        not isinstance(mean_units, str)
        or isinstance(horizon_sessions, (bool, np.bool_))
        or not isinstance(horizon_sessions, (int, np.integer))
        or (mean_units, horizon_sessions) not in (("log", HORIZON), ("arithmetic", 1))
    ):
        raise ValueError("Matching declared mean units and risk horizon required")
    history, grades, eligible, means, current, benchmarks = _validated(
        history,
        grades,
        eligible,
        means,
        current_weights,
        cash_weight,
        cost_bps,
        benchmark_indices,
    )
    mandatory = ~eligible | (grades < 2)
    mandatory[benchmarks] = True
    may_add = ~mandatory
    known_history = np.all(np.isfinite(history) & (history > 0), axis=0)
    known = known_history & np.isfinite(means)
    safe = np.where(mandatory, 0, np.minimum(current, CAP))
    protected = may_add & (current > 0) & ~known
    receipt = {
        "policy": POLICY
        if mean_units == "log"
        else "adaptive-funded-growth/2-daily-arithmetic-research",
        "horizon_sessions": horizon_sessions,
        "cap": CAP,
        "cash_weight": float(cash_weight),
        "cost_bps": float(cost_bps),
        "eligible": may_add.tolist(),
        "known": known.tolist(),
        "fixed": protected.tolist(),
        "mandatory_exits": mandatory.tolist(),
        "current_weights": current.tolist(),
    }
    if mean_units == "arithmetic":
        receipt["mean_units"] = mean_units
    if protected.any():
        receipt.update(
            status="unavailable",
            reason="missing_held_cross_risk",
            targets=safe.tolist(),
        )
        return safe, receipt
    selected = known & may_add
    if not selected.any():
        receipt.update(
            status="unavailable", reason="no_eligible_evidence", targets=safe.tolist()
        )
        return safe, receipt
    try:
        cov = covariance(history[:, selected], horizon_sessions=horizon_sessions)
    except ValueError:
        receipt.update(
            status="unavailable",
            reason="historical_risk_unavailable",
            targets=safe.tolist(),
        )
        return safe, receipt
    arithmetic = (
        means[selected] + 0.5 * np.diag(cov)
        if mean_units == "log"
        else means[selected].copy()
    )
    with np.errstate(over="ignore", invalid="ignore"):
        second = cov + np.outer(arithmetic, arithmetic)
    if not np.isfinite(second).all():
        receipt.update(
            status="unavailable", reason="moment_numeric_range", targets=safe.tolist()
        )
        return safe, receipt
    current_selected = current[selected]
    try:
        result, proof = _solve(
            arithmetic,
            second,
            current_selected,
            np.zeros(selected.sum()),
            np.full(selected.sum(), CAP),
            float(cash_weight),
            float(cost_bps) / 10000,
        )
    except (RuntimeError, ValueError, FloatingPointError, np.linalg.LinAlgError):
        receipt.update(
            status="unavailable", reason="optimizer_failed", targets=safe.tolist()
        )
        return safe, receipt
    receipt["certificate"] = proof
    receipt["selected_indices"] = np.flatnonzero(selected).tolist()
    receipt["arithmetic_means"] = arithmetic.tolist()
    receipt["covariance"] = cov.tolist()
    if not proof["certified"]:
        receipt.update(
            status="unavailable", reason="optimizer_uncertified", targets=safe.tolist()
        )
        return safe, receipt
    target = safe.copy()
    target[selected] = result
    receipt.update(
        status="optimized",
        targets=target.tolist(),
        purchases=float(np.maximum(target - current, 0).sum()),
        sales=float(np.maximum(current - target, 0).sum()),
    )
    return target, receipt
