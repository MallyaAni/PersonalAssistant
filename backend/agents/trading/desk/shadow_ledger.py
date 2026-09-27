"""A dry-run account for one policy, observed nightly; it never places an order.

The roadmap's forward step for a passing arm is a 4-6 week fidelity shadow
on its own dry-run ledger, judged by order-level agreement with a replay
of the simulator, a tracking difference of at most 5 bp a day, zero
sessions with negative cash and at least ten fills per new order class.
This module is that ledger for `policy_v4` (`graded-equal-weight/4`),
running beside the live `/3` paper book on the same desk report and the
same prices, with nothing in common with the broker.

The account is the simulator's on the arm's own terms: a decision is made
at the close from what the close could see (the desk's grades, the closing
prices, the account's value), sized by the shared `planner.plan` and
rounded to the whole shares a broker would take; it fills at the next
session's open, sells first and buys from the cash on hand plus the net
proceeds, at ten basis points a side, and a buy the cash cannot pay for is
scaled down with the rest and its remainder written down rather than
borrowed. Cash is never negative. The book is marked at each close, and
targets are re-decided every `REBALANCE_EVERY` sessions, the reset cadence
the arm was measured on (`market_pit_scorecard` runs every arm with
`rebalance=paper.REBALANCE_EVERY` and no exit overlay); between resets the
account holds, exactly as the measured curve does. The policy's would-be
targets are still written on every session, so grade churn between resets
is visible without being traded.

Storage follows `market.opportunity_shadow`: one JSON row per completed
transition under `<root>/desk/shadow/<policy-slug>/NNNNNNNN.json`, written
to a temporary file, fsynced and hard-linked into place so a row is either
whole or absent and a sequence number is never overwritten; the latest row
is the state, and a malformed row stops the account rather than resetting
it. Each row carries the policy version and an identity hash of this file
and `policy_v4.py`; when the code changes, the ledger refuses to continue
unless the continuation is declared in `shadow_ledger_migrations.json`
beside this module, so a frozen experiment cannot drift without saying so.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import paper, planner, policy_v4

VERSION = "shadow-ledger/1"
START_CASH = 100_000.0
# Ten basis points a side, the lower of the two costs every arm was priced at.
COST_BPS = 10.0
# The reset cadence the arm was measured on; between resets the book holds.
REBALANCE_EVERY = paper.REBALANCE_EVERY
# Declared continuations across code revisions: (from, to, reason) rows,
# outside the hash because the successor identity cannot be written into
# the code it hashes.
MIGRATIONS = Path(__file__).parent / "shadow_ledger_migrations.json"


# The folder name a policy version is stored under: the version with its
# slash made safe for a path ("graded-equal-weight/4" -> "graded-equal-weight-4").
def slug(policy_version: str) -> str:
    """Return the path-safe form of a policy version string."""
    return policy_version.replace("/", "-")


# Where one policy's ledger lives under the market data root.
def folder(root: Path, policy_version: str = policy_v4.POLICY_VERSION) -> Path:
    """Return `<root>/desk/shadow/<policy-slug>`."""
    return Path(root) / "desk" / "shadow" / slug(policy_version)


# The code identity of the experiment: the policy and this ledger, hashed as
# whole files, so any edit to either is caught before it can continue a
# frozen account.
def identity() -> str:
    """Return the sha256 of policy_v4.py and shadow_ledger.py."""
    code = b""
    for path in (Path(policy_v4.__file__), Path(__file__)):
        code += path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
    return hashlib.sha256(code).hexdigest()


# Commit one complete transition without overwriting any prior sequence.
def append(folder: Path, row: dict) -> dict:
    """Write `row` as `<sequence>.json`; refuse to replace an existing one."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{row['sequence']:08d}.json"
    descriptor, name = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(row, stream, allow_nan=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, target)
    finally:
        os.unlink(name)
    return row


# The last completed transition, or None on a fresh folder. A row that does
# not parse raises: a malformed record never resets the account.
def latest(folder: Path) -> dict | None:
    """Return the highest-sequence row, or None."""
    paths = sorted(Path(folder).glob("[0-9]*.json"))
    return json.loads(paths[-1].read_text(encoding="utf-8")) if paths else None


# The declared continuation from one identity to another, or None.
def migration(from_identity: str, to_identity: str, path: Path | None = None):
    """Return the declared migration row for the pair, or None."""
    path = path or MIGRATIONS
    if not path.exists():
        return None
    for row in json.loads(path.read_text(encoding="utf-8")):
        if row.get("from") == from_identity and row.get("to") == to_identity:
            return row
    return None


# The state to advance from: the latest row, continued under a declared
# migration when the code has changed, or a fresh sequence-0 account.
def initialize(
    folder: Path, code_identity: str, now: datetime, migrations: Path | None = None
) -> dict:
    """Return the current state row, creating sequence 0 on a fresh folder."""
    prior = latest(folder)
    if prior:
        if prior["policy"] != policy_v4.POLICY_VERSION:
            raise ValueError("Frozen experiment changed; use a separate run directory")
        if prior["identity"] != code_identity:
            declared = migration(prior["identity"], code_identity, migrations)
            if declared is None:
                raise ValueError(
                    "Frozen experiment changed; use a separate run directory"
                )
            return {
                **prior,
                "identity": code_identity,
                "identity_from": prior["identity"],
                "migration": declared["reason"],
            }
        return prior
    return append(
        folder,
        {
            "version": VERSION,
            "policy": policy_v4.POLICY_VERSION,
            "identity": code_identity,
            "sequence": 0,
            "session": None,
            "started_at": now.isoformat(),
            "observed_at": now.isoformat(),
            "cash": START_CASH,
            "shares": {},
            "equity": START_CASH,
            "return_1d": None,
            "pending": None,
            "sessions_since_rebalance": REBALANCE_EVERY,
            "fills": [],
            "refusals": [],
            "targets": {},
            "status": "Awaiting the first completed session",
        },
    )


# Only the finite, positive prices of a {ticker: price} map, as floats.
def _priced(prices: dict) -> dict[str, float]:
    out = {}
    for ticker, value in (prices or {}).items():
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            out[ticker] = price
    return out


# Whether `session` is the very next session after `prior` on the panel's
# calendar: the only case in which today's open is the open the pending
# targets were decided for. A missed nightly, or a prior session the panel
# no longer holds, is not.
def _is_next_session(dates: np.ndarray, prior: str | None, session: str) -> bool:
    if prior is None:
        return False
    days = np.asarray(dates, dtype="datetime64[D]")
    here = np.flatnonzero(days == np.datetime64(session))
    there = np.flatnonzero(days == np.datetime64(prior))
    return bool(len(here) and len(there) and here[0] - there[0] == 1)


# Split the pending share orders into the sells and the buys they imply at
# today's open, as share deltas; a name with no opening price is refused
# and left as it is.
def _legs(
    shares: dict[str, int], orders: dict[str, int], opens: dict[str, float]
) -> tuple[dict[str, int], dict[str, int], list[dict]]:
    sells: dict[str, int] = {}
    buys: dict[str, int] = {}
    refusals: list[dict] = []
    for ticker in sorted(orders):
        wanted = int(orders[ticker])
        have = int(shares.get(ticker, 0))
        if wanted == have:
            continue
        if ticker not in opens:
            refusals.append(
                {
                    "ticker": ticker,
                    "shares": wanted - have,
                    "reason": "no opening price",
                }
            )
        elif wanted < have:
            sells[ticker] = have - wanted
        else:
            buys[ticker] = wanted - have
    return sells, buys, refusals


# One fill's journal line.
def _fill_row(ticker: str, side: str, shares: int, price: float, fee: float) -> dict:
    return {
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "price": price,
        "cost": fee,
    }


# Fill the pending share orders at today's open: sells first at ten basis
# points, then buys from the cash on hand plus the net proceeds, scaled down
# together and floored to whole shares when the cash is short. Returns the
# new (cash, shares, fills, refusals); cash never goes below zero.
def _fill(
    cash: float,
    shares: dict[str, int],
    orders: dict[str, int],
    opens: dict[str, float],
) -> tuple[float, dict[str, int], list[dict], list[dict]]:
    cost = COST_BPS / 1e4
    held = dict(shares)
    sells, buys, refusals = _legs(held, orders, opens)
    fills: list[dict] = []
    for ticker, qty in sells.items():
        price = opens[ticker]
        fee = qty * price * cost
        cash += qty * price - fee
        held[ticker] = int(held.get(ticker, 0)) - qty
        if held[ticker] <= 0:
            held.pop(ticker, None)
        fills.append(_fill_row(ticker, "sell", qty, price, fee))
    spend = sum(qty * opens[t] * (1.0 + cost) for t, qty in buys.items())
    scale = min(1.0, max(0.0, cash) / spend) if spend > 0 else 1.0
    for ticker, qty in buys.items():
        price = opens[ticker]
        affordable = math.floor(qty * scale + 1e-10)
        # Whole-share flooring can still leave the basket a few dollars over
        # what the cash holds; the last share comes off rather than the cash
        # going negative.
        while affordable > 0 and affordable * price * (1.0 + cost) > cash + 1e-9:
            affordable -= 1
        if affordable < qty:
            refusals.append(
                {"ticker": ticker, "shares": qty - affordable, "reason": "cash"}
            )
        if affordable <= 0:
            continue
        fee = affordable * price * cost
        cash -= affordable * price + fee
        held[ticker] = int(held.get(ticker, 0)) + affordable
        fills.append(_fill_row(ticker, "buy", affordable, price, fee))
    return max(cash, 0.0), held, fills, refusals


# The account's value at `prices`; a held name without a price fails closed
# rather than being marked at zero or at yesterday's close.
def _mark(cash: float, shares: dict[str, int], prices: dict[str, float]) -> float:
    missing = sorted(t for t, q in shares.items() if q > 0 and t not in prices)
    if missing:
        raise ValueError("held valuation unavailable: " + ", ".join(missing))
    return float(cash + sum(q * prices[t] for t, q in shares.items() if q > 0))


# The policy's target weights on the report's last session, keyed by ticker
# and holding only the names it wants.
def decide(report) -> dict[str, float]:
    """Return {ticker: weight} from `policy_v4.targets` on the last session."""
    panel = report.panel
    last = len(panel.dates) - 1
    eligible = np.ones(len(panel.tickers), dtype=bool)
    weights = policy_v4.targets(
        report.graded.grades[last],
        panel.close[last],
        eligible,
        panel.index(panel.benchmark),
    )
    return {
        ticker: float(w)
        for ticker, w in zip(panel.tickers, weights, strict=True)
        if w > 0
    }


# The whole-share orders that move `shares` to `weights`, sized at the close
# by the shared planner: {ticker: shares to end up holding} for every name
# that moves.
def _orders(
    weights: dict[str, float],
    shares: dict[str, int],
    equity: float,
    closes: dict[str, float],
) -> dict[str, int]:
    held = {t: float(q) for t, q in shares.items() if q > 0}
    moves = planner.plan(weights, held, equity, closes)
    orders: dict[str, int] = {}
    for move in moves:
        qty = int(round(move.qty))
        if qty <= 0:
            continue
        have = int(shares.get(move.symbol, 0))
        orders[move.symbol] = have + qty if move.side == "buy" else max(have - qty, 0)
    return orders


# One nightly observation: fill yesterday's pending orders at today's open,
# mark at today's close, record the day's return, then decide from today's
# grades. Observing a session already recorded appends nothing.
def observe(
    root: Path,
    report,
    prices_open_today: dict,
    prices_close_today: dict,
    session: str,
    now: datetime | None = None,
    migrations: Path | None = None,
) -> dict:
    """Append and return the row for `session`, or return the row already there."""
    now = now or datetime.now(UTC)
    where = folder(root)
    state = initialize(where, identity(), now, migrations)
    prior = state["session"]
    if prior == session:
        return state
    if prior is not None and session < prior:
        raise ValueError(f"session {session} is before the ledger's {prior}")
    opens = _priced(prices_open_today)
    closes = _priced(prices_close_today)
    cash = float(state["cash"])
    shares = {t: int(q) for t, q in (state.get("shares") or {}).items() if int(q) > 0}
    fills: list[dict] = []
    refusals: list[dict] = []
    pending = state.get("pending")
    if pending:
        if _is_next_session(report.panel.dates, prior, session):
            cash, shares, fills, refusals = _fill(
                cash, shares, pending["orders"], opens
            )
        else:
            # A missed nightly cannot manufacture a fill at an open that has
            # already passed; the intent is cancelled and said so.
            refusals.append(
                {
                    "ticker": None,
                    "shares": None,
                    "reason": (
                        f"pending orders decided {pending['decided']} cancelled: "
                        f"{session} is not the next session"
                    ),
                }
            )
    equity = _mark(cash, shares, closes)
    previous_equity = float(state["equity"])
    return_1d = (
        equity / previous_equity - 1.0
        if prior is not None and previous_equity > 0
        else None
    )
    since = int(state.get("sessions_since_rebalance", REBALANCE_EVERY)) + 1
    weights = decide(report)
    due = since >= REBALANCE_EVERY
    new_pending = None
    if due:
        orders = _orders(weights, shares, equity, closes)
        new_pending = {"decided": session, "targets": weights, "orders": orders}
        since = 0
    # The state's own keys carry forward (version, policy, identity, the
    # start time, and a declared migration's provenance when there is one).
    row = {
        **state,
        "sequence": int(state["sequence"]) + 1,
        "session": session,
        "observed_at": now.isoformat(),
        "cash": cash,
        "shares": shares,
        "equity": equity,
        "return_1d": return_1d,
        "pending": new_pending,
        "sessions_since_rebalance": since,
        "fills": fills,
        "refusals": refusals,
        "targets": weights,
        "marks": {t: closes[t] for t in sorted(shares)},
        "status": "Observed; targets reset" if due else "Observed; holding",
    }
    return append(where, row)


# The record's receipt for one observation: what the fidelity shadow needs
# to be judged from the nightly records alone.
def receipt(row: dict) -> dict:
    """Return the small dict the desk record carries for this policy."""
    pending = row.get("pending") or {}
    return {
        "sequence": row.get("sequence"),
        "session": row.get("session"),
        "equity": row.get("equity"),
        "return_1d": row.get("return_1d"),
        "orders_decided": len(pending.get("orders") or {}),
        "fills": len(row.get("fills") or []),
        "refusals": len(row.get("refusals") or []),
        "note": row.get("status"),
    }
