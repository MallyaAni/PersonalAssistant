"""Research-only covariance sizing; fixed specification, funded next-open accounts.

This module never imports a live allocator or sends orders. Grades and dated
membership are supplied evidence, not reconstructed historical availability.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import policy_v5
from backend.market.allocation_evaluation import metrics
from backend.market.allocation_replay import AllocationInstruction, replay

POLICY = "skfolio-covariance-sizing/1-research"
LOOKBACK = 252
CADENCE = 20
COSTS = (10.0, 25.0)
CAP = policy_v5.HOLD_CAP
LINES = (POLICY, policy_v5.POLICY_VERSION, "equal-weight-pit", "SPY", "QQQ")


# Serialize research evidence with one reproducible digest and no nonfinite values.
def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


# Freeze the only candidate before any market outcomes are evaluated.
def specification():
    return {
        "policy": POLICY,
        "covariance": "skfolio LedoitWolf on trailing 252 adjusted-close returns",
        "objective": "minimum variance; no return predictor or tuned expected return",
        "lookback_sessions": LOOKBACK,
        "cadence_sessions": CADENCE,
        "cadence_anchor": "source row zero; never reset at reporting boundaries",
        "grade_floor": "A",
        "cap": CAP,
        "gross": "min(1, eligible A/A+ count * cap), identical to /5",
        "turnover_budget": (
            "max(same-reset /5 target turnover, minimum feasible target turnover)"
        ),
        "turnover_basis": "L1 target change; realized account turnover separate",
        "turnover_relaxation": "minimum required by changed eligibility/gross only",
        "missing_covariance": "candidate basket unavailable; explicit cash target",
        "execution": "stock-index-cash-adapter/1-research; next adjusted open",
        "cash_yield": 0.0,
        "costs_bps": list(COSTS),
        "controls": list(LINES[1:]),
        "control_execution": "identical funded daily accounts and 20-session resets",
        "live_parity": False,
        "adoption_eligible": False,
    }


# Reject ambiguous calendars, malformed eligibility and price-basis declarations.
def validate(panel, grades, eligible, provenance):  # noqa: C901 - explicit refusals
    dates = np.asarray(panel.dates)
    symbols = tuple(panel.tickers)
    if (
        dates.ndim != 1
        or dates.dtype != np.dtype("datetime64[D]")
        or len(dates) < 2
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("ordered, unique daily sessions are required")
    if (
        len(symbols) < 3
        or len(set(symbols)) != len(symbols)
        or any(not isinstance(s, str) or not s or s.strip() != s for s in symbols)
        or not {"SPY", "QQQ"}.issubset(symbols)
    ):
        raise ValueError("unique stock symbols plus SPY and QQQ are required")
    shape = (len(dates), len(symbols))
    prices = {}
    for key in ("open", "close", "adj_close"):
        value = np.asarray(getattr(panel, key))
        if value.shape != shape or value.dtype.kind not in "iuf":
            raise ValueError(f"{key} must match the numeric source grid")
        if np.isinf(value).any() or np.any(np.isfinite(value) & (value <= 0)):
            raise ValueError("prices must be positive or explicitly missing")
        prices[key] = value.astype(float, copy=True)
    grades, eligible = np.asarray(grades), np.asarray(eligible)
    if grades.shape != shape or grades.dtype.kind not in "iu":
        raise ValueError("integer grades must match the source grid")
    if np.any((grades < -1) | (grades > 3)):
        raise ValueError(
            "grades must be unknown (-1) or the declared C through A+ scale"
        )
    if eligible.shape != shape or eligible.dtype.kind != "b":
        raise ValueError("explicit Boolean membership must match the source grid")
    if np.any(eligible[:, [symbols.index("SPY"), symbols.index("QQQ")]]):
        raise ValueError("benchmarks cannot be eligible book members")
    if (
        not isinstance(provenance, dict)
        or provenance.get("price_basis") != "close-ratio-adjusted"
    ):
        raise ValueError("explicit close-ratio-adjusted price basis required")
    if provenance.get("eligibility_mode") not in (
        "archived-point-in-time",
        "recomputed-current-vintage",
        "conditional-price-only",
    ):
        raise ValueError("explicit grade/membership evidence mode required")
    hashes = provenance.get("source_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("source hashes are required")
    if any(
        not isinstance(h, str)
        or len(h) != 64
        or any(c not in "0123456789abcdef" for c in h)
        for h in hashes.values()
    ):
        raise ValueError("source hashes must be lowercase SHA256 values")
    return (
        SimpleNamespace(dates=dates.copy(), tickers=symbols, **prices),
        grades.copy(),
        eligible.copy(),
    )


# Load optional optimizers lazily so absence cannot masquerade as a successful strategy.
def dependencies():
    try:
        import cvxpy as cp
        from skfolio.moments import LedoitWolf
        from skfolio.prior import EmpiricalPrior
    except ImportError as exc:
        raise RuntimeError(
            "skfolio and cvxpy must be installed in an isolated research environment"
        ) from exc
    return cp, LedoitWolf, EmpiricalPrior


# Minimize covariance with an explicit total-L1 constraint independent of API semantics.
def optimize(returns, previous, gross, total_budget, forced_exits):
    cp, covariance_class, prior_class = dependencies()
    previous = np.asarray(previous, dtype=float)
    selected_budget = max(0.0, total_budget - forced_exits)
    if len(previous) * CAP == gross:
        result = np.full(len(previous), CAP)
        if np.abs(result - previous).sum() > selected_budget + 1e-12:
            raise RuntimeError("unique capped allocation violates turnover budget")
        return result
    if selected_budget <= 1e-12 and abs(previous.sum() - gross) <= 1e-12:
        return previous.copy()

    # Bind the entire investable weight change rather than each name separately.
    def constraint(weights):
        delta = gross - float(previous.sum())
        if abs(selected_budget - abs(delta)) <= 1e-12:
            # At the feasibility boundary, every change must have the same sign.
            return weights >= previous if delta >= 0 else weights <= previous
        return cp.norm1(weights - previous) <= selected_budget

    prior = prior_class(covariance_estimator=covariance_class()).fit(returns)
    covariance = prior.return_distribution_.covariance
    weights = cp.Variable(len(previous))
    # Direct variance avoids a redundant norm epigraph at narrow turnover bounds.
    problem = cp.Problem(
        cp.Minimize(cp.quad_form(weights, covariance)),
        [weights >= 0.0, weights <= CAP, cp.sum(weights) == gross, constraint(weights)],
    )
    problem.solve(solver="CLARABEL", tol_gap_abs=1e-10, tol_feas=1e-10)
    if problem.status != cp.OPTIMAL:
        raise RuntimeError("optimizer did not establish an optimal solution")
    weights = np.asarray(weights.value, dtype=float)
    if (
        weights.shape != previous.shape
        or not np.isfinite(weights).all()
        or np.any(weights < -1e-8)
        or np.any(weights > CAP + 1e-8)
        or abs(weights.sum() - gross) > 1e-8
        or np.abs(weights - previous).sum() + forced_exits > total_budget + 1e-8
    ):
        raise RuntimeError("optimizer violated the declared portfolio contract")
    # Numerical dust is neither a short position nor a deliberate over-cap target.
    result = np.clip(weights, 0.0, CAP)
    if result.sum() > gross:
        result *= gross / result.sum()
    return result


# Read only the current eligible basket and its completed trailing return observations.
def candidate_target(panel, grades, eligible, t, previous, reference_turnover):
    base = policy_v5.targets(
        grades[t], panel.adj_close[t], eligible[t], panel.tickers.index("SPY")
    )
    selected = base > 0
    evidence = {"session": str(panel.dates[t]), "eligible_names": int(selected.sum())}
    if not selected.any():
        return base, {**evidence, "status": "empty_basket"}
    if t < LOOKBACK:
        return np.zeros_like(base), {
            **evidence,
            "status": "unavailable",
            "reason": "insufficient trailing sessions",
        }
    history = panel.adj_close[t - LOOKBACK : t + 1, selected]
    if not np.isfinite(history).all() or np.any(history <= 0):
        return np.zeros_like(base), {
            **evidence,
            "status": "unavailable",
            "reason": "missing trailing covariance prices",
        }
    returns = history[1:] / history[:-1] - 1.0
    gross = float(base.sum())
    forced = float(previous[~selected].sum())
    minimum = forced + abs(gross - float(previous[selected].sum()))
    budget = max(reference_turnover, minimum)
    out = np.zeros_like(base)
    out[selected] = optimize(returns, previous[selected], gross, budget, forced)
    return out, {
        **evidence,
        "status": "optimized",
        "lookback_start": str(panel.dates[t - LOOKBACK]),
        "information_through": str(panel.dates[t]),
        "gross": gross,
        "minimum_turnover": minimum,
        "declared_turnover_budget": budget,
        "target_turnover": float(np.abs(out - previous).sum()),
        "reference_target_turnover": reference_turnover,
        "turnover_relaxed": minimum > reference_turnover + 1e-10,
    }


# Build immutable close-time paths on the original cadence for all funded controls.
def paths(panel, grades, eligible, first):
    all_rows, observations = {}, []
    for line in LINES:
        previous = np.zeros(len(panel.tickers))
        previous_reference = np.zeros(len(panel.tickers))
        rows = []
        for t in range(first, len(panel.dates) - 1):
            reset = t == first or t % CADENCE == 0
            target = None
            if reset:
                if line == POLICY:
                    reference = policy_v5.targets(
                        grades[t],
                        panel.adj_close[t],
                        eligible[t],
                        panel.tickers.index("SPY"),
                    )
                    reference_turnover = float(
                        np.abs(reference - previous_reference).sum()
                    )
                    target, observation = candidate_target(
                        panel, grades, eligible, t, previous, reference_turnover
                    )
                    previous_reference = reference
                    observations.append(observation)
                elif line == policy_v5.POLICY_VERSION:
                    target = policy_v5.targets(
                        grades[t],
                        panel.adj_close[t],
                        eligible[t],
                        panel.tickers.index("SPY"),
                    )
                elif line == "equal-weight-pit":
                    keep = eligible[t] & np.isfinite(panel.adj_close[t])
                    target = keep.astype(float) / max(1, int(keep.sum()))
                else:
                    target = np.zeros(len(panel.tickers))
                    target[panel.tickers.index(line)] = 1.0
                previous = target.copy()
            stock = (
                None
                if target is None
                else {
                    s: float(target[j])
                    for j, s in enumerate(panel.tickers)
                    if s not in ("SPY", "QQQ")
                }
            )
            rows.append(
                AllocationInstruction(
                    session=str(panel.dates[t]),
                    information_through=str(panel.dates[t]),
                    evidence_id=f"{line}:{panel.dates[t]}",
                    stock_scale=1.0,
                    spy_weight=float(previous[panel.tickers.index("SPY")]),
                    qqq_weight=float(previous[panel.tickers.index("QQQ")]),
                    stock_weights=stock,
                    rebalance=reset,
                )
            )
        all_rows[line] = rows
    return all_rows, observations


# Compute net metrics and common-calendar rolling wins without restarting each window.
def summarize(account, reference_accounts):
    dates = account["dates"][1:]
    returns = account["nav"][1:] / account["nav"][:-1] - 1.0
    windows = (
        ("all", None, None),
        ("2016-20", "2016-01-01", "2021-01-01"),
        ("2021-26", "2021-01-01", "2027-01-01"),
    )
    rows = []
    for name, start, end in windows:
        keep = (
            np.ones(len(dates), dtype=bool)
            if start is None
            else (dates >= np.datetime64(start)) & (dates < np.datetime64(end))
        )
        count = int(keep.sum())
        if not count:
            rows.append({"window": name, "status": "unavailable", "sessions": 0})
            continue
        stats = metrics(returns[keep])
        rows.append(
            {
                "window": name,
                "status": "measured",
                "sessions": count,
                "start": str(dates[keep][0]),
                "end": str(dates[keep][-1]),
                "cagr": stats["annual"],
                "max_drawdown_loss": stats["drawdown"],
                "sharpe_zero_cash_yield": stats["sharpe"],
                "total_return": stats["total"],
                "turnover_one_way": float(account["turnover"][1:][keep].sum()),
                "turnover_annualized": float(
                    account["turnover"][1:][keep].sum() * 252 / count
                ),
                "fees_account_units": float(account["fees"][1:][keep].sum()),
            }
        )
    wins = {}
    if len(returns) >= 252:
        own = account["nav"][252:] / account["nav"][:-252]
        for line, other in reference_accounts.items():
            comparison = other["nav"][252:] / other["nav"][:-252]
            wins[line] = {
                "windows": len(own),
                "win_rate": float(np.mean(own > comparison)),
            }
    return {"windows": rows, "rolling_252_against": wins}


# Price fixed causal paths once at each declared cost using the existing funded ledger.
def backtest(panel, grades, eligible, provenance, *, start="2016-01-04"):
    panel, grades, eligible = validate(panel, grades, eligible, provenance)
    if not isinstance(start, str) or date.fromisoformat(start).isoformat() != start:
        raise ValueError("start must be a plain YYYY-MM-DD date")
    first = int(np.searchsorted(panel.dates, np.datetime64(start, "D")))
    if first >= len(panel.dates) - 1:
        raise ValueError("start must leave at least one executable next session")
    dependencies()
    instructions, observations = paths(panel, grades, eligible, first)
    costs = []
    for cost in COSTS:
        accounts = {
            line: replay(panel, rows, first=first, cost_bps=cost)
            for line, rows in instructions.items()
        }
        rows = []
        for line, account in accounts.items():
            rows.append(
                {
                    "line": line,
                    **summarize(account, accounts),
                    "instruction_path_sha256": account["instruction_path"]["sha256"],
                }
            )
        costs.append(
            {
                "cost_bps": cost,
                "results": rows,
                "curves": {
                    line: {
                        key: account[key].tolist()
                        for key in ("nav", "cash", "fees", "turnover")
                    }
                    for line, account in accounts.items()
                },
            }
        )
    spec = specification()
    return {
        "schema": "open-source-portfolio-backtest/1",
        "specification": spec,
        "specification_sha256": digest(spec),
        "provenance": provenance,
        "dates": panel.dates[first:].astype(str).tolist(),
        "costs": costs,
        "candidate_observations": observations,
        "candidate_unavailable_resets": sum(
            o["status"] == "unavailable" for o in observations
        ),
        "eligible_unknown_grade_cells": int(
            (eligible[first:] & (grades[first:] < 0)).sum()
        ),
        "skfolio_version": importlib.metadata.version("skfolio"),
        "adoption_eligible": False,
        "historical_availability_verified": False,
        "limitations": [
            "Conditional supplied grades/membership; no exact live reconstruction.",
            "Daily fills omit intraday dip timing, exits, FOMC and broker settlement.",
            "Target changes constrained; actual funded turnover reported separately.",
            "Split reports retain account state; no fitting on outcomes.",
        ],
    }


# Load a pickle-free supplied snapshot without fetching data or touching source files.
def load_snapshot(path, provenance_path):
    path = Path(path)
    with np.load(path, allow_pickle=False) as data:
        needed = {
            "dates",
            "symbols",
            "open",
            "close",
            "adj_close",
            "grades",
            "eligible",
        }
        if not needed.issubset(data.files):
            raise ValueError(
                "snapshot is missing declared price/grade/membership arrays"
            )
        panel = SimpleNamespace(
            dates=data["dates"],
            tickers=tuple(data["symbols"].tolist()),
            open=data["open"],
            close=data["close"],
            adj_close=data["adj_close"],
        )
        grades, eligible = data["grades"], data["eligible"]
    provenance = json.loads(Path(provenance_path).read_text())
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if provenance.get("snapshot_sha256") != actual:
        raise ValueError("snapshot SHA256 does not match supplied provenance")
    return (*validate(panel, grades, eligible, provenance), provenance)
