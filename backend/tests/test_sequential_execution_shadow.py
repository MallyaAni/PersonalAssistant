"""Causal source parity and actual-intent isolation for the fixed-model bridge."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import live_policy, paper
from backend.market import alpaca_trading, calendar, learned_entry_data
from backend.market import sequential_execution_shadow as shadow
from backend.market.sip_cube import SessionCube


# Supply past daily context plus a source cube whose future rows must remain unused.
def case(session="2026-10-05"):
    session = np.datetime64(session, "D")
    dates = np.busday_offset(session, np.arange(-300, 2)).astype("datetime64[D]")
    names = ("ONE", "SPY", "QQQ")
    panel = SimpleNamespace(
        dates=dates, tickers=names, adj_close=np.full((len(dates), 3), 10.0)
    )
    grades = np.full(panel.adj_close.shape, 3)
    eligible = np.ones(panel.adj_close.shape, dtype=bool)
    bars = {name: np.full((2, 26), 10.0) for name in ("open", "high", "low", "close")}
    bars["volume"] = np.full((2, 26), 100.0)
    cube = SessionCube(
        "ONE",
        dates[-2:].copy(),
        **bars,
        prior_close=np.full(2, 10.0),
        auction_open=np.full(2, 10.0),
        auction_volume=np.full(2, 100.0),
        excluded={},
    )
    return panel, grades, eligible, cube


# Give each required evidence source its own known publication clock.
def observation(args, clock=0, feed="sip", **options):
    session = str(args[3].dates[0])
    received = datetime.fromisoformat(f"{session}T09:45:01").replace(
        tzinfo=calendar.NEW_YORK
    ) + timedelta(minutes=15 * clock)
    published = {
        name: received - timedelta(hours=16)
        for name in ("history", "grades", "membership")
    }
    return shadow.observe(
        *args,
        clock,
        options.pop("received_at", received),
        published_at=options.pop("published_at", published),
        feed=feed,
        **options,
    )


# Reproduce a numeric head without estimator fitting or any future execution input.
def model(mean=0.001):
    head = {
        "imputer": np.zeros(21),
        "indicators": np.array([], dtype=np.int64),
        "center": np.zeros(21),
        "scale": np.ones(21),
        "coef": np.zeros(21),
        "intercept": np.array(mean),
    }
    return shadow.FrozenModel(
        {f"{clock}_{side}": head for clock in range(24) for side in range(2)},
        "2026-08-14",
        shadow.MANIFEST_SHA,
        "fixture",
    )


# Compare the exact21 features with the unchanged historical preparation.
@pytest.mark.parametrize("clock", [0, 7, 23, 24])
def test_prefix_matches_original_preparation(clock):
    args = case()
    original = learned_entry_data.prepare(*args[:3], {"ONE": args[3]})
    packet = observation(args, clock)
    np.testing.assert_array_equal(packet.features, original["X"][-2, clock, 0])
    assert packet.valid == original["valid"][-2, clock, 0]
    assert packet.raw_price == 10
    assert packet.supported


# Change every future price and label-bearing candle without changing this decision.
def test_future_daily_prices_bars_and_grades_do_not_change_features_or_decision():
    args = case()
    before = observation(args, 7)
    args[0].adj_close[-2:] = 123456
    args[1][-1] = -999
    args[2][-1] = False
    for name in ("open", "high", "low", "close", "volume"):
        values = getattr(args[3], name)
        values[0, 8:] = np.nan
        values[1] = -999
    after = observation(args, 7)
    np.testing.assert_array_equal(after.features, before.features)
    assert shadow.decide(after, model(), "buy") == shadow.decide(before, model(), "buy")


# Missing prior prefixes block learned inference but not an observed terminal deadline.
def test_missing_prefix_is_unavailable_and_terminal_has_no_forecast_requirement():
    args = case()
    args[3].volume[0, 2] = np.nan
    ordinary = observation(args, 7)
    final = observation(args, 24)
    assert not ordinary.valid
    assert shadow.decide(ordinary, model(), "buy")["state"] == "unavailable"
    assert shadow.decide(final, replace(model(), heads={}), "buy")["state"] == (
        "terminal_attempt"
    )
    args[3].close[0, 24] = np.nan
    assert shadow.decide(observation(args, 24), model(), "buy")["state"] == (
        "unavailable"
    )


# Keep early-close sessions explicitly unsupported instead of remapping trained clocks.
def test_early_close_is_unsupported_and_cannot_attempt():
    packet = observation(case("2026-11-27"), 13)
    assert not packet.supported
    assert shadow.decide(packet, model(), "buy")["state"] == "unavailable"


# Disclose frozen-month age and feed differences while keeping both sides' sign rules.
def test_signs_feed_and_frozen_month_are_explicit():
    packet = observation(case(), feed="iex")
    assert shadow.decide(packet, model(), "buy")["state"] == "wait"
    result = shadow.decide(packet, model(), "sell")
    assert result["state"] == "execute"
    assert result["frozen_model_carry_forward"]
    assert not result["feed_domain_matches_training"]
    assert result["order_submission"] is False
    assert shadow.decide(packet, model(0), "buy")["state"] == "execute"
    assert shadow.decide(packet, model(np.nan), "buy")["state"] == "unavailable"


# Reject absent evidence roles, future publication and stale/forming source receipts.
@pytest.mark.parametrize(
    "kind", ["missing_role", "future", "forming", "stale", "naive"]
)
def test_publication_and_source_clock_boundaries(kind):
    args = case()
    received = datetime(2026, 10, 5, 9, 45, tzinfo=calendar.NEW_YORK)
    published = {name: received for name in ("history", "grades", "membership")}
    if kind == "missing_role":
        del published["grades"]
    elif kind == "future":
        published["grades"] += timedelta(seconds=1)
    elif kind == "forming":
        received -= timedelta(seconds=1)
    elif kind == "stale":
        received += timedelta(minutes=15)
    elif kind == "naive":
        received = received.replace(tzinfo=None)
    with pytest.raises(ValueError, match="publication|published|Receipt|Timezone"):
        shadow.observe(*args, 0, received, published_at=published, feed="sip")


# Build a real broker client whose transport permits only account/position/order GETs.
def broker(root, *, mutate=None, cash=0, opened=(), qty=10):
    calls = []

    # Use the production broker parser and fail immediately on any non-GET method.
    def transport(method, url, headers, body):
        assert method == "GET"
        assert body is None
        calls.append(url)
        if mutate:
            mutate(len(calls))
        if url.endswith("/account"):
            row = {"cash": str(cash), "equity": "100", "buying_power": "100"}
        elif url.endswith("/positions"):
            row = [
                {
                    "symbol": "ONE",
                    "qty": str(qty),
                    "market_value": "100",
                    "avg_entry_price": "10",
                    "current_price": "10",
                    "unrealized_pl": "0",
                }
            ]
        else:
            row = list(opened)
        return 200, json.dumps(row).encode()

    client = alpaca_trading.AlpacaTradingClient(
        "fixture", "fixture", transport=transport
    )
    return client, calls


# Persist original production-shaped intents only in an isolated temporary market root.
def state(root, extra=()):
    rows = [
        {
            "client_order_id": "sell",
            "symbol": "ONE",
            "side": "sell",
            "qty": 20,
            "execute_on": "2026-10-05",
            "execution_timing": "dip_or_close",
            "reason": "original sell",
            "execution": {"reference_price": 11},
        },
        {
            "client_order_id": "buy",
            "symbol": "ONE",
            "side": "buy",
            "qty": 20,
            "execute_on": "2026-10-05",
            "execution_timing": "dip_or_close",
            "reason": "original buy",
            "execution": {"reference_price": 9},
        },
        *extra,
    ]
    path = paper.state_path(root)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"policy_version": live_policy.ACTIVE, "pending": rows}))
    return path


# Freeze every original identity and reference with no source-file or broker writes.
def test_actual_intents_are_read_only_and_sales_cannot_fabricate_funding(tmp_path):
    path = state(tmp_path)
    before = path.read_bytes()
    client, calls = broker(tmp_path)
    received = datetime(2026, 10, 5, 9, 44, tzinfo=calendar.NEW_YORK)
    snapshot = shadow.freeze_intents(
        tmp_path, client, "2026-10-05", clock=lambda: received
    )
    packet = observation(case())
    results = shadow.inspect_intents(snapshot, {"ONE": packet}, model(-0.001))
    assert len(calls) == 6
    assert path.read_bytes() == before
    assert snapshot["orders"] == json.loads(before)["pending"]
    assert all(not row["order_submission"] for row in results)
    assert all(not row["actual_fill"] for row in results)
    assert results[1]["state"] == "unfunded_or_uncovered"
    assert results[1]["conditional_whole_share_capacity_at_observed_price"] == 0
    assert results[1]["original_order"]["qty"] == 20
    assert results[1]["current_gate_state"] == "wait"
    assert results[1]["first_available_state"] == "execute"
    terminal = observation(case(), 24)
    results = shadow.inspect_intents(snapshot, {"ONE": terminal}, model())
    assert results[0]["conditional_whole_share_capacity_at_observed_price"] == 10
    assert results[1]["conditional_whole_share_capacity_at_observed_price"] == 0
    locked = shadow.inspect_intents(
        snapshot, {"ONE": terminal}, model(), attempted_ids=("sell", "buy")
    )
    assert all(row["state"] == "previously_attempted" for row in locked)


# Surface excluded sent, event and differently timed orders instead of dropping them.
def test_every_excluded_intent_is_disclosed_and_working_orders_block_snapshot(tmp_path):
    extras = [
        {"client_order_id": "sent", "sent": {"at": "known"}},
        {"client_order_id": "sending", "sending": "known"},
        {"client_order_id": "event", "event_id": "event"},
        {"client_order_id": "different", "execution_timing": "next_open"},
    ]
    state(tmp_path, extras)
    received = datetime(2026, 10, 5, 9, 44, tzinfo=calendar.NEW_YORK)
    client, _ = broker(tmp_path)
    result = shadow.freeze_intents(
        tmp_path, client, "2026-10-05", clock=lambda: received
    )
    assert len(result["orders"]) == 2
    assert len(result["excluded"]) == 4
    client, _ = broker(tmp_path, opened=[{"id": "working"}])
    result = shadow.freeze_intents(
        tmp_path, client, "2026-10-05", clock=lambda: received
    )
    assert result["status"] == "no_eligible_intents"
    assert len(result["excluded"]) == 6


# Abort at the first changed source boundary rather than freeze a mixed-version book.
def test_concurrent_state_changes_are_rejected_without_overwriting_them(tmp_path):
    path = state(tmp_path)

    # Reproduce a simultaneous live writer while account GETs are in flight.
    def mutate(count):
        if count == 2:
            path.write_text("{}")

    client, _ = broker(tmp_path, mutate=mutate)
    with pytest.raises(ValueError, match="Concurrent"):
        shadow.freeze_intents(
            tmp_path,
            client,
            "2026-10-05",
            clock=lambda: datetime(2026, 10, 5, 9, 44, tzinfo=calendar.NEW_YORK),
        )
    assert path.read_text() == "{}"


# Unknown actual observations never fabricate prices, fills or executable capacity.
def test_missing_observation_and_pre_snapshot_source_are_rejected(tmp_path):
    state(tmp_path)
    client, _ = broker(tmp_path, cash=100)
    snapshot = shadow.freeze_intents(
        tmp_path,
        client,
        "2026-10-05",
        clock=lambda: datetime(2026, 10, 5, 9, 46, tzinfo=calendar.NEW_YORK),
    )
    results = shadow.inspect_intents(snapshot, {}, model())
    assert all(row["state"] == "missing_observation" for row in results)
    with pytest.raises(ValueError, match="Observation"):
        shadow.inspect_intents(snapshot, {"ONE": observation(case())}, model())


# Match live's key-presence refusal rather than fall back from malformed policies.
@pytest.mark.parametrize("policy", [{}, None, "", False])
def test_present_execution_policy_never_falls_back_to_ordinary(tmp_path, policy):
    path = state(tmp_path)
    data = json.loads(path.read_text())
    data["pending"][0]["execution_policy"] = policy
    path.write_text(json.dumps(data))
    client, _ = broker(tmp_path)
    result = shadow.freeze_intents(
        tmp_path,
        client,
        "2026-10-05",
        clock=lambda: datetime(2026, 10, 5, 9, 44, tzinfo=calendar.NEW_YORK),
    )
    assert len(result["orders"]) == 1
    assert result["excluded"] == [
        {"client_order_id": "sell", "reason": "nonordinary_policy"}
    ]
