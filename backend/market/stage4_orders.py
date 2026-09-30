"""Stage 4's orders: every buy and sell the live executor makes, from its journal.

`docs/research/stage4-plan-2026-09-29.md` ("The decision", "The decision
test") re-times every order of the live executor as the `ew-redeploy`
control runs it. This module produces those orders; `stage4_decisions`
prices them.

**The run.** `run_control` is stage 3's T-S1 control line exactly
(`stage3_overlay.price(..., CONTROL, ...)`): `simulate.run` on the
point-in-time report from one start offset, under
`profit_taking.control_options` (the live options plus the redeploy of idle
cash), with `policy_v4.allocator(mask)`, no weight filter and no mid-cycle
trims. The only addition is the journal: an `OrderJournal`, a
`midcycle_ew.Ledger` that also keeps each decision's submitted units. A
journal is passive - the simulator never reads what it records - so the
run's returns are the control's to the bit (`test_stage4_orders.py`).

**What the journal sees.** For every decision session t the simulator
calls `mark(t, ...)` with the closing state of t (after t's own fills) and
then `decision(t, submitted_units, ...)`, where `submitted_units` are the
shares the decision wants to hold. The decision fills in session t + 1
(buys at the open from the cash on hand, sells at the close, a sell held
back when the name opens green) and `mark(t + 1, ...)` follows. So for each
name:

- submitted change = submitted units(t) - shares at mark(t);
- executed change = shares at mark(t + 1) - shares at mark(t), which only
  decision t's fills can move.

**An order** is one changed position (the plan: "Each changed position is
one order, with its side, kind, grade at t and weight"). `basis` fixes which
change:

- `EXECUTED` (the default): the executed change - what the executor
  actually traded. A reset buy the cash on hand could not pay for fills in
  part, and its unpaid rest is retried by the next session's decision, where
  it is an order of that decision; a sell held back on a green open is no
  order at t, and becomes one when a later decision sells it.
- `SUBMITTED`: the submitted change, whether or not it traded. It counts a
  retried remainder twice (at the reset and at the retry) and prices sells
  the executor held back. Kept for the addendum's choice; never the default.

Both changes are kept on every order. The weight is |units| x the adjusted
close at t / NAV at t, the order's notional over the account's equity at the
decision. A change whose weight is not above `DUST` (float residue) is no
order.

**Kinds.** The raw kind is the Ledger's classification of the decision
(`midcycle_ew.Ledger.decision`): `rebalance` (the scheduled reset),
`midcycle` (the live mid-cycle plan: rotation, deferred retry, band entries
and the redeploy of idle cash), `topup` (the reset top-up, not an option of
the control) and `event` (an FOMC lifecycle session or a session whose event
scale changed). The finer `detail`:

- sells: `trim` (the name is graded A or A+ at t), `rotation_exit` (graded
  below A, on a non-reset session), `reset_exit` (graded below A, on a
  reset);
- buys: `retry` (a mid-cycle buy of a name the previous decision deferred -
  its `deferred_units` metadata), `entry` (the name was not held at t), `add`
  (it was held);
- `event_buy` / `event_sell` for every order of an event decision.

The grade is the desk grade at t on the report the simulator ran
(`report.graded.grades[t, j]`; the point-in-time report grades a non-member
C).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np

from backend.agents.trading.desk import grading, policy_v4, simulate
from backend.cli.market_pit_scorecard import _since
from backend.market import profit_taking, stage3_verdict
from backend.market.midcycle_ew import EVENT, MIDCYCLE, REBALANCE, TOPUP, Ledger

if TYPE_CHECKING:
    from backend.agents.trading.desk.desk import DeskReport

PLAN = "docs/research/stage4-plan-2026-09-29.md"
# The control executor: stage 3's T-S1 control line.
CONTROL = profit_taking.CONTROL
# The cost the control run is simulated at. Orders barely depend on it (the
# cost moves cash and NAV); stage 3's T-S1 verdict read its control at 25 bp.
COST_BPS = stage3_verdict.VERDICT_COST_BPS
# Which change is an order.
EXECUTED = "executed"
SUBMITTED = "submitted"
BASES = (EXECUTED, SUBMITTED)
# A change of at most this share of equity is float residue, not an order.
DUST = 1e-12
# The Ledger's decision kinds.
KINDS = (REBALANCE, MIDCYCLE, TOPUP, EVENT)
# The finer classification.
TRIM = "trim"
ROTATION_EXIT = "rotation_exit"
RESET_EXIT = "reset_exit"
ENTRY = "entry"
ADD = "add"
RETRY = "retry"
EVENT_BUY = "event_buy"
EVENT_SELL = "event_sell"
BUY_DETAILS = (ENTRY, ADD, RETRY, EVENT_BUY)
SELL_DETAILS = (ROTATION_EXIT, RESET_EXIT, TRIM, EVENT_SELL)
# Grades: A and A+ are the book's grades.
A = grading.ORDINAL[grading.A]
A_PLUS = grading.ORDINAL[grading.A_PLUS]
B = grading.ORDINAL[grading.B]

assert CONTROL == "ew-redeploy"
assert (A_PLUS, A, B) == (3, 2, 1)


class OrderJournal(Ledger):
    """A `midcycle_ew.Ledger` that also keeps every decision's submitted units.

    The Ledger keeps the decision kinds and the closing marks; this adds,
    per decision session, the submitted units, the reason and the deferred
    units the decision leaves for the next session's retry. It changes
    nothing the simulator does.
    """

    # Start empty, as the Ledger does, with the submitted units per session.
    def __init__(self) -> None:
        super().__init__()
        self.tickers: tuple[str, ...] = ()
        self.submitted: dict[int, np.ndarray] = {}
        self.reasons: dict[int, str] = {}
        self.deferred: dict[int, frozenset[str]] = {}

    # Keep the calendar, the names and the closes the orders are valued at.
    def assert_inputs(
        self, sessions: Any, symbols: Any, opens: Any, closes: Any, cost_bps: float
    ) -> None:
        super().assert_inputs(sessions, symbols, opens, closes, cost_bps)
        self.tickers = tuple(str(s) for s in symbols)

    # Classify the decision as the Ledger does and keep its submitted units.
    # The simulator decides once per session; a second decision on the same
    # session would overwrite the first, so it is refused.
    def decision(
        self,
        session: Any,
        submitted_units: Any,
        desired_weights: Any,
        reason: Any,
        metadata: dict[str, Any] | None,
    ) -> int:
        t = int(session)
        if t in self.submitted:
            raise ValueError(f"two decisions on session {t}")
        handle: int = super().decision(  # type: ignore[no-untyped-call]
            session, submitted_units, desired_weights, reason, metadata
        )
        self.submitted[t] = np.array(submitted_units, dtype=float)
        self.reasons[t] = str(reason)
        deferred = (metadata or {}).get("deferred_units") or {}
        self.deferred[t] = frozenset(
            str(s) for s, qty in deferred.items() if float(qty) > 0
        )
        return handle


@dataclass(frozen=True)
class Orders:
    """One control run's orders, one per changed position, by (session, column)."""

    session: np.ndarray  # (M,) int64: the decision session t (panel row)
    column: np.ndarray  # (M,) int64: the name's panel column
    ticker: np.ndarray  # (M,) str
    side: np.ndarray  # (M,) str: "buy" (units > 0) or "sell"
    units: np.ndarray  # (M,) float: the signed change the basis counts
    submitted: np.ndarray  # (M,) float: the signed submitted change
    executed: np.ndarray  # (M,) float: the signed executed change (t -> t + 1)
    weight: np.ndarray  # (M,) float: |units| x close_t / NAV_t
    kind: np.ndarray  # (M,) str: the Ledger kind of the decision
    detail: np.ndarray  # (M,) str: the finer classification
    grade: np.ndarray  # (M,) int: the desk grade at t
    held: np.ndarray  # (M,) float: shares held at t, before the order
    start: int  # the run's first decision session
    stop: int  # one past its last decision session
    basis: str = EXECUTED
    meta: dict[str, Any] = field(default_factory=dict)

    # The number of orders.
    def __len__(self) -> int:
        return int(len(self.session))

    # True for a buy.
    @property
    def buy(self) -> np.ndarray:
        """Return the (M,) buy flags."""
        return self.side == "buy"

    # The orders `keep` selects (a mask or indices), with the same run bounds;
    # the run-level counts in `meta` do not carry over to a subset.
    def subset(self, keep: np.ndarray) -> Orders:
        """Return the selected orders."""
        return replace(
            self,
            meta={"subset": True},
            session=self.session[keep],
            column=self.column[keep],
            ticker=self.ticker[keep],
            side=self.side[keep],
            units=self.units[keep],
            submitted=self.submitted[keep],
            executed=self.executed[keep],
            weight=self.weight[keep],
            kind=self.kind[keep],
            detail=self.detail[keep],
            grade=self.grade[keep],
            held=self.held[keep],
        )


# The finer classification of one order from its side, the decision's
# kind, the grade at t, whether the name was held at t and whether the
# previous decision deferred a buy of it.
def classify(
    side: str, kind: str, grade: int, held_before: bool, deferred: bool
) -> str:
    """Return the order's detail label."""
    if kind == EVENT:
        return EVENT_BUY if side == "buy" else EVENT_SELL
    if side == "sell":
        if int(grade) >= A:
            return TRIM
        return RESET_EXIT if kind == REBALANCE else ROTATION_EXIT
    if kind == MIDCYCLE and deferred:
        return RETRY
    return ADD if held_before else ENTRY


# How a submitted change traded: not at all, in part, in full, or (never
# expected) beyond it.
def _execution(submitted: float, executed: float) -> str:
    """Return the execution status of one submitted change."""
    if executed == 0.0:
        return "submitted_not_executed"
    if abs(executed) < abs(submitted) * (1.0 - 1e-9):
        return "executed_in_part"
    if abs(executed - submitted) <= abs(submitted) * 1e-9:
        return "executed_in_full"
    return "executed_beyond"


# Every order of a finished run, from its journal: per decision session,
# the changed positions on `basis`, each with its side, units, weight,
# kind, detail and grade (from `grades`, the report's (T, N) grades). The
# mark at t precedes decision t and the mark at t + 1 closes it; a decision
# without both is refused. `meta` counts what the other basis would have
# counted: the submitted changes that did not trade, or traded in part.
def extract_orders(
    journal: OrderJournal, grades: np.ndarray, basis: str = EXECUTED
) -> Orders:
    """Return the run's Orders."""
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}, not {basis!r}")
    if journal.closes is None or not journal.submitted:
        raise ValueError("the journal saw no run")
    grades = np.asarray(grades)
    closes = np.asarray(journal.closes, dtype=float)
    sessions = sorted(journal.submitted)
    rows: list[tuple[Any, ...]] = []
    status: Counter[str] = Counter()
    previous_deferred: frozenset[str] = frozenset()
    last = None
    for t in sessions:
        if t not in journal.marks or (t + 1) not in journal.marks:
            raise ValueError(f"decision {t} lacks its opening or closing mark")
        _, before, nav, _ = journal.marks[t]
        _, after, _, _ = journal.marks[t + 1]
        submitted = journal.submitted[t] - before
        executed = after - before
        kind = journal.kinds[t]
        deferred: frozenset[str] = frozenset()
        if last == t - 1:
            deferred = previous_deferred
        for j in np.flatnonzero((submitted != 0) | (executed != 0)):
            j = int(j)
            price = closes[t, j]
            sub, exe = float(submitted[j]), float(executed[j])
            units = exe if basis == EXECUTED else sub
            valued = bool(nav > 0 and np.isfinite(price))
            if not valued:
                # No close at t (or no NAV): the change cannot be weighted.
                status["unvalued"] += 1
                continue
            weight = abs(units) * price / nav
            if abs(sub) * price / nav > DUST:
                status[_execution(sub, exe)] += 1
            if not weight > DUST:
                continue
            side = "buy" if units > 0 else "sell"
            ticker = journal.tickers[j]
            grade = int(grades[t, j])
            held_before = bool(before[j] > 0)
            detail = classify(side, kind, grade, held_before, ticker in deferred)
            rows.append(
                (
                    t,
                    j,
                    ticker,
                    side,
                    units,
                    sub,
                    exe,
                    weight,
                    kind,
                    detail,
                    grade,
                    float(before[j]),
                )
            )
        previous_deferred = journal.deferred.get(t, frozenset())
        last = t
    columns = list(zip(*rows, strict=True)) if rows else [()] * 12
    return Orders(
        session=np.asarray(columns[0], dtype=np.int64),
        column=np.asarray(columns[1], dtype=np.int64),
        ticker=np.asarray(columns[2], dtype=str),
        side=np.asarray(columns[3], dtype=str),
        units=np.asarray(columns[4], dtype=float),
        submitted=np.asarray(columns[5], dtype=float),
        executed=np.asarray(columns[6], dtype=float),
        weight=np.asarray(columns[7], dtype=float),
        kind=np.asarray(columns[8], dtype=str),
        detail=np.asarray(columns[9], dtype=str),
        grade=np.asarray(columns[10], dtype=np.int64),
        held=np.asarray(columns[11], dtype=float),
        start=int(sessions[0]),
        stop=int(sessions[-1]) + 1,
        basis=basis,
        meta={
            "decisions": len(sessions),
            "status": dict(status),
            "kinds": dict(Counter(journal.kinds.values())),
        },
    )


@dataclass(frozen=True)
class ControlRun:
    """One offset of the control executor: its orders, journal and returns."""

    since: date | None
    orders: Orders
    journal: OrderJournal
    returns: (
        np.ndarray
    )  # the simulator's daily returns from `since` (SimResult.returns)


# Run the control executor from `since` exactly as stage 3's T-S1 control
# line (`stage3_overlay.price` with the control): `simulate.run` on the
# restricted report under `profit_taking.control_options` with the policy's
# allocator (`policy_v4.allocator(mask)` unless `allocator` names another,
# such as `policy_v5.allocator(mask)` for the `/5` book) and an
# OrderJournal (its FOMC ceiling set as the Ledger's is), at `cost_bps`;
# then the orders on `basis`.
def run_control(
    restricted: DeskReport,
    mask: np.ndarray,
    since: date | None,
    cost_bps: float = COST_BPS,
    basis: str = EXECUTED,
    allocator: Callable[..., Any] | None = None,
) -> ControlRun:
    """Return the ControlRun of one offset."""
    panel = restricted.panel
    options = profit_taking.control_options(panel)
    journal = OrderJournal()
    journal.exposure = options.get("event_exposure")
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=policy_v4.allocator(mask) if allocator is None else allocator,
        journal=journal,
        **options,
    )
    orders = extract_orders(journal, restricted.graded.grades, basis)
    return ControlRun(since, orders, journal, np.asarray(result.returns, dtype=float))


# The control executor from each of the first `offsets` sessions (the
# scorecard's start phases, `market_pit_scorecard._since`), as stage 3 ran
# its offsets, under `allocator` (the default policy_v4's); returns each
# offset's orders.
def run_offsets(
    restricted: DeskReport,
    mask: np.ndarray,
    offsets: int,
    cost_bps: float = COST_BPS,
    basis: str = EXECUTED,
    log: Callable[[str], None] | None = None,
    allocator: Callable[..., Any] | None = None,
) -> list[Orders]:
    """Return [Orders per offset]."""
    if offsets < 1:
        raise ValueError("offsets must be at least 1")
    out: list[Orders] = []
    for k in range(int(offsets)):
        run = run_control(
            restricted, mask, _since(restricted.panel, k), cost_bps, basis, allocator
        )
        out.append(run.orders)
        if log is not None:
            start = run.orders.start
            log(f"  offset {k}: {len(run.orders)} orders from session {start}")
    return out


# The payload's record of one offset's orders: counts by side, kind and
# detail, the grades, the weights, and what the other basis would count.
# `sessions` is the decision sessions the orders span (default: the whole
# run's; a window's subset passes the window's count).
def order_counts(orders: Orders, sessions: int | None = None) -> dict[str, Any]:
    """Return the counts of one run's orders."""
    by = Counter(zip(orders.side.tolist(), orders.kind.tolist(), strict=True))
    detail = Counter(zip(orders.side.tolist(), orders.detail.tolist(), strict=True))
    grades = Counter(zip(orders.side.tolist(), orders.grade.tolist(), strict=True))
    weight = orders.weight[np.isfinite(orders.weight)]
    sessions = max(orders.stop - orders.start, 0) if sessions is None else int(sessions)
    return {
        "basis": orders.basis,
        "orders": len(orders),
        "buys": int(orders.buy.sum()),
        "sells": int((~orders.buy).sum()),
        "decision_sessions": sessions,
        "orders_per_session": len(orders) / sessions if sessions else math.nan,
        "by_kind": {f"{s}/{k}": n for (s, k), n in sorted(by.items())},
        "by_detail": {f"{s}/{d}": n for (s, d), n in sorted(detail.items())},
        "by_grade": {f"{s}/{g}": n for (s, g), n in sorted(grades.items())},
        "mean_weight": float(weight.mean()) if len(weight) else math.nan,
        "min_weight": float(weight.min()) if len(weight) else math.nan,
        "below_1bp_of_equity": int((weight < 1e-4).sum()),
        "weight_per_session": float(weight.sum() / sessions) if sessions else math.nan,
        # The run-level counts; None for a subset, which cannot recount them.
        "submitted_status": dict(orders.meta["status"])
        if "status" in orders.meta
        else None,
        "decision_kinds": dict(orders.meta["kinds"])
        if "kinds" in orders.meta
        else None,
    }
