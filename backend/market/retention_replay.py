"""Account-aware research adapter for fixed held-B retention comparisons.

Destination proposals are forecast inputs, never available cash or fills.
Execution remains the simulator's shared cash-constrained planner.
"""

from __future__ import annotations

import numpy as np

from backend.agents.trading.desk import paper, policy_v5
from backend.market.learned_retention import (
    RetentionPlan,
    plan_retention,
    reset_targets,
)


class RetentionAdapter:
    # Bind one immutable symbol/date grid and one declared comparison arm.
    def __init__(
        self, symbols, eligible, relative, spy, cost_bps, *, unconditional=False
    ):
        self.symbols = tuple(symbols)
        self.eligible = np.array(eligible, copy=True)
        self.relative = np.array(relative, dtype=float, copy=True)
        self.spy = np.array(spy, dtype=float, copy=True)
        if (
            not self.symbols
            or len(set(self.symbols)) != len(self.symbols)
            or self.eligible.ndim != 2
            or self.eligible.dtype.kind != "b"
            or self.relative.shape != self.eligible.shape
            or self.eligible.shape[1] != len(self.symbols)
            or self.spy.shape != (len(self.eligible),)
            or np.isinf(self.relative).any()
            or np.isinf(self.spy).any()
            or not isinstance(unconditional, bool)
            or isinstance(cost_bps, bool)
            or not np.isfinite(cost_bps)
            or not 0 <= cost_bps < 10000
        ):
            raise ValueError(
                "Aligned finite-or-missing forecasts and eligibility required"
            )
        self.cost_bps = float(cost_bps)
        self.unconditional = unconditional
        self.events = []
        for values in (self.eligible, self.relative, self.spy):
            values.setflags(write=False)

    # Compare ordinary B exits with their unchanged incumbent destination proposal.
    def _plan(self, t, grades, prices, held, nav, weights, blocked, mandatory):
        size = len(self.symbols)
        if self.unconditional:
            retained = np.zeros(size)
            valid = (grades == 1) & self.eligible[t] & (held > 0) & ~mandatory
            retained[valid] = np.minimum(
                held[valid], policy_v5.HOLD_CAP * nav / prices[valid]
            )
            mask = retained > 0
            result = RetentionPlan(
                retained,
                mask,
                np.where(mask, retained * prices / nav, 0),
                self.eligible[t] & (grades >= 2) & ~blocked & ~mandatory,
                np.full(size, np.nan),
                tuple("unconditional_retain" if item else "incumbent" for item in mask),
            )
        else:
            try:
                result = plan_retention(
                    grades,
                    self.eligible[t],
                    prices,
                    held,
                    nav,
                    self.relative[t],
                    weights,
                    hard_cap=policy_v5.HOLD_CAP,
                    cost_bps=self.cost_bps,
                    blocked=blocked,
                    thesis_exits=mandatory,
                    spy_forecast=float(self.spy[t])
                    if np.isfinite(self.spy[t])
                    else None,
                    trim_to_cap=True,
                )
            except ValueError as exc:
                if str(exc) != "Replacement destination exceeds the existing hard cap":
                    raise
                self.events.append({"day": int(t), "boundary": "destination_capacity"})
                return None
        for stock in np.flatnonzero((grades == 1) & (held > 0)):
            self.events.append(
                {
                    "day": int(t),
                    "symbol": self.symbols[stock],
                    "reason": result.reasons[stock],
                    "retained_shares": float(result.retained_shares[stock]),
                    "edge": float(result.edge[stock])
                    if np.isfinite(result.edge[stock])
                    else None,
                }
            )
        return result

    # Reserve retained marked weight before the unchanged reset basket is funded.
    def reset(self, t, target, prices, held, cash, grades, blocked):
        nav = float(cash + np.where(held > 0, held * prices, 0).sum())
        marked = np.where(held > 0, held * prices, 0)
        shortfalls = np.where(blocked, 0, np.maximum(target * nav - marked, 0))
        released = float(np.maximum(marked - target * nav, 0).sum())
        weights = np.zeros(len(self.symbols))
        if released > 0 and shortfalls.sum() > 0:
            weights = shortfalls / max(released, float(shortfalls.sum()))
        mandatory = (grades < 1) | ~self.eligible[t]
        plan = self._plan(t, grades, prices, held, nav, weights, blocked, mandatory)
        if plan is None or not plan.retain_mask.any():
            return target.copy()
        # Preserve gated A holdings outside the basket that can receive fresh capital.
        protected = np.where(blocked, target, 0)
        return protected + reset_targets(
            np.where(blocked, 0, target),
            plan,
            hard_cap=policy_v5.HOLD_CAP,
            stock_budget=1.0 - float(protected.sum()),
        )

    # Remove only ordinary B exits, then let the shared planner rebuild funding.
    def midcycle(self, t, prices, held, grades, finished, excluded, equity, cash):
        ordinary = {
            symbol
            for symbol, reason in finished.items()
            if reason == "grade rotation"
            and grades.get(symbol) == "B"
            and held.get(symbol, 0) > 0
        }
        if not ordinary:
            return dict(finished), set(excluded), {}
        ordinal = {"C": 0, "B": 1, "A": 2, "A+": 3}
        values = np.array([prices.get(s, np.nan) for s in self.symbols], dtype=float)
        quantities = np.array([held.get(s, 0) for s in self.symbols], dtype=float)
        grade_values = np.array([ordinal.get(grades.get(s), -1) for s in self.symbols])
        blocked = np.array([s in excluded for s in self.symbols])
        mandatory = np.array(
            [s in finished and s not in ordinary for s in self.symbols]
        )
        proposal = paper._rotation_orders(
            finished, held, prices, equity, str(t), paper.PaperState(), excluded, False
        )
        released = sum(o.qty * prices[o.symbol] for o in proposal if o.side == "sell")
        weights = np.zeros(len(self.symbols))
        if released > 0:
            for order in proposal:
                if order.side == "buy":
                    weights[self.symbols.index(order.symbol)] += (
                        order.qty * prices[order.symbol] / released
                    )
        plan = self._plan(
            t, grade_values, values, quantities, equity, weights, blocked, mandatory
        )
        if plan is None:
            return dict(finished), set(excluded), {}
        retained = {
            s: float(plan.retained_shares[j])
            for j, s in enumerate(self.symbols)
            if plan.retain_mask[j] and s in ordinary
        }
        return (
            {s: reason for s, reason in finished.items() if s not in retained},
            set(excluded) | set(retained),
            retained,
        )
