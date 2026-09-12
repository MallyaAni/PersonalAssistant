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


# The band-reversal blocker: a name can earn a target weight and still be
# rejecting its upper Bollinger band, and then it is not bought - the grade
# says what to own, but the desk will not buy into a move that is already
# rolling over at the top. Sells pass regardless, and a name not rejecting
# the band is bought as before.
def test_buys_are_blocked_when_the_daily_rejects_the_upper_band():
    state = paper.PaperState()
    orders, new, what = paper.plan(
        "2026-09-04",
        state,
        equity=100_000.0,
        held={"MU": 10.0},
        prices={"SNDK": 200.0, "PANW": 180.0, "MU": 150.0, "TINY": 10.0},
        targets={"SNDK": 0.076, "PANW": 0.063, "TINY": 0.001},
        grades={"SNDK": "A+", "PANW": "A+", "MU": "C", "TINY": "A"},
        entry_blocked={"SNDK"},
    )
    assert what == "rebalance"
    # SNDK is the top-rated name, but its daily is rejecting its upper
    # Bollinger band, so it is not bought; PANW is bought; the MU exit is
    # not a buy and still happens.
    assert [(o.symbol, o.side, o.qty) for o in orders] == [
        ("MU", "sell", 10),
        ("PANW", "buy", 35),
    ]
    assert new.opened == {"PANW": "2026-09-04"}


# Whole shares are rounded to the nearest, not floored.
#
# Market-on-open orders must be whole shares, and flooring always rounds
# toward holding less - which bites hardest where a share is expensive.
# Measured on the real book: a 4.9% target in a 1,740 stock floored to 2
# shares, 29% short of what was asked, and the book came out 12% under its
# target gross with nearly all the miss in that one name.
def test_share_counts_round_to_nearest_not_down():
    orders, _new, _what = paper.plan(
        "2026-09-07",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"DEAR": 1740.0, "CHEAP": 52.0},
        targets={"DEAR": 0.049, "CHEAP": 0.104},
        grades={"DEAR": "A+", "CHEAP": "A+"},
    )
    counts = {o.symbol: o.qty for o in orders}
    # 0.049 x 100,000 / 1,740 = 2.83 shares. Floor buys 2 and is 29% short;
    # nearest buys 3 and is 6% over, which is less wrong.
    assert counts["DEAR"] == 3
    # A target that lands on a whole number is unaffected either way.
    assert counts["CHEAP"] == 200


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


# The operator's one-time move: a forced rebalance on a session the desk
# has already planned as a hold plans the targets anyway and restarts the
# clock; without the flag the same call is refused as already planned.
def test_a_forced_rebalance_overrides_the_clock_and_the_seen_session():
    state = paper.PaperState(
        last_rebalance="2026-09-08",
        sessions_since_rebalance=2,
        sessions_seen=["2026-09-10"],
    )
    refused, same, why = paper.plan(
        "2026-09-10", state, 50_000.0, {"MU": 10.0}, {"MU": 100.0}, {"SNDK": 0.1}, {}
    )
    assert refused == []
    assert why == "already planned for this session"
    orders, new, what = paper.plan(
        "2026-09-10",
        state,
        50_000.0,
        {"MU": 10.0},
        {"MU": 100.0, "SNDK": 100.0},
        {"SNDK": 0.1},
        {"MU": "B", "SNDK": "A"},
        force_rebalance=True,
    )
    assert what == "rebalance"
    assert {(o.symbol, o.side, o.qty) for o in orders} == {
        ("MU", "sell", 10),
        ("SNDK", "buy", 50),
    }
    assert new.last_rebalance == "2026-09-10"
    assert new.previous_rebalance == "2026-09-08"
    assert new.sessions_since_rebalance == 0
    assert new.sessions_seen == ["2026-09-10"]


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
            # Queued for the next open, not an auction order: on 2026-09-08
            # eight of nine opg orders expired unfilled on the paper venue.
            assert json.loads(body)["time_in_force"] == "day"
            assert json.loads(body)["type"] == "market"
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
        "time_in_force": "day",
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


# A sell queued for the closing auction rides the cls TIF, so an exit
# decided on one close fills at the next session's close, not its open.
def test_submit_market_on_close_rides_the_closing_auction(monkeypatch):
    calls = []

    def transport(method, url, headers, body):
        calls.append(json.loads(body))
        return 200, json.dumps({"id": "o2"}).encode()

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    client.submit_market_on_close(
        "ETN", 21, "sell", client_order_id="anios-2026-09-10-sell-etn-7"
    )
    assert calls[-1] == {
        "symbol": "ETN",
        "qty": "21",
        "side": "sell",
        "type": "market",
        "time_in_force": "cls",
        "client_order_id": "anios-2026-09-10-sell-etn-7",
    }


# The green-day rule's hold: a pending sell is dropped from pending and
# journaled as a deliberate skip (terminal, not a failed order), while the
# rest of the plan's orders stay put.
def test_skip_sell_marks_a_pending_sell_as_deliberately_held():
    state = paper.PaperState()
    state.pending = [
        {
            "client_order_id": "anios-2026-09-10-sell-etn-7",
            "symbol": "ETN",
            "side": "sell",
            "qty": 21,
            "session": "2026-09-10",
            "reason": "leaves the book",
        },
        {
            "client_order_id": "anios-2026-09-10-buy-anet-8",
            "symbol": "ANET",
            "side": "buy",
            "qty": 39,
            "session": "2026-09-10",
            "reason": "rebalance to 0.075",
        },
    ]
    out = paper.skip_sell(state, "anios-2026-09-10-sell-etn-7")
    assert [p["client_order_id"] for p in out.pending] == [
        "anios-2026-09-10-buy-anet-8"
    ]
    entry = next(
        e
        for e in out.journal
        if e["client_order_id"] == "anios-2026-09-10-sell-etn-7"
    )
    assert entry["status"] == paper.SKIPPED
    assert entry["terminal"] is True
    assert entry["qty"] == 21


# A rebalance whose only unfilled leg was deliberately skipped still
# concludes: the green-day hold keeps the position on purpose, so the
# rebalance clock must not roll back and re-plan it as a failure.
def test_a_rebalance_with_a_skipped_leg_concludes_without_rolling_back():
    state = paper.PaperState()
    state.unconfirmed_rebalance = "2026-09-10"
    state.last_rebalance = "2026-09-10"
    state.previous_rebalance = "2026-09-08"
    state.journal = [
        {
            "client_order_id": "anios-2026-09-10-sell-etn-7",
            "symbol": "ETN",
            "side": "sell",
            "qty": 21,
            "session": "2026-09-10",
            "status": paper.SKIPPED,
            "filled_qty": 0,
            "filled_price": 0.0,
            "terminal": True,
        },
        {
            "client_order_id": "anios-2026-09-10-buy-anet-8",
            "symbol": "ANET",
            "side": "buy",
            "qty": 39,
            "session": "2026-09-10",
            "status": "filled",
            "filled_qty": 39,
            "filled_price": 194.3,
            "terminal": True,
        },
    ]
    out = paper.apply_settlements(state, [])
    assert out.unconfirmed_rebalance is None
    assert out.last_rebalance == "2026-09-10"
    assert out.sessions_since_rebalance == 0


# A cancel is issued against the broker's own order id, never the client
# order id the desk chose: the broker's DELETE endpoint takes the UUID it
# issued, and the desk's id would 404. The open orders are read back and
# matched by client order id before the DELETE goes out, and a confirmed
# cancel is reported as cancelled.
def test_cancel_orders_deletes_by_the_brokers_order_id():
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url))
        if method == "GET" and url.endswith("/orders?status=open&limit=500"):
            return 200, json.dumps(
                [
                    {
                        "id": "o-broker-1",
                        "client_order_id": "anios-2026-09-10-sell-etn-7",
                        "symbol": "ETN",
                    },
                    {
                        "id": "o-broker-2",
                        "client_order_id": "anios-2026-09-10-buy-anet-8",
                        "symbol": "ANET",
                    },
                ]
            ).encode()
        if method == "DELETE":
            return 200, json.dumps({"id": "o-broker-1", "status": "canceled"}).encode()
        return 404, b"{}"

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    outcomes = client.cancel_orders(["anios-2026-09-10-sell-etn-7"])
    deletes = [url for method, url in calls if method == "DELETE"]
    assert deletes == [
        "https://paper-api.alpaca.markets/v2/orders/o-broker-1"
    ]
    assert outcomes == {"anios-2026-09-10-sell-etn-7": "cancelled"}


# A live order the broker refuses to cancel must not read as cancelled:
# the caller journals a deliberate hold only when the withdrawal happened,
# so a refused cancel raises instead of being swallowed.
def test_cancel_orders_raises_when_the_broker_refuses():
    def transport(method, url, headers, body):
        if method == "GET" and url.endswith("/orders?status=open&limit=500"):
            return 200, json.dumps(
                [
                    {
                        "id": "o-broker-1",
                        "client_order_id": "anios-2026-09-10-sell-etn-7",
                        "symbol": "ETN",
                    }
                ]
            ).encode()
        if method == "DELETE":
            return 403, b'{"message": "the auction is locked"}'
        return 404, b"{}"

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    with pytest.raises(alpaca_trading.AlpacaTradingError):
        client.cancel_orders(["anios-2026-09-10-sell-etn-7"])


# A client order id that no longer appears among the open orders is
# already gone - filled, expired or withdrawn by hand - so it is reported
# as such rather than as a failed cancel or a confirmed one: the caller
# must not journal a deliberate hold for an order that already filled.
def test_cancel_orders_skips_an_order_that_is_already_gone():
    deletes: list[str] = []

    def transport(method, url, headers, body):
        if method == "GET" and url.endswith("/orders?status=open&limit=500"):
            return 200, json.dumps([]).encode()
        if method == "DELETE":
            deletes.append(url)
            return 200, b"[]"
        return 404, b"{}"

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    outcomes = client.cancel_orders(["anios-2026-09-10-sell-etn-7"])
    assert deletes == []
    assert outcomes == {"anios-2026-09-10-sell-etn-7": "already_gone"}


# A cancel the broker accepts without confirming - the order is left in
# pending_cancel and can still fill - must not read as cancelled, or a
# caller would journal a hold for an order that may yet execute.
def test_cancel_orders_reports_an_unconfirmed_cancel():
    def transport(method, url, headers, body):
        if method == "GET" and url.endswith("/orders?status=open&limit=500"):
            return 200, json.dumps(
                [
                    {
                        "id": "o-broker-1",
                        "client_order_id": "anios-2026-09-10-sell-etn-7",
                        "symbol": "ETN",
                    }
                ]
            ).encode()
        if method == "DELETE":
            return 200, json.dumps(
                {"id": "o-broker-1", "status": "pending_cancel"}
            ).encode()
        return 404, b"{}"

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    outcomes = client.cancel_orders(["anios-2026-09-10-sell-etn-7"])
    assert outcomes == {"anios-2026-09-10-sell-etn-7": "unconfirmed"}
