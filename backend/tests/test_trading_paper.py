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
    # The sale is only half of it: the money follows the names the desk still
    # wants. MU frees 40 x $150 = $6,000, SNDK is the only taker and has room
    # under the name cap, so it buys 30 shares at $200. Selling to cash - which
    # is what this did before - measured 24 points of CAGR a year worse.
    assert [(o.symbol, o.side, o.qty) for o in orders] == [
        ("MU", "sell", 40),
        ("SNDK", "buy", 30),
    ]
    assert "bearish candle" in orders[0].reason
    assert "redeploying" in orders[1].reason
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


# The session that completes the rebalance clock realigns the whole book.
# Read from the constant, not written as 20: the cadence moved to 120 when
# price entries took over the timing, and a hardcoded number would have made
# that look like a regression instead of the change it was.
def test_rebalance_clock():
    state = paper.PaperState(
        last_rebalance="2026-08-01",
        sessions_since_rebalance=paper.REBALANCE_EVERY - 1,
    )
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
        e for e in out.journal if e["client_order_id"] == "anios-2026-09-10-sell-etn-7"
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
            return 204, b""
        if method == "GET" and url.endswith("/orders/o-broker-1"):
            return 200, json.dumps(
                {"id": "o-broker-1", "status": "canceled", "filled_qty": "0"}
            ).encode()
        return 404, b"{}"

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    outcomes = client.cancel_orders(["anios-2026-09-10-sell-etn-7"])
    deletes = [url for method, url in calls if method == "DELETE"]
    assert deletes == ["https://paper-api.alpaca.markets/v2/orders/o-broker-1"]
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
    # Acknowledgement and order status are separate broker responses.
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
            return 204, b""
        if method == "GET" and url.endswith("/orders/o-broker-1"):
            return 200, json.dumps(
                {"id": "o-broker-1", "status": "pending_cancel"}
            ).encode()
        return 404, b"{}"

    client = alpaca_trading.AlpacaTradingClient("k", "s", transport=transport)
    outcomes = client.cancel_orders(["anios-2026-09-10-sell-etn-7"])
    assert outcomes == {"anios-2026-09-10-sell-etn-7": "unconfirmed"}


# Mid-cycle price entries: the calendar chooses what the book holds, price
# chooses when each name is entered. Measured 2026-09-18; the constants and
# the evidence are at the top of paper.py.
def test_a_price_entry_is_paid_from_cash_and_sized_by_the_band():
    state = paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=3)

    def plan_at(band):
        return paper.plan(
            "2026-09-04",
            paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=3),
            100_000.0,
            {"MU": 200.0, "AMD": 200.0, "SNDK": 0.0},
            {"MU": 100.0, "AMD": 100.0, "SNDK": 50.0},
            {"MU": 0.2, "AMD": 0.2, "SNDK": 0.0},
            {"MU": "A", "AMD": "A", "SNDK": "A+"},
            entries={"SNDK": band},
        )

    orders, _new, what = plan_at(1.5)
    assert what == "entries"
    by_symbol = {o.symbol: o for o in orders}
    # Paid from cash, so the names the desk still wants are left alone. This
    # test asserted the opposite until 2026-09-20: the add was funded by
    # trimming them pro rata, which held gross exposure fixed and meant the
    # book could never put money to work however strong the signal. On the
    # live account that was 43% invested against 57% idle.
    assert set(by_symbol) == {"SNDK"}
    assert by_symbol["SNDK"].side == "buy"
    assert all(o.side == "buy" for o in orders)
    # Sized by how far through its band the name closed, not a flat 3%.
    expected = paper.entry_size(1.5)
    assert by_symbol["SNDK"].qty == int(round(expected * 100_000.0 / 50.0))
    # And a stronger reading at that price is a bigger position.
    weaker = {o.symbol: o for o in plan_at(paper.ENTRY_BAND_Z)[0]}
    stronger = {o.symbol: o for o in plan_at(2.2)[0]}
    assert weaker["SNDK"].qty < by_symbol["SNDK"].qty < stronger["SNDK"].qty
    # The cap is still the backstop, whatever the reading.
    huge = {o.symbol: o for o in plan_at(9.0)[0]}
    assert huge["SNDK"].qty * 50.0 <= paper.ENTRY_NAME_CAP * 100_000.0 + 1.0


# A name already at the cap takes nothing more, however far it has moved.
def test_a_capped_name_is_not_added_to():
    state = paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=3)
    orders, _new, what = paper.plan(
        "2026-09-04",
        state,
        100_000.0,
        {"SNDK": 300.0, "MU": 100.0},
        {"SNDK": 50.0, "MU": 100.0},
        {"SNDK": 0.15, "MU": 0.1},
        {"SNDK": "A+", "MU": "A"},
        entries={"SNDK": 1.0},
    )
    assert orders == []
    assert what == "hold"


# The band-rejection gate still blocks a buy, entries included.
def test_a_blocked_name_gets_no_price_entry():
    state = paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=3)
    orders, _new, _what = paper.plan(
        "2026-09-04",
        state,
        100_000.0,
        {"MU": 200.0},
        {"MU": 100.0, "SNDK": 50.0},
        {"MU": 0.2},
        {"MU": "A", "SNDK": "A+"},
        entry_blocked={"SNDK"},
        entries={"SNDK": 1.0},
    )
    assert orders == []


# With nothing else held there is nothing to fund from, so the gross is
# never grown to pay for an entry.
def test_an_entry_never_grows_the_gross():
    state = paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=3)
    orders, _new, _what = paper.plan(
        "2026-09-04", state, 100_000.0, {}, {"SNDK": 50.0}, {}, {"SNDK": "A+"},
        entries={"SNDK": 1.0},
    )
    assert orders == []


# The deferred buy leg. Buys are bounded to the cash on hand and sells fill
# on the following close, so a rebalance whose buys outrun the cash used to
# leave the sale proceeds idle until the next entry or the next reset -
# about five CAGR points, measured. The unpaid shares are written down
# instead and re-issued once on the next session, from the cash the sells
# have delivered by then.
def test_a_cash_bound_rebalance_records_its_unpaid_shares_and_retries_once():
    prices = {"OLD": 400.0, "SNDK": 100.0, "PANW": 100.0, "MU": 100.0, "AMD": 100.0}
    targets = {"SNDK": 0.15, "PANW": 0.15, "MU": 0.15, "AMD": 0.15}
    grades = {"OLD": "C", "SNDK": "A+", "PANW": "A", "MU": "A", "AMD": "A"}
    # 100,000 of equity, 40,000 of it in OLD, and 60,000 of buys at 150
    # shares each. With only 40,000 of cash on hand the buys are scaled to
    # two thirds, and OLD's proceeds arrive at the close, too late.
    orders, after, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        100_000.0,
        {"OLD": 100.0},
        prices,
        targets,
        grades,
        cash=40_000.0,
    )
    assert what == "rebalance"
    assert [(o.symbol, o.side, o.qty) for o in orders] == [
        ("OLD", "sell", 100),
        ("AMD", "buy", 100),
        ("MU", "buy", 100),
        ("PANW", "buy", 100),
        ("SNDK", "buy", 100),
    ]
    # The 50 shares of each name the cash could not pay for are remembered.
    assert after.deferred_buys == {"SNDK": 50, "PANW": 50, "MU": 50, "AMD": 50}

    # The next session: OLD's sale has settled, the cash is there, and the
    # remainder is issued before anything else - exactly the remainder, as
    # buys, with nothing else on the tape.
    held = {"SNDK": 100.0, "PANW": 100.0, "MU": 100.0, "AMD": 100.0}
    retry, later, what2 = paper.plan(
        "2026-09-05",
        after,
        100_000.0,
        held,
        prices,
        targets,
        grades,
        cash=60_000.0,
    )
    assert what2 == "deferred buys"
    assert sorted((o.symbol, o.side, o.qty) for o in retry) == [
        ("AMD", "buy", 50),
        ("MU", "buy", 50),
        ("PANW", "buy", 50),
        ("SNDK", "buy", 50),
    ]
    assert all("deferred" in o.reason for o in retry)
    assert later.sessions_since_rebalance == 1
    # One retry, then it is over: nothing is carried to a third session.
    assert later.deferred_buys == {}
    # A later hold session issues nothing.
    quiet, _final, what3 = paper.plan(
        "2026-09-08",
        later,
        100_000.0,
        {s: 150.0 for s in held},
        prices,
        targets,
        grades,
        cash=40_000.0,
    )
    assert quiet == []
    assert what3 == "hold"


# The retry is bounded by the cash on hand and by the name cap, and its own
# shortfall is not chased: whatever the second session cannot pay for is
# dropped rather than carried to a third.
def test_the_retry_is_bounded_by_cash_and_the_cap_and_never_chased():
    prices = {"SNDK": 100.0, "PANW": 100.0}
    grades = {"SNDK": "A+", "PANW": "A"}
    state = paper.PaperState(
        last_rebalance="2026-09-04",
        sessions_since_rebalance=0,
        deferred_buys={"SNDK": 50.0, "PANW": 50.0},
    )
    # SNDK already holds 140 shares against a cap of 150 (15% of 100,000 at
    # 100), so its retry is 10; PANW has room for all 50; the cash pays for
    # 30 shares in all, shared pro rata.
    orders, after, what = paper.plan(
        "2026-09-05",
        state,
        100_000.0,
        {"SNDK": 140.0, "PANW": 100.0},
        prices,
        {"SNDK": 0.15, "PANW": 0.15},
        grades,
        cash=3_000.0,
    )
    assert what == "deferred buys"
    assert sorted((o.symbol, o.side, o.qty) for o in orders) == [
        ("PANW", "buy", 25),
        ("SNDK", "buy", 5),
    ]
    assert sum(o.qty * prices[o.symbol] for o in orders) <= 3_000.0
    assert after.deferred_buys == {}


# A name the desk no longer wants gets no retry: the remainder is dropped
# when the grade has fallen below A (the rotation sells it instead) or the
# daily is rejecting its band, the same gates a mid-cycle entry passes.
def test_a_downgraded_or_blocked_remainder_is_dropped():
    prices = {"SNDK": 100.0, "PANW": 100.0, "MU": 100.0}
    state = paper.PaperState(
        last_rebalance="2026-09-04",
        sessions_since_rebalance=0,
        deferred_buys={"SNDK": 50.0, "PANW": 50.0, "MU": 50.0},
    )
    orders, after, _what = paper.plan(
        "2026-09-05",
        state,
        100_000.0,
        {"SNDK": 100.0, "PANW": 100.0, "MU": 100.0},
        prices,
        {"SNDK": 0.15, "PANW": 0.15},
        {"SNDK": "A+", "PANW": "A", "MU": "B"},
        finished={"MU": "graded B; the desk wants the money elsewhere"},
        entry_blocked={"PANW"},
        cash=60_000.0,
    )
    by_symbol = {(o.symbol, o.side): o.qty for o in orders}
    # MU is rotated out, not bought; PANW's remainder waits for nothing;
    # SNDK's is the only retry. MU's proceeds redeploy into SNDK too, so
    # the SNDK buy is the retry plus the rotation's share, inside the cap.
    assert ("MU", "sell") in by_symbol
    assert ("MU", "buy") not in by_symbol
    retried = [o for o in orders if o.reason.startswith("deferred")]
    assert [o.symbol for o in retried] == ["SNDK"]
    # PANW's only buy tonight is the /4 redeploy of the idle cash, which has
    # no band gate by design (the simulator's `mc-redeploy` has none): it is
    # brought to its 15% target, not retried.
    panw = [o for o in orders if o.symbol == "PANW" and o.side == "buy"]
    assert [o.kind for o in panw] == [paper.REDEPLOY_KIND]
    assert by_symbol[("PANW", "buy")] == 50
    assert 50 <= by_symbol[("SNDK", "buy")] <= 150 - 100
    assert after.deferred_buys == {}


# The retry takes the cash first; a new entry on the same session gets what
# is left, and ITS shortfall is what the next session carries.
def test_the_retry_is_paid_before_a_new_entry_whose_shortfall_is_carried():
    prices = {"SNDK": 100.0, "NEW": 100.0}
    state = paper.PaperState(
        last_rebalance="2026-09-04",
        sessions_since_rebalance=0,
        deferred_buys={"SNDK": 50.0},
    )
    orders, after, what = paper.plan(
        "2026-09-05",
        state,
        100_000.0,
        {"SNDK": 100.0},
        prices,
        {"SNDK": 0.15},
        {"SNDK": "A+", "NEW": "A"},
        entries={"NEW": 1.5},
        cash=6_050.0,
    )
    assert what == "entries"
    by_symbol = {o.symbol: o.qty for o in orders}
    assert by_symbol["SNDK"] == 50
    # entry_size(1.5) of 100,000 at 100 is 33 shares; 1,050 of cash is left
    # after the retry, so 10 are bought and 23 are carried.
    assert by_symbol["NEW"] == 10
    assert after.deferred_buys == {"NEW": 23}


# A rebalance supersedes whatever the previous session left unpaid: the
# targets are re-planned from scratch and the old remainder is not added
# on top of them.
def test_a_rebalance_drops_the_previous_remainder():
    state = paper.PaperState(
        last_rebalance="2026-08-01",
        sessions_since_rebalance=paper.REBALANCE_EVERY - 1,
        deferred_buys={"SNDK": 50.0},
    )
    orders, after, what = paper.plan(
        "2026-09-05",
        state,
        100_000.0,
        {"SNDK": 100.0},
        {"SNDK": 100.0},
        {"SNDK": 0.10},
        {"SNDK": "A+"},
        cash=90_000.0,
    )
    assert what == "rebalance"
    assert orders == []
    assert after.deferred_buys == {}


# A state file written before the deferred leg existed still loads, with
# nothing deferred, and the remainder round-trips through the file.
def test_state_files_without_deferred_buys_still_load(tmp_path):
    from dataclasses import asdict

    path = paper.state_path(tmp_path)
    path.parent.mkdir(parents=True)
    old = {k: v for k, v in asdict(paper.PaperState()).items() if k != "deferred_buys"}
    old["last_rebalance"] = "2026-09-04"
    path.write_text(json.dumps(old), encoding="utf-8")
    loaded = paper.load_state(tmp_path)
    assert loaded.last_rebalance == "2026-09-04"
    assert loaded.deferred_buys == {}
    loaded.deferred_buys = {"SNDK": 50.0}
    paper.save_state(tmp_path, loaded)
    assert paper.load_state(tmp_path).deferred_buys == {"SNDK": 50.0}
    assert "deferred_buys" in json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The redeploy of idle cash (execution policy /4, 2026-09-27).
# ---------------------------------------------------------------------------


# The scorecard's synthetic report on its last session, read the way the
# nightly reads the account: prices at the close, every name graded, the
# policy's targets from `live_policy.targets`, a book of held shares and
# the cash beside it. Returns everything both planners take.
def _redeploy_inputs(held_weights: dict[str, float], cash_share: float):
    from backend.agents.trading.desk import live_policy
    from backend.tests.test_market_pit_scorecard import _report

    report = _report()
    panel = report.panel
    last = len(panel.dates) - 1
    prices = {t: float(panel.close[last, j]) for j, t in enumerate(panel.tickers)}
    grades = {
        t: report.graded.letter(last, j)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    targets = live_policy.targets(report)
    equity = 250_000.0
    held = {s: w * equity / prices[s] for s, w in held_weights.items()}
    cash = cash_share * equity
    assert abs(sum(held_weights.values()) + cash_share - 1.0) < 1e-12
    return report, str(panel.dates[last]), prices, grades, targets, equity, held, cash


# The parity test: the live planner's redeploy leg and the simulator's
# `_redeploy_orders` (the `mc-redeploy` variant) on the same inputs - the
# policy's targets from `live_policy.targets`, six A+ names at 1/6 each
# (above the entry leg's 15% cap), four held under weight, one rotating out,
# one graded in since the reset and unheld, a planned rotation buy and a
# planned entry to account for - put the same dollars into the same names to
# 1e-9, and those dollars are each name's shortfall to its target weight
# times equity, scaled by the one fill ratio. Then with whole shares, on a
# session with nothing else to buy, the live plan's redeploy is the
# simulator's leg in whole shares: within one share a name, never more in
# total, never a name past its target (`paper._whole_share_fill`).
def test_the_live_redeploy_matches_the_simulator_to_1e_9():
    from backend.agents.trading.desk import simulate

    report, session, prices, grades, targets, equity, held, cash = _redeploy_inputs(
        {"AAA": 0.12, "BBB": 0.10, "CCC": 0.14, "DDD": 0.09, "FFF": 0.16}, 0.39
    )
    assert set(targets) == {"AAA", "BBB", "CCC", "DDD", "EEE", "FFF"}
    assert all(abs(w - 1 / 6) < 1e-12 for w in targets.values())
    # FFF is rotating out tonight; EEE was not wanted at the reset (graded in
    # since) and is not held; the others were wanted at the reset.
    finished = {"FFF": "graded B; the desk wants the money elsewhere"}
    at_rebalance = {s: w for s, w in targets.items() if s != "EEE"}
    planned = [
        paper.PaperOrder("FFF", "sell", held["FFF"], finished["FFF"]),
        paper.PaperOrder(
            "AAA", "buy", 2_000.0 / prices["AAA"], "redeploying a downgraded name"
        ),
        paper.PaperOrder(
            "BBB", "buy", 3_000.0 / prices["BBB"], "price entry: breakout"
        ),
    ]
    sim = simulate._redeploy_orders(
        planned, held, prices, equity, grades, finished, targets, at_rebalance,
        cash, simulate.REDEPLOY_BUFFER, session, paper.PaperState(),
    )
    live = paper._redeploy_orders(
        planned, held, prices, equity, grades, finished, targets, at_rebalance,
        cash, paper.REDEPLOY_BUFFER, session, paper.PaperState(), whole_shares=False,
    )
    assert paper.REDEPLOY_BUFFER == simulate.REDEPLOY_BUFFER == 0.02
    sim_dollars = {o.symbol: o.qty * prices[o.symbol] for o in sim}
    live_dollars = {o.symbol: o.qty * prices[o.symbol] for o in live}
    assert set(sim_dollars) == set(live_dollars) == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    for symbol in sim_dollars:
        assert abs(sim_dollars[symbol] - live_dollars[symbol]) < 1e-9, symbol
    # Translate: the shortfall of each taker to its target, in dollars, after
    # the planned buys count toward the name; the spare cash is the cash less
    # the planned buys less the buffer; every taker is filled by the same ratio.
    projected = dict(held)
    projected["AAA"] += planned[1].qty
    projected["BBB"] += planned[2].qty
    shortfall = {
        s: (targets[s] - projected.get(s, 0.0) * prices[s] / equity) * equity
        for s in ("AAA", "BBB", "CCC", "DDD", "EEE")
    }
    spare = cash - 5_000.0 - 0.02 * equity
    fill = min(1.0, spare / sum(shortfall.values()))
    assert 0 < fill < 1  # the cash is short of the whole shortfall tonight
    for symbol, want in shortfall.items():
        assert abs(live_dollars[symbol] - want * fill) < 1e-9, symbol
    assert abs(sum(live_dollars.values()) - spare) < 1e-9
    assert all(o.kind == paper.REDEPLOY_KIND and o.side == "buy" for o in live)
    assert all(o.reason == sim[0].reason for o in live)

    # Whole shares through `plan`: no rotation, no entry, no retry tonight,
    # so the live redeploy is the simulator's leg floored to shares.
    quiet = paper.PaperState(
        last_rebalance="2026-01-02",
        sessions_since_rebalance=4,
        policy_version="graded-equal-weight/4",
        rebalance_targets=at_rebalance,
    )
    orders, after, what = paper.plan(
        session, quiet, equity, held, prices, targets, grades,
        finished={}, entry_blocked=set(), entries={}, cash=cash,
    )
    assert what == "redeploy"
    sim_plain = simulate._redeploy_orders(
        [], held, prices, equity, grades, {}, targets, at_rebalance,
        cash, simulate.REDEPLOY_BUFFER, session, paper.PaperState(),
    )
    # Whole shares spend the simulator's dollars to within a share a name:
    # never more in total, never a name past its target, and what is left
    # unspent is less than the cheapest share that would still fit a leg.
    sim_by = {o.symbol: o.qty * prices[o.symbol] for o in sim_plain}
    live_by = {o.symbol: o.qty * prices[o.symbol] for o in orders}
    assert set(live_by) <= set(sim_by)
    assert all(float(o.qty).is_integer() and o.qty > 0 for o in orders)
    for symbol, dollars in live_by.items():
        assert abs(dollars - sim_by[symbol]) < prices[symbol] + 1e-9, symbol
        final = (held.get(symbol, 0.0) * prices[symbol] + dollars) / equity
        assert final <= targets[symbol] + 1e-9, symbol
    assert sum(live_by.values()) <= sum(sim_by.values()) + 1e-9
    assert sum(sim_by.values()) - sum(live_by.values()) < max(prices.values())
    assert all(o.kind == paper.REDEPLOY_KIND for o in orders)
    assert sum(o.qty * prices[o.symbol] for o in orders) <= cash - 0.02 * equity
    assert after.deferred_buys == {}


# With the rule off the planner is the /3 planner byte for byte: the orders,
# their ids, reasons and sequence, the state after, on a session with idle
# cash, a rotation, a blocked name, a band entry and a deferred retry all at
# once. The expected values were read off the planner before the redeploy
# existed (commit 8b4ec386) and are pinned here. With the rule on, the same
# session plans the same orders plus redeploy buys and nothing else changes.
def test_the_planner_with_the_redeploy_off_is_the_v3_planner(monkeypatch):
    prices = {"AAA": 100.0, "BBB": 50.0, "CCC": 20.0, "DDD": 80.0, "EEE": 40.0}
    grades = {"AAA": "A+", "BBB": "A", "CCC": "B", "DDD": "A+", "EEE": "A"}
    targets = {"AAA": 0.2, "BBB": 0.2, "DDD": 0.2, "EEE": 0.2}
    held = {"AAA": 120.0, "BBB": 200.0, "CCC": 500.0, "DDD": 100.0}
    leaving = "graded B; the desk wants the money elsewhere"

    def run():
        state = paper.PaperState(
            last_rebalance="2026-09-04",
            sessions_since_rebalance=3,
            policy_version="graded-equal-weight/4",
            deferred_buys={"DDD": 30.0},
            rebalance_targets=dict(targets),
        )
        return paper.plan(
            "2026-09-09", state, 100_000.0, held, prices, targets, grades,
            finished={"CCC": leaving},
            entry_blocked={"BBB"}, entries={"AAA": 1.3, "EEE": 1.2}, cash=40_000.0,
        )

    rotation = "redeploying a downgraded name"
    entry = "price entry: breakout through its own 20-day band"
    deferred = "deferred buy: the remainder cash could not pay for last session"
    v3 = [
        ("CCC", "sell", 500, leaving, "sell-ccc-1"),
        ("DDD", "buy", 57, rotation, "buy-ddd-3"),
        ("EEE", "buy", 52, entry, "buy-eee-4"),
        ("DDD", "buy", 30, deferred, "buy-ddd-0"),
        ("AAA", "buy", 30, rotation, "buy-aaa-2"),
    ]
    v3 = [(*row[:4], f"anios-2026-09-09-{row[4]}") for row in v3]

    def rows(orders):
        return [(o.symbol, o.side, o.qty, o.reason, o.client_order_id) for o in orders]

    monkeypatch.setattr(paper, "REDEPLOY_IDLE_CASH", False)
    orders, after, what = run()
    assert what == "entries"
    assert rows(orders) == v3
    assert all(o.kind is None for o in orders)
    assert after.deferred_buys == {}
    assert after.order_seq == 5
    assert after.opened == {"DDD": "2026-09-09", "EEE": "2026-09-09"}
    assert after.sessions_since_rebalance == 4

    monkeypatch.setattr(paper, "REDEPLOY_IDLE_CASH", True)
    orders_on, after_on, what_on = run()
    plain = [o for o in orders_on if o.kind != paper.REDEPLOY_KIND]
    assert rows(plain) == v3
    redeploy = [o for o in orders_on if o.kind == paper.REDEPLOY_KIND]
    assert redeploy
    assert all(o.side == "buy" for o in redeploy)
    assert what_on == "entries"  # the entries still name the day
    # 40,000 cash: 3,000 retry, 5,700 + 3,000 rotation buys, 2,080 entry,
    # 2,000 buffer leave 24,220 spare; the takers are the A/A+ names held or
    # bought tonight, each short of 20%, and CCC (rotating out) is never one.
    assert {o.symbol for o in redeploy} <= {"AAA", "BBB", "DDD", "EEE"}
    assert "CCC" not in {o.symbol for o in redeploy}
    bought = sum(o.qty * prices[o.symbol] for o in orders_on if o.side == "buy")
    assert bought <= 40_000.0
    assert after_on.sessions_since_rebalance == 4
    assert after_on.deferred_buys == {}


# The redeploy never buys a name rotating out or graded below A, never
# spends past the cash on hand, keeps the buffer, sends no leg under
# MIN_TRADE, and does nothing when the spare cash is under the floor.
def test_the_redeploy_respects_the_rotation_the_cash_and_the_buffer():
    prices = {"AAA": 100.0, "BBB": 100.0, "CCC": 100.0, "DDD": 100.0}
    grades = {"AAA": "A+", "BBB": "A", "CCC": "B", "DDD": "A+"}
    targets = {"AAA": 0.2, "BBB": 0.2, "DDD": 0.2}
    held = {"AAA": 100.0, "BBB": 100.0, "CCC": 300.0, "DDD": 100.0}
    finished = {"CCC": "graded B; the desk wants the money elsewhere"}
    state = paper.PaperState(
        last_rebalance="2026-09-04", sessions_since_rebalance=2,
        policy_version="graded-equal-weight/4", rebalance_targets=dict(targets),
    )
    # 100,000 of equity, 40,000 in cash. CCC's sale delivers at the close and
    # pays for nothing tonight; its 30,000 is redeployed pro rata by the
    # rotation into the held names under the 15% cap (5,000 each), and the
    # redeploy then fills the rest of each shortfall from what the cash allows.
    orders, after, what = paper.plan(
        "2026-09-08", state, 100_000.0, held, prices, targets, grades,
        finished=finished, entry_blocked=set(), entries={}, cash=40_000.0,
    )
    assert what == "exits"
    buys = [o for o in orders if o.side == "buy"]
    assert "CCC" not in {o.symbol for o in buys}
    assert sum(o.qty * prices[o.symbol] for o in buys) <= 40_000.0 - 2_000.0
    redeploy = [o for o in buys if o.kind == paper.REDEPLOY_KIND]
    assert {o.symbol for o in redeploy} == {"AAA", "BBB", "DDD"}
    for o in redeploy:
        assert o.qty * prices[o.symbol] >= paper.MIN_TRADE * 100_000.0
    # No name ends above its 20% target: 100 held + 50 rotation + redeploy.
    final = dict(held)
    for o in buys:
        final[o.symbol] += o.qty
    for symbol in ("AAA", "BBB", "DDD"):
        assert final[symbol] * prices[symbol] <= 0.2 * 100_000.0 + 1e-9
    # The buffer is what stays: spare = 40,000 - 15,000 rotation buys - 2,000.
    spent = sum(o.qty * prices[o.symbol] for o in buys)
    assert 40_000.0 - spent >= 2_000.0

    # Spare cash under MIN_TRADE of equity: nothing is sent.
    quiet, _, what2 = paper.plan(
        "2026-09-09", after, 100_000.0,
        {"AAA": 190.0, "BBB": 190.0, "DDD": 190.0}, prices, targets, grades,
        finished={}, entry_blocked=set(), entries={}, cash=2_400.0,
    )
    assert quiet == []
    assert what2 == "hold"
    # Cash exactly at the buffer: nothing is sent either.
    quiet2, _, _ = paper.plan(
        "2026-09-10", after, 100_000.0,
        {"AAA": 190.0, "BBB": 190.0, "DDD": 190.0}, prices, targets, grades,
        finished={}, entry_blocked=set(), entries={}, cash=2_000.0,
    )
    assert quiet2 == []


# A name graded in since the reset - the policy wants it tonight, the reset
# wanted none of it, the book holds none - is a taker at its full target,
# above the 15% entry cap and with no band gate; a name the reset wanted
# that the book does not hold (its buy was band-blocked at the reset) is
# not. When the state predates the field (None), no unheld name is a taker
# and the held names take the cash; an empty dict (a reset that wanted
# nothing) makes every wanted name new, as in the simulator.
def test_a_name_graded_in_since_the_reset_is_a_taker_at_its_target():
    prices = {"AAA": 100.0, "BBB": 100.0, "NEW": 50.0, "SKIP": 100.0}
    grades = {"AAA": "A+", "BBB": "A+", "NEW": "A", "SKIP": "A+"}
    targets = {"AAA": 0.2, "BBB": 0.2, "NEW": 0.2, "SKIP": 0.2}
    held = {"AAA": 200.0, "BBB": 200.0}
    common = dict(finished={}, entry_blocked={"NEW"}, entries={}, cash=60_000.0)

    def state(at_rebalance):
        return paper.PaperState(
            last_rebalance="2026-09-04", sessions_since_rebalance=1,
            policy_version="graded-equal-weight/4", rebalance_targets=at_rebalance,
        )

    orders, _, what = paper.plan(
        "2026-09-05", state({"AAA": 0.2, "BBB": 0.2, "SKIP": 0.2}),
        100_000.0, held, prices, targets, grades, **common,
    )
    assert what == "redeploy"
    assert [(o.symbol, o.qty, o.kind) for o in orders] == [
        ("NEW", 400, paper.REDEPLOY_KIND)
    ]
    # Predating the field: the held names are at target already, so nothing.
    none, _, what_none = paper.plan(
        "2026-09-05", state(None), 100_000.0, held, prices, targets, grades, **common
    )
    assert none == []
    assert what_none == "hold"
    # A reset that wanted nothing: every wanted unheld name is new.
    every, _, _ = paper.plan(
        "2026-09-05", state({}), 100_000.0, held, prices, targets, grades, **common
    )
    assert sorted((o.symbol, o.qty) for o in every) == [("NEW", 400), ("SKIP", 200)]


# The day after a reset. The reset's sells fill at the close and its buys at
# the open are paid only from the cash on hand, so on an invested book the
# buys go partly unpaid and are deferred. The next session is an ordinary
# one: the deferred retry takes what its gates allow (band gate, 15% cap),
# and the redeploy then puts the rest of the cash the sells delivered into
# the shortfall names, up to their 20% targets, leaving the buffer. Before
# the redeploy the book sat 25% in cash for the rest of the cycle.
def test_the_session_after_a_reset_redeploys_the_unpaid_buys():
    prices = {"OLD": 100.0, "AAA": 100.0, "BBB": 100.0, "CCC": 100.0, "DDD": 100.0}
    grades = {"OLD": "C", "AAA": "A+", "BBB": "A+", "CCC": "A+", "DDD": "A+"}
    targets = {"AAA": 0.2, "BBB": 0.2, "CCC": 0.2, "DDD": 0.2}
    # A 100,000 book: 800 OLD (80,000) and 20,000 cash. The reset sells OLD
    # and asks for 200 of each name under the allocation targets. Cash pays
    # for a quarter; the mid-cycle entry cap does not cut the reset's buys.
    reset, after_reset, what = paper.plan(
        "2026-09-04", paper.PaperState(), 100_000.0, {"OLD": 800.0}, prices,
        targets, grades, finished={}, entry_blocked=set(), entries={}, cash=20_000.0,
    )
    assert what == "rebalance"
    assert not any(o.kind == paper.REDEPLOY_KIND for o in reset)
    assert after_reset.rebalance_targets == targets
    assert {(o.symbol, o.side, o.qty) for o in reset} == {
        ("OLD", "sell", 800), ("AAA", "buy", 50), ("BBB", "buy", 50),
        ("CCC", "buy", 50), ("DDD", "buy", 50),
    }
    assert after_reset.deferred_buys == {s: 150.0 for s in targets}
    # The next session: OLD's 80,000 has arrived, the book holds 50 of each.
    # The retry is capped at 15% (150 shares a name, 100 more each) and
    # band-blocked on DDD; the redeploy takes the rest to 20% - AAA, BBB and
    # CCC 50 more each, DDD (no band gate) 150 - and the buffer stays.
    held = {s: 50.0 for s in targets}
    orders, after, what2 = paper.plan(
        "2026-09-05", after_reset, 100_000.0, held, prices, targets, grades,
        finished={}, entry_blocked={"DDD"}, entries={}, cash=80_000.0,
    )
    assert what2 == "deferred buys"
    retried = {o.symbol: o.qty for o in orders if o.reason.startswith("deferred")}
    assert retried == {"AAA": 100, "BBB": 100, "CCC": 100}
    redeployed = {o.symbol: o.qty for o in orders if o.kind == paper.REDEPLOY_KIND}
    assert redeployed == {"AAA": 50, "BBB": 50, "CCC": 50, "DDD": 150}
    final = {s: held[s] + retried.get(s, 0) + redeployed.get(s, 0) for s in targets}
    assert final == {s: 200.0 for s in targets}  # every name at its 20% target
    spent = sum(o.qty * prices[o.symbol] for o in orders if o.side == "buy")
    assert spent == 60_000.0
    assert 80_000.0 - spent == 20_000.0  # the 20% the policy's cap leaves
    assert after.deferred_buys == {}
    # At the targets the next session sends nothing: the 20% the policy's cap
    # leaves is not idle cash the redeploy may spend.
    quiet, _, what3 = paper.plan(
        "2026-09-08", after, 100_000.0, {s: 200.0 for s in targets}, prices,
        targets, grades, finished={}, entry_blocked=set(), entries={}, cash=20_000.0,
    )
    assert quiet == []
    assert what3 == "hold"


# `bound_orders` caps an entry or a rotation buy at the 15% entry cap and
# lets a redeploy buy through to its own target (20% here): the redeploy is
# bounded by the target already, and cutting it to 15% on the way out
# would reopen the reset's leak it exists to close.
def test_bound_orders_do_not_cap_a_redeploy_at_the_entry_cap():
    prices = {"AAA": 100.0, "BBB": 100.0}
    held = {"AAA": 100.0, "BBB": 100.0}
    entry = paper.PaperOrder("AAA", "buy", 100, "price entry")
    redeploy = paper.PaperOrder(
        "BBB", "buy", 100, "redeploy", kind=paper.REDEPLOY_KIND
    )
    bounded = paper.bound_orders(
        [entry, redeploy], held, prices, 100_000.0, 50_000.0
    )
    assert {o.symbol: o.qty for o in bounded} == {"AAA": 50, "BBB": 100}


# A redeploy order's kind travels through settlement into the journal, so
# the record's settled rows and the fills history can name the leg.
def test_a_redeploy_carries_its_kind_through_settlement():
    pending = [
        {
            "client_order_id": "anios-2026-09-08-buy-aaa-0", "symbol": "AAA",
            "side": "buy", "qty": 10, "session": "2026-09-08",
            "reason": "redeploy: cash beyond the buffer put back to its target weights",
            "kind": paper.REDEPLOY_KIND, "execution": {},
        },
        {
            "client_order_id": "anios-2026-09-08-buy-bbb-1", "symbol": "BBB",
            "side": "buy", "qty": 5, "session": "2026-09-08",
            "reason": "price entry", "execution": {},
        },
    ]
    broker = [
        {"client_order_id": "anios-2026-09-08-buy-aaa-0", "status": "filled",
         "filled_qty": 10, "filled_avg_price": 101.0},
        {"client_order_id": "anios-2026-09-08-buy-bbb-1", "status": "filled",
         "filled_qty": 5, "filled_avg_price": 50.0},
    ]
    settled = paper.settle(pending, broker)
    assert [s.kind for s in settled] == [paper.REDEPLOY_KIND, None]
    state = paper.apply_settlements(paper.PaperState(pending=pending), settled)
    assert {row["symbol"]: row.get("kind") for row in state.journal} == {
        "AAA": paper.REDEPLOY_KIND, "BBB": None,
    }


# A state file from before the redeploy existed loads with no reset targets
# on record (None, not an empty dict, so the planner can tell "unknown" from
# "the reset wanted nothing"), and the field round-trips through the file.
def test_state_files_without_rebalance_targets_still_load(tmp_path):
    from dataclasses import asdict

    path = paper.state_path(tmp_path)
    path.parent.mkdir(parents=True)
    old = {
        k: v for k, v in asdict(paper.PaperState()).items() if k != "rebalance_targets"
    }
    old["last_rebalance"] = "2026-09-04"
    path.write_text(json.dumps(old), encoding="utf-8")
    loaded = paper.load_state(tmp_path)
    assert loaded.rebalance_targets is None
    loaded.rebalance_targets = {"SNDK": 0.2}
    paper.save_state(tmp_path, loaded)
    assert paper.load_state(tmp_path).rebalance_targets == {"SNDK": 0.2}


# The rule is on, its buffer is the simulator's, and the execution policy
# version says so: /6 keeps /5 (the redeploy, the reset sizing) and spends
# the redeploy's whole-share rounding remainder.
def test_the_redeploy_is_on_and_the_execution_policy_is_v6():
    from backend.agents.trading.desk import simulate

    assert paper.REDEPLOY_IDLE_CASH is True
    assert paper.REDEPLOY_BUFFER == simulate.REDEPLOY_BUFFER == 0.02
    assert paper.POLICY_VERSION == "cash-bounded-breakout-rotation/6"
