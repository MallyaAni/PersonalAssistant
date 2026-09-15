"""The FOMC overlay priced against the book that never traded it, meeting by meeting.

The paper book cuts held shares before a meeting and restores them after
(`event_execution`). Whether that helps is unknown: two completed meetings
since the guidance change, and every variant cost return over 2021-2026.
So the rule stays as it is and is judged by a gate written before the
outcome of the next meeting was known (`docs/research/fomc-gate-2026-09-15.md`).

The counterfactual is exact for the paper account. For every confirmed
event fill, a sale of q shares at p on session s means the book without
the overlay still holds q shares: its equity on any later session t is the
live equity plus q x (close_t - p). A restoration buy of q at p is the
reverse. Once a cycle is fully restored the difference is the overlay's
realised round trip. Commissions are zero on the paper account; a
second column charges the overlay's traded notional at a stated cost so
the verdict does not rest on free trading.

Nothing here changes a decision. The block is written nightly beside the
record and read by the page.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

VERSION = "fomc-gate/1"
FIRST_MEETING = "2026-09-16"
MIN_MEETINGS = 6
COST_BP = 25.0
NAME = "fomc-gate.json"


# The confirmed fills of each event cycle, oldest first.
def cycles(state) -> list[dict]:
    """Return [{id, decision_date, fills, active}] from the paper journal."""
    by_id: dict[str, list[dict]] = {}
    for row in state.journal:
        event_id = row.get("event_id")
        if not event_id or int(row.get("filled_qty") or 0) <= 0:
            continue
        by_id.setdefault(event_id, []).append(row)
    active = (state.event_cycle or {}).get("id")
    out = []
    for event_id, fills in by_id.items():
        decision = event_id.rsplit(":", 1)[-1]
        if decision < FIRST_MEETING:
            continue
        out.append(
            {
                "id": event_id,
                "decision_date": decision,
                "fills": sorted(
                    fills, key=lambda r: (r.get("session") or "", r.get("side"))
                ),
                "active": event_id == active,
            }
        )
    return sorted(out, key=lambda c: c["decision_date"])


# The live-minus-counterfactual difference on a session from the fills so far.
def overlay_difference(
    fills: list[dict], session: str, close: Callable
) -> float | None:
    """Return live equity minus the no-overlay equity on `session`, or None."""
    total = 0.0
    for row in fills:
        if (row.get("session") or "") > session:
            continue
        mark = close(row["symbol"], session)
        if mark is None:
            return None
        qty = float(row.get("filled_qty") or 0)
        price = float(row.get("filled_price") or 0)
        gain_kept = qty * (mark - price)  # what holding on would have earned
        total += -gain_kept if row.get("side") == "sell" else gain_kept
    return total


# Shares the overlay sold and never bought back, by symbol.
def unrestored(fills: list[dict]) -> dict[str, int]:
    """Return {symbol: net shares still sold} over the cycle's fills."""
    net: dict[str, int] = {}
    for row in fills:
        qty = int(row.get("filled_qty") or 0)
        symbol = row["symbol"]
        net[symbol] = net.get(symbol, 0) + (qty if row.get("side") == "sell" else -qty)
    return {s: q for s, q in net.items() if q > 0}


# The overlay's traded notional in a cycle, for the cost-adjusted column.
def traded_notional(fills: list[dict]) -> float:
    """Return the sum of |qty x price| over the cycle's confirmed fills."""
    return sum(
        abs(float(r.get("filled_qty") or 0) * float(r.get("filled_price") or 0))
        for r in fills
    )


# One meeting's row: both equity paths across the cycle's window and the effect.
def meeting_row(cycle: dict, history: list[dict], close: Callable) -> dict:
    """Return the meeting's effect, drawdowns and window."""
    by_session = {h["session"]: float(h["equity"]) for h in history}
    sessions = sorted(by_session)
    first_fill = min(r["session"] for r in cycle["fills"])
    start_index = (
        max(0, sessions.index(first_fill) - 1) if first_fill in sessions else None
    )
    if start_index is None:
        return {
            "decision_date": cycle["decision_date"],
            "status": "window not in the equity history",
            "complete": False,
        }
    last = (
        sessions[-1] if cycle["active"] else max(r["session"] for r in cycle["fills"])
    )
    window = [s for s in sessions[start_index:] if s <= last]
    live, without = [], []
    for s in window:
        diff = overlay_difference(cycle["fills"], s, close)
        if diff is None:
            return {
                "decision_date": cycle["decision_date"],
                "status": f"no mark for a fill on {s}",
                "complete": False,
            }
        live.append(by_session[s])
        without.append(by_session[s] - diff)
    base = live[0]
    effect = live[-1] - without[-1]
    cost = traded_notional(cycle["fills"]) * COST_BP / 10_000
    left = unrestored(cycle["fills"])
    # Complete means the round trip closed: every share the overlay sold
    # was bought back. A cycle the policy released with shares unbought
    # (cash-limited) is shown but does not count toward the gate, since
    # its effect would keep moving with those shares' prices.
    complete = not cycle["active"] and not left
    if cycle["active"]:
        status = "cycle open"
    elif left:
        status = "ended unrestored: " + ", ".join(
            f"{s} {q}" for s, q in sorted(left.items())
        )
    else:
        status = "restored"
    return {
        "decision_date": cycle["decision_date"],
        "window": [window[0], window[-1]],
        "sessions": len(window) - 1,
        "complete": complete,
        "status": status,
        "unrestored": left,
        "effect": effect,
        "effect_pct": effect / base if base else None,
        "effect_after_costs": effect - cost,
        "effect_after_costs_pct": (effect - cost) / base if base else None,
        "traded_notional": traded_notional(cycle["fills"]),
        "drawdown_live": _drawdown(live),
        "drawdown_without": _drawdown(without),
        "fills": len(cycle["fills"]),
    }


def _drawdown(path: list[float]) -> float:
    peak, worst = path[0], 0.0
    for v in path:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1 if peak else 0.0)
    return worst


# The gate, applied to the completed meetings only.
def verdict(rows: list[dict]) -> dict:
    """Return the standing of the gate: waiting, keep or retire."""
    done = [r for r in rows if r.get("complete") and "effect_after_costs" in r]
    total = sum(r["effect_after_costs"] for r in done)
    total_pct = sum(r["effect_after_costs_pct"] or 0.0 for r in done)
    deeper = sum(1 for r in done if r["drawdown_live"] < r["drawdown_without"])
    if len(done) < MIN_MEETINGS:
        standing = "waiting"
    elif total > 0 and deeper <= len(done) // 2:
        standing = "keep"
    else:
        standing = "retire"
    return {
        "standing": standing,
        "completed_meetings": len(done),
        "required": MIN_MEETINGS,
        "effect_after_costs": total,
        "effect_after_costs_pct": total_pct,
        "meetings_with_deeper_live_drawdown": deeper,
        "rule": (
            f"after {MIN_MEETINGS} completed meetings from {FIRST_MEETING}: "
            f"keep when the summed effect after {COST_BP:.0f} bp on traded "
            "notional is positive and the live drawdown is not deeper in more "
            "than half the meetings; otherwise retire. A change to the policy "
            "restarts the count."
        ),
    }


# Closes from the store, by symbol and session.
def store_closes(store) -> Callable:
    """Return close(symbol, session) reading the bars frames once each."""
    cache: dict[str, dict[str, float]] = {}

    def close(symbol: str, session: str) -> float | None:
        if symbol not in cache:
            frame = store.read_frame("bars", symbol)
            cache[symbol] = (
                {
                    str(d)[:10]: float(c)
                    for d, c in zip(
                        frame[0]["session_date"], frame[0]["close"], strict=False
                    )
                }
                if frame
                else {}
            )
        return cache[symbol].get(session)

    return close


# The whole block: every meeting since the first, the standing of the gate.
def report(root: Path, store=None, now: datetime | None = None) -> dict:
    """Return the gate block as plain data."""
    from backend.agents.trading.desk import paper
    from backend.market.store import MarketStore

    state = paper.load_state(Path(root))
    close = store_closes(store or MarketStore(Path(root)))
    rows = [meeting_row(c, state.history, close) for c in cycles(state)]
    return {
        "version": VERSION,
        "written": (now or datetime.now(tz=UTC)).isoformat(timespec="seconds"),
        "first_meeting": FIRST_MEETING,
        "cost_bp": COST_BP,
        "meetings": rows,
        "verdict": verdict(rows),
        "basis": (
            "paper account fills and closes; the book without the overlay holds "
            "every share the overlay sold until the overlay bought it back"
        ),
    }


def path(root: Path) -> Path:
    """Where the block lives."""
    return Path(root) / "desk" / NAME


# Write the block beside the records; never raise into the nightly.
def write(root: Path, store=None) -> dict | None:
    """Write the block and return it, or None with the reason printed."""
    try:
        block = report(root, store)
    except Exception as exc:  # noqa: BLE001 - evidence, never a reason to stop
        print(f"\nFOMC gate: not written ({type(exc).__name__}: {exc})")
        return None
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(block, indent=1), encoding="utf-8")
    v = block["verdict"]
    print(
        f"\nFOMC gate: {v['completed_meetings']} of {v['required']} meetings complete, "
        f"standing {v['standing']}, effect after costs {v['effect_after_costs']:+,.0f}"
    )
    for row in block["meetings"]:
        if "effect" in row:
            print(
                f"  {row['decision_date']} {row['status']:12} "
                f"effect {row['effect']:+,.0f} "
                f"({100 * (row['effect_pct'] or 0):+.2f}%), "
                f"drawdown live {100 * row['drawdown_live']:.1f}% "
                f"without {100 * row['drawdown_without']:.1f}%"
            )
        else:
            print(f"  {row['decision_date']} {row['status']}")
    return block


def load(root: Path) -> dict | None:
    """Return the last written block, or None."""
    target = path(root)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
