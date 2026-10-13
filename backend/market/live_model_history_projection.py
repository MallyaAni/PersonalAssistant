"""Project verified current-model account decisions without rewriting old research."""

import gzip
import json
from hashlib import sha256
from pathlib import Path

from backend.market.grade_led_policy import POLICY
from backend.market.strategy_simulation import instant, number

SCHEMA = "live-model-historical-sizing/1"
DIRECTORY = "desk/live-model-history"


# Authenticate an immutable session archive before using any account amount.
def session(root, record):
    name = record["session"]
    if len(name) != 10 or instant(name + "T16:01:00-04:00").date().isoformat() != name:
        raise ValueError("Explicit archived session required")
    raw = (Path(root) / "sessions" / (name + ".json.gz")).read_bytes()
    if sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError("Historical account session integrity differs")
    result = json.loads(gzip.decompress(raw))
    if result["session"] != name:
        raise ValueError("Historical account session identity differs")
    return result


# Require each nonzero chart decision to match its durable whole-share order.
def validate_intent(intent, quantity, date):
    if quantity and (
        intent is None or intent["qty"] != quantity or intent["session"] != date
    ):
        raise ValueError("Historical order quantity differs from durable intent")


# Preserve funded order quantities, zero signals and raw model targets separately.
def nightly(value, stocks, decisions):
    night = value["nightly"]
    if night["status"] != "planned":
        for stock in stocks.values():
            stock["targets"].append(
                {
                    "date": night["session"],
                    "weight": None,
                    "status": night["status"],
                    "reason": night.get("reason"),
                }
            )
        return
    entry = night["entry"]
    pending = {row["symbol"]: row for row in value["new_intents"]}
    held = value["broker"]["holdings"]
    for row in entry["actions"]:
        name = row["ticker"]
        if name not in stocks:
            continue
        if row["policy"] != POLICY or row["is_fill"] is not False:
            raise ValueError("Grade-led historical decision policy differs")
        qty = number(row["order_quantity"])
        if type(qty) is not int:
            raise ValueError("Whole-share historical quantity required")
        target = {
            "date": night["session"],
            "weight": number(row["target_weight"]),
            "model_weight": row.get("model_target_weight"),
            "holding": held.get(name, 0),
            "grade": row.get("grade"),
            "status": row["action_status"],
        }
        stocks[name]["targets"].append(target)
        signal = row.get("grade_signal")
        if qty == 0 and signal not in ("buy", "sell"):
            continue
        action = row["action"].upper() if qty else signal.upper()
        if action not in ("BUY", "ADD", "SELL", "TRIM"):
            raise ValueError("Historical order has no supported direction")
        intent = pending.get(name)
        validate_intent(intent, qty, night["session"])
        identity = (
            intent["client_order_id"] if intent else f"signal:{name}:{night['session']}"
        )
        decision = {
            "id": identity,
            "ticker": name,
            "date": night["session"],
            "at": instant(night["at"]).isoformat(),
            "action": action,
            "qty": qty,
            "grade": row.get("grade"),
            "previous_grade": row.get("previous_grade"),
            "grade_signal": signal,
            "target_weight": target["weight"],
            "model_target_weight": target["model_weight"],
            "holding": target["holding"],
            "reason": row.get("signal_reason") or row.get("why"),
            "status": row.get("signal_status"),
            "execute_on": intent.get("execute_on") if intent else None,
            "timing": intent.get("execution_timing") if intent else None,
            "executed_qty": 0,
            "state": "not_executed" if qty else "no_order",
        }
        if identity in decisions:
            raise ValueError("Duplicate historical decision identity")
        decisions[identity] = decision
        stocks[name]["decisions"].append(decision)


# Match simulated execution receipts to their original decisions and raw shares.
def fills(rows, stocks, decisions):
    for row in rows:
        if row["filled_qty"] == 0:
            continue
        identity = row["client_order_id"]
        decision = decisions.get(identity)
        if decision is None or decision["ticker"] != row["symbol"]:
            raise ValueError("Historical simulated fill has no original decision")
        at = instant(row["at"])
        qty, price = (
            number(row["filled_qty"], positive=True),
            number(row["price"], positive=True),
        )
        if at <= instant(decision["at"]) or row["side"] != (
            "buy" if decision["action"] in ("BUY", "ADD") else "sell"
        ):
            raise ValueError("Historical execution timing or side differs")
        decision["executed_qty"] += qty
        if decision["executed_qty"] > decision["qty"]:
            raise ValueError("Historical fill exceeds original funded shares")
        decision["state"] = (
            "executed" if decision["executed_qty"] == decision["qty"] else "partial"
        )
        stocks[row["symbol"]]["trades"].append(
            {
                "id": identity,
                "date": at.date().isoformat(),
                "at": at.isoformat(),
                "action": decision["action"],
                "qty": qty,
                "price": price,
                "fee": number(row["fee"]),
                "decision_date": decision["date"],
                "decision_at": decision["at"],
            }
        )


# Build new per-stock history only after an independent whole-account verification.
def project(root, verification):
    root = Path(root)
    raw = (root / "completion.json").read_bytes()
    account = json.loads(raw)
    if (
        verification["status"] != "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT"
        or verification["account_sha256"] != sha256(raw).hexdigest()
        or account["policy"] != POLICY
        or account["real_orders"] is not False
        or account["basis"] != "fixed_current_models_applied_retrospectively"
        or account["base_models_fitted"] != 0
    ):
        raise ValueError("Independent current-model historical account proof required")
    capture = account["grade_overlay"]["histories"]
    provenance = {
        key: account[key]
        for key in (
            "cost_bps",
            "holding_config_sha256",
            "timing_config_sha256",
            "model_receipt_sha256",
            "risk_receipt_sha256",
            "timing_model_receipt_sha256",
            "timing_residual_receipt_sha256",
            "original_holding_publication",
            "original_holding_fit_date",
            "basis",
            "source_sha256",
            "capture_sha256",
        )
    }
    provenance.update(
        account_sha256=sha256(raw).hexdigest(),
        projection_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        verification=verification,
    )
    stocks = {
        name: {
            "schema": SCHEMA,
            "policy": POLICY,
            "ticker": name,
            "counterfactual": True,
            "real_orders": False,
            "start": account["first"],
            "through": account["through"],
            "starting_cash": 100000,
            "starting_holdings": {},
            "provenance": provenance,
            "decisions": [],
            "trades": [],
            "targets": [],
        }
        for name in sorted(capture)
    }
    initial = json.loads(gzip.decompress((root / "initial.json.gz").read_bytes()))
    decisions = {}
    nightly({**initial, "new_intents": initial["intents"]}, stocks, decisions)
    for record in account["sessions"]:
        value = session(root, record)
        fills(value["fills"], stocks, decisions)
        nightly(value, stocks, decisions)
    if (
        sum(len(stock["trades"]) for stock in stocks.values())
        != verification["filled_receipts"]
    ):
        raise ValueError("Historical projection omitted a verified execution")
    return stocks
