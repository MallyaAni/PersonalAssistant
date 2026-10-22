"""Current chart judgments shared by every browser, separate from all accounts."""

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.agents.trading import current_setup
from backend.market import (
    alpaca,
    desk_freshness,
    deskrecord,
    grade_led_policy,
    holdings,
    live_chart,
    live_technical,
    session_price_snapshot,
)
from backend.market import calendar as calendar

VERSION = "current-opportunities/1"
BATCH_SIZE = 12


# Identify the exact grade and candle evidence without advancing any observation clock.
def identity(record, snapshot):
    evidence = {
        "grades": record.get("grades"),
        "session": record.get("session"),
        "snapshot": snapshot,
        "prompt": current_setup.SYSTEM,
        "version": VERSION,
    }
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


# Read bounded display inputs; corrupt evidence stays unavailable.
def load(path):
    try:
        if path.stat().st_size > 2_000_000:
            return {}
        raw = json.loads(path.read_text())
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


# Keep only finite positive raw prices as selectable model references.
def level(out, key, label, value):
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    ):
        out[key] = {"label": label, "price": float(value)}


# Assemble dated technical and raw IEX facts without changing numerical models.
def facts_for(record, snapshot, bars_by_symbol, now):
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    grades = holdings.live_grades(record, technical, value)
    deadlines = desk_freshness.grade_expiries(snapshot, grades)
    status = calendar.exchange_status(now)
    facts = []
    for symbol, grade in sorted(grades.items()):
        quote = snapshot["quotes"][symbol]
        observed = desk_freshness.timestamp(quote.get("bar"))
        try:
            bars = live_chart.qualify(bars_by_symbol.get(symbol, []), now, status)
        except ValueError:
            continue
        # No partial/future candle may influence a completed-candle judgment.
        bars = [
            bar
            for bar in bars
            if bar.start <= observed and bar.start + timedelta(minutes=15) <= now
        ]
        if not bars or bars[-1].start != observed:
            continue
        detail = (snapshot.get("technical_detail") or {}).get(symbol)
        if not detail:
            continue
        levels = {}
        total = sum(bar.volume for bar in bars)
        level(
            levels,
            "vwap",
            "session VWAP (IEX closes weighted by IEX volume)",
            sum(bar.close * bar.volume for bar in bars) / total if total > 0 else None,
        )
        level(
            levels, "session_low", "observed session low", min(bar.low for bar in bars)
        )
        level(
            levels,
            "session_high",
            "observed session high",
            max(bar.high for bar in bars),
        )
        short = detail.get("short") or {}
        # Price-fraction distances preserve adjustment scale; absolute technical
        # levels are adjusted and cannot be mixed directly with raw IEX prices.
        for name, sign in (("support", -1), ("resistance", 1)):
            distance = short.get(name + "_distance")
            if isinstance(distance, (int, float)) and math.isfinite(distance):
                level(
                    levels,
                    name,
                    "daily " + name + " reference",
                    quote["last"] * (1 + sign * distance),
                )
        fact = {
            "ticker": symbol,
            "grade": grade["grade_live"],
            "entry_permitted": grade["grade_live"]
            in grade_led_policy.admitted_for(
                (record.get("targets") or {}).get("policy")
            ),
            "decision_session": record["session"],
            "bar": observed.isoformat(),
            "valid_until": deadlines[symbol],
            "price": quote["last"],
            "levels": levels,
            "technical": live_technical.lines(detail),
            "session_open": bars[0].open,
            "candles": [
                {
                    "at": bar.start.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars
            ],
            "volume_scope": (
                "Current-session IEX only; no consolidated relative-volume comparison"
            ),
            "other_votes_as_of": record["session"],
        }
        facts.append(fact)
    return facts


# Lock each candle's collection and publish judgments progressively.
def collect(root, writer, now=None, fetch=None):
    root = Path(root)
    if not session_price_snapshot.supported():
        return {"status": "unavailable"}
    folder = root / "desk/current-opportunities"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "collect.lock").open("a") as lock:
        import fcntl

        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "busy"}
        observed_now = now or datetime.now(UTC)
        record, _ = deskrecord.latest_pair(root)
        snapshot = load(root / "desk/live.json")
        if not record:
            return {"status": "unavailable"}
        technical, _ = desk_freshness.grade_inputs(snapshot, record, observed_now)
        if not technical:
            return {"status": "unavailable"}
        source_id = identity(record, snapshot)
        prior = load(folder / "latest.json")
        same = prior.get("source_id") == source_id
        checked = desk_freshness.timestamp(prior.get("checked_at"))
        if same and (
            len(prior.get("rows", {})) == len(record.get("grades", {}))
            or prior.get("attempts", 0) >= 3
            or checked
            and (observed_now - checked).total_seconds() < 60
        ):
            return {"status": "unchanged"}
        status = calendar.exchange_status(observed_now)
        day = datetime.fromisoformat(status["opens_at"]).date()
        # One bounded free IEX universe fetch, never a recent-end SIP query.
        bars = (fetch or alpaca.fetch_bars_multi)(
            sorted(technical), day, day, feed="iex", adjustment="raw"
        )
        facts = facts_for(record, snapshot, bars, observed_now)
        if same:
            original = load(folder / "inputs/latest.json")
            original_facts = {
                fact["ticker"]: fact
                for fact in original.get("facts", [])
                if isinstance(fact, dict)
                and fact.get("ticker") in prior.get("rows", {})
            }
            # Successful judgments retain the raw prefix that produced them.
            facts = [original_facts.get(fact["ticker"], fact) for fact in facts]
            fresh_names = {fact["ticker"] for fact in facts}
            facts.extend(
                fact for name, fact in original_facts.items() if name not in fresh_names
            )
        covered = {fact["ticker"] for fact in facts}
        unavailable = {
            symbol: "Chart judgment unavailable: incomplete current IEX candles."
            for symbol in record.get("grades", {})
            if symbol not in covered
        }
        inputs = folder / "inputs"
        inputs.mkdir(exist_ok=True)
        # Preserve the precise raw prefix behind the latest display judgment;
        # this does not rewrite an actual or research account history.
        session_price_snapshot._publish(
            inputs, {"source_id": source_id, "facts": facts}
        )
        envelope = {
            "version": VERSION,
            "source_id": source_id,
            "decision_session": record["session"],
            "snapshot_at": snapshot.get("as_of"),
            "generated_at": None,
            "checked_at": observed_now.isoformat(),
            "attempts": prior.get("attempts", 0) + 1 if same else 1,
            "status": "building",
            "rows": prior.get("rows", {}) if same else {},
            "unavailable": unavailable,
            "universe": sorted(record.get("grades") or {}),
        }
        session_price_snapshot._publish(folder, envelope)
        for offset in range(0, len(facts), BATCH_SIZE):
            clock = now or datetime.now(UTC)
            batch = [
                fact
                for fact in facts[offset : offset + BATCH_SIZE]
                if clock < desk_freshness.timestamp(fact["valid_until"])
                and fact["ticker"] not in envelope["rows"]
            ]
            judged = current_setup.assess(batch, writer)
            by_name = {fact["ticker"]: fact for fact in batch}
            for judgment in judged:
                fact = by_name[judgment["ticker"]]
                envelope["rows"][fact["ticker"]] = {
                    **judgment,
                    "status": "model_assessment",
                    "price": fact["price"],
                    "bar": fact["bar"],
                    "valid_until": fact["valid_until"],
                    "levels": fact["levels"],
                    "model": writer.model,
                    "generated_at": (now or datetime.now(UTC)).isoformat(),
                    "prompt_version": current_setup.VERSION,
                }
            envelope["generated_at"] = (now or datetime.now(UTC)).isoformat()
            session_price_snapshot._publish(folder, envelope)
        envelope["status"] = (
            "complete"
            if len(envelope["rows"]) + len(unavailable) == len(envelope["universe"])
            else "partial"
        )
        session_price_snapshot._publish(folder, envelope)
        return {
            "status": "collected",
            "rows": len(envelope["rows"]),
            "unavailable": len(unavailable),
        }


# Reject corrupt prices and policy violations before displaying a stored judgment.
def valid_row(row, grade, policy=None):
    try:
        if not isinstance(row["levels"], dict) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("price"), (float, int))
            or not math.isfinite(item["price"])
            or item["price"] <= 0
            or not isinstance(item.get("label"), str)
            for item in row["levels"].values()
        ):
            return False
        current_setup.validate_row(
            row,
            {
                "levels": row["levels"],
                "candles": [row["bar"]],
                "entry_permitted": (grade or {}).get("grade_live")
                in grade_led_policy.admitted_for(policy),
            },
        )
        return True
    except (KeyError, TypeError, ValueError):
        return False


# Load only factual receipts belonging to the stored display assessment.
def stored_facts(root, stored):
    inputs = load(Path(root) / "desk/current-opportunities/inputs/latest.json")
    if inputs.get("source_id") != stored.get("source_id") or not isinstance(
        inputs.get("facts"), list
    ):
        return None
    return {
        fact.get("ticker"): fact for fact in inputs["facts"] if isinstance(fact, dict)
    }


# Keep missing-provider explanations scoped to currently graded names.
def missing_reasons(stored, grades):
    unavailable = stored.get("unavailable")
    if not isinstance(unavailable, dict):
        return {}
    return {name: reason for name, reason in unavailable.items() if name in grades}


# Serve judgments only for their exact snapshot and original evidence deadline.
def read(root, record, snapshot, now):
    stored = load(Path(root) / "desk/current-opportunities/latest.json")
    if stored.get("version") != VERSION or stored.get("source_id") != identity(
        record, snapshot
    ):
        return {"status": "pending", "rows": {}}
    facts = stored_facts(root, stored)
    if facts is None:
        return {"status": "unavailable", "rows": {}}
    rows = {}
    candidates = stored.get("rows")
    if not isinstance(candidates, dict):
        return {"status": "unavailable", "rows": {}}
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    grades = holdings.live_grades(record, technical, value)
    if not grades:
        return {"status": "stale", "rows": {}, "unavailable": {}}
    for symbol, row in candidates.items():
        if not isinstance(row, dict) or row.get("ticker") != symbol:
            continue
        fact = facts.get(symbol)
        if not fact or any(
            row.get(key) != fact.get(key)
            for key in ("price", "levels", "bar", "valid_until")
        ):
            continue
        if not valid_row(
            row, grades.get(symbol), (record.get("targets") or {}).get("policy")
        ):
            continue
        until = desk_freshness.timestamp(row.get("valid_until"))
        generated = desk_freshness.timestamp(row.get("generated_at"))
        bar = desk_freshness.timestamp(row.get("bar"))
        quote = (snapshot.get("quotes") or {}).get(symbol) or {}
        if (
            symbol in (record.get("grades") or {})
            and until
            and generated
            and bar
            and bar + timedelta(minutes=15) <= generated <= now < until
            and bar == desk_freshness.timestamp(quote.get("bar"))
        ):
            rows[symbol] = row
    return {
        "status": stored.get("status", "unavailable"),
        "rows": rows,
        "unavailable": missing_reasons(stored, grades),
        "generated_at": stored.get("generated_at"),
        "snapshot_at": stored.get("snapshot_at"),
    }
