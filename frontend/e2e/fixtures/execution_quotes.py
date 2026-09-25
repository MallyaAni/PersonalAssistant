"""Produce synthetic browser evidence through the real execution/decision functions.

Run from the repository root with the backend test dependencies available:
``PYTHONPATH=. python frontend/e2e/fixtures/execution_quotes.py --check``.
Without --check, print the regenerated JSON for review. No provider, account,
database, runtime, fitting or persistence boundary is used.
"""

import hashlib
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.market import decision_view, execution_quotes
from backend.tests.test_decision_view import FIRING, setup


# Refuse an external boundary even if a future producer implementation starts using it.
def forbidden(*args, **kwargs):
    raise AssertionError("External boundary reached by synthetic execution fixture")


# Keep complete decision rows with display evidence for one synthetic stock.
def produce():
    cases = {}
    with (
        patch.object(socket.socket, "connect", forbidden),
        patch.object(socket, "create_connection", forbidden),
        patch.object(execution_quotes, "fetch", forbidden),
        patch.object(execution_quotes.alpaca, "credentials", forbidden),
        patch.object(execution_quotes.alpaca_trading, "client_from_env", forbidden),
    ):
        for name in (
            "tight_sip",
            "wide_sip",
            "tight_iex",
            "wide_iex",
            "closed_clock",
            "unknown_clock",
            "stale_quote",
            "absent_quote",
        ):
            record, snapshot, quoted, now = setup()
            record["written"] = "2026-09-11T21:05:00Z"
            if name.endswith("iex"):
                quoted["feed"] = "iex"
            if name.startswith("wide"):
                quoted["quotes"]["S11"].update(bp=95, ap=105)
            if name.endswith("clock"):
                now = datetime(2026, 9, 14, 1, 1, tzinfo=UTC)
                quoted["market_open"] = False if name == "closed_clock" else None
                quoted["feed"] = "iex"
                for raw in quoted["quotes"].values():
                    raw["t"] = now.isoformat()
                for raw in snapshot["quotes"].values():
                    raw["bar"] = "2026-09-11T19:45:00Z"
                snapshot["as_of"] = "2026-09-11T20:01:00Z"
            if name == "stale_quote":
                quoted["quotes"]["S11"]["t"] = (now - timedelta(seconds=31)).isoformat()
            if name == "absent_quote":
                quoted["quotes"].pop("S11")
            row = decision_view.build(
                record, [], 100000, snapshot, quoted, now, entries=FIRING, cash=100000
            )["rows"]["S11"]
            ready = name in ("tight_sip", "tight_iex", "wide_iex")
            assert row["strategy_action"] == "Buy"
            assert row["action"] == ("Buy" if ready else "Hold")
            assert row["executable"] is ready
            assert row["quote"]["eligible"] is ready
            assert row["quote"].get("spread_verified") is {
                "tight_sip": True,
                "tight_iex": True,
                "wide_iex": False,
            }.get(name)
            if name.endswith("clock"):
                assert row["blocker"] == "market closed or clock unavailable"
                assert row["quote"]["reason"] == "Market closed or clock unavailable"
            cases[name] = {
                "now": now.isoformat(),
                "regular_clock": quoted["market_open"],
                "snapshot": {
                    **snapshot,
                    "quotes": {"S11": snapshot["quotes"]["S11"]},
                    "technical": {"S11": snapshot["technical"]["S11"]},
                    "value": {"S11": snapshot["value"]["S11"]},
                },
                "row": row,
            }
    root = Path(__file__).resolve().parents[3]
    sources = (
        "backend/market/execution_quotes.py",
        "backend/market/decision_view.py",
        "backend/tests/test_decision_view.py",
        "backend/tests/test_intraday_candidate.py",
    )
    return {
        "schema": "synthetic-execution-browser-evidence/1",
        "producer": "frontend/e2e/fixtures/execution_quotes.py",
        "source_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in sources
        },
        "record": {**record, "grades": {"S11": record["grades"]["S11"]}},
        "cases": cases,
    }


# Compare saved evidence to fresh real-function outputs, or print its regeneration.
def main():
    result = produce()
    if sys.argv[1:] == ["--check"]:
        saved = json.loads(Path(__file__).with_suffix(".json").read_text())
        assert saved == result, "Execution fixture differs from current producers"
        print(f"Verified {len(result['cases'])} real-produced execution browser cases")
    elif sys.argv[1:]:
        raise SystemExit("Usage: execution_quotes.py [--check]")
    else:
        print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
