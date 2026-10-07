"""Experimental purchase/cash-exit selection from causal ten-session forecasts.

These are mean-log comparisons with cash, not execution orders, calibrated
probabilities, expected terminal wealth or an optimal portfolio allocation.
"""

from dataclasses import dataclass

import numpy as np

from backend.market.learned_retention import _mask, _numbers, _scalar

POLICY = "learned-cash-selection/1"
MODES = ("joint", "quantity_control", "buy_only", "exit_only")


# Keep purchase permission separate from covered discretionary exit proposals.
@dataclass(frozen=True)
class CashSelection:
    no_buy: np.ndarray
    cash_exit: np.ndarray
    cash_exit_shares: np.ndarray
    absolute_mean: np.ndarray
    buy_edge: np.ndarray
    hold_edge: np.ndarray
    reasons: tuple[str, ...]


# Compare ordinary eligible A/A+ positions with the declared zero-yield cash leg.
def select_cash_opportunities(  # noqa: C901 - retain explicit evidence refusal/fallback
    grades,
    eligible,
    prices,
    held,
    nav,
    relative,
    spy,
    cost_bps,
    *,
    mandatory=None,
    mode="joint",
):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Explicit supported cash-selection mode required")
    raw = np.asarray(grades)
    if raw.ndim != 1 or not len(raw):
        raise ValueError("Nonempty ordinal grade vector required")
    size = len(raw)
    grades = _numbers(raw, (size,), "grades")
    if np.any(grades != np.floor(grades)) or np.any((grades < -1) | (grades > 3)):
        raise ValueError("Ordinal grades must be -1 through3")
    eligible = _mask(eligible, size, "eligible")
    mandatory = _mask(mandatory, size, "mandatory", optional=True)
    prices = _numbers(prices, (size,), "prices", missing=True)
    held = _numbers(held, (size,), "held")
    relative = _numbers(relative, (size,), "relative", missing=True)
    if np.isinf(prices).any() or np.isinf(relative).any() or np.any(held < 0):
        raise ValueError(
            "Finite-or-missing prices/forecasts and nonnegative holdings required"
        )
    if np.any(np.isfinite(prices) & (prices <= 0)) or np.any(
        (held > 0) & ~np.isfinite(prices)
    ):
        raise ValueError("Positive finite prices required for existing holdings")
    nav = _scalar(nav, "nav", 0, np.inf, lower_inclusive=False)
    with np.errstate(over="ignore", invalid="ignore"):
        marked = np.where(held > 0, held * prices, 0)
    if not np.isfinite(marked).all() or marked.sum() > nav * (1 + 1e-10):
        raise ValueError("Existing marked holdings cannot exceed NAV")
    cost = _scalar(cost_bps, "cost_bps", 0, 10000) / 10000
    if cost == 1:
        raise ValueError("Cost must be below10000bp")
    if spy is None:
        spy = np.nan
    elif (
        isinstance(spy, (bool, np.bool_))
        or not isinstance(spy, (int, float, np.integer, np.floating))
        or np.isinf(spy)
    ):
        raise ValueError("Finite-or-missing numeric SPY forecast required")
    absolute = np.full(size, np.nan)
    known = np.isfinite(relative) & np.isfinite(spy)
    with np.errstate(over="ignore", invalid="ignore"):
        absolute[known] = relative[known] + spy
    if np.any(known & ~np.isfinite(absolute)):
        raise ValueError("Absolute forecast exceeds finite numerical range")
    buy_edge = absolute - np.log1p(cost)
    hold_edge = absolute - np.log1p(-cost)
    ordinary = eligible & (grades >= 2) & ~mandatory
    cash_exit = (
        ordinary & known & (held > 0) & (hold_edge < 0)
        if mode in ("joint", "exit_only")
        else np.zeros(size, dtype=bool)
    )
    no_buy = (
        ordinary & known & (buy_edge <= 0)
        if mode in ("joint", "buy_only")
        else cash_exit.copy()
    )
    quantities = np.where(cash_exit, held, 0)
    reasons = []
    for column in range(size):
        if mandatory[column]:
            reason = "mandatory_incumbent"
        elif not ordinary[column]:
            reason = "ineligible_incumbent"
        elif not known[column]:
            reason = "forecast_unavailable"
        elif cash_exit[column]:
            reason = "forecast_cash_exit"
        elif no_buy[column]:
            reason = "purchase_no_edge"
        elif mode == "quantity_control":
            reason = "quantity_control"
        elif mode == "exit_only":
            reason = "exit_preserves_purchase"
        else:
            reason = "purchase_edge"
        reasons.append(reason)
    for value in (no_buy, cash_exit, quantities, absolute, buy_edge, hold_edge):
        value.setflags(write=False)
    return CashSelection(
        no_buy, cash_exit, quantities, absolute, buy_edge, hold_edge, tuple(reasons)
    )


# Bind frozen model arrays to one account's selection receipts without fitting.
class CashSelectionAdapter:
    # Preserve the declared stock/date grid and reject ambiguous forecast inputs.
    def __init__(
        self, symbols, eligible, relative, spy, cost_bps, *, dates, mode="joint"
    ):
        if not isinstance(mode, str) or mode not in MODES:
            raise ValueError("Explicit supported cash-selection mode required")
        self.mode = mode
        self.symbols = tuple(symbols)
        raw_dates = np.asarray(dates)
        if raw_dates.ndim != 1 or raw_dates.dtype.kind != "M":
            raise ValueError(
                "Explicit chronological datetime64 forecast calendar required"
            )
        self.dates = raw_dates.astype("datetime64[D]", copy=True)
        if np.any(np.isnat(self.dates)) or np.any(self.dates[1:] <= self.dates[:-1]):
            raise ValueError("Forecast calendar must contain unique increasing dates")
        self.eligible = np.array(eligible, copy=True)
        raw_relative, raw_spy = np.asarray(relative), np.asarray(spy)
        self.relative = np.array(raw_relative, dtype=float, copy=True)
        self.spy = np.array(raw_spy, dtype=float, copy=True)
        if (
            not self.symbols
            or any(
                not isinstance(name, str) or not name.strip() for name in self.symbols
            )
            or len(set(self.symbols)) != len(self.symbols)
            or self.eligible.ndim != 2
            or not len(self.eligible)
            or len(self.dates) != len(self.eligible)
            or self.eligible.dtype.kind != "b"
            or self.eligible.shape[1] != len(self.symbols)
            or self.relative.shape != self.eligible.shape
            or self.spy.shape != (len(self.eligible),)
            or raw_relative.dtype.kind not in "iuf"
            or raw_spy.dtype.kind not in "iuf"
            or np.isinf(self.relative).any()
            or np.isinf(self.spy).any()
        ):
            raise ValueError(
                "Aligned numeric forecasts and boolean eligibility required"
            )
        for column, name in enumerate(self.symbols):
            if name in ("SPY", "QQQ") and np.isfinite(self.relative[:, column]).any():
                raise ValueError("Stock forecasts must exclude benchmark symbols")
        self.cost_bps = _scalar(cost_bps, "cost_bps", 0, 10000)
        if self.cost_bps == 10000:
            raise ValueError("Cost must be below10000bp")
        for values in (self.dates, self.eligible, self.relative, self.spy):
            values.setflags(write=False)
        self.events = []

    # Read exactly one causal row and retain both purchase and holding comparisons.
    def decide(self, t, grades, prices, held, nav, mandatory=None):
        if (
            isinstance(t, bool)
            or not isinstance(t, (int, np.integer))
            or not 0 <= t < len(self.eligible)
        ):
            raise ValueError("Decision index outside the declared forecast calendar")
        plan = select_cash_opportunities(
            grades,
            self.eligible[t],
            prices,
            held,
            nav,
            self.relative[t],
            self.spy[t],
            self.cost_bps,
            mandatory=mandatory,
            mode=self.mode,
        )
        for column in np.flatnonzero(np.asarray(grades) >= 2):
            self.events.append(
                {
                    "day": int(t),
                    "symbol": self.symbols[column],
                    "reason": plan.reasons[column],
                    "no_buy": bool(plan.no_buy[column]),
                    "cash_exit_shares": float(plan.cash_exit_shares[column]),
                    "absolute_mean": float(plan.absolute_mean[column])
                    if np.isfinite(plan.absolute_mean[column])
                    else None,
                    **({"mode": self.mode} if self.mode != "joint" else {}),
                }
            )
        return plan
