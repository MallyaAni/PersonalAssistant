"""Read published strategy percentages without live accounts or model execution."""

from datetime import datetime
from zipfile import BadZipFile

from backend.market import grade_led_policy, live_model_decision

VERSION = "published-model-allocation/1"


# Keep missing model evidence distinct from account balances and grades.
def unavailable(record, now, reason, status="unavailable"):
    return {
        "version": VERSION, "status": status, "reason": reason,
        "policy": grade_led_policy.POLICY,
        "session": record.get("session"), "observed_at": record.get("written"),
        "as_of": now.isoformat(), "valid_until": None, "rows": {},
    }


# Authenticate original allocation independently of later orders and fills.
def read(root, record, now):
    record = record if isinstance(record, dict) else {}
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Aware allocation observation required")
    try:
        if not record:
            return unavailable(record, now, "Awaiting a published model allocation")
        until = live_model_decision._valid_until(record["session"])
        if now >= until:
            return unavailable(
                record, now,
                "Published model allocation expired; awaiting the next strategy plan",
                "stale",
            )
        written = datetime.fromisoformat(record["written"])
        if written.utcoffset() is None or written > now:
            raise ValueError("Original allocation publication clock required")
        digest, config, report = live_model_decision._authenticate(root, record, now)
        receipt, _, _ = live_model_decision._validate(record, config, report)
        weights = record["targets"]["weights"]
        if set(weights) != set(record["grades"]):
            raise ValueError("Complete published strategy universe required")
        values = {
            name: live_model_decision._number(value) for name, value in weights.items()
        }
        if (
            any(value > 1 for value in values.values())
            or sum(values.values()) > 1 + 1e-10
        ):
            raise ValueError("Published portfolio percentages exceed capital")
        return {
            "version": VERSION, "status": "available", "reason": None,
            "policy": config["policy"], "session": record["session"],
            "observed_at": record["written"], "as_of": now.isoformat(),
            "valid_until": until.isoformat(), "record_sha256": digest,
            "receipt_sha256": live_model_decision._digest(receipt),
            "basis": "original_published_strategy_allocation_not_trade_quantity",
            "rows": {name: {"target_weight": value} for name, value in values.items()},
        }
    except (
        OSError, ValueError, KeyError, TypeError, AttributeError,
        OverflowError, IndexError, EOFError, BadZipFile,
    ):
        return unavailable(
            record, now, "Published model allocation could not be verified"
        )
