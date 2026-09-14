"""Recover missed paper-only FOMC reductions without rerunning a nightly decision."""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import event_execution, event_risk, paper
from backend.agents.trading.desk.desk import book_panel
from backend.cli import market_daily
from backend.market import alpaca_trading, calendar, desk_freshness
from backend.market.store import MarketStore


# Identify every execution component whose deployed version authorizes recovery.
def execution_hash():
    base = Path(__file__).resolve().parents[1]
    files = (
        "cli/market_event_recovery.py",
        "cli/market_daily.py",
        "cli/market_balancer.py",
        "agents/trading/desk/event_execution.py",
        "agents/trading/desk/event_risk.py",
        "agents/trading/desk/paper.py",
        "market/alpaca_trading.py",
    )
    return hashlib.sha256(
        b"".join((base / name).read_bytes() for name in files)
    ).hexdigest()


# Activate only the exact execution code in the backend that passed deployment gates.
def activate(root):
    path = root / "desk" / "event-recovery-enabled.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"sha256": execution_hash(), "activated_at": datetime.now(UTC).isoformat()}
        )
    )
    temporary.replace(path)


# A collector pulling new source cannot trade until the matching backend is deployed.
def activated(root):
    try:
        return (
            json.loads((root / "desk" / "event-recovery-enabled.json").read_text())[
                "sha256"
            ]
            == execution_hash()
        )
    except (OSError, ValueError, KeyError):
        return False


# Reconcile only complete broker evidence; an absent order cannot prove no fill.
def reconcile(client, state):
    if not state.pending:
        return state, []
    since = min(row["session"] for row in state.pending)
    broker = client.orders_since(f"{since}T00:00:00Z")
    ids = {row.get("client_order_id") for row in broker}
    missing = [row for row in state.pending if row["client_order_id"] not in ids]
    if missing:
        return state, missing
    return paper.apply_settlements(state, paper.settle(state.pending, broker)), []


# Refuse stale decisions, expired events and non-regular execution windows.
def ineligible(state, latest, snapshot, policy, client, today):
    decision = state.event_cycle.get("decision_date") or policy.get("decision_date")
    if not policy.get("calendar_known") or not decision:
        return "calendar unavailable"
    # Intraday recovery never restores exposure or revives an expired reduction.
    if today > date.fromisoformat(decision):
        return "awaiting nightly restoration"
    if not client.clock().get("is_open"):
        return "waiting for market open"
    if snapshot.get("decision_session") != latest["session"]:
        return "decision mismatch"
    if (
        calendar._future_session_offset(
            np.datetime64(latest["session"]), np.datetime64(today)
        )
        != 1
    ):
        return "previous-session decision required"
    return None


# Execute only the remaining reduction, preserving IDs across uncertain submissions.
def recover(root, latest, snapshot, policy, client, now):
    if client.base_url != alpaca_trading.PAPER_URL:
        raise ValueError("Recovery requires the official paper endpoint")
    state = paper.load_state(root)
    active = bool(state.event_cycle) or policy.get("factor") == event_risk.REDUCED
    result = {"as_of": now.isoformat(), "policy": policy, "active": active}
    if not active:
        return {**result, "status": "monitoring"}
    today = now.astimezone(desk_freshness.NEW_YORK).date()
    reason = ineligible(state, latest, snapshot, policy, client, today)
    if reason:
        return {**result, "status": reason}
    described = desk_freshness.describe(snapshot, now)
    state, missing = reconcile(client, state)
    paper.save_state(root, state)
    held = {p.symbol: p.qty for p in client.positions()}
    required = set(held) | {row["symbol"] for row in state.pending} | {"SPY"}
    if (
        any(
            described.get("quote_status", {}).get(s, {}).get("stale", True)
            for s in required
        )
        or described["stale"]
    ):
        return {**result, "status": "fresh completed prices required"}
    prices = {s: float(snapshot["quotes"][s]["last"]) for s in required}
    if not all(np.isfinite(p) and p > 0 for p in prices.values()):
        return {**result, "status": "valid prices required"}
    if missing:
        expected_event = state.event_cycle.get("id")
        if not expected_event or any(
            row.get("event_id") != expected_event or row["side"] != "sell"
            for row in state.pending
        ):
            return {**result, "status": "waiting for existing orders"}
        if any(row["qty"] > held.get(row["symbol"], 0) for row in missing):
            return {**result, "status": "holdings below pending reduction"}
        # A broker retry reuses the same client ID, never a newly sized replacement.
        orders = [
            paper.PaperOrder(
                row["symbol"],
                row["side"],
                row["qty"],
                row["reason"],
                row["client_order_id"],
                row["event_id"],
            )
            for row in missing
        ]
    elif state.pending or client.open_orders():
        return {**result, "status": "waiting for existing orders"}
    else:
        orders, state, _ = event_execution.plan(
            latest["session"],
            state,
            held,
            prices,
            client.account().cash,
            policy,
            advance_clock=False,
        )
        state.pending = [
            {
                "client_order_id": o.client_order_id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": o.qty,
                "session": today.isoformat(),
                "reason": o.reason,
                "event_id": o.event_id,
                "execution": {
                    "decision_at": now.isoformat(),
                    "reference_price": prices[o.symbol],
                    "reference_session": today.isoformat(),
                    "reference_source": "completed 15-minute bar",
                    "reference_bar": snapshot["quotes"][o.symbol]["bar"],
                },
            }
            for o in orders
        ]
        paper.save_state(root, state)
    submitted, refused = market_daily._submit(
        client, orders, today.isoformat(), True, intraday_event_reduction=True
    )
    market_daily._remember_acknowledgments(state, submitted, root, True, orders)
    return {
        **result,
        "status": "reduction pending" if state.pending else "reduction settled",
        "pending_orders": len(state.pending),
        "refused_orders": len(refused),
        "sold": event_execution.filled(state, "sell"),
        "cycle": state.event_cycle,
    }


# Recompute the historical policy and publish a separate current execution read.
def run(root: Path, latest: dict, snapshot: dict):
    if not activated(root):
        return {"status": "waiting for gated deployment"}
    now = datetime.now(UTC)
    with paper.transaction(root):
        try:
            panel, _ = book_panel(
                MarketStore(root), date.fromisoformat(latest["session"])
            )
            if str(panel.dates[-1]) != latest["session"]:
                raise ValueError("Policy history does not match decision")
            policy = event_risk.decision(panel)
            result = recover(
                root, latest, snapshot, policy, alpaca_trading.client_from_env(), now
            )
        except Exception as exc:
            # Keep failure visible without exposing provider text or credentials.
            result = {
                "as_of": now.isoformat(),
                "active": bool(paper.load_state(root).event_cycle),
                "status": "recovery unavailable",
                "error_type": type(exc).__name__,
            }
        path = root / "desk" / "event-live.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_suffix(".tmp")
        pending.write_text(json.dumps(result, indent=2), encoding="utf-8")
        pending.replace(path)
        return result


# The deployment script enables the running artifact without submitting any orders.
def main():
    import argparse

    from backend.config.settings import settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true", required=True)
    parser.parse_args()
    activate(Path(settings.MARKET_DATA_ROOT))
    print("FOMC recovery activated for the deployed execution code")


if __name__ == "__main__":
    main()
