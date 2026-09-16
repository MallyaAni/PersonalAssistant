"""Four order-lifecycle defects from the 2026-09-16 review, each pinned.

What has to hold: an event order the broker never acknowledged settles as
missing instead of freezing every later plan, while an acknowledged one
that the broker no longer lists keeps its intent; every pending desk
order is withdrawn before a plan is sent, this session's included; the
balancer's green-day hold is written on the row the saved state holds,
not a stale copy; and the broker's order listing follows pages until it
is complete.
"""

import json
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.cli import market_balancer, market_daily
from backend.market import alpaca_trading


class _Broker:
    def __init__(self, orders):
        self.orders = orders

    def orders_since(self, after):
        return self.orders


def _event_row(order_id, acknowledged: bool) -> dict:
    execution = {"decision_at": "2026-09-14T16:48:14+00:00", "reference_price": 100.0}
    if acknowledged:
        execution["created_at"] = "2026-09-14T16:48:16Z"
    return {
        "client_order_id": order_id,
        "symbol": "NVDA",
        "side": "buy",
        "qty": 5,
        "session": "2026-09-14",
        "event_id": "fomc-3-session-weakness/2:2026-09-16",
        "execution": execution,
    }


# A never-acknowledged event order is known never to have traded.
def test_a_never_sent_event_order_settles_as_missing(tmp_path, capsys):
    state = paper.PaperState()
    state.pending = [_event_row("anios-2026-09-14-buy-nvda-1", acknowledged=False)]
    updated, settled = market_daily._reconcile(_Broker([]), state, tmp_path, False)
    assert [s.status for s in settled] == ["missing"]
    assert updated.pending == []
    assert "outcome unknown" not in capsys.readouterr().out


# An acknowledged event order the broker no longer lists keeps its intent.
def test_an_acknowledged_event_order_missing_at_the_broker_keeps_its_intent(
    tmp_path, capsys
):
    state = paper.PaperState()
    state.pending = [_event_row("anios-2026-09-14-buy-nvda-1", acknowledged=True)]
    updated, settled = market_daily._reconcile(_Broker([]), state, tmp_path, False)
    assert settled == []
    assert len(updated.pending) == 1
    assert "outcome unknown" in capsys.readouterr().out


# Every pending desk order is withdrawn before a plan is sent, including a
# row planned this session by a forced rerun.
def test_every_pending_order_is_withdrawn_before_replanning():
    state = paper.PaperState()
    state.pending = [
        {"client_order_id": "anios-2026-09-15-buy-nvda-0", "session": "2026-09-15"},
        {"client_order_id": "anios-2026-09-16-buy-nvda-1", "session": "2026-09-16"},
    ]
    assert market_daily._ids_to_withdraw(state) == [
        "anios-2026-09-15-buy-nvda-0",
        "anios-2026-09-16-buy-nvda-1",
    ]


# The second green-day hold is written on the row the saved state holds:
# with the first cancel confirmed and the second unconfirmed, the saved
# pending row carries the requested hold.
def test_a_second_green_day_hold_survives_the_first_skip(tmp_path: Path, monkeypatch):
    import datetime as dt

    class _FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 9, 11, 14, 30, tzinfo=dt.UTC)

    monkeypatch.setattr(market_balancer, "datetime", _FakeDT)
    record = {
        "session": "2026-09-10",
        "actions": [
            {"ticker": "ADBE", "last_close": 300.0},
            {"ticker": "HPE", "last_close": 52.0},
        ],
    }
    state = paper.PaperState()
    state.pending = [
        {
            "client_order_id": "anios-2026-09-10-sell-adbe-7",
            "symbol": "ADBE",
            "side": "sell",
            "qty": 33,
            "session": "2026-09-10",
        },
        {
            "client_order_id": "anios-2026-09-10-sell-hpe-8",
            "symbol": "HPE",
            "side": "sell",
            "qty": 95,
            "session": "2026-09-10",
        },
    ]
    paper.save_state(tmp_path, state)
    outcomes = {
        "anios-2026-09-10-sell-adbe-7": "cancelled",
        "anios-2026-09-10-sell-hpe-8": "unconfirmed",
    }
    fake_client = type(
        "C", (), {"cancel_orders": lambda self, ids: {i: outcomes[i] for i in ids}}
    )()
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: fake_client)
    quotes = {
        "ADBE": {"open": 305.0, "bar": "2026-09-11T14:15:00+00:00"},
        "HPE": {"open": 53.0, "bar": "2026-09-11T14:15:00+00:00"},
    }
    market_balancer._green_day_skip(tmp_path, record, quotes, tmp_path / "intraday.log")
    back = paper.load_state(tmp_path)
    hpe = next(p for p in back.pending if p["symbol"] == "HPE")
    assert hpe.get("hold_requested") is True
    assert all(p["symbol"] != "ADBE" for p in back.pending)


# The order listing follows pages by the last submission time until a
# short page arrives, and never counts an order twice.
def test_orders_since_follows_pages_until_complete():
    pages = [
        [
            {"id": f"o{i}", "submitted_at": f"2026-09-1{i % 5}T10:00:{i:02d}Z"}
            for i in range(3)
        ],
        [
            {"id": "o2", "submitted_at": "2026-09-12T10:00:02Z"},
            {"id": "o3", "submitted_at": "2026-09-13T10:00:03Z"},
            {"id": "o4", "submitted_at": "2026-09-14T10:00:04Z"},
        ],
        [{"id": "o5", "submitted_at": "2026-09-15T10:00:05Z"}],
    ]
    calls = []

    def call(method, path, body=None):
        calls.append(path)
        return pages[len(calls) - 1] if len(calls) <= len(pages) else []

    client = alpaca_trading.AlpacaTradingClient.__new__(
        alpaca_trading.AlpacaTradingClient
    )
    client._call = call
    out = client.orders_since("2026-09-10T00:00:00Z", limit=3)
    assert [o["id"] for o in out] == ["o0", "o1", "o2", "o3", "o4", "o5"]
    assert len(calls) == 3
    assert "after=2026-09-12T10:00:02Z" in calls[1]
    assert json.dumps(out)  # plain data
