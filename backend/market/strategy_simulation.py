"""Read-only display projections of an authenticated latest-policy account.

These are counterfactual portfolio decisions and executions, never broker history.
The carried predecessor prefix is excluded rather than relabelled as learned.
"""

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from backend.market.learned_holding_transition import POLICY

SCHEMA = "latest-strategy-simulation/1"
DIRECTORY = "desk/strategy-simulation"


# Require explicit finite account numbers without accepting booleans as sizes.
def number(value, *, positive=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError("Finite nonnegative simulation amount required")
    return value


# Require original timezone-aware decision and execution instants.
def instant(value):
    at = datetime.fromisoformat(value)
    if at.utcoffset() is None:
        raise ValueError("Aware simulation instant required")
    return at


# Preserve original nightly targets and funded quantities in each stock view.
def _project_decisions(account, nights, tickers):
    for night in nights:
        entry = night["entry"]
        observed = instant(night["at"])
        weights = entry.get("selected_targets", {}).get("weights", {})
        for name in tickers:
            weight = weights.get(name)
            tickers[name]["targets"].append(
                {
                    "date": night["session"],
                    "weight": number(weight) if weight is not None else None,
                }
            )
        actions = {row["ticker"]: row for row in entry.get("actions", [])}
        for intent in account["intents"]:
            if intent["session"] != night["session"]:
                continue
            name = intent["symbol"]
            if name not in tickers:
                raise ValueError("Simulation intent outside authenticated cohort")
            action = actions.get(name, {})
            label = (
                "BUY"
                if intent["side"] == "buy"
                else "TRIM"
                if action.get("action") == "trim"
                else "SELL"
            )
            qty = number(intent["qty"], positive=True)
            price = action.get("last_close")
            equity = number(entry["equity"], positive=True)
            tickers[name]["decisions"].append(
                {
                    "id": intent["client_order_id"],
                    "date": night["session"],
                    "ticker": name,
                    "at": observed.isoformat(),
                    "execute_on": intent.get("execute_on"),
                    "action": label,
                    "qty": qty,
                    "weight": qty * number(price, positive=True) / equity
                    if price is not None
                    else None,
                    "target_weight": weights.get(name),
                    "reason": intent["reason"],
                    "timing": intent.get(
                        "execution_timing", entry.get("execution_rule")
                    ),
                }
            )
    return {row["id"]: row for value in tickers.values() for row in value["decisions"]}


# Preserve executed sizes and times while keeping unfilled plans distinct.
def _project_trades(account, nights, tickers, decisions):
    start = account["holding_start"]
    night_index = {row["session"]: row for row in nights}
    intents = {row["client_order_id"]: row for row in account["intents"]}
    for fill in account["fills"]:
        if (
            fill["status"] == "expired"
            and fill["filled_qty"] == 0
            and fill["price"] is None
        ):
            continue
        decision = decisions.get(fill["client_order_id"])
        if decision is None:
            if intents[fill["client_order_id"]]["session"] >= start:
                raise ValueError("Latest-policy execution has no matching decision")
            continue
        at = instant(fill["at"])
        if (
            at < instant(decision["at"])
            or at.date().isoformat() > account["last"]
            or fill["symbol"] != decision["ticker"]
            or fill["side"] != ("buy" if decision["action"] == "BUY" else "sell")
        ):
            raise ValueError("Simulation fill precedes its decision")
        qty, price = (
            number(fill["filled_qty"], positive=True),
            number(fill["price"], positive=True),
        )
        if qty > decision["qty"]:
            raise ValueError("Simulation fill exceeds planned size")
        equity = number(
            night_index[intents[fill["client_order_id"]]["session"]]["entry"]["equity"],
            positive=True,
        )
        tickers[fill["symbol"]]["trades"].append(
            {
                "id": fill["client_order_id"],
                "date": at.date().isoformat(),
                "at": at.isoformat(),
                "action": decision["action"],
                "qty": qty,
                "price": price,
                "fee": number(fill["fee"]),
                "weight": qty * price / equity,
                "decision_at": decision["at"],
                "decision_date": decision["date"],
            }
        )
    for value in tickers.values():
        for decision in value["decisions"]:
            executed = sum(
                row["qty"] for row in value["trades"] if row["id"] == decision["id"]
            )
            decision["executed_qty"] = executed
            if executed > decision["qty"]:
                raise ValueError("Simulation partial fills exceed planned size")
            decision["state"] = (
                "executed"
                if executed == decision["qty"]
                else "partial"
                if executed > 0
                else "not_executed"
            )
    return tickers


# Summarize the shared portfolio without including its predecessor-policy prefix.
def _summary(account, nights, tickers, provenance):
    start = account["holding_start"]
    names = sorted(tickers)
    sessions = {row["session"]: row for row in account["sessions"]}
    first = sessions[nights[0]["session"]]
    last = sessions[account["last"]]
    for name in names:
        tickers[name]["latest_target"] = nights[-1]["entry"]["selected_targets"][
            "weights"
        ].get(name)
        tickers[name]["latest_holding"] = last["holdings"].get(name, 0)
    curve = [
        {"date": row["session"], "equity": row["nav"], "cash": row["cash"]}
        for row in account["sessions"]
        if row["session"] >= start
    ]
    return {
        "schema": SCHEMA,
        "policy": POLICY,
        "provenance": provenance,
        "start": start,
        "through": account["last"],
        "initial_cash": account["initial_cash"],
        "starting_equity": first["nav"],
        "starting_holdings": first["holdings"],
        "starting_basis": "carried portfolio at learned-policy transition",
        "ending_equity": last["nav"],
        "ending_cash": last["cash"],
        "ending_holdings": last["holdings"],
        "curve": curve,
        "latest_positions": nights[-1]["entry"].get("positions", []),
        "latest_decisions": [
            row
            for value in tickers.values()
            for row in value["decisions"]
            if row["date"] == account["last"]
        ],
        "stock_overview": {
            name: {
                "target": value["latest_target"],
                "holding": value["latest_holding"],
                "last_trade": value["trades"][-1] if value["trades"] else None,
                "trades": len(value["trades"]),
            }
            for name, value in tickers.items()
        },
        "latest_targets": nights[-1]["entry"]["selected_targets"]["weights"],
        "counterfactual": True,
        "real_orders": False,
        "tickers": tickers,
    }


# Project one reconciled account without recomputing targets or inventing trades.
def project(account, provenance):
    if account["policy"] != POLICY or account["cost_bps"] != provenance["cost_bps"]:
        raise ValueError("Installed strategy and simulation costs must match")
    nights = [
        row
        for row in account["nightlies"]
        if row["session"] >= account["holding_start"]
        and row.get("entry", {}).get("policy") == POLICY
    ]
    if not nights or nights[-1]["session"] != account["last"]:
        raise ValueError("Completed latest-policy nightly coverage required")
    tickers = {
        name: {"ticker": name, "decisions": [], "trades": [], "targets": []}
        for name in sorted(nights[-1]["entry"]["selected_targets"]["weights"])
    }
    decisions = _project_decisions(account, nights, tickers)
    _project_trades(account, nights, tickers, decisions)
    return _summary(account, nights, tickers, provenance)


# Join only new verified sessions to the immutable completed carried account.
def continue_account(account, continuation, parent_sha):
    if (
        continuation["parent_account_sha256"] != parent_sha
        or continuation["policy"] != account["policy"]
        or continuation["cost_bps"] != account["cost_bps"]
        or continuation["counterfactual"] is not True
        or continuation["base_models_fitted"] != 0
        or continuation["original_account_replayed"] is not False
        or continuation["first"] != account["last"]
        or continuation["last"] <= account["last"]
        or continuation["sessions"][0] != account["sessions"][-1]
        or continuation["nightlies"][0] != account["nightlies"][-1]
    ):
        raise ValueError("Exact carried-account continuation required")
    for key in ("sessions", "nightlies"):
        dates = [row["session"] for row in continuation[key]]
        if dates != sorted(set(dates)) or dates[-1] != continuation["last"]:
            raise ValueError("Complete nonoverlapping continuation required")
    result = {**account, "last": continuation["last"]}
    for key in ("sessions", "nightlies"):
        result[key] = [*account[key], *continuation[key][1:]]
    for key in ("intents", "fills"):
        result[key] = [*account[key], *continuation[key]]
    return result


# Check published views against the installed configuration on every read.
def read(root, ticker=None):
    base = Path(root)
    folder = base / DIRECTORY
    manifest = json.loads((folder / "manifest.json").read_bytes())
    config = (base / "desk/learned-holding/config.json").read_bytes()
    if manifest["config_sha256"] != hashlib.sha256(config).hexdigest():
        raise ValueError("Simulation does not match the installed strategy")
    value = json.loads(config)
    if value["policy"] != POLICY or value["cost_bps"] != manifest["cost_bps"]:
        raise ValueError("Simulation policy or costs differ from installed strategy")
    name = "summary" if ticker is None else ticker.upper()
    if name not in manifest["files"] or not name.replace("-", "").isalnum():
        raise ValueError("Simulation unavailable for this stock")
    version = manifest["version"]
    if len(version) != 64 or any(char not in "0123456789abcdef" for char in version):
        raise ValueError("Simulation version must be a content digest")
    raw = (folder / version / (name + ".json")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
        raise ValueError("Simulation projection integrity differs")
    result = json.loads(raw)
    if (
        manifest["schema"] != SCHEMA
        or result["schema"] != SCHEMA
        or result["policy"] != POLICY
        or result["counterfactual"] is not True
        or result["real_orders"] is not False
        or result["provenance"]["config_sha256"] != manifest["config_sha256"]
        or result["provenance"]["cost_bps"] != manifest["cost_bps"]
        or result["provenance"]["projection_source_sha256"]
        != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        or (ticker is not None and result["ticker"] != name)
        or (ticker is not None and not isinstance(result.get("splits"), list))
    ):
        raise ValueError("Simulation projection contract differs")
    return result
