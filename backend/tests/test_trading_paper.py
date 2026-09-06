"""The paper book's rules and the Alpaca trading client."""

import json

import pytest

from backend.agents.trading.desk import paper
from backend.market import alpaca_trading


# The first session rebalances to the targets in whole shares, sells first,
# skips moves under half a percent of equity, and never repeats a session.
def test_first_plan_rebalances_and_is_idempotent():
    state = paper.PaperState()
    orders, new, what = paper.plan(
        "2026-09-04",
        state,
        equity=100_000.0,
        held={"MU": 10.0},
        prices={"SNDK": 200.0, "PANW": 180.0, "MU": 150.0, "TINY": 10.0},
        targets={"SNDK": 0.076, "PANW": 0.063, "TINY": 0.001},
        grades={"SNDK": "A+", "PANW": "A+", "MU": "C", "TINY": "A"},
    )
    assert what == "rebalance"
    assert [(o.symbol, o.side, o.qty) for o in orders] == [
        ("MU", "sell", 10),
        ("SNDK", "buy", 38),
        ("PANW", "buy", 35),
    ]
    assert orders[0].reason == "leaves the book"
    assert new.last_rebalance == "2026-09-04"
    assert new.opened == {"SNDK": "2026-09-04", "PANW": "2026-09-04"}
    again, same, why = paper.plan("2026-09-04", new, 100_000.0, {}, {}, {}, {})
    assert again == []
    assert why == "already planned for this session"
    assert same is new


# Between rebalances nothing trades except the exits the exit analyst names,
# and the rebalance clock advances.
def test_hold_then_exit_when_the_analyst_says_so():
    state = paper.PaperState(
        last_rebalance="2026-08-01",
        sessions_since_rebalance=3,
        opened={"MU": "2026-07-01", "SNDK": "2026-07-01"},
    )
    orders, new, what = paper.plan(
        "2026-09-04",
        state,
        equity=100_000.0,
        held={"MU": 40.0, "SNDK": 38.0},
        prices={"MU": 150.0, "SNDK": 200.0},
        targets={"SNDK": 0.08},
        grades={"MU": "C", "SNDK": "A+"},
        finished={"MU": "a bearish candle at the top of its Bollinger band"},
    )
    assert what == "exits"
    assert [(o.symbol, o.side, o.qty) for o in orders] == [("MU", "sell", 40)]
    assert "bearish candle" in orders[0].reason
    assert new.sessions_since_rebalance == 4
    assert "MU" not in new.opened
    quiet, _new, what2 = paper.plan(
        "2026-09-05",
        paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=3),
        100_000.0,
        {"MU": 40.0},
        {"MU": 150.0},
        {"SNDK": 0.08},
        {"MU": "C"},
    )
    assert quiet == []
    assert what2 == "hold"


# The twentieth session since the last rebalance realigns the whole book.
def test_rebalance_clock():
    state = paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=19)
    orders, new, what = paper.plan(
        "2026-09-04",
        state,
        50_000.0,
        {"MU": 10.0},
        {"MU": 100.0, "SNDK": 100.0},
        {"SNDK": 0.1},
        {"MU": "B", "SNDK": "A"},
    )
    assert what == "rebalance"
    assert {(o.symbol, o.side, o.qty) for o in orders} == {
        ("MU", "sell", 10),
        ("SNDK", "buy", 50),
    }
    assert new.sessions_since_rebalance == 0


# The state round-trips through its file and the snapshot books P/L from
# the first equity seen.
def test_state_and_snapshot(tmp_path):
    state = paper.PaperState()
    entry = paper.snapshot(
        state, "2026-09-04", 100_000.0, 60_000.0, [{"symbol": "SNDK", "qty": 38}]
    )
    assert entry["pl"] == 0.0
    later = paper.snapshot(state, "2026-09-05", 101_000.0, 60_000.0, [])
    assert later["pl"] == pytest.approx(1000.0)
    assert later["pl_pct"] == pytest.approx(0.01)
    assert [h["session"] for h in state.history] == ["2026-09-04", "2026-09-05"]
    paper.save_state(tmp_path, state)
    back = paper.load_state(tmp_path)
    assert back.start_equity == 100_000.0
    assert back.history[-1]["equity"] == 101_000.0
    assert paper.load_state(tmp_path / "nowhere").start_equity is None


# The client sends the right requests and refuses anything but paper.
def test_client_requests(monkeypatch):
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, headers["APCA-API-KEY-ID"], body))
        if url.endswith("/account"):
            return (
                200,
                json.dumps(
                    {
                        "equity": "100000",
                        "cash": "60000",
                        "buying_power": "120000",
                        "last_equity": "99000",
                    }
                ).encode(),
            )
        if url.endswith("/positions"):
            return (
                200,
                json.dumps(
                    [
                        {
                            "symbol": "SNDK",
                            "qty": "38",
                            "market_value": "7600",
                            "avg_entry_price": "200",
                            "current_price": "200",
                            "unrealized_pl": "0",
                        }
                    ]
                ).encode(),
            )
        if url.endswith("/orders") and method == "POST":
            return (
                200,
                json.dumps({"id": "o1", "symbol": json.loads(body)["symbol"]}).encode(),
            )
        if url.endswith("/orders") and method == "DELETE":
            return 207, b"[]"
        return 404, b'{"message": "no"}'

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    account = client.account()
    assert account.equity == 100_000.0
    assert client.positions()[0].symbol == "SNDK"
    order = client.submit_market_on_open("SNDK", 5, "buy")
    assert order["id"] == "o1"
    sent = json.loads(calls[-1][3])
    assert sent == {
        "symbol": "SNDK",
        "qty": "5",
        "side": "buy",
        "type": "market",
        "time_in_force": "opg",
    }
    with pytest.raises(alpaca_trading.AlpacaTradingError):
        client.submit_market_on_open("SNDK", 0, "buy")
    with pytest.raises(alpaca_trading.AlpacaTradingError):
        client._call("GET", "/missing")
    monkeypatch.setenv("APCA_API_KEY_ID", "k")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "s")
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets/v2")
    with pytest.raises(alpaca_trading.AlpacaTradingError):
        alpaca_trading.client_from_env(transport)
    monkeypatch.delenv("APCA_API_BASE_URL")
    assert (
        alpaca_trading.client_from_env(transport).base_url == alpaca_trading.PAPER_URL
    )
