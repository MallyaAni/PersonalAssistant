"""Real installed numeric verdicts survive waiting and never become fabricated fills."""

import json
from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import calendar
from backend.market import learned_live_timing as runtime
from backend.market import learned_order_observation as observed
from backend.tests.test_forward_execution import fitted as fitted
from backend.tests.test_forward_execution import residual_archive as residual_archive
from backend.tests.test_forward_market_evidence import NOW, capture_payloads
from backend.tests.test_learned_live_timing import context, install, pending


# Run the actual installed sender with authentic synthetic heads and provider bytes.
@pytest.fixture
def observation_factory(tmp_path, fitted, residual_archive, monkeypatch):
    install(tmp_path, fitted, residual_archive)
    original_observe = runtime.observe
    monkeypatch.setattr(
        runtime.sequential_shadow_context, "load_context", lambda *args: context()
    )
    monkeypatch.setattr(runtime.alpaca, "credentials", lambda: {})

    # Freeze only external evidence and clocks; preserve actual inference and dispatch.
    def run(price=150):
        client, row = pending(tmp_path, price=price)
        bodies = capture_payloads(
            NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
        )
        quotes = json.loads(bodies[-1])
        for quote in quotes["quotes"].values():
            quote.update(bp=price - 0.005, ap=price + 0.005)
        bodies[-1] = json.dumps(quotes).encode()
        pages = iter(bodies)

        # Exercise original bounded source parsing without an external GET.
        def transport(url, headers):
            return 200, next(pages)

        # Restore genuine published models inside the sender's existing transaction.
        def observe(root, rows, snapshot, now, factory):
            return original_observe(
                root,
                rows,
                snapshot,
                now,
                factory,
                transport=transport,
                clock=lambda: NOW + timedelta(seconds=2),
            )

        monkeypatch.setattr(runtime, "observe", observe)
        lines = intraday_orders.send_due(tmp_path, {}, NOW, lambda: client)
        state = paper.load_state(tmp_path)
        return state, client, lines, price

    return run, tmp_path


# Read the persisted observation using the same account and price as its actual capture.
def view(root, state, price, *, now=NOW + timedelta(seconds=2), **changes):
    fields = {"held": {}, "equity": 10000, "budget": 10000, "prices": {"AAOI": price}}
    fields.update(changes)
    return observed.for_rows(root, state.pending, now, **fields)


# A waiting verdict is durable even though no order was submitted.
def test_waiting_numeric_verdict_survives_actual_sender(observation_factory):
    run, root = observation_factory
    state, client, lines, price = run()
    assert not lines
    assert client.orders_since("2026-10-05T00:00:00Z") == []
    row = state.pending[0]
    assert "sent" not in row
    result = view(root, state, price)[row["client_order_id"]]
    assert result["state"] == "wait"
    assert result["current"] is True
    assert result["fill_proven"] is False
    assert result["observed_price"] == 150
    reference = row["timing_observation"]
    raw = (root / reference["path"]).read_bytes()
    assert sha256(raw).hexdigest() == reference["sha256"]
    batch = json.loads(raw)
    assert batch["verdicts"][row["client_order_id"]]["intent"] == observed.identity(row)
    assert "forward_receipt" not in batch["verdicts"][row["client_order_id"]]["timed"]
    assert set(reference) == {"path", "sha256"}


# Quantity, side and session changes cannot inherit an earlier order's verdict.
@pytest.mark.parametrize(
    "change",
    [{"qty": 6}, {"side": "sell"}, {"execute_on": "2026-10-06"}, {"symbol": "QQQ"}],
)
def test_changed_order_identity_is_unavailable(observation_factory, change):
    run, root = observation_factory
    state, _, _, price = run()
    state.pending[0].update(change)
    assert view(root, state, price) == {}


# Hash failures in either shared evidence or original inference cannot be displayed.
@pytest.mark.parametrize("defect", ["batch", "inference", "path"])
def test_missing_original_bytes_never_display_an_observation(
    observation_factory, defect
):
    run, root = observation_factory
    state, _, _, price = run()
    reference = state.pending[0]["timing_observation"]
    path = root / reference["path"]
    if defect == "inference":
        path = (
            root / json.loads(path.read_bytes())["forward_receipt"]["inference"]["path"]
        )
    if defect == "path":
        reference["path"] = "../../outside.json"
    else:
        path.write_bytes(path.read_bytes() + b" ")
    assert view(root, state, price) == {}


# Changed funding, price, source or expired clocks remain historical observations.
@pytest.mark.parametrize(
    "change", ["cash", "equity", "held", "price", "expiry", "config", "future"]
)
def test_stale_or_changed_observation_is_not_current(observation_factory, change):
    run, root = observation_factory
    state, _, _, price = run()
    fields, now = {}, NOW + timedelta(seconds=2)
    if change == "cash":
        fields["budget"] = 0
    elif change == "equity":
        fields["equity"] = 11000
    elif change == "held":
        fields["held"] = {"AAOI": 1}
    elif change == "price":
        fields["prices"] = {"AAOI": 99}
    elif change == "expiry":
        now += timedelta(seconds=31)
    elif change == "future":
        now -= timedelta(seconds=1)
    else:
        (root / runtime.CONFIG).write_text("{}")
    result = view(root, state, price, now=now, **fields)[
        state.pending[0]["client_order_id"]
    ]
    assert result["state"] == "wait"
    assert result["current"] is False
    assert observed.clock_status(result, now)[0] == "waiting"


# The actual broker's filled quantity and fill price override any model observation.
def test_broker_fill_is_authoritative_over_model_readiness(observation_factory):
    run, root = observation_factory
    state, _, lines, price = run(price=99)
    assert len(lines) == 1
    row = state.pending[0]
    broker = {
        "client_order_id": row["client_order_id"],
        "symbol": "AAOI",
        "side": "buy",
        "qty": "5",
        "filled_qty": "5",
        "filled_avg_price": "98.5",
        "status": "filled",
        "filled_at": (NOW + timedelta(seconds=3)).isoformat(),
    }
    shown = intraday_orders.board_orders(
        state,
        broker_orders=[broker],
        latch=None,
        quotes={},
        held={"AAOI": 5},
        prices={"AAOI": 110},
        equity=10000,
        now=NOW + timedelta(seconds=4),
        root=root,
        budget=9000,
    )[0]
    assert shown["state"] == "filled"
    assert shown["qty"] == 5
    assert shown["price"] == 98.5
    assert shown["quantity_basis"] == "filled"
    assert shown["learned_timing"]["state"] == "execute"
    assert shown["learned_timing"]["current"] is False
    assert "1%" not in shown["when"]
    assert shown["level"] is None


# An expired or unavailable model cannot substitute the incumbent's price trigger.
def test_board_waiting_uses_original_model_state(observation_factory):
    run, root = observation_factory
    state, _, _, price = run()
    shown = intraday_orders.board_orders(
        state,
        broker_orders=[],
        latch=None,
        quotes={"AAOI": {"open": 100, "last": 90}},
        held={},
        prices={"AAOI": price},
        equity=10000,
        now=NOW + timedelta(seconds=2),
        root=root,
        budget=10000,
    )[0]
    assert shown["state"] == "waiting"
    assert shown["learned_timing"]["state"] == "wait"
    assert shown["level"] is None
    assert "1%" not in shown["when"]


# Final completion states the deadline without mislabelling it as a learned forecast.
def test_final_completion_never_carries_percent_level(tmp_path):
    client, _ = pending(tmp_path)
    late = NOW.replace(hour=15, minute=59)
    client.observe(late, {"AAOI": 99}, True)
    lines = intraday_orders.send_due(tmp_path, {}, late, lambda: client)
    assert len(lines) == 1
    stored = paper.load_state(tmp_path).pending[0]
    assert stored["sent"]["level"] is None
    assert "forward_timing" not in stored["sent"]


# Shared plan text never represents mixed or unknown timing as the learned policy.
@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ([runtime.POLICY], runtime.POLICY),
        ([runtime.POLICY, None], "order-specific"),
        (["unknown-policy"], "unavailable"),
        ([None], None),
    ],
)
def test_plan_timing_matches_actual_ordinary_rows(tags, expected):
    rows = [
        dict(execution_timing=intraday_orders.INTRADAY_TIMING, timing_policy=tag)
        for tag in tags
    ]
    state = SimpleNamespace(pending=rows, policy_version="incumbent")
    rule, text = observed.plan_timing(state)
    assert rule == expected
    assert text is None or "1%" not in text


# A learned plan with no pending ordinary rows still names its adopted timing.
@pytest.mark.parametrize("retained", [False, True])
def test_empty_learned_plan_names_its_policy(retained):
    from backend.market.joint_funded_policy import MARKET_TIMED_POLICY
    from backend.market.learned_holding_transition import POLICY as RETAINED_POLICY

    policy = RETAINED_POLICY if retained else MARKET_TIMED_POLICY
    state = SimpleNamespace(pending=[], policy_version=policy)
    assert observed.plan_timing(state)[0] == runtime.POLICY


# A non-session cannot appear actionable from a historical model observation.
def test_holiday_clock_is_unavailable():
    holiday = NOW.replace(month=12, day=25)
    assert observed.clock_status(None, holiday) == (
        "waiting",
        "Exchange session unavailable",
    )


# The real paper-plan assembly reads the saved verdict and the paper funding budget.
@pytest.mark.parametrize("retained", [False, True])
def test_paper_api_plan_uses_recorded_learned_decision(
    observation_factory, monkeypatch, retained
):
    from backend.api.v1 import market
    from backend.market.joint_funded_policy import MARKET_TIMED_POLICY
    from backend.market.learned_holding_transition import POLICY as RETAINED_POLICY

    run, root = observation_factory
    state, client, _, price = run()
    policy = RETAINED_POLICY if retained else MARKET_TIMED_POLICY
    state.policy_version = policy
    state.last_rebalance = "2026-10-01"
    monkeypatch.setattr(market, "_root", lambda: root)
    monkeypatch.setattr(
        market, "_live_snapshot", lambda: {"quotes": {"AAOI": {"last": price}}}
    )
    monkeypatch.setattr(
        intraday_orders,
        "qualify_snapshot",
        lambda rows, snapshot, now: (snapshot, NOW + timedelta(seconds=2)),
    )
    shown = market._paper_plan(client, state, [], 10000, cash=10000, buying_power=10000)
    assert shown["rule"] == runtime.POLICY
    assert shown["policy"] == policy
    assert shown["until_rebalance"] is None
    assert "1%" not in str(shown["rule_text"])
    assert shown["orders"][0]["learned_timing"]["current"] is True
    assert shown["orders"][0]["state"] == "waiting"
    unfunded = market._paper_plan(client, state, [], 10000, cash=0, buying_power=10000)
    assert unfunded["orders"][0]["learned_timing"]["current"] is False
