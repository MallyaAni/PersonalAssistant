"""Candidate behavior through the real dispatcher and persisted paper state.

All budgets below are synthetic fixture inputs, not proposed trading thresholds.
The broker is a recording transport; no account or market-data request is made.
"""

import json
from copy import deepcopy
from datetime import UTC, date, timedelta
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import alpaca_trading, entry_timing
from backend.market import bounded_execution as bounded
from backend.tests.test_intraday_orders import (
    TODAY,
    Broker,
    latch,
    ny,
    quote,
    row,
    save,
)


# Supply explicit fixture budgets without changing the active policy or allocator.
def candidate(side="buy", intent=None, **changes):
    order = row(side=side)
    options = dict(
        limit_price=99.10 if side == "buy" else 89.50,
        decision_at=ny(18, day=TODAY - timedelta(days=1)).isoformat(),
        expires_at=ny(15, 50).isoformat(),
        quote_source="fixture-nbbo",
        max_quote_age_seconds=10,
        max_trigger_age_seconds=120,
        max_spread_bps=25,
        intent=intent or ("entry" if side == "buy" else "exit"),
    )
    options.update(changes)
    return bounded.bind(order, **options)


# Add timestamped raw-basis bid/ask evidence separately from the historical candle.
def snapshot(now=None, bid=98.90, ask=99.00, **changes):
    now = now or ny(10, 16)
    executable = dict(
        symbol="AAA",
        bid=bid,
        ask=ask,
        bid_size=20,
        ask_size=20,
        timestamp=(now - timedelta(seconds=1)).isoformat(),
        received_at=now.isoformat(),
        source="fixture-nbbo",
        price_basis="raw",
    )
    executable.update(changes)
    bar = quote(98.90, now.replace(minute=0))
    bar["execution_quote"] = executable
    return {"quotes": {"AAA": bar}}


# Reuse a provider-shaped quote packet across adapter and integration cases.
def provider_packet(now=None, feed="iex"):
    raw = snapshot(now)["quotes"]["AAA"]["execution_quote"]
    return {
        "feed": feed,
        "market_open": True,
        "fetched_at": raw["received_at"],
        "quotes": {
            "AAA": {
                "bp": raw["bid"],
                "ap": raw["ask"],
                "bs": raw["bid_size"],
                "as": raw["ask_size"],
                "t": raw["timestamp"],
            }
        },
    }


# Record IOC requests while leaving broker funds unchanged to stress reservations.
class LimitBroker(Broker):
    # Initialize a recording broker with explicit available cash and buying power.
    def __init__(self, cash=1000, **kwargs):
        super().__init__(**kwargs)
        self.cash = cash

    # Return actual fixture funds without fabricating pending sale proceeds.
    def account(self):
        return SimpleNamespace(cash=self.cash, buying_power=self.cash)

    # Record a limit attempt as accepted, never as filled.
    def submit_limit_ioc(self, symbol, qty, side, price, cid):
        response = self._take(bounded.LIMIT_IOC, symbol, qty, side, cid)
        return {
            **response,
            "time_in_force": "ioc",
            "status": "new",
            "limit_price": price,
        }


# Read the board's actual projection for the same persisted order and snapshot.
def view(order, root, snap, now=None, broker=None):
    now = now or ny(10, 16)
    return intraday_orders.board_row(
        order,
        broker=broker,
        latch=entry_timing.load(root, TODAY),
        quote=snap["quotes"]["AAA"],
        held=15,
        price=99,
        equity=1000,
        now=now,
    )


# Reproduce a recovered dip that the incumbent still allows after a sharp rebound.
def test_latched_dip_does_not_authorize_chasing(tmp_path):
    trigger = {
        "bar": ny(10).isoformat(),
        "price": 98.5,
        "seen_at": ny(10, 15).isoformat(),
    }
    latch(tmp_path, buy=trigger)
    snap = snapshot(bid=109.90, ask=110)
    old = intraday_orders.decide(
        row(),
        {"open": 100, "buy_trigger": trigger},
        snap["quotes"]["AAA"],
        ny(10, 16),
        TODAY,
    )
    assert old["send"] == intraday_orders.MARKET
    order = candidate()
    save(tmp_path, order)
    before = entry_timing.load(tmp_path, TODAY)
    broker = LimitBroker()
    assert intraday_orders.send_due(tmp_path, snap, ny(10, 16), lambda: broker) == []
    assert broker.sent == []
    projected = view(order, tmp_path, snap)
    assert projected["state"] == "waiting"
    assert projected["execution_guard"]["state"] == "price_blocked"
    assert entry_timing.load(tmp_path, TODAY) == before
    kept = paper.load_state(tmp_path).pending[0]["execution"]
    assert kept["bounded_observations"][0]["guard"]["state"] == "price_blocked"


# Give exits explicit urgency without making routine trims abandon their trigger.
def test_exit_bypasses_bounce_but_preserves_price_floor():
    now = ny(14)
    bar = snapshot(now, bid=90, ask=90.10)["quotes"]["AAA"]
    bar["last"] = 90
    old = intraday_orders.decide(row(side="sell"), {"open": 100}, bar, now, TODAY)
    assert old["send"] is None
    urgent = intraday_orders.decide(candidate("sell"), {"open": 100}, bar, now, TODAY)
    trim = intraday_orders.decide(
        candidate("sell", "trim"), {"open": 100}, bar, now, TODAY
    )
    assert urgent["send"] == bounded.LIMIT_IOC
    assert trim["send"] is None
    bar["execution_quote"].update(bid=89, ask=89.1)
    assert (
        intraday_orders.decide(candidate("sell"), {"open": 100}, bar, now, TODAY)[
            "guard"
        ]["state"]
        == "price_blocked"
    )


# Reject candle-only, wrong-source, stale and unusable quote inputs before submission.
@pytest.mark.parametrize(
    "change",
    [
        {"source": "other"},
        {"symbol": "BBB"},
        {"price_basis": "adjusted"},
        {"timestamp": ny(10, 15).isoformat()},
        {"timestamp": ny(10, 17).isoformat()},
        {"received_at": ny(10, 17).isoformat()},
        {"received_at": "2026-09-30T10:16:00"},
        {"bid": 101},
        {"ask": float("nan")},
        {"bid_size": 0},
        {"ask_size": True},
        {"bid": 95},
    ],
)
def test_invalid_executable_quotes_cannot_become_orders(change):
    bar = snapshot(**change)["quotes"]["AAA"]
    verdict = intraday_orders.decide(candidate(), {"open": 100}, bar, ny(10, 16), TODAY)
    assert verdict["send"] is None
    assert verdict["guard"]["state"] == "quote_unavailable"


# Fail closed when only a candle is available, even in the close fallback window.
def test_close_never_substitutes_market_or_candle_for_executable_quote():
    now = ny(15, 35)
    bar = quote(100, ny(15, 15))
    verdict = intraday_orders.decide(candidate(), {"open": 100}, bar, now, TODAY)
    assert verdict["send"] is None
    assert verdict["guard"]["state"] == "quote_unavailable"


# Permit the closing fallback only as a fresh bounded IOC attempt.
def test_close_fallback_remains_bounded():
    now = ny(15, 35)
    bar = snapshot(now)["quotes"]["AAA"]
    bar["last"] = 100
    verdict = intraday_orders.decide(candidate(), {"open": 100}, bar, now, TODAY)
    assert verdict["send"] == bounded.LIMIT_IOC
    assert verdict["guard"]["limit_price"] == "99.10"


# Keep an expired trigger historical even when a fresh quote is within the bound.
def test_old_trigger_requires_new_permission_not_silent_renewal():
    now = ny(14)
    trigger = {
        "bar": ny(9, 30).isoformat(),
        "price": 98.5,
        "seen_at": ny(9, 45).isoformat(),
    }
    verdict = intraday_orders.decide(
        candidate(),
        {"open": 100, "buy_trigger": trigger},
        snapshot(now)["quotes"]["AAA"],
        now,
        TODAY,
    )
    assert verdict["send"] is None
    assert verdict["guard"]["state"] == "signal_expired"


# Enforce expiry at the boundary, even if the old rule would send a market order.
def test_permission_expires_without_close_fallback():
    now = ny(15, 50)
    verdict = intraday_orders.decide(
        candidate(), {"open": 100}, snapshot(now)["quotes"]["AAA"], now, TODAY
    )
    assert verdict["send"] is None
    assert verdict["guard"]["state"] == "expired"


# Honor the reviewed early-close clock rather than assuming a four o'clock close.
def test_early_close_permission_cannot_queue_next_session():
    day = date(2026, 11, 27)
    order = candidate("sell")
    order["execute_on"] = order["execution_policy"]["session"] = day.isoformat()
    order["execution_policy"]["expires_at"] = ny(13, day=day).isoformat()
    now = ny(13, day=day)
    verdict = intraday_orders.decide(
        order, {"open": 100}, snapshot(now)["quotes"]["AAA"], now, day
    )
    assert verdict["send"] is None
    assert verdict["guard"]["state"] == "expired"


# Never interpret an invalid or mutated candidate contract as the incumbent policy.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "unknown"),
        ("qty", True),
        ("limit_price", -1),
        ("max_quote_age_seconds", float("inf")),
        ("intent", "guess"),
        ("decision_at", "naive"),
        ("session", "2026-10-02"),
    ],
)
def test_contract_errors_block_instead_of_falling_back(field, value):
    order = candidate()
    order["execution_policy"][field] = value
    verdict = intraday_orders.decide(
        order, {"open": 100}, snapshot()["quotes"]["AAA"], ny(10, 16), TODAY
    )
    assert verdict["send"] is None
    assert verdict["guard"]["state"] == "invalid_contract"


# Size an actual IOC attempt using cash at its maximum possible execution price.
def test_cash_sizing_and_board_submission_state_persist(tmp_path):
    order = candidate()
    save(tmp_path, order)
    broker = LimitBroker(cash=198.15)
    snap = snapshot()
    intraday_orders.send_due(tmp_path, snap, ny(10, 16), lambda: broker)
    assert broker.sent[0][3] == 1
    kept = paper.load_state(tmp_path).pending[0]
    assert kept["sent"]["qty"] == 1
    assert kept["execution"]["bounded_attempt"]["limit_price"] == "99.10"
    projected = view(kept, tmp_path, snap)
    assert projected["state"] == "sent"
    assert projected["filled_qty"] is None
    assert "IOC limit" in projected["status"]
    intraday_orders.send_due(tmp_path, snap, ny(10, 16), lambda: broker)
    assert len(broker.sent) == 1


# Reserve earlier IOC attempts even if broker cash has not updated in the batch.
def test_batch_cannot_spend_the_same_cash_twice(tmp_path):
    first, second = candidate(), candidate()
    second["client_order_id"] = second["execution_policy"]["client_order_id"] = (
        "anios-second"
    )
    save(tmp_path, first, second)
    broker = LimitBroker(cash=1000)
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    assert len(broker.sent) == 1
    assert "no funded quantity" in paper.load_state(tmp_path).pending[1]["send_error"]


# Reserve legacy attempts too when a bounded buy follows them in the same batch.
@pytest.mark.parametrize("lost_response", [False, True])
def test_mixed_batch_cannot_reuse_cash_for_legacy_market_buy(tmp_path, lost_response):
    legacy, bounded_buy = row(), candidate()
    bounded_buy["client_order_id"] = bounded_buy["execution_policy"][
        "client_order_id"
    ] = "anios-bounded-second"
    save(tmp_path, legacy, bounded_buy)
    broker = LimitBroker(cash=1000)

    # Margin buying power cannot replace actual cash or a known reservation.
    def account():
        return SimpleNamespace(cash=1000, buying_power=2000)

    broker.account = account
    original = broker.submit_market

    # An accepted request can lose its response without proving that it was refused.
    def submit_market(*args):
        result = original(*args)
        if lost_response:
            raise alpaca_trading.AlpacaTradingError("Response unavailable")
        return result

    broker.submit_market = submit_market
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    assert len(broker.sent) == 1
    assert broker.sent[0][0] == intraday_orders.MARKET
    assert (
        "Working buy reservation is unknown"
        in paper.load_state(tmp_path).pending[1]["send_error"]
    )


# Refuse unknown reservations and unusable funds rather than inventing cash.
@pytest.mark.parametrize(
    ("cash", "existing"),
    [
        (float("nan"), []),
        (
            1000,
            [{"client_order_id": "manual", "side": "buy", "qty": "2", "status": "new"}],
        ),
    ],
)
def test_unknown_funding_blocks_submission(tmp_path, cash, existing):
    save(tmp_path, candidate())
    broker = LimitBroker(cash=cash, existing=existing)
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    assert broker.sent == []
    assert "Cash unavailable" in paper.load_state(tmp_path).pending[0]["send_error"]


# Bound the total sold across same-symbol rows to actual long shares.
def test_sell_attempts_reserve_shares_without_funding_buys(tmp_path):
    first, second, buy = candidate("sell"), candidate("sell"), candidate()
    second["client_order_id"] = second["execution_policy"]["client_order_id"] = (
        "anios-second-sell"
    )
    save(tmp_path, first, second, buy)
    broker = LimitBroker(cash=0, held={"AAA": 15})
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    assert [request[3] for request in broker.sent] == [10, 5]
    assert all(request[1] == "sell" for request in broker.sent)


# Recover a broker-accepted request after expiry without placing a replacement.
def test_crash_recovery_precedes_expired_permission(tmp_path):
    order = candidate(expires_at=ny(10, 16).isoformat())
    order["sending"] = ny(10, 15).isoformat()
    save(tmp_path, order)
    accepted = {
        "client_order_id": order["client_order_id"],
        "symbol": "AAA",
        "type": "limit",
        "time_in_force": "ioc",
        "limit_price": "99.10",
        "submitted_at": ny(10, 15).isoformat(),
        "status": "new",
        "side": "buy",
        "qty": "10",
    }
    broker = LimitBroker(existing=[accepted], is_open=False)
    intraday_orders.send_due(tmp_path, {}, ny(10, 17), lambda: broker)
    assert broker.sent == []
    assert paper.load_state(tmp_path).pending[0]["sent"]["adopted"] is True


# Preserve the original opportunity and actual partial fill through settlement.
def test_partial_settlement_preserves_permission_and_unfilled_quantity(tmp_path):
    order = candidate()
    save(tmp_path, order)
    broker = LimitBroker()
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    state = paper.load_state(tmp_path)
    settled = paper.Settled(
        client_order_id=order["client_order_id"],
        symbol="AAA",
        side="buy",
        qty=10,
        session=TODAY.isoformat(),
        status="partial",
        filled_qty=2,
        filled_price=99,
        terminal=True,
    )
    paper.save_state(tmp_path, paper.apply_settlements(state, [settled]))
    kept = paper.load_state(tmp_path)
    assert kept.pending == []
    assert kept.journal[0]["qty"] == 10
    assert kept.journal[0]["filled_qty"] == 2
    assert kept.journal[0]["execution_policy"] == order["execution_policy"]
    assert len(kept.journal[0]["execution"]["bounded_observations"]) == 1


# Confirm the transport never becomes a market, resting or extended-hours order.
@pytest.mark.parametrize(
    ("side", "price", "expected"),
    [
        ("buy", 99.109, "99.10"),
        ("sell", 99.101, "99.11"),
        ("buy", 0.12349, "0.1234"),
        ("sell", 0.12341, "0.1235"),
    ],
)
def test_limit_transport_rounds_inward_and_never_relaxes_bound(side, price, expected):
    captured = []

    # Capture the real client's JSON instead of contacting an account.
    def transport(method, url, headers, body):
        captured.append(json.loads(body))
        return 200, b'{"status":"accepted"}'

    client = alpaca_trading.AlpacaTradingClient(
        "fixture", "fixture", transport=transport
    )
    client.submit_limit_ioc("AAA", 2, side, price, "anios-fixture")
    assert captured == [
        {
            "symbol": "AAA",
            "qty": "2",
            "side": side,
            "type": "limit",
            "limit_price": expected,
            "time_in_force": "ioc",
            "extended_hours": False,
            "client_order_id": "anios-fixture",
        }
    ]


# Reject a real-money endpoint before any request can leave the client.
def test_candidate_transport_refuses_nonpaper_endpoint():
    # Any attempted network call makes this acceptance case fail.
    def transport(*args):
        pytest.fail("No request may reach this endpoint")

    client = alpaca_trading.AlpacaTradingClient(
        "fixture",
        "fixture",
        base_url="https://api.alpaca.markets/v2",
        transport=transport,
    )
    with pytest.raises(alpaca_trading.AlpacaTradingError, match="paper-only"):
        client.submit_limit_ioc("AAA", 2, "buy", 99, "anios-fixture")


# Binding cannot mutate the input row or silently accept missing permission budgets.
def test_binding_is_explicit_and_preserves_original_order():
    original = row()
    copy = deepcopy(original)
    assert candidate()["execution_policy"]["version"] == bounded.VERSION
    assert original == copy
    assert "execution_policy" not in original
    with pytest.raises(ValueError, match="budgets required"):
        candidate(max_spread_bps=0)


# Recheck quote freshness after slow account reads before approving a submission.
def test_submission_rechecks_elapsed_time_after_funding(tmp_path, monkeypatch):
    save(tmp_path, candidate())
    broker = LimitBroker()
    clock = {"elapsed": 0.0}

    # Delay the account response without sleeping or contacting a service.
    def account():
        clock["elapsed"] = 20.0
        return SimpleNamespace(cash=1000, buying_power=1000)

    monkeypatch.setattr(broker, "account", account)
    monkeypatch.setattr(intraday_orders.time, "monotonic", lambda: clock["elapsed"])
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    assert broker.sent == []
    kept = paper.load_state(tmp_path).pending[0]
    assert kept["execution"]["bounded_attempt"]["state"] == "quote_unavailable"
    assert "sending" not in kept


# Include older working sells when allocating the position's remaining shares.
def test_existing_sell_reservation_cannot_be_sold_again(tmp_path):
    save(tmp_path, candidate("sell"))
    existing = [
        {
            "client_order_id": "manual",
            "symbol": "AAA",
            "side": "sell",
            "qty": "12",
            "filled_qty": "2",
            "status": "new",
        }
    ]
    broker = LimitBroker(held={"AAA": 15}, existing=existing)
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    assert broker.sent[0][3] == 5


# Preserve blocked opportunities without counting repeated observations as new signals.
def test_blocked_observation_is_deduplicated_without_claiming_a_fill(tmp_path):
    save(tmp_path, candidate())
    snap = snapshot(bid=109.90, ask=110)

    # No broker needs to be constructed for an ineligible price.
    def factory():
        pytest.fail("Blocked orders do not need a broker")

    intraday_orders.send_due(tmp_path, snap, ny(10, 16), factory)
    intraday_orders.send_due(tmp_path, snap, ny(10, 17), factory)
    intraday_orders.send_due(tmp_path, snap, ny(10, 17).astimezone(UTC), factory)
    kept = paper.load_state(tmp_path)
    assert len(kept.pending[0]["execution"]["bounded_observations"]) == 1
    assert kept.journal == []
    assert "sent" not in kept.pending[0]


# A malformed opt-in field must not activate the incumbent's market fallback.
def test_empty_contract_never_falls_back_to_legacy_market_order():
    order = row(execution_policy=None)
    verdict = intraday_orders.decide(
        order, {"open": 100}, snapshot()["quotes"]["AAA"], ny(10, 16), TODAY
    )
    assert verdict["send"] is None
    assert verdict["guard"]["state"] == "invalid_contract"


# A colliding client id must not turn a different broker order into a confirmed attempt.
def test_crash_recovery_rejects_a_conflicting_order(tmp_path):
    order = candidate(expires_at=ny(10, 16).isoformat())
    order["sending"] = ny(10, 15).isoformat()
    save(tmp_path, order)
    existing = [
        {
            "client_order_id": order["client_order_id"],
            "symbol": "AAA",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": "10",
        }
    ]
    broker = LimitBroker(existing=existing)
    intraday_orders.send_due(tmp_path, {}, ny(10, 17), lambda: broker)
    assert broker.sent == []
    kept = paper.load_state(tmp_path).pending[0]
    assert "sent" not in kept
    assert "does not confirm" in kept["send_error"]


# Unknown submission outcomes retain their cash reservation until read back.
def test_submission_failure_cannot_release_funding_inside_batch(tmp_path):
    first, second = candidate(), candidate()
    second["client_order_id"] = second["execution_policy"]["client_order_id"] = (
        "anios-second"
    )
    save(tmp_path, first, second)
    broker = LimitBroker(cash=1000, refuse="unknown server response")
    intraday_orders.send_due(tmp_path, snapshot(), ny(10, 16), lambda: broker)
    kept = paper.load_state(tmp_path).pending
    assert "sending" in kept[0]
    assert "sending" not in kept[1]
    assert "no funded quantity" in kept[1]["send_error"]


# Adapt existing provider packets without relabeling a single venue as consolidated.
def test_existing_quote_adapter_preserves_provenance_and_original_snapshot():
    snap = snapshot()
    original = deepcopy(snap)
    evidence = provider_packet()
    enriched = bounded.with_quotes(snap, evidence)
    assert snap == original
    executable = enriched["quotes"]["AAA"]["execution_quote"]
    assert executable["source"] == "iex"
    assert executable["timestamp"] == evidence["quotes"]["AAA"]["t"]
    assert executable["received_at"] == evidence["fetched_at"]
    assert executable["price_basis"] == "raw"


# Use the existing bid/ask reader lazily for a valid candidate lacking quote evidence.
def test_dispatcher_reuses_existing_quote_reader(tmp_path):
    save(tmp_path, candidate(quote_source="iex"))
    snap = snapshot()
    del snap["quotes"]["AAA"]["execution_quote"]
    calls = []

    # Return a timestamped provider packet without credentials or a network call.
    def reader(symbols):
        calls.append(symbols)
        return provider_packet()

    broker = LimitBroker()
    intraday_orders.send_due(
        tmp_path, snap, ny(10, 16), lambda: broker, quote_reader=reader
    )
    assert calls == [["AAA"]]
    assert broker.sent[0][0] == bounded.LIMIT_IOC
    assert (
        paper.load_state(tmp_path).pending[0]["execution"]["bounded_attempt"]["quote"][
            "source"
        ]
        == "iex"
    )


# Refuse a feed downgrade rather than borrowing another feed's execution permission.
def test_source_change_cannot_silently_qualify_candidate(tmp_path):
    save(tmp_path, candidate(quote_source="sip"))
    snap = snapshot()
    del snap["quotes"]["AAA"]["execution_quote"]

    # Simulate the reader's disclosed fallback to a single-venue quote.
    def reader(symbols):
        return provider_packet()

    broker = LimitBroker()
    intraday_orders.send_due(
        tmp_path, snap, ny(10, 16), lambda: broker, quote_reader=reader
    )
    assert broker.sent == []
    assert (
        paper.load_state(tmp_path).pending[0]["execution"]["bounded_observations"][0][
            "guard"
        ]["state"]
        == "quote_unavailable"
    )


# Keep the incumbent's data requests and execution behavior unchanged.
def test_legacy_dispatcher_never_requests_candidate_quotes(tmp_path):
    save(tmp_path, row())
    snap = snapshot()
    del snap["quotes"]["AAA"]["execution_quote"]

    # Fail if an adopted-policy order requests a new bid/ask collection.
    def reader(symbols):
        pytest.fail("Legacy orders do not request candidate quotes")

    broker = Broker()
    intraday_orders.send_due(
        tmp_path, snap, ny(10, 16), lambda: broker, quote_reader=reader
    )
    assert broker.sent[0][0] == intraday_orders.MARKET


# Exercise the API's real paper-plan projection with the same qualified evidence.
def test_api_paper_plan_uses_candidate_guard_without_changing_strategy(
    tmp_path, monkeypatch
):
    from backend.api.v1 import market
    from backend.market import execution_quotes

    class FixedTime:
        # Keep the handler's observation clock at the declared fixture session.
        @staticmethod
        def now(tz):
            return ny(10, 16).astimezone(tz)

    order = candidate(quote_source="iex")
    save(tmp_path, order)
    snap = snapshot()
    del snap["quotes"]["AAA"]["execution_quote"]
    monkeypatch.setattr(market, "datetime", FixedTime)
    monkeypatch.setattr(market, "_root", lambda: tmp_path)
    monkeypatch.setattr(market, "_live_snapshot", lambda: snap)
    monkeypatch.setattr(execution_quotes, "fetch", lambda symbols: provider_packet())
    broker = LimitBroker()
    plan = market._paper_plan(broker, paper.load_state(tmp_path), [], 1000)
    projected = plan["orders"][0]
    assert projected["execution_guard"]["state"] == "due"
    assert projected["execution_guard"]["quote"]["source"] == "iex"
    assert projected["execution_policy"]["version"] == bounded.VERSION
    assert plan["rule"] == intraday_orders.INTRADAY_TIMING
    assert broker.sent == []
    assert "sent" not in paper.load_state(tmp_path).pending[0]


# A malformed candidate must still have a serializable, non-actionable board result.
def test_invalid_contract_projection_never_publishes_nonfinite_budget(tmp_path):
    order = candidate()
    order["execution_policy"]["max_quote_age_seconds"] = float("inf")
    projected = view(order, tmp_path, snapshot())
    assert projected["state"] == "waiting"
    json.dumps(projected, allow_nan=False)
