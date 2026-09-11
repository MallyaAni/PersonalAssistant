"""The paper book: the desk's decisions carried out on the paper account.

The rules are the ones that measured best, and nothing else:

* Every `REBALANCE_EVERY` sessions the paper book is brought to the desk's
  target weights (buys and sells at the next open, whole shares, moves
  smaller than `MIN_TRADE` of equity skipped).
* Between rebalances the book is left alone. Nothing else trades. There
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
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading.desk import planner

REBALANCE_EVERY = 20
MIN_TRADE = 0.005
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


@dataclass(frozen=True)
class PaperOrder:
    """One order for the next open."""

    symbol: str
    side: str
    qty: int
    reason: str


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


# Write the state.
def save_state(root: Path, state: PaperState) -> Path:
    """Write the PaperState and return its path."""
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    return path


# The plan for one session: the orders to submit for the next open and the
# state after it. `held` is {symbol: shares}, `prices` {symbol: last close},
# `targets` {symbol: weight} from the desk's book, `grades` {symbol: letter}
# for every name graded today.
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
) -> tuple[list[PaperOrder], PaperState, str]:
    """Return (orders, new state, what the day was).

    `force_rebalance` rebalances to the targets tonight whatever the clock
    says and restarts the clock from this session. It is the operator's
    one-time move - the desk's rule never sets it - and it is the one case
    a session already planned is planned again, deliberately: the caller
    cancels the broker's open orders before submitting the new ones.
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
        for o in planner.plan(target_map, held_map, equity, price_map):
            qty = int(round(o.qty))
            if qty <= 0:
                continue
            if abs(qty) * o.reference_price < MIN_TRADE * equity:
                continue
            if o.side == "buy":
                orders.append(PaperOrder(o.symbol, "buy", qty, o.reason))
                new.opened.setdefault(o.symbol, session)
            else:
                orders.append(PaperOrder(o.symbol, "sell", qty, o.reason))
        what = "rebalance"
    else:
        new.sessions_since_rebalance = state.sessions_since_rebalance + 1
        for symbol, why in done.items():
            qty = int(held.get(symbol, 0))
            if qty > 0:
                orders.append(PaperOrder(symbol, "sell", qty, why))
                new.opened.pop(symbol, None)
        what = "hold" if not orders else "exits"
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
                terminal=status in ("filled", "dead", "missing")
                or (status == "partial" and raw not in _WORKING),
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
        }
    new.journal = [journal[k] for k in sorted(journal)]
    still_working = {
        s.client_order_id
        for s in settled
        if s.status == "open" or (s.status == "partial" and not s.terminal)
    }
    new.pending = [
        row
        for row in state.pending
        if str(row.get("client_order_id") or "") in still_working
    ]
    if state.unconfirmed_rebalance is None:
        return new
    # The rebalance's whole set of legs, from the journal's latest entry per
    # order, so a terminal leg is never forgotten when another fills later.
    legs = [e for e in new.journal if e["session"] == state.unconfirmed_rebalance]
    if not legs or any(not e["terminal"] for e in legs):
        # Nothing to conclude yet; ask again next session.
        return new
    if all(e["status"] == "filled" for e in legs):
        new.unconfirmed_rebalance = None
        return new
    # It did not go through. Put the clock back so it is tried again.
    new.unconfirmed_rebalance = None
    new.last_rebalance = state.previous_rebalance
    new.sessions_since_rebalance = REBALANCE_EVERY
    return new


# A stable id for one order, chosen before it is sent.
def order_id(session: str, symbol: str, side: str) -> str:
    """Return the client order id for a symbol on a session."""
    return f"anios-{session}-{side}-{symbol}".lower()


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
