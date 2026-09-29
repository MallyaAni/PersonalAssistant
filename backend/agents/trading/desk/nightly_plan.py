"""Account-independent nightly inputs and the existing account planner boundary.

Broker reconciliation, submission and account-state persistence stay with their
caller. A saved block describes the inputs actually used; it is not a personal
account enrollment or permission to execute a historical plan.
"""

from copy import deepcopy

from backend.agents.trading.desk import event_execution, event_risk, live_policy, paper

SCHEMA = "nightly-planner-inputs/1"


# Preserve the executor's raw-close sizing and its original symbol ordering.
def build(report, session: str) -> dict:
    panel = report.panel
    last = len(panel.dates) - 1
    return {
        "schema": SCHEMA,
        "session": session,
        "price_session": str(panel.dates[last]),
        "allocation_policy": live_policy.ACTIVE,
        "execution_policy": paper.POLICY_VERSION,
        "event_policy_version": event_risk.VERSION,
        "price_basis": "raw_close",
        "entry_basis": "adjusted_close_bollinger_z",
        "prices": {
            ticker: float(panel.close[last, column])
            for column, ticker in enumerate(panel.tickers)
            if panel.close[last, column] == panel.close[last, column]
        },
        "targets": live_policy.targets(report),
        "grades": {
            ticker: report.graded.letter(last, column)
            for column, ticker in enumerate(panel.tickers)
            if ticker != panel.benchmark
        },
    }


# Event protection and unresolved orders never depend on entry-band calculation.
def uses_event_plan(state: paper.PaperState, policy: dict) -> bool:
    return bool(
        state.pending
        or state.event_cycle
        or policy.get("factor") == event_risk.REDUCED
        or not policy["calendar_known"]
    )


# Attach the context at its existing position after broker reconciliation.
def complete(inputs, policy, blocking_flags, *, entries=None, downgrades=None) -> dict:
    return {
        **deepcopy(inputs),
        "event_policy": deepcopy(policy),
        "blocking_flags": dict(blocking_flags),
        # None means not evaluated on the event/pending branch, never no signal.
        "entries": deepcopy(entries),
        # All covered downgrades, not merely the paper account's held names.
        "downgrades": deepcopy(downgrades),
    }


# Run unchanged planners on an independent account state, with no external effects.
def plan(inputs, state, equity, held, cash, *, force_rebalance=False):
    expected = {
        "schema": SCHEMA,
        "allocation_policy": live_policy.ACTIVE,
        "execution_policy": paper.POLICY_VERSION,
        "event_policy_version": event_risk.VERSION,
    }
    for field, version in expected.items():
        if inputs.get(field) != version:
            raise ValueError(f"Unsupported nightly planner {field}")
    state = deepcopy(state)
    session = inputs["session"]
    policy = inputs["event_policy"]
    prices = inputs["prices"]
    if uses_event_plan(state, policy):
        return event_execution.plan(session, state, held, prices, cash, policy)
    if inputs["entries"] is None or inputs["downgrades"] is None:
        raise ValueError("Ordinary nightly planner inputs were not evaluated")
    return paper.plan(
        session,
        state,
        equity,
        held,
        prices,
        inputs["targets"],
        inputs["grades"],
        finished={s: why for s, why in inputs["downgrades"].items() if held.get(s)},
        force_rebalance=force_rebalance,
        entry_blocked={s for s, blocked in inputs["blocking_flags"].items() if blocked},
        entries=inputs["entries"],
        cash=cash,
    )


# Only a block from an actual planner call supersedes the legacy record fallback.
def recorded(entry: dict | None, session: str) -> dict | None:
    inputs = (entry or {}).get("planner_inputs")
    if not isinstance(inputs, dict) or inputs.get("schema") != SCHEMA:
        return None
    if inputs.get("session") != session or inputs.get("price_session") != session:
        return None
    return deepcopy(inputs)


# Expand the exact planner targets to the record's existing all-graded-name shape.
def record_targets(inputs: dict) -> dict:
    return {
        "policy": inputs["allocation_policy"],
        "weights": {s: inputs["targets"].get(s, 0.0) for s in inputs["grades"]},
    }
