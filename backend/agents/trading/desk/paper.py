"""The paper book: the desk's decisions carried out on the paper account.

The rules are the ones that measured best, and nothing else:

* Every `REBALANCE_EVERY` sessions the paper book is brought to the desk's
  target weights (buys and sells at the next open, whole shares, moves
  smaller than `MIN_TRADE` of equity skipped).
* Between rebalances the book is left alone except for the exit rule: a
  held name whose grade has been C for `PATIENCE` consecutive sessions is
  sold at the next open. No price stop, because every stop measured worse
  than none on every name.
* The plan for a session is made once. Running the day twice submits
  nothing the second time.

The state (the rebalance clock, each held name's run of C grades, the
starting equity and the equity history) lives in one JSON file under the
market data root, next to the desk records, so the track record is a
file anyone can read.
"""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading.desk.grading import ORDINAL, B

REBALANCE_EVERY = 20
PATIENCE = 10
MIN_TRADE = 0.005
PAPER_KIND = "paper"


@dataclass
class PaperState:
    """What the paper book remembers between sessions."""

    sessions_seen: list[str] = field(default_factory=list)
    last_rebalance: str | None = None
    sessions_since_rebalance: int = 0
    c_streak: dict[str, int] = field(default_factory=dict)
    start_equity: float | None = None
    history: list[dict] = field(default_factory=list)


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
) -> tuple[list[PaperOrder], PaperState, str]:
    """Return (orders, new state, what the day was)."""
    if session in state.sessions_seen:
        return [], state, "already planned for this session"
    new = PaperState(**asdict(state))
    new.sessions_seen = state.sessions_seen + [session]
    # The run of C grades per held name.
    streak = {}
    for symbol in held:
        below = ORDINAL.get(grades.get(symbol, "C"), 0) < ORDINAL[B]
        streak[symbol] = state.c_streak.get(symbol, 0) + 1 if below else 0
    new.c_streak = streak
    orders: list[PaperOrder] = []
    rebalance = (
        state.last_rebalance is None
        or state.sessions_since_rebalance + 1 >= REBALANCE_EVERY
    )
    if rebalance:
        new.last_rebalance = session
        new.sessions_since_rebalance = 0
        for symbol in sorted(set(held) | set(targets)):
            price = prices.get(symbol)
            if not price or price <= 0:
                continue
            target_qty = math.floor(targets.get(symbol, 0.0) * equity / price)
            delta = target_qty - int(held.get(symbol, 0))
            if abs(delta) * price < MIN_TRADE * equity:
                continue
            if delta > 0:
                orders.append(
                    PaperOrder(
                        symbol, "buy", delta, f"rebalance to {targets[symbol]:.3f}"
                    )
                )
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
        for symbol, run in streak.items():
            qty = int(held.get(symbol, 0))
            if run >= PATIENCE and qty > 0:
                orders.append(
                    PaperOrder(symbol, "sell", qty, f"grade below B for {run} sessions")
                )
        what = "hold" if not orders else "exits"
    # Sells first, so the buys have the cash.
    orders.sort(key=lambda o: (o.side != "sell", -o.qty))
    return orders, new, what


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
