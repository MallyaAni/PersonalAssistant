"""Audit recorded timing permissions, without inventing accounts or broker fills.

Every supplied stock observation remains in the denominator. The archive's
original nightly grades define the eligible-grade subset; this is not an order
replay. Policy versions and hashes remain separate. The current candle and the
latched trigger are evaluated at actual publication time, never bar start time.
"""

from collections import Counter
from statistics import median

from backend.market import entry_timing


# Summarize exposure to old buy permissions once per stock/session and per observation.
def summarize(rows):
    available = [
        row for row in rows if row["status"] in ("available", "conditional_open")
    ]
    triggered = [row for row in available if row["buy_state"] == "triggered"]
    eligible = [
        row
        for row in triggered
        if row["nightly_grade"] in ("A+", "A") and not row["event_paused"]
    ]
    recovered = [row for row in eligible if row["price_above_buy_level_bp"] > 0]
    return {
        "observations": len(rows),
        "statuses": dict(Counter(row["status"] for row in rows)),
        "unique_stock_sessions": len({(row["symbol"], row["session"]) for row in rows}),
        "triggered_buy_observations": len(triggered),
        "eligible_grade_triggered_observations": len(eligible),
        "eligible_grade_recovered_observations": len(recovered),
        "eligible_grade_recovered_stock_sessions": len(
            {(row["symbol"], row["session"]) for row in recovered}
        ),
        "median_recovery_bp": median(
            row["price_above_buy_level_bp"] for row in recovered
        )
        if recovered
        else None,
        "maximum_recovery_bp": max(
            (row["price_above_buy_level_bp"] for row in recovered), default=None
        ),
        "median_trigger_age_minutes": median(
            row["trigger_age_minutes"] for row in recovered
        )
        if recovered
        else None,
    }


# Classify unavailable prefixes without pretending final latch files are full histories.
def unavailable(stamp, bar, valid, latch, price, cutoff, mode):
    if stamp > cutoff:
        return "after_data_as_of"
    if stamp < bar + entry_timing.BAR or valid is None or stamp >= valid:
        return "unavailable_at_publication"
    if latch is None:
        return "missing_latch"
    if price is None:
        return "missing_price"
    trigger = latch.get("buy_trigger") or {}
    seen = entry_timing._instant(trigger.get("seen_at"))
    history_start = entry_timing._instant(latch.get("history_started_at"))
    opened = entry_timing._price(latch.get("open"))
    session = bar.astimezone(entry_timing.NEW_YORK).date()
    past = (
        entry_timing._observed_trigger(latch, opened, "buy", stamp, session)
        if opened
        else None
    )
    if (
        seen
        and seen > stamp
        and past is None
        and (history_start is None or history_start > stamp)
    ):
        return "prefix_indeterminate"
    opening = entry_timing._instant(latch.get("open_seen_at"))
    if opening is not None:
        return "available" if opening <= stamp else "opening_not_observed"
    if mode == "recorded_only":
        return "opening_receipt_unrecorded"
    first = latch.get("first_bar") or {}
    first_bar = entry_timing._instant(first.get("bar"))
    first_seen = entry_timing._instant(first.get("seen_at"))
    if first_seen is not None and first_seen > stamp:
        return "opening_not_observed"
    if first_bar is None or first_bar + entry_timing.BAR > stamp:
        return "opening_evidence_unavailable"
    return "conditional_open"


# Measure one original stock observation only after its evidence gates pass.
def measure(record, symbol, stamp, bar, valid, session, payload, cutoff):
    row = {
        "symbol": symbol,
        "session": session.isoformat(),
        "observed_at": record["as_of"],
        "bar": record["bar"],
        "version": record["version"],
        "policy_sha256": record["policy_sha256"],
        "source_sha256": record["source_sha256"],
        "event_paused": record.get("event_paused") is True,
        "nightly_grade": (record.get("nightly_grades") or {})
        .get(symbol, {})
        .get("grade"),
        "intraday_grade": (record.get("grades") or {})
        .get(symbol, {})
        .get("grade_live"),
        "entry_state": (record.get("entry_states") or {}).get(symbol),
    }
    latch = entry_timing.row_for(
        payload.get("latches", {}).get(session.isoformat()), symbol, session
    )
    price = entry_timing._price((record.get("prices") or {}).get(symbol))
    row["status"] = unavailable(
        stamp, bar, valid, latch, price, cutoff, payload["opening_evidence"]
    )
    if row["status"] not in ("available", "conditional_open"):
        return row
    timed = entry_timing.timing(latch, None, "buy", stamp, session)
    triggered = entry_timing._instant(timed.get("trigger_bar"))
    row.update(
        buy_state=timed["state"],
        price=price,
        buy_level=timed["level"],
        trigger_bar=timed["trigger_bar"],
        trigger_price=timed["trigger_price"],
        trigger_age_minutes=(stamp - triggered - entry_timing.BAR).total_seconds() / 60
        if triggered
        else None,
        price_above_buy_level_bp=(price / timed["level"] - 1) * 10000
        if timed["level"]
        else None,
    )
    return row


# Replay published permissions with metrics separated by original policy.
def audit(payload):
    if (
        payload.get("schema") != "recorded-timing-audit/1"
        or payload.get("price_basis") != "raw"
    ):
        raise ValueError("Explicit recorded timing schema and raw price basis required")
    cutoff = entry_timing._instant(payload.get("data_as_of"))
    if cutoff is None:
        raise ValueError("Aware data_as_of required")
    if payload.get("opening_evidence") not in (
        "recorded_only",
        "assume_known_after_first_bar",
    ):
        raise ValueError("Explicit opening-evidence mode required")
    rows, identities = [], set()
    for record in sorted(
        payload["records"], key=lambda item: (item["as_of"], item["source_sha256"])
    ):
        stamp = entry_timing._instant(record.get("as_of"))
        bar = entry_timing._instant(record.get("bar"))
        valid = entry_timing._instant(record.get("valid_until"))
        if stamp is None or bar is None:
            raise ValueError("Original publication and bar times required")
        session = bar.astimezone(entry_timing.NEW_YORK).date()
        symbols = set().union(
            *(
                record.get(key) or {}
                for key in ("grades", "prices", "nightly_grades", "entry_states")
            )
        )
        for symbol in sorted(symbols):
            identity = (
                record["version"],
                record["policy_sha256"],
                record["bar"],
                symbol,
            )
            if identity in identities:
                raise ValueError("Duplicate recorded observation")
            identities.add(identity)
            rows.append(
                measure(record, symbol, stamp, bar, valid, session, payload, cutoff)
            )
    groups = {}
    for row in rows:
        key = f"{row['version']}:{row['policy_sha256']}"
        groups.setdefault(key, []).append(row)
    return {
        "schema": "recorded-timing-audit-results/1",
        "data_as_of": payload["data_as_of"],
        "opening_evidence": payload["opening_evidence"],
        "scope": (
            "Recorded signal permissions; no account, execution or profitability claim"
        ),
        "coverage": {
            "observations": len(rows),
            "symbols": len({row["symbol"] for row in rows}),
            "sessions": sorted({row["session"] for row in rows}),
            "statuses": dict(Counter(row["status"] for row in rows)),
        },
        "policy_groups": {key: summarize(group) for key, group in groups.items()},
        "rows": rows,
    }
