"""Execution measured as a series, with the waiting told apart from the trading.

Each order the desk sends carries the reference price its decision was
made at (the daily close for a rebalance, the completed fifteen-minute
bar for an intraday event cut). The journal keeps the fill. The whole
distance between them, signed so that paying up on a buy or selling
down on a sell is positive, is the cost of getting from the decision to
the position - but most of it is usually not execution at all.

A nightly order is decided at one session's close and reaches the market
at the next session's open, so the market's move in between is priced
into the fill before any broker touches it. On 2026-09-17 the desk's
nine FOMC restoration buys measured +234 bp against their decision
price; +243 bp of that was the overnight gap and -9 bp was the actual
trading, which was good. Reporting only the total made good execution
look like a disaster and would have hidden a real one.

So each fill is split at a benchmark: the price the order could first
have traded at once it reached the market. For an order queued for the
open that is the fill session's open; for a scheduled sell queued into
the closing auction it is that session's close; for an intraday event
cut it is the reference bar itself, which the order is already trading
against. Drift is decision to benchmark, slippage is benchmark to fill,
and the two add to the old total exactly. Drift is display-only: for an
overlay fill it is already inside the FOMC gate's effect, and for a
rebalance fill it is already inside the account's realised return, so
nothing here may ever be netted into a P&L. Nothing here changes an
order.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.agents.trading.desk import execution_evidence
from backend.market import report_files

VERSION = "execution-quality/2"
NAME = "execution.json"
RECENT = 20
# An intraday event cut prices itself against a completed fifteen-minute
# bar and fills seconds later in the same session: there is no waiting to
# tell apart, so its benchmark is that reference and its drift is zero.
INTRADAY_SOURCE = "completed 15-minute bar"
NEW_YORK = ZoneInfo("America/New_York")
OPEN_MINUTE = 9 * 60 + 30
CLOSE_MINUTE = 16 * 60


# Where an order first reached the market, by the way it was sent: a
# scheduled sell goes into the closing auction, everything else is queued
# for the open, and an intraday cut is already trading against its bar.
def benchmark_kind(row: dict) -> str:
    """Return "reference", "close" or "open" for the row's order type."""
    if (row.get("execution") or {}).get("reference_source") == INTRADAY_SOURCE:
        return "reference"
    if row.get("side") == "sell" and not row.get("event_id"):
        return "close"
    return "open"


# Whether the order was sent into the session it filled in rather than
# queued ahead of it. A retry that goes out at eleven o'clock has no
# opening price to be measured against: the morning already happened
# before it was sent, and booking that as slippage inverts the sign on a
# sell into a rally.
def _submitted_within(execution: dict, session: str | None) -> bool:
    """Return True when the order was submitted inside `session`'s hours."""
    stamp = execution_evidence.timestamp(execution.get("submitted_at"))
    if not stamp or not session:
        return False
    try:
        when = datetime.fromisoformat(stamp).astimezone(NEW_YORK)
    except (TypeError, ValueError):
        return False
    if when.date().isoformat() != session:
        return False
    return OPEN_MINUTE <= when.hour * 60 + when.minute < CLOSE_MINUTE


# The benchmark price itself, read from the store's own bar for the session
# the fill actually completed in. None when the session is unknown, when the
# bar is not on file, or when the order was sent into that session rather
# than queued ahead of it - each of which leaves the fill's total measured
# and its split unknown rather than wrong.
def benchmark_price(row: dict, store, session: str | None, reference: float):
    """Return the price the order could first have traded at, or None."""
    kind = benchmark_kind(row)
    if kind == "reference":
        return reference
    if store is None or not session:
        return None
    if kind == "open" and _submitted_within(row.get("execution") or {}, session):
        return None
    try:
        # The newest partition, not one pinned to the session: the nightly
        # labels its partition with the UTC date, so after 20:00 New York
        # there is no partition at or before the session it just fetched.
        # The session_date match below is what guarantees the right bar.
        history = store.read(row.get("symbol"))
    except Exception:  # noqa: BLE001 - evidence, never a reason to stop
        return None
    if history is None:
        return None
    for bar in getattr(history, "bars", ()) or ():
        if str(getattr(bar, "session_date", "")) != session:
            continue
        price = getattr(bar, kind, None)
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None
    return None


# One row per confirmed fill with a usable reference price. `store` supplies
# the benchmark bar; without it every row still carries its total.
def fill_rows(state, store=None) -> list[dict]:
    """Return one row per fill, each split into drift and slippage."""
    out = []
    for row in state.journal:
        qty = float(row.get("filled_qty") or 0)
        fill = row.get("filled_price")
        execution = row.get("execution") or {}
        reference = execution.get("reference_price")
        bps = execution_evidence.decision_shortfall_bps(
            row.get("side"), fill, reference
        )
        if qty <= 0 or bps is None:
            continue
        reference = float(reference)
        notional = qty * reference
        # The session the fill completed in, from the broker's own stamp; a
        # row without one keeps its plan session, which is all the older
        # rebalance rows have.
        decision_session = row.get("session")
        filled = execution_evidence.completion_session(execution)
        session = filled or decision_session
        # The benchmark is read for the session the fill completed in and
        # for no other. A row whose broker stamp is missing keeps its total
        # and reports no split; the plan session's bar is always on file and
        # would produce a confident, wrong answer.
        mark = benchmark_price(row, store, filled, reference)
        sign = 1 if row.get("side") == "buy" else -1
        drift = None if mark is None else sign * qty * (mark - reference)
        slip = None if mark is None else sign * qty * (float(fill) - mark)
        out.append(
            {
                "session": session,
                "decision_session": decision_session,
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "kind": "fomc" if row.get("event_id") else "rebalance",
                "qty": qty,
                "notional": notional,
                "bps": bps,
                "dollars": bps / 1e4 * notional,
                "source": execution.get("reference_source"),
                "benchmark": mark,
                "benchmark_kind": benchmark_kind(row),
                "drift_dollars": drift,
                "slippage_dollars": slip,
                "drift_bps": None if drift is None else drift / notional * 1e4,
                "slippage_bps": None if slip is None else slip / notional * 1e4,
            }
        )
    return sorted(out, key=lambda r: (r["session"] or "", r["symbol"] or ""))


# Notional-weighted shortfall and totals over a set of rows. Drift and
# slippage are weighted over the rows that have a benchmark only, and
# `measured` says how many that was, so a partial split never reads as a
# figure for every fill.
def aggregate(rows: list[dict]) -> dict:
    """Return the totals for the rows, with the split where it is known."""
    notional = sum(r["notional"] for r in rows)
    dollars = sum(r["dollars"] for r in rows)
    # The net can sit near zero while fills scatter widely on both sides;
    # the absolute figure says how far from the decision price fills land.
    absolute = sum(abs(r["dollars"]) for r in rows)
    split = [r for r in rows if r.get("slippage_dollars") is not None]
    measured = sum(r["notional"] for r in split)
    drift = sum(r["drift_dollars"] for r in split)
    slip = sum(r["slippage_dollars"] for r in split)
    return {
        "fills": len(rows),
        "notional": notional,
        "dollars": dollars,
        "bps": dollars / notional * 1e4 if notional else None,
        "abs_bps": absolute / notional * 1e4 if notional else None,
        "measured": len(split),
        "measured_notional": measured,
        "drift_dollars": drift if split else None,
        "slippage_dollars": slip if split else None,
        "drift_bps": drift / measured * 1e4 if measured else None,
        "slippage_bps": slip / measured * 1e4 if measured else None,
    }


# The block: all time, the recent sessions, by kind, and the session series.
def report(state, now: datetime | None = None, store=None) -> dict:
    """Return the execution-quality block as plain data."""
    rows = fill_rows(state, store)
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
        # The worst fills are the worst *trades*: a name that gapped is not
        # an execution failure, and sorting on the total would leave this
        # table permanently occupied by whichever names moved overnight. A
        # fill with no slippage has nothing to rank and is left out rather
        # than ranked by a different quantity.
        "worst": sorted(
            [r for r in rows if r["slippage_bps"] is not None],
            key=lambda r: -r["slippage_bps"],
        )[:5],
        "basis": (
            "slippage is the benchmark to the fill: what the trading cost. "
            "Drift is the decision price to the benchmark - the market's own "
            "move between deciding and reaching the market. Equity is already "
            "struck from actual fill prices, so adding drift to any result "
            "would double-count it; it is shown to explain the total and is "
            "never a figure to add. The benchmark is the fill session's open "
            "for an order queued ahead of the open, its close for a scheduled "
            "sell sent into the closing auction, and the reference bar itself "
            "for an intraday cut; a fill whose session, bar or order path is "
            "not one of those is counted in the total and left out of the "
            "split. The benchmark comes from the daily consolidated bar while "
            "the fill comes from the broker, so a few basis points of any "
            "slippage figure are that difference rather than execution. "
            "Signed so that paying up on a buy or selling down on a sell is "
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
    from backend.market.store import MarketStore

    try:
        # The benchmark bars live in the same store the paper state does.
        block = report(paper.load_state(Path(root)), store=MarketStore(Path(root)))
    except Exception as exc:  # noqa: BLE001 - evidence, never a reason to stop
        print(f"\nexecution quality: not written ({type(exc).__name__}: {exc})")
        return None
    if not report_files.write_json(path(root), block, "execution quality"):
        return None
    a, r = block["all_time"], block["recent"]
    total = f"{a['bps']:+.1f} bp" if a["bps"] is not None else "no fills"
    slip = (
        f"{a['slippage_bps']:+.1f} bp" if a["slippage_bps"] is not None else "unsplit"
    )
    drift = f"{a['drift_bps']:+.1f} bp" if a["drift_bps"] is not None else "unsplit"
    recent = (
        f"{r['slippage_bps']:+.1f} bp" if r["slippage_bps"] is not None else "no fills"
    )
    print(
        f"\nexecution quality: {a['fills']} fills, {slip} slippage "
        f"({a['measured']} split); {drift} drift to the benchmark; {total} in all "
        f"against the decision price ({a['dollars']:+,.0f}); last {r['sessions']} "
        f"sessions {recent} slippage"
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
