"""The paper book: the desk's decisions carried out on the paper account.

The rules are the ones that measured best, and nothing else:

* Every `REBALANCE_EVERY` sessions the paper book is brought to the desk's
  target weights (buys and sells at the next open, whole shares, moves
  smaller than `MIN_TRADE` of equity skipped).
* Between rebalances the book is left alone except for the versioned FOMC
  cycle in event_execution.py. It cuts held shares once and restores confirmed
  reductions after the meeting, without restarting the rebalance clock. There
  is no price stop, because every stop measured worse than none on every
  name; no grade-based exit, because it cut winners; and no band exit,
  because that cost 3.0% a year when it was finally measured inside these
  rules rather than per trade. `plan` still accepts a `finished` map so a
  trigger that does measure well can be given one, but none does yet. The
  note at the top of `desk/exit.py` has the numbers.
* The plan for a session is made once. Running the day twice submits
  nothing the second time.

The state (the rebalance clock, each held name's run of C grades, the
starting equity and the equity history) lives in one JSON file under the
market data root, next to the desk records, so the track record is a
file anyone can read.
"""

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading.desk import execution_evidence, planner

REBALANCE_EVERY = 120
MIN_TRADE = 0.005
# Mid-cycle entries, measured 2026-09-18 and corrected 2026-09-19. The
# calendar decides WHAT the book holds; price decides WHEN each name is
# entered. A name graded A or better sitting more than ENTRY_TAIL ABOVE its
# 21-day average takes ENTRY_ADD of equity funded from the other holdings,
# capped at ENTRY_NAME_CAP.
#
# The upper tail only. The rule shipped on 2026-09-18 took both tails, on a
# forward-return table that counted a ten-session window on every session and
# so counted each observation about ten times over. Corrected for that
# overlap and split at the regime boundary, the dip tail does not survive:
# from 2020-10 it returned +0.93% against a +0.44% baseline with t 0.47, and
# with the 2020, 2022 and Q4-2018 dislocations removed it returned +0.45%
# over baseline at t 0.40. Forty percent of the 15% dip bucket sits in three
# calendar months. The edge was real before 2020 (+6.15% at a 75.8% hit rate)
# and is not there now.
#
# Through the harness across 20 start phases, taking the upper tail only
# against taking both, at the same threshold, funding and grade floor:
#
#                        CAGR   worst   Sharpe   worst DD   turn/yr
#   from 2021  both      43.83  36.62    1.205    -49.06      6.01x
#              upper     47.43  40.52    1.354    -45.33      5.49x
#   from 2018  both      36.80  29.82    1.138    -44.92      5.82x
#              upper     34.12  29.44    1.178    -42.19      5.02x
#
# In the regime the book trades the upper tail is better on every column at
# once; over the whole history it gives up 2.7 points of CAGR for a better
# Sharpe, a shallower drawdown and less turnover. Dropping the dip was a
# single pre-specified comparison, not a search: the forward returns and the
# outside literature had both condemned it first. The thresholds themselves
# were NOT re-fitted, because 20% was not separable from 15% once the sample
# was counted honestly, and a volatility-scaled trigger measured worse than
# either from 2021.
#
# For the calendar book with no price entries at all: 34.38% at Sharpe 1.468
# and -30.04%. It keeps the best Sharpe and much the shallowest drawdown, so
# the entries remain a deliberate trade of risk for return rather than a free
# improvement. `desk/entry.py` measures a DIFFERENT dip - 8% below the EMA or
# below the lower band, over five sessions - and that one still pays at its
# own horizon; it is not what was dropped here, and the book's 120-session
# hold was never able to harvest it.
#
# Funded rather than from cash: the add is taken pro rata from the other
# holdings, so gross exposure is unchanged and only the selection moves.
# Unfunded it returned less at a worse Sharpe and a deeper drawdown.
#
# Every figure carries the universe's survivorship, which market_survivorship
# measures at nineteen points a year, and every rule above carries it equally.
ENTRY_TAIL = 0.15
ENTRY_ADD = 0.03
ENTRY_NAME_CAP = 0.15
ENTRY_MIN_GRADE = ("A", "A+")
PAPER_KIND = "paper"


@dataclass
class PaperState:
    """What the paper book remembers between sessions."""

    sessions_seen: list[str] = field(default_factory=list)
    last_rebalance: str | None = None
    sessions_since_rebalance: int = 0
    # When each held name was opened, so the exit analyst can leave a
    # fresh position alone through its grace period.
    opened: dict[str, str] = field(default_factory=dict)
    start_equity: float | None = None
    history: list[dict] = field(default_factory=list)
    # Orders written down before they were sent, each with the id the
    # broker was asked to use. Written first so a crash between the
    # submission and the record is recoverable: the next session asks the
    # broker whether these exact orders exist rather than inferring it from
    # positions, which move for other reasons.
    pending: list[dict] = field(default_factory=list)
    # The durable order journal: every settled outcome, one entry per order
    # id (the latest wins), so a leg that was rejected in one round and a
    # leg that filled in a later round are both seen when the rebalance is
    # concluded. Without it a terminal outcome is dropped from `pending` and
    # forgotten the moment another leg still working fills later.
    journal: list[dict] = field(default_factory=list)
    # The session whose rebalance has been sent but not yet confirmed as
    # filled. Until it is, the rebalance has not happened.
    unconfirmed_rebalance: str | None = None
    # What the previous rebalance was, so an unconfirmed one can be rolled
    # back to it rather than guessed at.
    previous_rebalance: str | None = None
    # Monotonic per-order sequence, so a client order id is unique to one
    # submission. A forced rebalance of a session already planned used to
    # reuse ids (`anios-{session}-{side}-{symbol}`): the broker rejects a
    # second order carrying an id it has already seen, and the replacement
    # never reached the market.
    order_seq: int = 0
    event_cycle: dict = field(default_factory=dict)
    event_outcomes: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class PaperOrder:
    """One order for the next open."""

    symbol: str
    side: str
    qty: int
    reason: str
    # The id this submission will carry on the broker, chosen at plan time
    # so the write-down and the submit use the same one.
    client_order_id: str | None = None
    event_id: str | None = None


# Serialize paper writers across the nightly and intraday processes.
@contextmanager
def transaction(root: Path):
    import fcntl

    path = Path(root) / PAPER_KIND / "state.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# Where the state lives.
def state_path(root: Path) -> Path:
    """Return the paper state's path."""
    return Path(root) / PAPER_KIND / "state.json"


# Read the state, or a fresh one.
def load_state(root: Path) -> PaperState:
    """Return the PaperState on file, or an empty one."""
    path = state_path(root)
    if not path.exists():
        return PaperState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return PaperState(**data)


# Replace the state atomically so a crash cannot truncate pending order intent.
def save_state(root: Path, state: PaperState) -> Path:
    """Write the PaperState and return its path."""
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps(asdict(state), indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


# The plan for one session: the orders to submit for the next open and the
# state after it. `held` is {symbol: shares}, `prices` {symbol: last close},
# `targets` {symbol: weight} from the desk's book, `grades` {symbol:
# letter} for every name graded today.
# Mid-cycle entries: buy the tail names, funded pro rata from the rest.
#
# Gross is unchanged by construction. The buys are sized first, then the
# same dollar value is raised by trimming every OTHER holding in proportion
# to what it already holds, so the exposure the regime chose is untouched
# and only the selection moves. A name at its cap is not added to, and a
# trim too small to clear MIN_TRADE is dropped rather than sent.
def _entry_orders(
    entries: dict[str, float],
    held: dict[str, float],
    prices: dict[str, float],
    equity: float,
    session: str,
    state: "PaperState",
    blocked: set[str] | None,
) -> list["PaperOrder"]:
    """Return the funded buy and trim orders for tonight's tail entries."""
    if equity <= 0 or not entries:
        return []
    blocked = blocked or set()
    buys: list[tuple[str, int, float]] = []
    for symbol in sorted(entries):
        price = float(prices.get(symbol) or 0.0)
        if price <= 0 or symbol in blocked:
            continue
        current = float(held.get(symbol, 0)) * price / equity
        want = min(ENTRY_ADD, ENTRY_NAME_CAP - current)
        if want < MIN_TRADE:
            continue
        qty = int(round(want * equity / price))
        if qty > 0:
            buys.append((symbol, qty, qty * price))
    if not buys:
        return []

    donors = {
        s: float(q) * float(prices.get(s) or 0.0)
        for s, q in held.items()
        if q > 0 and s not in entries and (prices.get(s) or 0) > 0
    }
    pool = sum(donors.values())
    if pool <= 0:
        return []
    # If the rest of the book cannot fund the whole add, the add shrinks
    # rather than the gross growing.
    needed = sum(value for _, _, value in buys)
    if needed > pool:
        scale = pool / needed
        buys = [(s, max(1, int(q * scale)), v * scale) for s, q, v in buys]
        needed = sum(v for _, _, v in buys)

    orders: list[PaperOrder] = []
    for symbol, value in sorted(donors.items()):
        price = float(prices[symbol])
        qty = int(round(needed * (value / pool) / price))
        qty = min(qty, int(held[symbol]))
        if qty <= 0 or qty * price < MIN_TRADE * equity:
            continue
        seq = state.order_seq
        state.order_seq += 1
        orders.append(
            PaperOrder(
                symbol,
                "sell",
                qty,
                "funding a price entry",
                client_order_id=order_id(session, symbol, "sell", seq),
            )
        )
    for symbol, qty, _ in buys:
        seq = state.order_seq
        state.order_seq += 1
        orders.append(
            PaperOrder(
                symbol,
                "buy",
                qty,
                "price entry: a tail of its own 21-day average",
                client_order_id=order_id(session, symbol, "buy", seq),
            )
        )
        state.opened.setdefault(symbol, session)
    return orders


# The rebalance's orders: the shared planner's moves, rounded to the whole
# shares a broker accepts, gated on the band-reversal blocker, skipping a
# move too small to be worth its cost. Sells and trims pass whatever the
# gate says; a buy or add inside `entry_blocked` (the daily rejecting its
# upper Bollinger band) is held back, so the desk never buys a name whose
# own daily is rolling over at the top.
def _rebalance_orders(
    planner_moves,
    entry_blocked: set[str] | None,
    equity: float,
    session: str,
    new: PaperState,
) -> list[PaperOrder]:
    """Return the buy and sell orders for this rebalance."""
    orders: list[PaperOrder] = []
    for o in planner_moves:
        if o.side == "buy" and entry_blocked is not None and o.symbol in entry_blocked:
            continue
        qty = int(round(o.qty))
        if qty <= 0:
            continue
        if abs(qty) * o.reference_price < MIN_TRADE * equity:
            continue
        seq = new.order_seq
        new.order_seq += 1
        if o.side == "buy":
            orders.append(
                PaperOrder(
                    o.symbol,
                    "buy",
                    qty,
                    o.reason,
                    client_order_id=order_id(session, o.symbol, "buy", seq),
                )
            )
            new.opened.setdefault(o.symbol, session)
        else:
            orders.append(
                PaperOrder(
                    o.symbol,
                    "sell",
                    qty,
                    o.reason,
                    client_order_id=order_id(session, o.symbol, "sell", seq),
                )
            )
    return orders


# Plan this session's moves: rebalance to the targets, or the exits the
# caller named.
def plan(
    session: str,
    state: PaperState,
    equity: float,
    held: dict[str, float],
    prices: dict[str, float],
    targets: dict[str, float],
    grades: dict[str, str],
    finished: dict[str, str] | None = None,
    force_rebalance: bool = False,
    entry_blocked: set[str] | None = None,
    entries: dict[str, float] | None = None,
) -> tuple[list[PaperOrder], PaperState, str]:
    """Return (orders, new state, what the day was).

    `force_rebalance` rebalances to the targets tonight whatever the clock
    says and restarts the clock from this session. It is the operator's
    one-time move - the desk's rule never sets it - and it is the one case
    a session already planned is planned again, deliberately: the caller
    cancels the broker's open orders before submitting the new ones.

    `entry_blocked` is the set of symbols whose daily is rejecting its
    upper Bollinger band tonight (the exit analyst's own signal - a
    bearish candle at the band, or price in the upper fifth of a wide
    band). When given, no buy or add is placed for a name in it; sells and
    trims pass regardless. Measured on the book since 2015 this held only
    those buys back and beat the ungated book on return, Sharpe and
    drawdown, where requiring a full entry trigger starved the book.
    """
    if session in state.sessions_seen and not force_rebalance:
        return [], state, "already planned for this session"
    new = PaperState(**asdict(state))
    if session not in state.sessions_seen:
        new.sessions_seen = state.sessions_seen + [session]
    new.opened = {s: d for s, d in state.opened.items() if s in held}
    done = finished or {}
    orders: list[PaperOrder] = []
    rebalance = (
        force_rebalance
        or state.last_rebalance is None
        or state.sessions_since_rebalance + 1 >= REBALANCE_EVERY
    )
    if rebalance:
        new.previous_rebalance = state.last_rebalance
        new.last_rebalance = session
        new.sessions_since_rebalance = 0
        # The plan is the shared planner's, sized at the close the decision
        # could see; this path only rounds to the whole shares a broker
        # accepts and skips a move too small to be worth its cost. Nearest
        # whole share, not the floor: on a 100,000 book a 4.9% target in a
        # 1,740 stock floors to 2 shares, 29% short of what was asked for,
        # and the book came out 12% under its target gross. Rounding to
        # nearest halves the error and does not bias it one way.
        target_map = {s: float(w) for s, w in targets.items() if w > 0}
        held_map = {s: float(q) for s, q in held.items() if q > 0}
        price_map = {s: float(p) for s, p in prices.items() if p and p > 0}
        orders = _rebalance_orders(
            planner.plan(target_map, held_map, equity, price_map),
            entry_blocked,
            equity,
            session,
            new,
        )
        what = "rebalance"
    else:
        new.sessions_since_rebalance = state.sessions_since_rebalance + 1
        for symbol, why in done.items():
            qty = int(held.get(symbol, 0))
            if qty > 0:
                seq = new.order_seq
                new.order_seq += 1
                orders.append(
                    PaperOrder(
                        symbol,
                        "sell",
                        qty,
                        why,
                        client_order_id=order_id(session, symbol, "sell", seq),
                    )
                )
                new.opened.pop(symbol, None)
        # Price entries, after the session's exits are written. The calendar
        # chose what the book holds; this chooses when each name is entered.
        if entries:
            orders.extend(
                _entry_orders(
                    entries, held, prices, equity, session, new, entry_blocked
                )
            )
        what = "hold" if not orders else "entries" if entries else "exits"
    # Sells first, so the buys have the cash.
    orders.sort(key=lambda o: (o.side != "sell", -o.qty))
    return orders, new, what


# What the broker says became of each order this desk wrote down.
#
# An order that is accepted is not an order that is filled. It can be
# rejected at the open, expire unfilled when the auction does not cross,
# or fill in part. Until this existed the desk printed "submitted", saved a
# rebalance as done, and never looked again - so a rebalance the broker had
# refused counted as one that had happened, and the book sat twenty
# sessions from its next attempt at targets it had never reached.
#
# Statuses come from the broker rather than a guess about positions.
# Positions move for reasons that have nothing to do with this desk, so
# they cannot tell you whether your own order filled.
FILLED = ("filled",)
DEAD = ("canceled", "cancelled", "expired", "rejected", "done_for_day", "suspended")
# The broker statuses that mean an order may still fill or change: a partial
# reported as anything else has no more quantity coming. pending_cancel and
# pending_replace are deliberately included - the cancel or replacement is
# still in flight, so the order can still fill, and it must stay pending
# until the broker confirms a terminal outcome (filled, canceled, expired,
# rejected, ...) rather than being concluded early and replanned.
_WORKING = (
    "accepted",
    "new",
    "partially_filled",
    "open",
    "pending",
    "pending_cancel",
    "pending_replace",
)
# A leg the desk deliberately chose not to execute: the intraday green-day
# rule cancels a market-on-close sell for a name trading up at the open and
# journals it here. It is terminal (the broker's later cancel must not
# re-open it) and counts as done for the rebalance - the position is
# deliberately held, not a failed order to be retried.
SKIPPED = "skipped"
# The statuses that count a rebalance leg as concluded, whether it filled
# or was deliberately held.
DONE = ("filled", SKIPPED)


@dataclass(frozen=True)
class Settled:
    """One pending order, and what the broker did with it."""

    client_order_id: str
    symbol: str
    side: str
    qty: int
    session: str
    status: str  # filled, partial, dead, open, or missing
    filled_qty: int
    filled_price: float = 0.0  # the broker's average fill, 0 when nothing filled
    # Whether the broker will ever fill the rest of this order. An order
    # that is canceled or expired after a partial fill is terminal: the
    # outstanding quantity is not coming, so it is concluded, not kept
    # pending for an answer that can never arrive.
    terminal: bool = False
    execution: dict = field(default_factory=dict)


# Pure: match what was written down against what the broker reports.
def settle(pending: list[dict], broker_orders: list[dict]) -> list[Settled]:
    """Return the outcome of each pending order."""
    by_id = {
        str(order.get("client_order_id") or ""): order
        for order in broker_orders
        if order.get("client_order_id")
    }
    out: list[Settled] = []
    for row in pending:
        order = by_id.get(str(row.get("client_order_id") or ""))
        wanted = int(row.get("qty") or 0)
        raw = ""
        if order is None:
            # Never reached the broker, or reached it under another id.
            # Either way this desk cannot claim it traded.
            status, filled, price = "missing", 0, 0.0
        else:
            filled = int(float(order.get("filled_qty") or 0))
            price = float(order.get("filled_avg_price") or 0.0)
            raw = str(order.get("status") or "").lower()
            if raw in FILLED and filled >= wanted:
                status = "filled"
            elif (
                raw in ("canceled", "cancelled")
                and row.get("hold_requested")
                and row.get("side") == "sell"
            ):
                # The remaining quantity was deliberately held. Keep any
                # execution before cancellation in the same journal receipt.
                status = SKIPPED
            elif filled > 0:
                status = "partial"
            elif raw in DEAD:
                status = "dead"
            else:
                status = "open"
        out.append(
            Settled(
                client_order_id=str(row.get("client_order_id") or ""),
                symbol=str(row.get("symbol") or ""),
                side=str(row.get("side") or ""),
                qty=wanted,
                session=str(row.get("session") or ""),
                status=status,
                filled_qty=filled,
                filled_price=price,
                terminal=status in ("filled", "dead", "missing", SKIPPED)
                or (status == "partial" and raw not in _WORKING),
                execution={
                    **row.get("execution", {}),
                    **execution_evidence.broker_evidence(order),
                },
            )
        )
    return out


# What the closing auction would have paid against an actual fill, in
# basis points, signed so that positive means the close would have been
# worse: a buy filled below the close, a sell filled above it. The
# execution measurement found the close better for sells in four of five
# years and worse in 2026; the record writes this beside every fill so the
# paper account answers the question as sessions accumulate.
def close_shortfall_bps(side: str, filled_price: float, close: float) -> float | None:
    """Return the close's shortfall against the fill, or None without a fill."""
    if filled_price <= 0 or not close or close != close:
        return None
    sign = 1.0 if side == "buy" else -1.0
    return sign * (close - filled_price) / filled_price * 1e4


# Fold the outcomes back into the state.
#
# A rebalance whose orders did not all fill is not a rebalance. The clock
# rolls back to the one before it, so the next session plans the rebalance
# again instead of waiting out twenty sessions on a book that never
# reached its targets. Every outcome is written to the durable journal
# first, so a leg rejected in an earlier round is still seen when the last
# leg fills - a rebalance is concluded over all its legs' latest recorded
# outcomes, not over whichever ones happen to still be pending. Only an
# order still working stays pending; a partial the broker has now closed
# (canceled or expired) is a concluded partial, with its fill recorded,
# not an order waiting for an answer that can never arrive.
def apply_settlements(state: PaperState, settled: list[Settled]) -> PaperState:
    """Return the state after recording what the broker did."""
    new = PaperState(**asdict(state))
    journal = {str(row.get("client_order_id") or ""): row for row in state.journal}
    for s in settled:
        prior = next(
            (
                row
                for row in state.pending
                if row.get("client_order_id") == s.client_order_id
            ),
            journal.get(s.client_order_id, {}),
        )
        journal[s.client_order_id] = {
            "client_order_id": s.client_order_id,
            "symbol": s.symbol,
            "side": s.side,
            "qty": s.qty,
            "session": s.session,
            "status": s.status,
            "filled_qty": s.filled_qty,
            "filled_price": s.filled_price,
            "terminal": s.terminal,
            "event_id": prior.get("event_id"),
            "execution": {
                **journal.get(s.client_order_id, {}).get("execution", {}),
                **prior.get("execution", {}),
                **s.execution,
            },
        }
    new.journal = [journal[k] for k in sorted(journal)]
    still_working = {
        s.client_order_id
        for s in settled
        if s.status == "open" or (s.status == "partial" and not s.terminal)
    }
    new.pending = [
        {
            **row,
            "execution": journal[str(row.get("client_order_id") or "")]["execution"],
        }
        for row in state.pending
        if str(row.get("client_order_id") or "") in still_working
    ]
    if state.unconfirmed_rebalance is None:
        return new
    # The rebalance's whole set of legs, from the journal's latest entry per
    # order, so a terminal leg is never forgotten when another fills later.
    legs = [
        e
        for e in new.journal
        if e["session"] == state.unconfirmed_rebalance and not e.get("event_id")
    ]
    if not legs or any(not e["terminal"] for e in legs):
        # Nothing to conclude yet; ask again next session.
        return new
    if all(e["status"] in DONE for e in legs):
        new.unconfirmed_rebalance = None
        return new
    # It did not go through. Put the clock back so it is tried again.
    new.unconfirmed_rebalance = None
    new.last_rebalance = state.previous_rebalance
    new.sessions_since_rebalance = REBALANCE_EVERY
    return new


# A stable id for one order, chosen before it is sent. The sequence makes
# it unique to one submission: a forced rebalance of a session already
# planned must not reuse an id the broker has already seen.
def order_id(session: str, symbol: str, side: str, seq: int = 0) -> str:
    """Return the client order id for one submission of a symbol on a session."""
    return f"anios-{session}-{side}-{symbol}-{seq}".lower()


# Deliberately hold a position the desk planned to sell. The intraday
# green-day rule calls this when a name with a pending market-on-close sell
# is trading up at the open: the order is cancelled on the broker and this
# writes the hold into the state as a concluded leg, so the rebalance does
# not treat the cancelled sell as a failed order and roll the clock back.
def skip_sell(state: PaperState, client_order_id: str) -> PaperState:
    """Return the state with the given pending sell marked as deliberately held."""
    new = PaperState(**asdict(state))
    row = next(
        (r for r in new.pending if r.get("client_order_id") == client_order_id),
        None,
    )
    if row is None:
        return state
    new.pending = [
        r for r in new.pending if r.get("client_order_id") != client_order_id
    ]
    journal = {str(r.get("client_order_id") or ""): r for r in new.journal}
    journal[client_order_id] = {
        "client_order_id": client_order_id,
        "symbol": row.get("symbol", ""),
        "side": row.get("side", "sell"),
        "qty": int(row.get("qty") or 0),
        "session": row.get("session", ""),
        "status": SKIPPED,
        "filled_qty": 0,
        "filled_price": 0.0,
        "terminal": True,
        "execution": row.get("execution", {}),
        "event_id": row.get("event_id"),
    }
    new.journal = [journal[k] for k in sorted(journal)]
    return new


# Record the account after the day's orders: equity, cash, and the profit
# or loss since the paper book started.
def snapshot(
    state: PaperState, session: str, equity: float, cash: float, positions: list[dict]
) -> dict:
    """Append the day's equity to the state's history and return the entry."""
    if state.start_equity is None:
        state.start_equity = equity
    entry = {
        "session": session,
        "written": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "equity": equity,
        "cash": cash,
        "pl": equity - state.start_equity,
        "pl_pct": (equity / state.start_equity - 1.0) if state.start_equity else 0.0,
        "positions": positions,
    }
    state.history = [h for h in state.history if h.get("session") != session] + [entry]
    return entry
