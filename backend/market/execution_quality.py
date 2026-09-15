"""Execution measured as a series: every paper fill against its decision price.

Each order the desk sends carries the reference price its decision was
made at (the daily close for a rebalance, the completed fifteen-minute
bar for an intraday event cut). The journal keeps the fill. The
difference, signed so that paying up on a buy or selling down on a sell
is positive, is the cost of getting from the decision to the position.
The record already shows it per order on the night; this adds the
series the roadmap asks for: by session, by kind (scheduled rebalance
against FOMC overlay), and cumulative, in basis points of filled
notional and in dollars, so a change in execution shows up as a trend
and not as one night's footnote. Nothing here changes an order.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading.desk import execution_evidence

VERSION = "execution-quality/1"
NAME = "execution.json"
RECENT = 20


# One row per confirmed fill with a usable reference price.
def fill_rows(state) -> list[dict]:
    """Return [{session, symbol, side, kind, qty, notional, bps, dollars}]."""
    out = []
    for row in state.journal:
        qty = float(row.get("filled_qty") or 0)
        fill = row.get("filled_price")
        reference = (row.get("execution") or {}).get("reference_price")
        bps = execution_evidence.decision_shortfall_bps(
            row.get("side"), fill, reference
        )
        if qty <= 0 or bps is None:
            continue
        notional = qty * float(reference)
        out.append(
            {
                "session": row.get("session"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "kind": "fomc" if row.get("event_id") else "rebalance",
                "qty": qty,
                "notional": notional,
                "bps": bps,
                "dollars": bps / 1e4 * notional,
                "source": (row.get("execution") or {}).get("reference_source"),
            }
        )
    return sorted(out, key=lambda r: (r["session"] or "", r["symbol"] or ""))


# Notional-weighted shortfall and totals over a set of rows.
def aggregate(rows: list[dict]) -> dict:
    """Return {fills, notional, dollars, bps} for the rows."""
    notional = sum(r["notional"] for r in rows)
    dollars = sum(r["dollars"] for r in rows)
    return {
        "fills": len(rows),
        "notional": notional,
        "dollars": dollars,
        "bps": dollars / notional * 1e4 if notional else None,
    }


# The block: all time, the recent sessions, by kind, and the session series.
def report(state, now: datetime | None = None) -> dict:
    """Return the execution-quality block as plain data."""
    rows = fill_rows(state)
    sessions = sorted({r["session"] for r in rows if r["session"]})
    series = []
    running = 0.0
    for session in sessions:
        todays = [r for r in rows if r["session"] == session]
        agg = aggregate(todays)
        running += agg["dollars"]
        series.append({"session": session, **agg, "cumulative_dollars": running})
    recent = [r for r in rows if r["session"] in set(sessions[-RECENT:])]
    return {
        "version": VERSION,
        "written": (now or datetime.now(tz=UTC)).isoformat(timespec="seconds"),
        "all_time": aggregate(rows),
        "recent": {"sessions": len(sessions[-RECENT:]), **aggregate(recent)},
        "by_kind": {
            kind: aggregate([r for r in rows if r["kind"] == kind])
            for kind in ("rebalance", "fomc")
        },
        "by_side": {
            side: aggregate([r for r in rows if r["side"] == side])
            for side in ("buy", "sell")
        },
        "series": series,
        "worst": sorted(rows, key=lambda r: -r["bps"])[:5],
        "basis": (
            "signed so that paying up on a buy or selling down on a sell is "
            "positive; basis points of the decision's reference notional; the "
            "paper account pays no commission"
        ),
    }


def path(root: Path) -> Path:
    """Where the block lives."""
    return Path(root) / "desk" / NAME


# Write the block beside the records; never raise into the nightly.
def write(root: Path) -> dict | None:
    """Write the block and return it, or None with the reason printed."""
    from backend.agents.trading.desk import paper

    try:
        block = report(paper.load_state(Path(root)))
    except Exception as exc:  # noqa: BLE001 - evidence, never a reason to stop
        print(f"\nexecution quality: not written ({type(exc).__name__}: {exc})")
        return None
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(block, indent=1), encoding="utf-8")
    a, r = block["all_time"], block["recent"]
    bps = f"{a['bps']:+.1f} bp" if a["bps"] is not None else "no fills"
    recent = f"{r['bps']:+.1f} bp" if r["bps"] is not None else "no fills"
    print(
        f"\nexecution quality: {a['fills']} fills, {bps} against the decision price "
        f"({a['dollars']:+,.0f}); last {r['sessions']} sessions {recent}"
    )
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
