"""Pure scorecards for already evaluated, matched research accounts.

No prices are fetched and no portfolio is simulated here. SPY, QQQ and the
equal-weight control must arrive as actual account curves under the declared
execution/cost assumptions, not uncharged normalized prices. The caller owns
exchange-calendar completeness and input/execution provenance.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral

import numpy as np

from backend.market.harness import walk_forward_folds

SESSIONS_PER_YEAR = 252
ROLLING_WINDOWS = (63, 252)
REQUIRED_ACCOUNTS = frozenset({"candidate", "incumbent", "SPY", "QQQ", "equal_weight"})
PRIMARY_COMPARATORS = ("incumbent", "SPY", "QQQ")
REGIME_NAMES = (
    "above_200_mean_high_volatility",
    "above_200_mean_low_volatility",
    "below_200_mean_high_volatility",
    "below_200_mean_low_volatility",
    "unknown_or_unavailable",
)
TREND_SESSIONS = 200
VOLATILITY_SESSIONS = 20
VOLATILITY_MEDIAN_OBSERVATIONS = 252


@dataclass(frozen=True)
class Curve:
    """An account's net NAV, trading, exposure, and concentration evidence."""

    dates: np.ndarray
    equity: np.ndarray
    cost_bps: float
    traded_notional: float | None = None
    invested_fraction: np.ndarray | None = None
    largest_position_fraction: np.ndarray | None = None


@dataclass(frozen=True)
class RegimeEvidence:
    """Point-in-time SPY adjusted closes, including pre-evaluation warm-up."""

    dates: np.ndarray
    spy_adjusted_closes: np.ndarray


# Preserve the simulator's account, trading, exposure, and concentration evidence.
def from_simulation(result, cost_bps: float) -> Curve:
    if result.equity is None:
        raise ValueError("The simulator did not provide account equity")
    return Curve(
        np.asarray(result.dates).copy(),
        np.asarray(result.equity, dtype=float).copy(),
        cost_bps,
        float(result.traded),
        (
            None
            if getattr(result, "invested", None) is None
            else np.asarray(result.invested, dtype=float).copy()
        ),
        (
            None
            if getattr(result, "top_weight", None) is None
            else np.asarray(result.top_weight, dtype=float).copy()
        ),
    )


# Refuse omitted marks or dates instead of silently changing the comparison sample.
def _validated(curve: Curve):
    dates = np.asarray(curve.dates)
    equity = np.asarray(curve.equity, dtype=float)
    if dates.ndim != 1 or dates.dtype != np.dtype("datetime64[D]"):
        raise ValueError(
            "Daily session dates are required without timestamp truncation"
        )
    if len(dates) < 2 or np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("At least two sorted unique sessions are required")
    if equity.shape != dates.shape:
        raise ValueError("One equity observation is required for every session")
    if not np.isfinite(equity).all() or np.any(equity <= 0):
        raise ValueError("Missing or nonpositive account marks invalidate the curve")
    if curve.traded_notional is not None and (
        not math.isfinite(curve.traded_notional) or curve.traded_notional < 0
    ):
        raise ValueError("Traded notional must be finite and nonnegative")
    for label, values in (
        ("Invested fraction", curve.invested_fraction),
        ("Largest-position fraction", curve.largest_position_fraction),
    ):
        if values is None:
            continue
        fractions = np.asarray(values, dtype=float)
        if (
            fractions.shape != dates.shape
            or not np.isfinite(fractions).all()
            or np.any(fractions < 0)
            or np.any(fractions > 1 + 1e-12)
        ):
            raise ValueError(f"{label} requires one finite value in [0, 1] per session")
    return dates, equity


# Validate the complete, fixed comparison set on one unchanged session grid.
def _checked_curves(curves: Mapping[str, Curve], cost_bps: float):
    if cost_bps not in (10, 25):
        raise ValueError("The declared study reports 10 and 25 basis points")
    missing = REQUIRED_ACCOUNTS.difference(curves)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"The comparison is missing required accounts: {names}")
    checked = {}
    reference = None
    for name, curve in curves.items():
        dates, equity = _validated(curve)
        if curve.cost_bps != cost_bps:
            raise ValueError(f"{name}: execution costs differ from the comparison")
        if reference is None:
            reference = dates
        elif not np.array_equal(dates, reference):
            raise ValueError(
                f"{name}: account dates differ; no inner join is permitted"
            )
        checked[name] = equity
    return reference, checked


# Calculate net daily-return statistics without treating a short sample as a year.
def _metrics(equity, curve):
    intervals = len(equity) - 1
    years = intervals / SESSIONS_PER_YEAR
    returns = equity[1:] / equity[:-1] - 1
    net = float(equity[-1] / equity[0] - 1)
    try:
        cagr = math.expm1(math.log(equity[-1] / equity[0]) / years)
    except OverflowError as exc:
        raise ValueError("Annualized return is outside finite numerical range") from exc
    deviation = float(np.std(returns, ddof=1)) if intervals > 1 else 0.0
    # Constant compounded returns can leave rounding variance, not measured risk.
    resolution = 8 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(returns))))
    sharpe = (
        float(np.mean(returns) / deviation * math.sqrt(SESSIONS_PER_YEAR))
        if deviation > resolution
        else None
    )
    return {
        "return_intervals": intervals,
        "total_return": net,
        "cagr": cagr,
        "max_drawdown": float(np.min(equity / np.maximum.accumulate(equity) - 1)),
        "sharpe_zero_risk_free": sharpe,
        "traded_notional_per_starting_nav": (
            None
            if curve.traded_notional is None
            else float(curve.traded_notional / equity[0])
        ),
        "annual_traded_notional_over_mean_nav": (
            None
            if curve.traded_notional is None
            else float(curve.traded_notional / np.mean(equity) / years)
        ),
        "fees_paid_per_starting_nav": (
            None
            if curve.traded_notional is None
            else float(curve.traded_notional * curve.cost_bps / 1e4 / equity[0])
        ),
        "mean_invested_fraction": (
            None
            if curve.invested_fraction is None
            else float(np.mean(curve.invested_fraction))
        ),
        "maximum_invested_fraction": (
            None
            if curve.invested_fraction is None
            else float(np.max(curve.invested_fraction))
        ),
        "mean_largest_position_fraction": (
            None
            if curve.largest_position_fraction is None
            else float(np.mean(curve.largest_position_fraction))
        ),
        "maximum_largest_position_fraction": (
            None
            if curve.largest_position_fraction is None
            else float(np.max(curve.largest_position_fraction))
        ),
    }


# Count strict wins on identical overlapping windows, keeping ties explicit.
def _rolling_wins(equity, benchmark, window):
    count = len(equity) - window
    if count <= 0:
        return {"windows": 0, "win_rate": None, "ties": 0}
    own = equity[window:] / equity[:-window]
    other = benchmark[window:] / benchmark[:-window]
    tied = np.isclose(own, other, rtol=1e-12, atol=1e-12)
    wins = (own > other) & ~tied
    return {
        "windows": count,
        "win_rate": float(np.mean(wins)),
        "ties": int(tied.sum()),
    }


# State whether the candidate strictly beats every fixed primary comparator.
def _primary_objective(rows):
    candidate = rows["candidate"]["total_return"]
    margins = {
        benchmark: float(candidate - rows[benchmark]["total_return"])
        for benchmark in PRIMARY_COMPARATORS
    }
    return {
        "metric": "net_total_return",
        "candidate": "candidate",
        "comparators": list(PRIMARY_COMPARATORS),
        "candidate_minus_comparator": margins,
        "passes": all(margin > 0 for margin in margins.values()),
    }


# Compare already charged accounts only when every date and declared cost matches.
def scorecard(curves: Mapping[str, Curve], *, cost_bps: float) -> dict:
    """Return one matched 10- or 25-bp table with every fixed control.

    Equal weight, incumbent and candidate curves are supplied by the caller;
    this helper never replaces their missing outcomes or rebalances their NAVs.
    """
    reference, checked = _checked_curves(curves, cost_bps)
    rows = {}
    for name, equity in checked.items():
        rows[name] = _metrics(equity, curves[name])
        rows[name]["rolling_win_rate"] = {
            benchmark: {
                str(window): _rolling_wins(equity, checked[benchmark], window)
                for window in ROLLING_WINDOWS
            }
            for benchmark in ("SPY", "QQQ", "incumbent")
            if benchmark in checked
        }
    return {
        "first_session": str(reference[0]),
        "last_session": str(reference[-1]),
        "cost_bps": float(cost_bps),
        "cash_yield": 0.0,
        "annualization_sessions": SESSIONS_PER_YEAR,
        "rolling_windows_overlap": True,
        "rolling_tie_tolerance": {"relative": 1e-12, "absolute": 1e-12},
        "turnover_definition": (
            "Bought-plus-sold notional divided by starting NAV; annual figure uses "
            "mean observed NAV and elapsed session-years. Neither is the sum of "
            "individual trade notional divided by contemporaneous NAV."
        ),
        "fees_definition": (
            "Bought-plus-sold notional times the declared one-way cost, divided by "
            "starting NAV; unavailable when traded notional was not retained."
        ),
        "exposure_definition": (
            "Mean and maximum fraction of account NAV invested at supplied session "
            "marks; unavailable when the account did not retain that path."
        ),
        "concentration_definition": (
            "Mean and maximum largest-position share of account NAV at supplied "
            "session marks; unavailable when the account did not retain that path."
        ),
        "provenance": (
            "Supplied account curves; costs and execution are caller-attested"
        ),
        "primary_objective": _primary_objective(rows),
        "rows": rows,
    }


# Validate adjusted-close regime evidence while preserving bad values as unavailable.
def _validated_regime_evidence(evidence: RegimeEvidence):
    dates = np.asarray(evidence.dates)
    closes = np.asarray(evidence.spy_adjusted_closes, dtype=float)
    if dates.ndim != 1 or dates.dtype != np.dtype("datetime64[D]"):
        raise ValueError("Daily SPY evidence dates are required without truncation")
    if len(dates) < 2 or np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("Sorted unique SPY evidence sessions are required")
    if closes.shape != dates.shape:
        raise ValueError(
            "One point-in-time SPY adjusted close is required per evidence session"
        )
    return dates, closes


# Align evaluated sessions to a contiguous slice of the declared SPY evidence.
def _evidence_positions(account_dates, evidence_dates):
    positions = np.searchsorted(evidence_dates, account_dates)
    if np.any(positions >= len(evidence_dates)) or not np.array_equal(
        evidence_dates[positions], account_dates
    ):
        raise ValueError("SPY regime evidence must contain every account session")
    if np.any(np.diff(positions) != 1):
        raise ValueError("Account sessions must be contiguous in SPY regime evidence")
    return positions


# Calculate causal trailing volatility observations from raw close-to-close log returns.
def _trailing_volatility(closes):
    daily = np.full(len(closes), np.nan, dtype=float)
    valid_pair = (
        np.isfinite(closes[1:])
        & np.isfinite(closes[:-1])
        & (closes[1:] > 0)
        & (closes[:-1] > 0)
    )
    valid_indices = np.flatnonzero(valid_pair) + 1
    daily[valid_indices] = np.log(closes[valid_indices]) - np.log(
        closes[valid_indices - 1]
    )
    volatility = np.full(len(closes), np.nan, dtype=float)
    for end in range(VOLATILITY_SESSIONS, len(closes)):
        sample = daily[end - VOLATILITY_SESSIONS + 1 : end + 1]
        if np.isfinite(sample).all():
            volatility[end] = float(np.std(sample))
    return volatility


# Label each account return using only SPY evidence known before it began.
def regime_labels(account_dates, evidence: RegimeEvidence) -> np.ndarray:
    """Return one fixed trend/volatility label per account return interval."""
    account_dates = np.asarray(account_dates)
    if account_dates.ndim != 1 or account_dates.dtype != np.dtype("datetime64[D]"):
        raise ValueError("Daily account dates are required without truncation")
    if (
        len(account_dates) < 2
        or np.isnat(account_dates).any()
        or np.any(account_dates[1:] <= account_dates[:-1])
    ):
        raise ValueError("At least two sorted unique account sessions are required")
    evidence_dates, closes = _validated_regime_evidence(evidence)
    positions = _evidence_positions(account_dates, evidence_dates)
    volatility = _trailing_volatility(closes)
    labels = np.full(
        len(account_dates) - 1,
        REGIME_NAMES[-1],
        dtype=f"<U{max(map(len, REGIME_NAMES))}",
    )
    for interval, prior in enumerate(positions[:-1]):
        trend_start = prior - TREND_SESSIONS + 1
        median_start = prior - VOLATILITY_MEDIAN_OBSERVATIONS + 1
        if trend_start < 0 or median_start < 0:
            continue
        trend_sample = closes[trend_start : prior + 1]
        volatility_sample = volatility[median_start : prior + 1]
        if (
            not np.isfinite(closes[prior])
            or closes[prior] <= 0
            or not np.isfinite(trend_sample).all()
            or np.any(trend_sample <= 0)
            or not np.isfinite(volatility_sample).all()
        ):
            continue
        trend_mean = float(np.mean(trend_sample))
        volatility_median = float(np.median(volatility_sample))
        trend_side = "above" if closes[prior] >= trend_mean else "below"
        volatility_side = "high" if volatility[prior] > volatility_median else "low"
        labels[interval] = f"{trend_side}_200_mean_{volatility_side}_volatility"
    return labels


# Attribute log growth to selected intervals without annualizing a stitched segment.
def _conditional_metrics(equity, selected):
    chosen = np.diff(np.log(equity))[selected]
    if len(chosen) == 0:
        return {
            "return_intervals": 0,
            "log_growth_contribution": None,
            "compounded_selected_return": None,
            "mean_daily_log_return_bps": None,
        }
    log_growth = float(np.sum(chosen))
    try:
        total_return = math.expm1(log_growth)
    except OverflowError as exc:
        raise ValueError(
            "Conditional return is outside finite numerical range"
        ) from exc
    return {
        "return_intervals": int(len(chosen)),
        "log_growth_contribution": log_growth,
        "compounded_selected_return": total_return,
        "mean_daily_log_return_bps": float(np.mean(chosen) * 10000),
    }


# Describe a regime's chronology without treating months or episodes as trials.
def _regime_chronology(return_dates, selected):
    months = return_dates.astype("datetime64[M]")
    chosen_months = np.unique(months[selected])
    episodes = int(np.sum(selected & np.r_[True, ~selected[:-1]]))
    return len(chosen_months), episodes


# Compare the candidate's selected log returns with one matched comparator.
def _conditional_comparison(candidate, benchmark, selected, return_dates):
    if not np.any(selected):
        return {
            "excess_log_growth_contribution": None,
            "mean_daily_excess_log_bps": None,
            "positive_month_fraction": None,
        }
    excess = (np.diff(np.log(candidate)) - np.diff(np.log(benchmark)))[selected]
    selected_months = return_dates[selected].astype("datetime64[M]")
    monthly = np.asarray(
        [
            float(excess[selected_months == month].sum())
            for month in np.unique(selected_months)
        ]
    )
    return {
        "excess_log_growth_contribution": float(excess.sum()),
        "mean_daily_excess_log_bps": float(excess.mean() * 10000),
        "positive_month_fraction": float(np.mean(monthly > 0)),
    }


# Decompose matched account returns across the four frozen causal market regimes.
def regime_scorecard(
    curves: Mapping[str, Curve], *, cost_bps: float, evidence: RegimeEvidence
) -> dict:
    """Return fixed-regime compounded growth without selecting a switching rule."""
    reference, checked = _checked_curves(curves, cost_bps)
    labels = regime_labels(reference, evidence)
    regimes = {}
    return_dates = reference[1:]
    for name in REGIME_NAMES:
        selected = labels == name
        rows = {
            account: _conditional_metrics(equity, selected)
            for account, equity in checked.items()
        }
        comparisons = {
            benchmark: _conditional_comparison(
                checked["candidate"], checked[benchmark], selected, return_dates
            )
            for benchmark in PRIMARY_COMPARATORS
        }
        return_sessions = return_dates[selected]
        observed_months, episodes = _regime_chronology(return_dates, selected)
        contributions = [
            comparison["excess_log_growth_contribution"]
            for comparison in comparisons.values()
        ]
        regimes[name] = {
            "return_intervals": int(selected.sum()),
            "months_with_observations": observed_months,
            "contiguous_episodes": episodes,
            "first_return_session": (
                None if len(return_sessions) == 0 else str(return_sessions[0])
            ),
            "last_return_session": (
                None if len(return_sessions) == 0 else str(return_sessions[-1])
            ),
            "candidate_comparisons": comparisons,
            "candidate_beats_all_primary_comparators": (
                None
                if not np.any(selected)
                else all(value > 0 for value in contributions)
            ),
            "rows": rows,
        }
    return {
        "first_session": str(reference[0]),
        "last_session": str(reference[-1]),
        "cost_bps": float(cost_bps),
        "return_intervals": len(reference) - 1,
        "regime_intervals_reconcile": sum(
            block["return_intervals"] for block in regimes.values()
        )
        == len(reference) - 1,
        "regime_order": list(REGIME_NAMES),
        "definition": {
            "timing": (
                "The return ending on session t uses SPY evidence only through the "
                "preceding account session t-1."
            ),
            "trend": (
                "Point-in-time SPY adjusted close at t-1 at or above, otherwise "
                "below, the arithmetic mean of 200 adjusted closes ending at t-1."
            ),
            "volatility": (
                "Population standard deviation of 20 close-to-close SPY log returns "
                "ending at t-1, high only when above the median of 252 such "
                "observations ending at t-1; equality is low."
            ),
            "unknown": (
                "Insufficient or invalid evidence remains unknown; no return "
                "interval is dropped."
            ),
        },
        "conditional_path": (
            "Each row attributes the regime's one-session net log growth without "
            "restarting an account or annualizing stitched segments. It is not a "
            "regime-switching account."
        ),
        "regimes": regimes,
    }


# Keep starting NAV and interval diagnostics without inventing local trading totals.
def _fold_curve(curve: Curve, intervals: range) -> Curve:
    marks = slice(intervals.start, intervals.stop + 1)
    return Curve(
        dates=curve.dates[marks],
        equity=curve.equity[marks],
        cost_bps=curve.cost_bps,
        traded_notional=None,
        invested_fraction=(
            None if curve.invested_fraction is None else curve.invested_fraction[marks]
        ),
        largest_position_fraction=(
            None
            if curve.largest_position_fraction is None
            else curve.largest_position_fraction[marks]
        ),
    )


# Describe every selected or excluded return interval on the original account grid.
def _interval_coverage(dates, labels, start: int, stop: int) -> dict:
    return {
        "start_index": start,
        "stop_index_exclusive": stop,
        "return_intervals": stop - start,
        "starting_nav_session": None if start == stop else str(dates[start]),
        "first_return_session": None if start == stop else str(dates[start + 1]),
        "last_return_session": None if start == stop else str(dates[stop]),
        "regime_intervals": {
            name: int(np.sum(labels[start:stop] == name)) for name in REGIME_NAMES
        },
    }


# Compare local fold returns with each fixed benchmark, retaining ties separately.
def _fold_comparisons(rows) -> dict:
    comparisons = {}
    for account, row in rows.items():
        comparisons[account] = {}
        for benchmark in PRIMARY_COMPARATORS:
            if benchmark == account:
                continue
            margin = row["total_return"] - rows[benchmark]["total_return"]
            comparisons[account][benchmark] = {
                "net_total_return_difference": float(margin),
                "strict_win": bool(margin > 0),
                "tie": bool(margin == 0),
            }
    return comparisons


# Report chronological stability of examined accounts without calling it new validation.
def chronological_fold_scorecard(
    curves_by_cost: Mapping[float, Mapping[str, Curve]],
    *,
    evidence: RegimeEvidence,
    train_size: int,
    test_size: int,
    horizon: int,
    embargo: int = 0,
) -> dict:
    """Slice preserved accounts into purged chronological diagnostic blocks.

    The harness ranges index return intervals: interval i starts at mark i and
    ends at mark i+1. Each fold therefore retains test_size+1 marks. Reference
    history and purge ranges describe hypothetical fitting geometry only; this
    function never fits, selects, resets an account, or creates untouched data.
    """
    for name, value in (
        ("train_size", train_size),
        ("test_size", test_size),
        ("horizon", horizon),
        ("embargo", embargo),
    ):
        if isinstance(value, bool) or not isinstance(value, Integral):
            raise ValueError(f"{name} must be an integer number of sessions")
    train_size, test_size, horizon, embargo = map(
        int, (train_size, test_size, horizon, embargo)
    )
    if set(curves_by_cost) != {10, 25}:
        raise ValueError("Both 10 and 25 basis-point account tables are required")
    dates, _ = _checked_curves(curves_by_cost[10], 10)
    stressed_dates, _ = _checked_curves(curves_by_cost[25], 25)
    if not np.array_equal(dates, stressed_dates):
        raise ValueError("Account dates must match across both cost levels")
    if set(curves_by_cost[10]) != set(curves_by_cost[25]):
        raise ValueError("The same accounts are required at both cost levels")
    labels = regime_labels(dates, evidence)
    n_intervals = len(dates) - 1
    ranges = walk_forward_folds(n_intervals, train_size, test_size, horizon, embargo)
    first_test = min(train_size + horizon + embargo, n_intervals)
    evaluated_stop = first_test + len(ranges) * test_size
    partitions = {
        "reference_prefix": _interval_coverage(dates, labels, 0, first_test),
        "evaluated_folds": _interval_coverage(
            dates, labels, first_test, evaluated_stop
        ),
        "incomplete_tail": _interval_coverage(
            dates, labels, evaluated_stop, n_intervals
        ),
    }
    folds = []
    for number, (train, test) in enumerate(ranges, start=1):
        costs = {}
        for cost in (10, 25):
            sliced = {
                name: _fold_curve(curve, test)
                for name, curve in curves_by_cost[cost].items()
            }
            performance = scorecard(sliced, cost_bps=cost)
            costs[str(cost)] = {
                "performance": performance,
                "comparisons": _fold_comparisons(performance["rows"]),
                "regimes": regime_scorecard(sliced, cost_bps=cost, evidence=evidence),
            }
        folds.append(
            {
                "fold": number,
                "reference_history": {
                    "start_index": train.start,
                    "stop_index_exclusive": train.stop,
                    "decision_sessions": len(train),
                    "first_decision_session": str(dates[train.start]),
                    "last_decision_session": str(dates[train.stop - 1]),
                    "last_hypothetical_label_session": str(
                        dates[train.stop - 1 + horizon]
                    ),
                    "used_to_fit": False,
                },
                "purge_and_embargo": {
                    "start_index": train.stop,
                    "stop_index_exclusive": test.start,
                    "decision_sessions": test.start - train.stop,
                },
                "evaluation": _interval_coverage(dates, labels, test.start, test.stop),
                "cost_levels": costs,
            }
        )
    return {
        "analysis": "post_hoc_chronological_stability",
        "independent_validation": False,
        "adoption_eligible": False,
        "refit_performed": False,
        "status": "available" if folds else "insufficient_complete_folds",
        "parameters": {
            "train_size": int(train_size),
            "test_size": int(test_size),
            "horizon": int(horizon),
            "embargo": int(embargo),
        },
        "coverage": {
            "return_intervals": n_intervals,
            "complete_folds": len(folds),
            "partitions": partitions,
            "all_intervals_accounted_for": sum(
                part["return_intervals"] for part in partitions.values()
            )
            == n_intervals,
        },
        "full_sample": {
            str(cost): scorecard(curves_by_cost[cost], cost_bps=cost)
            for cost in (10, 25)
        },
        "folds": folds,
        "interpretation": (
            "Already-examined accounts sliced after outcomes were known. Test "
            "returns do not overlap, but the blocks are not independent trials "
            "or untouched out-of-sample evidence. Reference and purge geometry "
            "does not verify actual training, selection, or input availability. "
            "Existing survivorship, reconstruction, and source-vintage limitations "
            "remain. Exchange-session completeness and execution/cost provenance "
            "remain caller-attested."
        ),
        "account_continuity": (
            "Folds retain the continuous account's existing positions and net "
            "starting NAV. No fresh capital, entry trade, exit trade, or additional "
            "cost is simulated at a boundary. Fold drawdowns and rolling windows "
            "use only marks within that fold."
        ),
        "fold_trading_evidence": (
            "Fold turnover and fees are unavailable: a full-sample traded-notional "
            "total cannot be assigned to individual folds. Net NAV already includes "
            "the declared trading costs; none are subtracted again."
        ),
    }
