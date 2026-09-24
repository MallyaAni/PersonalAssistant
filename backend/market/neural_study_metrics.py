"""Pure scorecards for already evaluated, matched research accounts.

No prices are fetched and no portfolio is simulated here. SPY, QQQ and any
equal-weight control must arrive as actual account curves under the declared
execution/cost assumptions, not uncharged normalized prices. The caller owns
exchange-calendar completeness and input/execution provenance.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

SESSIONS_PER_YEAR = 252
ROLLING_WINDOWS = (63, 252)


@dataclass(frozen=True)
class Curve:
    """An account's net NAV and cumulative bought-plus-sold notional."""

    dates: np.ndarray
    equity: np.ndarray
    cost_bps: float
    traded_notional: float | None = None


# Preserve the simulator's actual account NAV and traded-dollar definition.
def from_simulation(result, cost_bps: float) -> Curve:
    if result.equity is None:
        raise ValueError("The simulator did not provide account equity")
    return Curve(
        np.asarray(result.dates).copy(),
        np.asarray(result.equity, dtype=float).copy(),
        cost_bps,
        float(result.traded),
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
    return dates, equity


# Calculate net daily-return statistics without treating a short sample as a year.
def _metrics(equity, traded_notional):
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
            None if traded_notional is None else float(traded_notional / equity[0])
        ),
        "annual_traded_notional_over_mean_nav": (
            None
            if traded_notional is None
            else float(traded_notional / np.mean(equity) / years)
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


# Compare already charged accounts only when every date and declared cost matches.
def scorecard(curves: Mapping[str, Curve], *, cost_bps: float) -> dict:
    """Return one 10- or 25-bp table, including SPY/QQQ rolling comparisons.

    Equal weight, incumbent and candidate curves are supplied by the caller;
    this helper never replaces their missing outcomes or rebalances their NAVs.
    """
    if cost_bps not in (10, 25):
        raise ValueError("The declared study reports 10 and 25 basis points")
    if not {"SPY", "QQQ"}.issubset(curves):
        raise ValueError("Both SPY and QQQ account curves are required")
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
    rows = {}
    for name, equity in checked.items():
        rows[name] = _metrics(equity, curves[name].traded_notional)
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
        "provenance": (
            "Supplied account curves; costs and execution are caller-attested"
        ),
        "rows": rows,
    }
