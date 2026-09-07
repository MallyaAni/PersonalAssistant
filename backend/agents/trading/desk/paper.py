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
) -> tuple[list[PaperOrder], PaperState, str]:
    """Return (orders, new state, what the day was)."""
    if session in state.sessions_seen:
        return [], state, "already planned for this session"
    new = PaperState(**asdict(state))
    new.sessions_seen = state.sessions_seen + [session]
    new.opened = {s: d for s, d in state.opened.items() if s in held}
    done = finished or {}
    orders: list[PaperOrder] = []
    rebalance = (
        state.last_rebalance is None
        or state.sessions_since_rebalance + 1 >= REBALANCE_EVERY
    )
    if rebalance:
        new.previous_rebalance = state.last_rebalance
        new.last_rebalance = session
        new.sessions_since_rebalance = 0
        for symbol in sorted(set(held) | set(targets)):
            price = prices.get(symbol)
            if not price or price <= 0:
                continue
            # Nearest whole share, not the floor. Market-on-open orders
            # must be whole shares, and flooring always rounds toward
            # holding less - which is worst exactly where it is least
            # affordable. On a 100,000 book a 4.9% target in a 1,740 stock
            # floors to 2 shares, 29% short of what was asked for, and the
            # book came out 12% under its target gross with almost all of
            # the miss in that one name. Rounding to nearest halves the
            # error and does not bias it one way.
            target_qty = round(targets.get(symbol, 0.0) * equity / price)
            delta = target_qty - int(held.get(symbol, 0))
            if abs(delta) * price < MIN_TRADE * equity:
                continue
            if delta > 0:
                orders.append(
                    PaperOrder(
                        symbol, "buy", delta, f"rebalance to {targets[symbol]:.3f}"
                    )
                )
                new.opened.setdefault(symbol, session)
            else:
                reason = (
                    "leaves the book"
                    if symbol not in targets
                    else f"rebalance to {targets[symbol]:.3f}"
                )
                orders.append(PaperOrder(symbol, "sell", -delta, reason))
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
        if order is None:
            # Never reached the broker, or reached it under another id.
            # Either way this desk cannot claim it traded.
            status, filled = "missing", 0
        else:
            filled = int(float(order.get("filled_qty") or 0))
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
            )
        )
    return out


# Fold the outcomes back into the state.
#
# A rebalance whose orders did not all fill is not a rebalance. The clock
# rolls back to the one before it, so the next session plans the rebalance
# again instead of waiting out twenty sessions on a book that never
# reached its targets. Orders still open are left pending and asked about
# again next session; everything settled is cleared.
def apply_settlements(state: PaperState, settled: list[Settled]) -> PaperState:
    """Return the state after recording what the broker did."""
    new = PaperState(**asdict(state))
    still_open = [
        row
        for row in state.pending
        if any(
            s.client_order_id == str(row.get("client_order_id") or "")
            and s.status == "open"
            for s in settled
        )
    ]
    new.pending = still_open
    if state.unconfirmed_rebalance is None:
        return new
    of_rebalance = [s for s in settled if s.session == state.unconfirmed_rebalance]
    if not of_rebalance or any(s.status == "open" for s in of_rebalance):
        # Nothing to conclude yet; ask again next session.
        return new
    if all(s.status == "filled" for s in of_rebalance):
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
