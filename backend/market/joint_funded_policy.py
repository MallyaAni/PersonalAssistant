"""Optional authenticated joint-risk decisions on the real funded paper path.

No production caller selects this policy. Missing risk is not a company exit;
cash is observed before any sale, and protected or unpriced holdings block
discretionary optimization. Existing event handling remains the dispatcher's.
"""

import hashlib
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import allocation, funded_execution, paper
from backend.market import adaptive_growth_policy as growth
from backend.market.direct_error_band import VolatilityHoldingReader
from backend.market.forward_arithmetic import ForwardVolatilityHoldingReader

POLICY = "joint-stock-risk-funded/1-research"
MATURITY_POLICY = "joint-stock-risk-funded/2-maturity-shadow"
CALIBRATED_POLICY = "joint-stock-risk-funded/3-log-calibration-research"
TIMED_POLICY = "joint-stock-risk-funded/4-calibrated-probability-timing-research"
HORIZON = "next_open_to_following_open_arithmetic_return"
PROTOCOL = "docs/research/joint-funded-account-plan-2026-10-04.md"
MATURITY_PROTOCOL = "docs/research/risk-qualified-funded-plan-2026-10-04.md"


# Refuse ambiguous account values rather than treating missing funding as zero.
def _number(value, *, positive=False):
    return (
        not isinstance(value, (bool, np.bool_))
        and isinstance(value, (int, float, np.integer, np.floating))
        and np.isfinite(value)
        and (value > 0 if positive else value >= 0)
    )


# Separate spendable cash from reserved wealth and refuse unvalued positions.
def _account(equity, held, prices, cash):
    if not _number(equity, positive=True) or not _number(cash):
        return {}, None, "account_cash_or_equity_unavailable"
    if any(not _number(qty) or float(qty) % 1 for qty in held.values()):
        return {}, None, "whole_share_holdings_unavailable"
    if any(
        qty > 0 and not _number(prices.get(name), positive=True)
        for name, qty in held.items()
    ):
        return {}, None, "held_mark_unavailable"
    marked = {
        name: float(qty) * float(prices[name]) for name, qty in held.items() if qty > 0
    }
    current = {name: value / float(equity) for name, value in marked.items()}
    if (
        not np.isfinite(list(marked.values())).all()
        or float(cash) / float(equity) + sum(current.values()) > 1 + 1e-10
    ):
        return {}, None, "inconsistent_account_equity"
    return current, max(0.0, float(equity) - float(cash) - sum(marked.values())), None


# Bind the reviewed reader and fixed fees without fitting or contacting a broker.
class JointFundedPolicy:
    version = POLICY
    protocol = PROTOCOL

    # Admit original or published forward risk on the still-private funded path.
    def __init__(self, reader, cost_bps):
        if not isinstance(
            reader, (VolatilityHoldingReader, ForwardVolatilityHoldingReader)
        ):
            raise ValueError("Authenticated volatility holding reader required")
        if not _number(cost_bps) or cost_bps >= 10000:
            raise ValueError("Finite per-side costs below 10000 bp required")
        self.reader = reader
        self.cost_bps = float(cost_bps)
        root = Path(__file__).resolve().parents[2]
        self.identity = {
            "policy": self.version,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "protocol_sha256": hashlib.sha256(
                (root / self.protocol).read_bytes()
            ).hexdigest(),
            "cost_bps": self.cost_bps,
            "horizon": HORIZON,
            "adoption_eligible": False,
        }

    # Require the entire original grade-eligible book without risk-based exclusions.
    def _required_stocks(self, grades, current, day, blocked, *, refusal=None):
        names = tuple(
            sorted(
                name
                for name, grade in grades.items()
                if grade >= 2 or (grade == 1 and current.get(name, 0) > 0)
            )
        )
        return names, {}

    # Decide from actual refreshed account marks and this completed report only.
    def decide(self, session, report, equity, held, prices, cash, blocked):
        if str(report.panel.dates[-1]) != session:
            raise ValueError("Exact current report session required")
        if isinstance(self.reader, ForwardVolatilityHoldingReader):
            self.reader.validate_report(report)
        dates = self.reader.dates
        hits = np.flatnonzero(dates == np.datetime64(session, "D"))
        if len(hits) != 1 or not np.array_equal(
            report.panel.dates, dates[: hits[0] + 1]
        ):
            raise ValueError("Original reader and complete report calendar required")
        last = len(report.panel.dates) - 1
        grades = {
            name: int(report.graded.grades[last, column])
            for column, name in enumerate(report.panel.tickers)
            if name not in ("SPY", "QQQ")
        }
        if any(value not in (-1, 0, 1, 2, 3) for value in grades.values()):
            raise ValueError("Observed ordinal grades required")
        receipt = {
            **self.identity,
            "session": session,
            "grades": grades,
            "status": "unavailable",
            "observed_equity": float(equity)
            if _number(equity, positive=True)
            else None,
            "observed_cash": float(cash) if _number(cash) else None,
        }
        current, reserve, reason = _account(equity, held, prices, cash)
        receipt["reserved_wealth"] = reserve
        receipt["current_weights"] = current
        exits = sorted(name for name in current if grades.get(name) == 0)
        protected = sorted(
            name for name in current if name not in grades or grades[name] < 0
        )
        targets = {
            name: weight for name, weight in current.items() if name not in exits
        }
        receipt.update(
            company_exits=exits,
            protected_holdings=protected,
            buy_blocked=sorted(blocked),
        )
        if reason is None and protected:
            reason = "protected_held_risk_unavailable"
        names, qualification = self._required_stocks(
            grades, current, int(hits[0]), blocked, refusal=reason
        )
        reason = reason or qualification.pop("refusal_reason", None)
        receipt.update(qualification)
        if reason is None and any(name not in self.reader.symbols for name in names):
            reason = "joint_symbol_unavailable"
        if reason is None and names:
            sample = self.reader.distribution(int(hits[0]), names)
            receipt["scenario"] = sample.receipt
            if sample.receipt["status"] != "available":
                reason = "joint_risk_unavailable"
            else:
                ordered = (*names, *exits)
                permission = np.array(
                    [1 if name in blocked else grades[name] for name in names]
                    + [0] * len(exits)
                )
                values = np.c_[
                    sample.scenarios, np.zeros((len(sample.scenarios), len(exits)))
                ]
                weights, proof = growth.allocate_distribution(
                    values,
                    sample.probabilities,
                    permission,
                    np.ones(len(ordered), dtype=bool),
                    np.array([current.get(name, 0.0) for name in ordered]),
                    float(cash) / float(equity),
                    self.cost_bps,
                    np.array([], dtype=np.int64),
                    horizon=HORIZON,
                )
                receipt["optimizer"] = proof
                if proof["status"] != "optimized":
                    reason = "joint_optimizer_unavailable"
                else:
                    targets.update(zip(ordered, weights.tolist(), strict=True))
        receipt.update(
            status="unavailable" if reason else "available",
            reason=reason or "joint_net_growth",
            targets=targets,
        )
        return targets, receipt

    # Convert a certified target to durable whole-share orders without sale funding.
    def plan(self, session, state, equity, held, prices, report, cash, blocked):
        new = paper.PaperState(**asdict(state))
        if session in state.sessions_seen:
            return [], new, "already planned for this session"
        targets, receipt = self.decide(
            session, report, equity, held, prices, cash, blocked
        )
        orders = []
        account_reason = receipt["reason"] in {
            "account_cash_or_equity_unavailable",
            "whole_share_holdings_unavailable",
            "held_mark_unavailable",
            "inconsistent_account_equity",
        }
        if not account_reason:
            decision = allocation.AllocationDecision(
                self.version,
                session,
                targets,
                max(0.0, 1 - sum(targets.values())),
                receipt["status"] == "available",
                (receipt["reason"],),
                (),
                None,
                allocation.BINDING_NONE,
            )
            basket = funded_execution.plan_funded(
                decision,
                held,
                prices,
                equity,
                cash,
                cost_bps=self.cost_bps,
                whole_shares=True,
                index_eligible=False,
                entry_cap=growth.CAP,
                min_trade=0.0,
            )
            receipt["execution"] = {
                "version": basket.version,
                "blocked": list(basket.blocked),
                "missing": list(basket.missing),
                "projected_liquid_cash": basket.projected_cash_amount,
                "projected_liquid_equity": basket.projected_equity,
                "projection_is_fill": False,
            }
            for order in basket.orders:
                seq = new.order_seq
                new.order_seq += 1
                orders.append(
                    paper.PaperOrder(
                        order.symbol,
                        order.side,
                        int(order.qty),
                        "company exit"
                        if order.symbol in receipt["company_exits"]
                        else "joint net-growth allocation",
                        client_order_id=paper.order_id(
                            session, order.symbol, order.side, seq
                        ),
                        execution_timing="next_open",
                    )
                )
        new.sessions_seen = [*state.sessions_seen, session]
        new.policy_version = self.version
        new.deferred_buys = {}
        new.opened = {
            name: day for name, day in state.opened.items() if held.get(name, 0) > 0
        }
        new.allocation_state = {
            "policy": self.version,
            "as_of": session,
            "targets": targets,
            "receipt": receipt,
        }
        return (
            orders,
            new,
            "joint-funded"
            if receipt["status"] == "available"
            else "joint-funded-unavailable",
        )


# Qualify new exposure from mature risk without removing mandatory held stocks.
class MaturityFundedPolicy(JointFundedPolicy):
    version = MATURITY_POLICY
    protocol = MATURITY_PROTOCOL

    # Exclude only unheld entrants and then retain one simultaneous required book.
    def _required_stocks(self, grades, current, day, blocked, *, refusal=None):
        candidates, _ = super()._required_stocks(grades, current, day, blocked)
        if refusal is not None:
            return candidates, {
                "entry_qualification": {
                    "policy": self.version,
                    "status": "not_evaluated",
                    "reason": refusal,
                }
            }
        required, admitted, retained, excluded = [], [], [], {}
        for name in candidates:
            if current.get(name, 0) > 0:
                retained.append(name)
                required.append(name)
            elif name in blocked:
                excluded[name] = {"reason": "buy_permission_blocked"}
            else:
                risk = self.reader.distribution(day, (name,))
                if risk.receipt["status"] == "available":
                    admitted.append(name)
                    required.append(name)
                else:
                    excluded[name] = {
                        "reason": "entry_risk_unavailable",
                        "risk": risk.receipt,
                    }
        return tuple(required), {
            "refusal_reason": "entry_risk_unavailable"
            if not required
            and any(
                row["reason"] == "entry_risk_unavailable" for row in excluded.values()
            )
            else None,
            "entry_qualification": {
                "policy": self.version,
                "considered_entrants": [
                    name for name in candidates if name not in retained
                ],
                "admitted_entrants": admitted,
                "mandatory_held": retained,
                "excluded_entries": excluded,
                "selection_uses_future_outcomes": False,
                "joint_risk_still_required": True,
            },
        }


# Use conditional scenarios for both additions and held exits on the private account.
class CalibratedMaturityFundedPolicy(MaturityFundedPolicy):
    version = CALIBRATED_POLICY
    protocol = "docs/research/conditional-holding-calibration-plan-2026-10-05.md"

    # Wrap original history or published current risk without altering default policies.
    def __init__(self, reader, cost_bps):
        from backend.market.conditional_holding_calibration import (
            CalibratedHoldingReader,
            ForwardCalibratedHoldingReader,
        )

        if type(reader) is VolatilityHoldingReader:
            reader = CalibratedHoldingReader(reader)
        elif type(reader) is ForwardVolatilityHoldingReader:
            reader = ForwardCalibratedHoldingReader(reader)
        elif type(reader) not in (
            CalibratedHoldingReader,
            ForwardCalibratedHoldingReader,
        ):
            raise ValueError(
                "Original or calibrated authenticated risk reader required"
            )
        super().__init__(reader, cost_bps)


# Join calibrated quantities to learned execution without delaying mandatory exits.
class ProbabilityTimedFundedPolicy(CalibratedMaturityFundedPolicy):
    version = TIMED_POLICY
    protocol = "docs/research/joint-probability-timing-plan-2026-10-05.md"
    timing_policy = "live-probability-timing/1-research"
    execution_rule = timing_policy

    # Preserve allocation economics and authenticate the separate execution mechanism.
    def __init__(self, reader, cost_bps):
        from backend.market import live_probability_timing

        if self.timing_policy != live_probability_timing.POLICY:
            raise ValueError("Registered probability timing version required")
        super().__init__(reader, cost_bps)
        self.identity.update(
            timing_policy=self.timing_policy,
            timing_source_sha256=hashlib.sha256(
                Path(live_probability_timing.__file__).read_bytes()
            ).hexdigest(),
            timing_horizon="one_decision_log_price_advantage",
        )

    # Route ordinary allocation intents intraday while keeping company exits immediate.
    def plan(self, session, state, equity, held, prices, report, cash, blocked):
        from backend.agents.trading.desk import intraday_orders

        orders, new, what = super().plan(
            session, state, equity, held, prices, report, cash, blocked
        )
        if not orders:
            return orders, new, what
        receipt = new.allocation_state["receipt"]
        exits = set(receipt["company_exits"])
        routed = [
            replace(order, execution_timing=intraday_orders.INTRADAY_TIMING)
            if order.symbol not in exits and not order.event_id and not order.priority
            else order
            for order in orders
        ]
        receipt["execution_timing"] = {
            "ordinary": self.timing_policy,
            "company_exit": "next_open",
            "orders": {
                order.client_order_id: order.execution_timing for order in routed
            },
        }
        return routed, new, what
