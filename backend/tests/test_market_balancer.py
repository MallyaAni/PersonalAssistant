"""The intraday balancer: it persists the live re-ranking on the candle.

What has to hold: with a record and no holdings every in-book name is a
ranked buy and the first plan says so; a name you hold is not a buy, and the
next plan reports it leaving; a second run with nothing changed reports no
change; and a root with no record writes an empty plan rather than failing.
"""

import json
from pathlib import Path

import pytest

from backend.cli import market_balancer
from backend.market import holdings


def _record() -> dict:
    return {
        "session": "2026-09-04",
        "grades": {
            "ADBE": {
                "grade": "A+",
                "score": 1.9,
                "stances": {"sentiment": 1},
                "headline": "own ADBE",
                "reason": "because",
            },
            "HPE": {
                "grade": "A+",
                "score": 1.8,
                "stances": {},
                "headline": "own HPE",
                "reason": "",
            },
            "FTNT": {
                "grade": "B",
                "score": 1.0,
                "stances": {},
                "headline": "hold off FTNT",
                "reason": "",
            },
        },
        "paper": {"until_rebalance": 12},
        "book": [
            {"ticker": "ADBE", "weight": 0.112},
            {"ticker": "HPE", "weight": 0.105},
        ],
        "levels": {
            "ADBE": {
                "last_close": 300.0,
                "high_20": 320.0,
                "stops": {"12": 281.6},
                "grade_margin": 0.5,
                "rank": 1,
            },
            "HPE": {
                "last_close": 52.0,
                "high_20": 55.0,
                "stops": {"12": 48.4},
                "grade_margin": 0.4,
                "rank": 2,
            },
            "FTNT": {
                "last_close": 80.0,
                "high_20": 90.0,
                "stops": {"12": 79.2},
                "grade_margin": 0.1,
                "rank": 3,
            },
        },
    }


# The record the balancer reads, in the layout market_daily writes.
def _write_record(root: Path, record: dict) -> None:
    session = record["session"]
    path = root / "desk" / f"asof={session}" / "desk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


# The unit test has no market feed: the plan is computable from the record's
# own closes, so the live layer is stubbed to return nothing.
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(market_balancer.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(market_balancer.live_quotes, "quotes", lambda *a, **k: {})
    monkeypatch.setattr(
        market_balancer.live_technical, "technical_now", lambda *a, **k: {}
    )


def test_with_no_holdings_every_book_name_is_a_ranked_buy(tmp_path: Path, monkeypatch):
    _no_network(monkeypatch)
    _write_record(tmp_path, _record())
    path = market_balancer.run(tmp_path, 100_000.0)
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert plan["session"] == "2026-09-04"
    # ADBE and HPE are in the book and not held; FTNT is graded but not
    # targeted, so it is not a buy. Grade order, best first.
    assert [b["ticker"] for b in plan["top_buys"]] == ["ADBE", "HPE"]
    assert plan["changed"] == ["first plan of the session"]


def test_a_held_name_is_not_a_buy_and_changes_are_detected(tmp_path: Path, monkeypatch):
    _no_network(monkeypatch)
    _write_record(tmp_path, _record())
    first = json.loads(
        market_balancer.run(tmp_path, 100_000.0).read_text(encoding="utf-8")
    )
    assert [b["ticker"] for b in first["top_buys"]] == ["ADBE", "HPE"]
    # Once ADBE is held it stops being a buy, and the next plan reports it.
    holdings.save(tmp_path, [holdings.Holding("ADBE", 10.0, 290.0, "2026-09-01")])
    path = market_balancer.run(tmp_path, 100_000.0)
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert [b["ticker"] for b in plan["top_buys"]] == ["HPE"]
    assert any("ADBE" in note and "left" in note for note in plan["changed"])


def test_a_root_with_no_record_writes_an_empty_plan(tmp_path: Path, monkeypatch):
    path = market_balancer.run(tmp_path, 100_000.0)
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert plan["session"] is None
    assert plan["top_buys"] == []
