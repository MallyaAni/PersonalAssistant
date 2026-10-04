"""Optional authenticated joint-risk decisions on the real funded paper path.

No production caller selects this policy. Missing risk is not a company exit;
cash is observed before any sale, and protected or unpriced holdings block
discretionary optimization. Existing event handling remains the dispatcher's.
"""

import hashlib
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import allocation, funded_execution, paper
from backend.market import adaptive_growth_policy as growth
from backend.market.direct_error_band import VolatilityHoldingReader
from backend.market.forward_arithmetic import ForwardVolatilityHoldingReader

POLICY = "joint-stock-risk-funded/1-research"
HORIZON = "next_open_to_following_open_arithmetic_return"
PROTOCOL = "docs/research/joint-funded-account-plan-2026-10-04.md"


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
            "policy": POLICY,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "protocol_sha256": hashlib.sha256(
                (root / PROTOCOL).read_bytes()
            ).hexdigest(),
            "cost_bps": self.cost_bps,
            "horizon": HORIZON,
            "adoption_eligible": False,
        }

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
        names = tuple(
            sorted(
                name
                for name, grade in grades.items()
                if grade >= 2 or (grade == 1 and current.get(name, 0) > 0)
            )
        )
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
                POLICY,
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
        new.policy_version = POLICY
        new.deferred_buys = {}
        new.opened = {
            name: day for name, day in state.opened.items() if held.get(name, 0) > 0
        }
        new.allocation_state = {
            "policy": POLICY,
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
