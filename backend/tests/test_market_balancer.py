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
                "rejecting_band": False,
            },
            "HPE": {
                "last_close": 52.0,
                "high_20": 55.0,
                "stops": {"12": 48.4},
                "grade_margin": 0.4,
                "rank": 2,
                "rejecting_band": False,
            },
            "FTNT": {
                "last_close": 80.0,
                "high_20": 90.0,
                "stops": {"12": 79.2},
                "grade_margin": 0.1,
                "rank": 3,
                "rejecting_band": False,
            },
        },
        "actions": [
            {"ticker": "ADBE", "last_close": 300.0, "rejecting_band": False},
            {"ticker": "HPE", "last_close": 52.0, "rejecting_band": False},
            {"ticker": "FTNT", "last_close": 80.0, "rejecting_band": False},
        ],
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


# A name can earn a target weight and still be rejecting its upper
# Bollinger band tonight; the balancer must not rank it a buy. This is the
# blocker the nightly plan runs, and it is what keeps a name whose daily
# is rolling over at the top out of the ranked buys.
def test_a_book_name_rejecting_the_upper_band_is_not_a_buy(tmp_path: Path, monkeypatch):
    _no_network(monkeypatch)
    record = _record()
    record["levels"]["HPE"]["rejecting_band"] = True
    record["actions"][1]["rejecting_band"] = True
    _write_record(tmp_path, record)
    plan = json.loads(
        market_balancer.run(tmp_path, 100_000.0).read_text(encoding="utf-8")
    )
    # HPE is in the book, targeted and unheld, but its daily is rejecting
    # its upper Bollinger band: it is not a buy. ADBE's is not, so it is.
    assert [b["ticker"] for b in plan["top_buys"]] == ["ADBE"]


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


# A name with a pending market-on-close sell that is trading up at the open
# is not exited into its own rally: the broker's order is cancelled, the
# state marks the sell deliberately skipped, and a name trading down keeps
# its sell. The rule only acts in the 9-11 EDT weekday window.
def test_a_green_name_is_not_sold_into_its_own_rally(tmp_path: Path, monkeypatch):
    import datetime as dt

    from backend.agents.trading.desk import paper

    class _FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 9, 11, 14, 30, tzinfo=dt.timezone.utc)

    monkeypatch.setattr(market_balancer, "datetime", _FakeDT)
    _write_record(tmp_path, _record())
    state = paper.PaperState()
    state.pending = [
        {
            "client_order_id": "anios-2026-09-10-sell-adbe-7",
            "symbol": "ADBE",
            "side": "sell",
            "qty": 33,
            "session": "2026-09-10",
            "reason": "leaves the book",
        },
        {
            "client_order_id": "anios-2026-09-10-sell-hpe-8",
            "symbol": "HPE",
            "side": "sell",
            "qty": 95,
            "session": "2026-09-10",
            "reason": "leaves the book",
        },
    ]
    paper.save_state(tmp_path, state)

    cancelled: list[str] = []
    fake_client = type(
        "C",
        (),
        {
            "cancel_orders": lambda self, ids: (
                cancelled.extend(ids),
                {i: "cancelled" for i in ids},
            )[1]
        },
    )()
    from backend.market import alpaca_trading

    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: fake_client)

    record = json.loads(
        (tmp_path / "desk" / "asof=2026-09-04" / "desk.json").read_text(
            encoding="utf-8"
        )
    )
    # ADBE opens up (305 > 300 close), HPE opens down (51 < 52 close).
    quotes = {"ADBE": {"open": 305.0}, "HPE": {"open": 51.0}}
    market_balancer._green_day_skip(
        tmp_path, record, quotes, tmp_path / "intraday.log"
    )

    assert cancelled == ["anios-2026-09-10-sell-adbe-7"]
    back = paper.load_state(tmp_path)
    assert [p["client_order_id"] for p in back.pending] == [
        "anios-2026-09-10-sell-hpe-8"
    ]
    entry = next(
        e
        for e in back.journal
        if e["client_order_id"] == "anios-2026-09-10-sell-adbe-7"
    )
    assert entry["status"] == paper.SKIPPED
    assert "green-day skipped" in (tmp_path / "intraday.log").read_text(
        encoding="utf-8"
    )


# Outside the opening hour the rule must not cancel anything: a quote
# arriving in the afternoon is a different question than the open, and the
# desk should not act on it.
def test_the_green_day_rule_is_quiet_outside_the_window(
    tmp_path: Path, monkeypatch
):
    import datetime as dt

    from backend.agents.trading.desk import paper

    class _FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 9, 11, 20, 0, tzinfo=dt.timezone.utc)

    monkeypatch.setattr(market_balancer, "datetime", _FakeDT)
    _write_record(tmp_path, _record())
    state = paper.PaperState()
    state.pending = [
        {
            "client_order_id": "anios-2026-09-10-sell-adbe-7",
            "symbol": "ADBE",
            "side": "sell",
            "qty": 33,
            "session": "2026-09-10",
            "reason": "leaves the book",
        }
    ]
    paper.save_state(tmp_path, state)

    cancelled: list[str] = []
    fake_client = type(
        "C",
        (),
        {
            "cancel_orders": lambda self, ids: (
                cancelled.extend(ids),
                {i: "cancelled" for i in ids},
            )[1]
        },
    )()
    from backend.market import alpaca_trading

    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: fake_client)

    record = json.loads(
        (tmp_path / "desk" / "asof=2026-09-04" / "desk.json").read_text(
            encoding="utf-8"
        )
    )
    market_balancer._green_day_skip(
        tmp_path, record, {"ADBE": {"open": 305.0}}, tmp_path / "intraday.log"
    )

    assert cancelled == []
    back = paper.load_state(tmp_path)
    assert [p["client_order_id"] for p in back.pending] == [
        "anios-2026-09-10-sell-adbe-7"
    ]


# A green name whose cancel the broker has not confirmed - the order is
# still working and can still fill - must not be journaled as a deliberate
# zero-fill hold: the state leaves it pending so the next reconcile records
# what the broker actually did.
def test_an_unconfirmed_cancel_is_not_journaled_as_a_hold(
    tmp_path: Path, monkeypatch
):
    import datetime as dt

    from backend.agents.trading.desk import paper

    class _FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 9, 11, 14, 30, tzinfo=dt.timezone.utc)

    monkeypatch.setattr(market_balancer, "datetime", _FakeDT)
    _write_record(tmp_path, _record())
    state = paper.PaperState()
    state.pending = [
        {
            "client_order_id": "anios-2026-09-10-sell-adbe-7",
            "symbol": "ADBE",
            "side": "sell",
            "qty": 33,
            "session": "2026-09-10",
            "reason": "leaves the book",
        }
    ]
    paper.save_state(tmp_path, state)

    fake_client = type(
        "C",
        (),
        {
            "cancel_orders": lambda self, ids: {i: "unconfirmed" for i in ids},
        },
    )()
    from backend.market import alpaca_trading

    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: fake_client)

    record = json.loads(
        (tmp_path / "desk" / "asof=2026-09-04" / "desk.json").read_text(
            encoding="utf-8"
        )
    )
    market_balancer._green_day_skip(
        tmp_path, record, {"ADBE": {"open": 305.0}}, tmp_path / "intraday.log"
    )

    back = paper.load_state(tmp_path)
    # Still pending: the broker has not confirmed the cancel, so nothing is
    # concluded and no zero-fill hold is journaled.
    assert [p["client_order_id"] for p in back.pending] == [
        "anios-2026-09-10-sell-adbe-7"
    ]
    assert not any(
        e.get("client_order_id") == "anios-2026-09-10-sell-adbe-7"
        and e.get("status") == paper.SKIPPED
        for e in back.journal
    )
