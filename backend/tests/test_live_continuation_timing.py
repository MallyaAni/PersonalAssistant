"""Exercise continuation verdicts through the real sender and private persisted book."""

from copy import deepcopy
from datetime import timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market.live_continuation_timing import build_reader
from backend.tests.test_live_probability_timing import (
    NOW,
    SESSION,
    SYMBOLS,
    broker,
    intent,
    snapshot,
)


# Keep supplied test means and coordinate calls visible without model fitting.
class Means:
    # Store the two distinct side values used by the conditional continuation policy.
    def __init__(self, values=(-0.01, 0.01)):
        self.values, self.calls = values, []

    # Return only this clock's supplied vector without observing any fill outcomes.
    def provider(self, day, clock, stock):
        self.calls.append((day, clock, stock))
        return self.values


# Persist original intents and drive their ordinary execution through the actual sender.
def send(root, client, rows, source, *, now=NOW, clock=0, quotes=None, cost=0):
    state = paper.PaperState(pending=deepcopy(rows))
    paper.save_state(root, state)
    quotes, traces = quotes or snapshot(now), []
    reader = build_reader(source.provider, SYMBOLS, 0, clock, SESSION, now,
                          quotes, state.pending, client, cost, traces)
    lines = intraday_orders.send_due(root, quotes, now, lambda: client,
                                    timing_reader=reader)
    return traces, paper.load_state(root), lines


# Use opposite buy/sell signs even when observed prices never cross a percent level.
@pytest.mark.parametrize(("side", "means", "wanted"), [
    ("buy", (0.01, 0.01), "wait"),
    ("buy", (-0.01, -0.01), "execute"),
    ("sell", (0.01, 0.01), "execute"),
    ("sell", (-0.01, -0.01), "wait"),
    ("buy", (0.0, 0.0), "execute"),
    ("sell", (0.0, 0.0), "execute"),
])
def test_real_sender_continuation_directions(tmp_path, side, means, wanted):
    source, client = Means(means), broker(holdings={"AAA": 10})
    traces, state, _ = send(tmp_path, client, [intent(side=side)], source)
    assert traces[0]["state"] == wanted
    assert traces[0]["is_calibrated_confidence"] is False
    assert bool(state.pending[0].get("sent")) == (wanted == "execute")
    assert state.pending[0]["qty"] == 5


# Changing a later execution price cannot change the original decision or trace.
def test_future_fill_variations_preserve_trace_and_original_qty(tmp_path):
    traces = []
    for label, price in (("cheap", 8), ("expensive", 12)):
        client = broker()
        observed, state, _ = send(tmp_path / label, client, [intent()], Means())
        traces.append(observed)
        assert client.ledger()["holdings"] == {}
        assert client.ledger()["cash"] == 1000
        client.flush(NOW + timedelta(minutes=15), {"AAA": price})
        assert state.pending[0]["sent"]["qty"] == 5
        assert client.ledger()["holdings"] == {"AAA": 5}
    assert traces[0] == traces[1]


# Missing and malformed means cannot revert to an incumbent price trigger.
@pytest.mark.parametrize("means", [None, [1], [True, False], [np.nan, 0], [np.inf, 0]])
def test_unavailable_forecasts_keep_original_pending_intent(tmp_path, means):
    source = Means(means)
    traces, state, _ = send(tmp_path, broker(), [intent()], source)
    assert traces[0]["state"] == "unavailable"
    assert not state.pending[0].get("sent")
    assert state.pending[0]["qty"] == 5


# Unknown quote or cash evidence cannot invoke a model or submit an order.
@pytest.mark.parametrize("problem", ["stale", "peer_quote", "cash", "held_mark"])
def test_observation_and_funding_gate_precede_model(tmp_path, problem):
    client, rows, quotes, source = broker(), [intent()], snapshot(), Means()
    if problem == "stale":
        quotes["quotes"]["AAA"]["bar"] = NOW.isoformat()
    elif problem == "peer_quote":
        rows.append(intent("BBB", identifier="peer"))
        quotes["quotes"].pop("BBB")
    elif problem == "cash":
        client = broker(0, holdings={"BBB": 3})
    else:
        client = broker(holdings={"BBB": 3})
        client.observe(NOW, {"AAA": 10, "BBB": None}, True)
    traces, state, _ = send(tmp_path, client, rows, source, quotes=quotes)
    assert all(row["state"] in ("unavailable", "no_trade") for row in traces)
    assert not any(row.get("sent") for row in state.pending)
    assert source.calls == []


# The real sender caps sell shares and never sends a recorded original intent twice.
def test_whole_sale_cap_and_repeat_identity_are_preserved(tmp_path):
    client, source = broker(holdings={"AAA": 3}), Means()
    traces, state, _ = send(tmp_path, client, [intent(side="sell", qty=9)], source)
    assert traces[0]["observed_qty"] == 3
    assert state.pending[0]["sent"]["qty"] == 3
    calls = len(source.calls)
    _, again, lines = send(tmp_path, client, state.pending, source)
    assert len(source.calls) == calls
    assert lines == []
    assert again.pending[0]["sent"] == state.pending[0]["sent"]


# Available all-clock heads work before the unchanged shared terminal deadline.
def test_late_continuation_and_shared_deadline(tmp_path):
    late = NOW.replace(hour=15, minute=30)
    source = Means()
    traces, state, _ = send(tmp_path / "late", broker(now=late), [intent()], source,
                            now=late, clock=23)
    assert traces[0]["state"] == "execute"
    assert state.pending[0]["sent"]["qty"] == 5
    final = NOW.replace(hour=15, minute=45)
    terminal_source = Means((1.0, -1.0))
    traces, state, _ = send(tmp_path / "terminal", broker(now=final), [intent()],
                            terminal_source, now=final, clock=24)
    assert traces == []
    assert terminal_source.calls == []
    assert state.pending[0]["sent"]["qty"] == 5


# Events remain outside ordinary continuation timing even when their symbol matches.
def test_event_intent_is_not_overridden(tmp_path):
    row = intent()
    row["event_id"] = "event"
    source = Means()
    traces, state, lines = send(tmp_path, broker(), [row], source)
    assert traces == []
    assert source.calls == []
    assert lines == []
    assert not state.pending[0].get("sent")


# Confirm sale proceeds are unavailable to same-batch buys until observed settlement.
def test_sales_do_not_fabricate_funding_for_pending_buys(tmp_path):
    client, source = broker(50, holdings={"AAA": 5}), Means()
    rows = [intent(side="sell", identifier="sale"),
            intent("BBB", qty=10, identifier="buy")]
    traces, state, _ = send(tmp_path, client, rows, source)
    assert traces[1]["buying_power_budget"] == 50
    assert traces[1]["buy_funding_fraction"] == 0.5
    assert not state.pending[1].get("sent")
    assert client.ledger()["cash"] == 50
    later = NOW + timedelta(minutes=15)
    client.flush(later, {"AAA": 10})
    client.observe(later, {"AAA": 10, "BBB": 10}, True)
    follow, final, _ = send(tmp_path, client, state.pending, source, now=later, clock=1)
    assert follow[0]["buying_power_budget"] == 100
    assert final.pending[1]["sent"]["qty"] == 10
    assert client.ledger()["holdings"] == {}
