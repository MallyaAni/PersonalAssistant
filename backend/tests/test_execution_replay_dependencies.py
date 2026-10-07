"""Exercise explicit replay dependencies through actual planner and dispatcher."""

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, live_policy, paper
from backend.cli import market_daily
from backend.market import alpaca_trading
from backend.tests.test_intraday_orders import Broker, ny, quote, row, save
from backend.tests.test_live_policy import _EmptyBroker, _no_event, _report


# Refuse any accidental request for the environment's real broker account.
def forbidden_broker():
    raise AssertionError("Replay attempted to construct the environment broker")


# Store an actual nightly plan using a private broker and an explicit past clock.
def test_nightly_replay_uses_only_supplied_broker_and_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden_broker)
    _no_event(monkeypatch)
    broker = _EmptyBroker()
    instant = datetime(2026, 9, 3, 20, 1, tzinfo=UTC)
    result = market_daily.paper_trade(
        _report(), tmp_path, "2026-09-03", True,
        client_factory=lambda: broker, decision_at=instant,
    )
    state = paper.load_state(tmp_path)
    assert state.policy_version == live_policy.ACTIVE
    assert result["plan"] == "rebalance"
    assert result["orders"] == []
    assert result["planned"][0]["qty"] == 250
    assert state.pending[0]["execution"]["decision_at"] == instant.isoformat()
    assert state.pending[0]["execute_on"] == "2026-09-04"
    assert broker.orders == []


# Reject invalid historical clocks before even accessing a private or real broker.
@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 9, 3, 20, 1),
        datetime(2026, 9, 3, 19, 59, tzinfo=UTC),
        datetime(2026, 9, 4, 20, 1, tzinfo=UTC),
    ],
)
def test_nightly_invalid_explicit_clock_touches_nothing(tmp_path, instant):
    with pytest.raises(ValueError, match="[Nn]ightly decision"):
        market_daily.paper_trade(
            _report(), tmp_path, "2026-09-03", True,
            client_factory=forbidden_broker, decision_at=instant,
        )
    assert not paper.state_path(tmp_path).exists()


# Keep historical holidays, unreviewed years and pre-close private clocks rejected.
@pytest.mark.parametrize(
    "instant",
    [
        datetime(2018, 7, 4, 20, 1, tzinfo=UTC),
        datetime(2018, 11, 23, 17, 59, tzinfo=UTC),
        datetime(1900, 1, 31, 21, 1, tzinfo=UTC),
    ],
)
def test_private_historical_calendar_still_rejects_invalid_clocks(tmp_path, instant):
    session = instant.astimezone(intraday_orders.NEW_YORK).date().isoformat()
    report = SimpleNamespace(
        panel=SimpleNamespace(dates=np.array([session], "datetime64[D]"))
    )
    with pytest.raises(ValueError, match="Nightly decision"):
        market_daily.paper_trade(
            report, tmp_path, session, True,
            client_factory=forbidden_broker, decision_at=instant,
        )
    assert not paper.state_path(tmp_path).exists()


# Leave the environment broker's published-calendar boundary unchanged.
def test_historical_clock_without_private_broker_is_not_enabled(tmp_path):
    session = "2018-01-31"
    report = SimpleNamespace(
        panel=SimpleNamespace(dates=np.array([session], "datetime64[D]"))
    )
    with pytest.raises(ValueError, match="Nightly decision"):
        market_daily.paper_trade(
            report, tmp_path, session, True,
            decision_at=datetime(2018, 1, 31, 21, 1, tzinfo=UTC),
        )
    assert not paper.state_path(tmp_path).exists()


# Make a declared alternative timing verdict without changing quantity or funding.
def wait(row, latch, bar, now, today):
    return {"send": None, "timed": {"state": "waiting"}}


# A waiting model suppresses an ordinary legacy trigger without writing a submission.
def test_explicit_reader_preserves_a_waiting_pending_order(tmp_path):
    save(tmp_path, row())
    broker = Broker()
    observed = ny(10)
    snapshot = {"quotes": {"AAA": quote(98, ny(9, 45))}}
    assert intraday_orders.send_due(
        tmp_path, snapshot, observed, lambda: broker, timing_reader=wait
    ) == []
    pending = paper.load_state(tmp_path).pending[0]
    assert pending["qty"] == 10
    assert "sent" not in pending
    assert "sending" not in pending
    assert broker.sent == []


# Keep the shared final deadline authoritative even if the reader would wait.
def test_explicit_reader_cannot_remove_the_terminal_market_order(tmp_path):
    save(tmp_path, row())
    broker = Broker()

    # Fail if the replacement sees a decision owned by the shared final clock.
    def forbidden(*args):
        raise AssertionError("Custom timing called inside final deadline")

    intraday_orders.send_due(
        tmp_path, {}, ny(15, 45), lambda: broker, timing_reader=forbidden
    )
    pending = paper.load_state(tmp_path).pending[0]
    assert pending["sent"]["how"] == intraday_orders.MARKET
    assert pending["sent"]["qty"] == 10
    assert len(broker.sent) == 1


# Preserve ordinary sell caps and prevent a reader from rewriting pending shares.
def test_reader_receives_copies_and_actual_executor_caps_covered_sells(tmp_path):
    save(tmp_path, row(side="sell", qty=10))
    broker = Broker(held={"AAA": 3})
    snapshot = {"quotes": {"AAA": quote(100, ny(9, 45))}}

    # Attempt mutations to prove pending intent and shared quote bytes are isolated.
    def execute(request, latch, bar, now, today):
        request["qty"] = 1000
        bar["last"] = 9999
        return {"send": intraday_orders.MARKET, "timed": {"state": "execute"}}

    intraday_orders.send_due(
        tmp_path, snapshot, ny(10), lambda: broker, timing_reader=execute
    )
    pending = paper.load_state(tmp_path).pending[0]
    assert pending["qty"] == 10
    assert pending["sent"]["qty"] == 3
    assert snapshot["quotes"]["AAA"]["last"] == 100


# Refuse malformed reader contracts before contacting the broker or writing a send.
@pytest.mark.parametrize(
    "verdict",
    [None, {}, {"send": "limit", "timed": {"state": "execute"}},
     {"send": "market", "timed": {}}, {"timed": {"state": "waiting"}}],
)
def test_invalid_reader_does_not_submit_or_fall_back(tmp_path, verdict):
    save(tmp_path, row())
    before = paper.state_path(tmp_path).read_bytes()

    # Return a deliberately invalid contract through the genuine dispatcher.
    def invalid(*args):
        return verdict

    with pytest.raises(ValueError, match="explicit ordinary verdict"):
        intraday_orders.send_due(
            tmp_path, {}, ny(10), forbidden_broker, timing_reader=invalid
        )
    assert paper.state_path(tmp_path).read_bytes() == before


# Explicit IOC contracts retain their own guards and never invoke ordinary timing.
@pytest.mark.parametrize("contract", [None, {}, "unknown-policy"])
def test_reader_cannot_override_an_explicit_execution_contract(tmp_path, contract):
    save(tmp_path, row(execution_policy=contract))

    # Reject use of ordinary timing to bypass an invalid explicit execution policy.
    def forbidden(*args):
        raise AssertionError("Ordinary reader bypassed an explicit IOC contract")

    intraday_orders.send_due(
        tmp_path, {}, ny(10), forbidden_broker, timing_reader=forbidden
    )
    pending = paper.load_state(tmp_path).pending[0]
    assert "sent" not in pending
    assert pending["execution"]["bounded_observations"]
