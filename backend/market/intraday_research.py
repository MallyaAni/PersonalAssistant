"""Persist reproducible research decisions without touching account state."""

import hashlib
import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from backend.agents.trading.desk import intraday_candidate
from backend.agents.trading.desk.desk import book_panel
from backend.market import (
    desk_freshness,
    economics,
    execution_quotes,
    live_technical,
    opportunity,
)
from backend.market.store import MarketStore


# Identify the exact evening decision used by a research allocation.
def record_hash(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


# Reconstruct risk history only through the evening decision, then add observed prices.
def build(
    root: Path, record: dict, snapshot: dict, now: datetime | None = None
) -> dict:
    live_clock = now is None
    now = now or datetime.now(UTC)
    panel, _ = book_panel(MarketStore(root), date.fromisoformat(record["session"]))
    if str(panel.dates[-1]) != record["session"]:
        raise ValueError("Risk history does not match the evening decision")
    quotes = {
        name: SimpleNamespace(**quote)
        for name, quote in (snapshot.get("quotes") or {}).items()
    }
    panel = live_technical.with_live_row(
        panel, quotes, now.astimezone(desk_freshness.NEW_YORK).date()
    )
    result = intraday_candidate.calculate(
        record, snapshot, economics.load(root, now) or {}, panel, now
    )
    # Preserve public state features now; later reconstructions can leak future data.
    result["learning_state"] = {
        "schema": "desk-state/1",
        "observed_at": snapshot.get("as_of"),
        "technical": snapshot.get("technical") or {},
        "value": snapshot.get("value") or {},
        "technical_detail": snapshot.get("technical_detail") or {},
        "nightly_grades": record.get("grades") or {},
        "regime": record.get("regime") or {},
    }
    result["opportunity"] = {
        ticker: opportunity.explain(
            grade,
            result["grades"].get(ticker),
            snapshot["quotes"][ticker],
            result["valid_until"],
            now,
            record["session"],
        )
        for ticker, grade in record["grades"].items()
    }
    if live_clock:
        result["execution_quotes"] = execution_quotes.fetch(
            list(record.get("grades") or {})
        )
        result["as_of"] = datetime.now(UTC).isoformat()
        if desk_freshness.timestamp(result["as_of"]) >= desk_freshness.timestamp(
            result["valid_until"]
        ):
            raise ValueError("Inputs expired during collection")
    result["input_sha256"] = hashlib.sha256(
        json.dumps(
            {
                "record": record,
                "snapshot": snapshot,
                "execution_quotes": result.get("execution_quotes"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    base = Path(__file__).resolve().parents[1]
    result["policy_sha256"] = hashlib.sha256(
        b"".join(
            (base / name).read_bytes()
            for name in (
                "agents/trading/desk/intraday_candidate.py",
                "agents/trading/desk/portfolio_candidate.py",
                "agents/trading/desk/entry.py",
                "agents/trading/desk/risk.py",
                "agents/trading/desk/grading.py",
                "market/sizing.py",
                "market/holdings.py",
                "market/desk_freshness.py",
                "market/opportunity.py",
                "market/intraday_research.py",
            )
        )
    ).hexdigest()
    result["record_sha256"] = record_hash(record)
    return result


# Freeze the first decision per candle; repeated collection cannot rewrite its history.
def publish(root: Path, record: dict, snapshot: dict) -> dict:
    folder = root / "desk" / "intraday-research"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        result = build(root, record, snapshot)
        result["status"] = "available"
        identity = hashlib.sha256(
            f"{result['version']}:{result['session']}:{result['bar']}".encode()
        ).hexdigest()
        archive = folder / f"decision-{identity}.json"
        serialized = json.dumps(result, allow_nan=False, indent=2)
        descriptor, name = tempfile.mkstemp(
            dir=folder, prefix="decision-", suffix=".tmp"
        )
        pending_archive = Path(name)
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(serialized)
            os.link(pending_archive, archive)
        except FileExistsError:
            result = json.loads(archive.read_text())
        finally:
            pending_archive.unlink(missing_ok=True)
    except (ValueError, KeyError, OSError) as exc:
        result = {
            "status": "unavailable",
            "reason": "Research storage unavailable"
            if isinstance(exc, OSError)
            else str(exc),
            "as_of": datetime.now(UTC).isoformat(),
        }
        # Keep the last collected allocation for this decision on the board
        # through the close and feed gaps: a failed or expired run replaces
        # nothing the page can still show, it only marks availability.
        try:
            previous = json.loads((folder / "latest.json").read_text())
            if previous.get("session") == record.get("session") and previous.get(
                "targets"
            ):
                for key in (
                    "session",
                    "bar",
                    "valid_until",
                    "targets",
                    "grades",
                    "record_sha256",
                ):
                    if key in previous:
                        result[key] = previous[key]
        except (ValueError, OSError):
            pass
    descriptor, name = tempfile.mkstemp(dir=folder, prefix="latest-", suffix=".tmp")
    pending = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(result, stream, allow_nan=False, indent=2)
        pending.replace(folder / "latest.json")
    finally:
        pending.unlink(missing_ok=True)
    return result


# Never serve an expired research allocation as current, even while the process is down.
def load(root: Path, session: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    try:
        result = json.loads(
            (root / "desk" / "intraday-research" / "latest.json").read_text()
        )
        deadline = desk_freshness.timestamp(result.get("valid_until"))
        observed = desk_freshness.timestamp(result.get("as_of"))
        if result.get("status") != "available":
            return result
        if (
            result.get("session") != session
            or deadline is None
            or now >= deadline
            or observed is None
            or observed > now
        ):
            return {
                "status": "unavailable",
                "reason": "Research allocation expired or belongs to another decision",
            }
        return result
    except (ValueError, OSError):
        return {
            "status": "unavailable",
            "reason": "No research allocation has been collected",
        }


# Translate candidate weights into the existing holdings and funding preview shape.
def candidate_record(record: dict, decision: dict) -> dict:
    if decision.get("status") != "available":
        raise ValueError(decision.get("reason", "Research allocation unavailable"))
    if decision.get("record_sha256") != record_hash(record):
        raise ValueError("Research allocation belongs to a different evening decision")
    return {
        **record,
        "grades": {
            name: {
                **grade,
                "grade": (decision.get("grades", {}).get(name) or {}).get(
                    "grade_live", grade.get("grade")
                ),
                "score": (decision.get("grades", {}).get(name) or {}).get(
                    "score_live", grade.get("score", 0)
                ),
            }
            for name, grade in record.get("grades", {}).items()
        },
        "book": [
            {"ticker": name, "weight": weight}
            for name, weight in decision["targets"].items()
            if weight > 0
        ],
    }
