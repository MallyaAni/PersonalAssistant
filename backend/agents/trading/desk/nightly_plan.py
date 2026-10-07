"""Pure dispatch for the current nightly paper planner and its execution clock.

Broker reconciliation, cancellation, policy-change force inference, durable
intent writes and submission remain the caller's responsibilities. An explicit
private research policy can replace ordinary planning; default calls retain
both underlying planners and event handling takes priority in either case.
"""

from dataclasses import asdict, replace

from backend.agents.trading.desk import (
    event_execution,
    event_risk,
    intraday_orders,
    live_policy,
    paper,
)


# Tag ordinary orders on the current board clock while preserving event priorities.
def on_the_boards_clock(orders):
    if not intraday_orders.INTRADAY_EXECUTION:
        return list(orders)
    return [
        replace(order, execution_timing=intraday_orders.INTRADAY_TIMING)
        if not order.event_id and not order.priority
        else order
        for order in orders
    ]


# Select the event path before evaluating ordinary entry and rotation features.
def event_plan_required(state, event_policy):
    return bool(
        state.pending
        or state.event_cycle
        or event_policy.get("factor") == event_risk.REDUCED
        or not event_policy["calendar_known"]
    )


# Dispatch reconciled inputs with event priority and optional named research planning.
def plan(
    session,
    state,
    equity,
    held,
    prices,
    targets,
    grades,
    event_policy,
    *,
    finished,
    entry_blocked,
    entries,
    cash,
    force_rebalance=False,
    holding_policy=None,
    report=None,
):
    planning_state = paper.PaperState(**asdict(state))
    if event_plan_required(state, event_policy):
        orders, new_state, what = event_execution.plan(
            session, planning_state, held, prices, cash, event_policy
        )
    elif holding_policy is not None:
        orders, new_state, what = holding_policy.plan(
            session, planning_state, equity, held, prices, report, cash, entry_blocked
        )
    else:
        orders, new_state, what = paper.plan(
            session,
            planning_state,
            equity,
            held,
            prices,
            targets,
            grades,
            finished=finished,
            force_rebalance=force_rebalance,
            entry_blocked=entry_blocked,
            entries=entries,
            cash=cash,
        )
        orders = on_the_boards_clock(orders)
    if holding_policy is not None:
        new_state.policy_version = holding_policy.version
    elif not live_policy.needs_rebalance(state.policy_version) or what == "rebalance":
        new_state.policy_version = live_policy.ACTIVE
    return orders, new_state, what
