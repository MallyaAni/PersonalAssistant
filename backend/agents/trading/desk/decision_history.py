"""What the live policy would have said about one name, session by session.

The ticker chart carries the desk's grade changes, which are not trades.
The operator asked to see the trades beside them: on each session, would
the policy have bought, added, trimmed, sold or held the name, and at what
size, so an entry or an exit can be checked against the price that
followed. This module replays `policy_v4.targets` over the report's
history to answer that, and reads the paper account's real fills out of
the nightly records so the two can be drawn on the same candles.

Two things are deliberate. The replay runs on the point-in-time
membership mask, so a session's decision is made from the names the book
could have held on that session and not from today's list (a name added
this month has no decisions before it joined). And a decision is dated to
the close it was made at; the fill is the next session's open, which is
where the simulator prices it and where the paper account sends its buys.
The chart draws the decision on its own session, and the caption says so.

WHAT THE MARKERS MEAN UNDER `graded-equal-weight/4` (2026-09-27). A name's
target under /4 is 1/(number of A/A+ names) capped at HOLD_CAP, so it
drifts a little every session the count changes - AAOI was A+ every day
from Sep 8 to Sep 25 and its target went 8.3 -> 7.7 -> 9.1 -> 10 -> 12.5
-> 10 -> 9.1% - and the executor trades none of that drift: it brings the
book to the targets at the reset every `paper.REBALANCE_EVERY` sessions,
sells a name the desk downgrades mid-cycle, buys one that enters, and
(since the executor's /4) redeploys idle cash into names below target.
Read as weight moves, the drift produced an "add 2.5%" and a "trim 2.5%"
the account never traded, while the board said BUY 9.1%. So when the
replay is the active policy the series is classified by membership and
by the reset schedule: `buy` when the target goes 0 -> >0 (the name
enters the A/A+ book), `sell` when it goes >0 -> 0 (it leaves), `add` or
`trim` only on a reset session and only when the move is at least
ADD_TRIM_MIN (the rebalance really trades it), and `hold` for every other
target change, whatever its size. The reset sessions come from the paper
state's clock (`reset_sessions`); a history written with no clock on file
marks none and says so.

Nothing here trades. The series is display data written into the
per-name history file; the paper account and the record are read, never
written.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time, policy_v4
from backend.market import deskrecord, universe

POLICY = policy_v4.POLICY_VERSION
# A weight change smaller than this is a hold. Under equal weight every
# held name's weight shifts a little whenever the count of qualifying names
# changes (1/9 to 1/10 is 1.1 points), and none of those shifts is an
# order anyone would place; 2.5 points is above every such reshuffle at
# five names or more and below any real add or trim.
ADD_TRIM_MIN = 0.025
DECISION_NOTE = "signals at each close; sizes are % of the account"
ACTIONS = ("buy", "sell", "add", "trim", "hold")


# The policy's target weight for every (session, name) of the report, on
# the names the book could have held on each session. The mask is the
# dated membership history rather than today's list, because a decision
# replayed over a name the desk did not yet know about is not a decision
# the desk could have made, and a chart of those would verify nothing.
def target_matrix(
    report, history_path: Path = universe.MEMBERSHIP_HISTORY_PATH
) -> np.ndarray:
    """Return the (T, N) target weights under the live policy."""
    panel = report.panel
    mask = point_in_time.eligibility(panel.dates, tuple(panel.tickers), history_path)
    benchmark = panel.index(panel.benchmark)
    grades = report.graded.grades
    out = np.zeros(grades.shape, dtype=float)
    for t in range(len(panel.dates)):
        out[t] = policy_v4.targets(grades[t], panel.close[t], mask[t], benchmark)
    return out


# The action a weight move amounts to: entering is a buy and leaving is a
# sell whatever the size. Between the two it depends on who is asked.
# With `reset` None (a sizing policy whose every target move is an order,
# the /3 reading) a move under ADD_TRIM_MIN is a hold and a larger one an
# add or a trim. With `reset` given (the /4 reading, membership and
# schedule) a held name is traded only at the reset: on a reset session a
# move of at least ADD_TRIM_MIN is the add or trim the rebalance places,
# and on any other session every move is a hold, because the executor
# does not follow the denominator between resets.
def classify(previous: float, target: float, reset: bool | None = None) -> str:
    """Return one of ACTIONS for a move from `previous` to `target`."""
    if previous <= 0.0 < target:
        return "buy"
    if target <= 0.0 < previous:
        return "sell"
    if reset is False:
        return "hold"
    delta = target - previous
    # The threshold is inclusive; the epsilon keeps 0.10 -> 0.125 an add
    # whatever floating point makes of the subtraction.
    if delta >= ADD_TRIM_MIN - 1e-9:
        return "add"
    if delta <= -ADD_TRIM_MIN + 1e-9:
        return "trim"
    return "hold"


# One name's decision on every session from `since`: the target weight,
# the weight the session before, the change and the action it amounts to.
# The decision is made at the close of `date`; the fill it implies is the
# next session's open. `targets` accepts a precomputed `target_matrix` so
# a caller writing every name's file computes the matrix once. `resets`,
# when given (a set of session dates, possibly empty), switches the
# classification to the /4 reading - membership and the reset schedule -
# and every row then also says whether its session was a reset; left None
# the rows read exactly as they did before the schedule was known.
def series(
    report,
    ticker: str,
    since: date | None = None,
    targets: np.ndarray | None = None,
    history_path: Path = universe.MEMBERSHIP_HISTORY_PATH,
    resets: set[str] | None = None,
) -> list[dict]:
    """Return [{date, target_weight, previous_weight, delta_weight, action, ...}]."""
    panel = report.panel
    column = panel.index(ticker)
    if targets is None:
        targets = target_matrix(report, history_path)
    weights = np.nan_to_num(np.asarray(targets, dtype=float)[:, column], nan=0.0)
    start = np.datetime64(since) if since else panel.dates[0]
    rows: list[dict] = []
    previous = 0.0
    for t, day in enumerate(panel.dates):
        target = float(weights[t])
        if day >= start:
            reset = None if resets is None else str(day) in resets
            row = {
                "date": str(day),
                "target_weight": round(target, 6),
                "previous_weight": round(previous, 6),
                "delta_weight": round(target - previous, 6),
                "action": classify(previous, target, reset),
            }
            if reset is not None:
                row["rebalance"] = reset
            rows.append(row)
        previous = target
    return rows


# What the history file says about how its reset sessions were found.
RESETS_FROM_CLOCK = (
    "reset sessions from the paper state's rebalance clock and the nightly "
    "records; add/trim markers only on those, target drift between resets is "
    "not traded"
)
RESETS_UNKNOWN = (
    "no rebalance clock on file: no session is marked as a reset, so the "
    "series shows entries and exits only"
)


# The sessions the paper book was brought to its targets on, as the
# account's own bookkeeping records them: the state's `last_rebalance`
# and `previous_rebalance` (the two the clock keeps), plus every nightly
# record whose paper block planned a rebalance that the clock accepted
# (`plan == "rebalance"` with the clock restarted, `until_rebalance` equal
# to the full cycle; a refused rebalance leaves the clock where it was and
# is not a reset). The clock is not projected backward from the last reset
# in twenty-session steps: a forced rebalance (the move to /4) and a
# refused one both move it, so a projected date would be a guess where the
# state and the records are evidence. The note says which case applied.
def reset_sessions(root: Path) -> tuple[set[str], str]:
    """Return ({session dates the book rebalanced on}, the note for the file)."""
    from backend.agents.trading.desk import paper

    found: set[str] = set()
    try:
        state = paper.load_state(Path(root))
    except (OSError, ValueError, TypeError):
        state = None
    if state is None or not state.last_rebalance:
        return found, RESETS_UNKNOWN
    for stamp in (state.last_rebalance, state.previous_rebalance):
        if isinstance(stamp, str) and stamp:
            found.add(stamp[:10])
    for session in deskrecord.sessions(Path(root)):
        try:
            record = deskrecord.load(Path(root), session)
        except (OSError, ValueError):
            continue
        block = record.get("paper") if isinstance(record, dict) else None
        if not isinstance(block, dict) or block.get("plan") != "rebalance":
            continue
        try:
            until = int(block.get("until_rebalance", paper.REBALANCE_EVERY))
        except (TypeError, ValueError):
            continue
        if until >= paper.REBALANCE_EVERY:
            found.add(str(record.get("session") or session)[:10])
    return found, RESETS_FROM_CLOCK


# The plan leg a settled row names, as the one-key dict to add to its fill:
# {"kind": "redeploy"} on a redeploy buy (the executor's /4, 2026-09-27), so
# the chart can tell a redeploy fill from a rotation or an entry; empty for a
# row written before the field existed or carrying anything but a string, so
# those fills read exactly as before.
def _plan_leg(row: dict) -> dict:
    """Return {"kind": leg} when `row` names its plan leg, else {}."""
    kind = row.get("kind")
    return {"kind": kind} if isinstance(kind, str) and kind else {}


# The broker's real completion time, when the record kept it, so the
# fifteen-minute chart can place the fill on the bar it actually filled in
# rather than the executor's open/close convention. Absent on records written
# before the field existed.
def _filled_at(row: dict) -> dict:
    """Return {"filled_at": when} from the settled row's execution, else {}."""
    execution = row.get("execution")
    filled_at = execution.get("filled_at") if isinstance(execution, dict) else None
    return {"filled_at": filled_at} if isinstance(filled_at, str) and filled_at else {}


# The paper account's real fills in one name, read from the nightly
# records' `paper.settled` rows. A row counts when the broker filled some
# of it; the fill is dated to the session the broker completed it on when
# the record says, else to the record's session (the orders of a night
# fill on the next session, which is the night that reconciles them). The
# records are pruned to about a month and were written by several
# revisions, so every field is read defensively and a malformed row is
# skipped rather than fatal. A partial that settles again in a later
# record replaces its earlier reading, keyed on the order id.
def fills(root: Path, ticker: str) -> list[dict]:
    """Return [{date, side, qty, price[, kind]}] for `ticker`, oldest first."""
    found: dict[str, dict] = {}
    for session in deskrecord.sessions(root):
        try:
            record = deskrecord.load(root, session)
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        paper = record.get("paper")
        if not isinstance(paper, dict):
            continue
        settled = paper.get("settled")
        if not isinstance(settled, list):
            continue
        for index, row in enumerate(settled):
            if not isinstance(row, dict) or row.get("symbol") != ticker:
                continue
            try:
                qty = int(float(row.get("filled") or 0))
                price = float(row.get("filled_price") or 0.0)
            except (TypeError, ValueError):
                continue
            side = str(row.get("side") or "").lower()
            if qty <= 0 or price <= 0 or side not in ("buy", "sell"):
                continue
            when = row.get("completion_session") or record.get("session") or session
            key = str(row.get("client_order_id") or f"{session}:{index}")
            found[key] = {
                "date": str(when)[:10],
                "side": side,
                "qty": qty,
                "price": round(price, 4),
                **_plan_leg(row),
                **_filled_at(row),
            }
    return sorted(found.values(), key=lambda f: (f["date"], f["side"], f["qty"]))
