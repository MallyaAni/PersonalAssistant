"""Actual sender acceptance using a private broker and supplied frozen CDFs."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import calendar
from backend.market.live_probability_timing import build_reader
from backend.market.probabilistic_execution import Distribution
from backend.market.replay_broker import ReplayBroker

SESSION = date(2026, 8, 3)
NOW = datetime(2026, 8, 3, 9, 45, tzinfo=calendar.NEW_YORK)
SYMBOLS = ("SPY", "AAA", "QQQ", "BBB")


# Construct the actual ordinary pending shape without a model-derived quantity.
def intent(symbol="AAA", side="buy", qty=5, identifier="intent"):
    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "client_order_id": identifier,
        "session": "2026-07-31",
        "execute_on": SESSION.isoformat(),
        "execution_timing": intraday_orders.INTRADAY_TIMING,
        "event_id": None,
        "execution": {"reference_price": 10},
    }


# Supply exact completed raw bar evidence for the requested observation.
def snapshot(now=NOW, prices=None):
    return {
        "quotes": {
            name: {
                "last": price,
                "open": 10,
                "bar": (now - timedelta(minutes=15)).astimezone(UTC).isoformat(),
                "as_of": now.astimezone(UTC).isoformat(),
            }
            for name, price in (prices or {"AAA": 10, "BBB": 10}).items()
        }
    }


# Create observed private balances without exposing any future execution price.
def broker(cash=1000, holdings=None, now=NOW):
    held = holdings or {}
    client = ReplayBroker(
        cash, 0, initial_holdings=held, initial_average_prices={s: 10 for s in held}
    )
    client.observe(now, {"AAA": 10, "BBB": 10}, True)
    return client


# Keep synthetic forecast calls inspectable without calibration or model fitting.
class Provider:
    # Store fixed test forecasts with the original complete stock ordering.
    def __init__(self, mean=-0.01, *, verify=False):
        self.mean, self.calls = mean, []
        if verify:
            self.verification = {"status": "VERIFIED_SAVED_DISTRIBUTIONS"}
            self.symbols, self.dates = (
                SYMBOLS,
                np.array([SESSION], dtype="datetime64[D]"),
            )

    # Return a fixed empirical distribution at the named original stock index.
    def provider(self, day, clock, stock):
        self.calls.append((day, clock, stock))
        mean = self.mean[stock] if isinstance(self.mean, dict) else self.mean
        return Distribution(mean, 0, np.array([0.0]), np.array([1.0]))


# Freeze a reader and run the real sender against private persisted paper state.
def send(root, client, rows, provider, *, now=NOW, clock=0, quotes=None, cost=0):
    state = paper.PaperState()
    state.pending = deepcopy(rows)
    paper.save_state(root, state)
    quotes = quotes or snapshot(now)
    traces = []
    reader = build_reader(
        provider,
        SYMBOLS,
        0,
        clock,
        SESSION,
        now,
        quotes,
        state.pending,
        client,
        cost,
        traces,
    )
    lines = intraday_orders.send_due(
        root, quotes, now, lambda: client, timing_reader=reader
    )
    return traces, paper.load_state(root), lines


# The sender persists unchanged quantities while holdings stay unchanged until flush.
def test_actual_sender_uses_cdf_without_legacy_one_percent_gate(tmp_path):
    client, source = broker(), Provider(verify=True)
    traces, state, lines = send(tmp_path, client, [intent()], source.provider)
    assert len(lines) == 1
    assert state.pending[0]["sent"]["qty"] == 5
    assert state.pending[0]["sent"]["state"] == "execute"
    assert source.calls == [(0, 0, 1)]
    assert client.ledger()["holdings"] == {}
    assert client.ledger()["cash"] == 1000
    assert traces[0]["trade_fraction"] == 0.05
    assert traces[0]["expected_log_utility"] < 0
    client.flush(NOW + timedelta(minutes=15), {"AAA": 11})
    assert client.ledger()["holdings"] == {"AAA": 5}


# Later fill variation cannot change the already recorded timing decision.
def test_future_fill_variants_leave_verdict_and_trace_unchanged(tmp_path):
    traces = []
    for name, price in (("cheap", 8), ("expensive", 12)):
        client = broker()
        evidence, state, _ = send(
            tmp_path / name, client, [intent()], Provider().provider
        )
        traces.append(evidence)
        client.flush(NOW + timedelta(minutes=15), {"AAA": price})
        assert state.pending[0]["sent"]["qty"] == 5
    assert traces[0] == traces[1]


# Buy and sell utilities have opposite waiting directions at the same forecast.
@pytest.mark.parametrize(
    ("side", "mean", "state"),
    [
        ("buy", 0.01, "wait"),
        ("buy", -0.01, "execute"),
        ("sell", 0.01, "execute"),
        ("sell", -0.01, "wait"),
    ],
)
def test_actual_sender_buy_sell_direction(tmp_path, side, mean, state):
    traces, result, _ = send(
        tmp_path,
        broker(holdings={"AAA": 10}),
        [intent(side=side)],
        Provider(mean).provider,
    )
    assert traces[0]["state"] == state
    assert bool(result.pending[0].get("sent")) == (state == "execute")


# Forming, stale and future bars never reach the forecast provider or the broker.
@pytest.mark.parametrize(
    "defect", ["forming", "stale", "future_receipt", "missing_open", "missing_quote"]
)
def test_invalid_quote_blocks_provider_and_actual_submission(tmp_path, defect):
    quotes, source, client = snapshot(), Provider(), broker()
    if defect == "forming":
        quotes["quotes"]["AAA"]["bar"] = NOW.isoformat()
    elif defect == "stale":
        quotes["quotes"]["AAA"]["bar"] = (NOW - timedelta(minutes=30)).isoformat()
    elif defect == "future_receipt":
        quotes["quotes"]["AAA"]["as_of"] = (NOW + timedelta(seconds=1)).isoformat()
    elif defect == "missing_open":
        quotes["quotes"]["AAA"]["open"] = None
    else:
        quotes["quotes"].pop("AAA")
    traces, state, _ = send(
        tmp_path, client, [intent()], source.provider, quotes=quotes
    )
    assert traces[0]["state"] == "unavailable"
    assert not state.pending[0].get("sent")
    assert source.calls == []
    assert client.attempt_history == ()


# No funded quantity leaves the actual ordinary intent pending without resizing it.
def test_zero_cash_retains_pending_and_avoids_forecast_call(tmp_path):
    client, source = broker(0, holdings={"BBB": 10}), Provider()
    traces, state, _ = send(tmp_path, client, [intent()], source.provider)
    assert traces[0]["state"] == "no_trade"
    assert traces[0]["trade_fraction"] == 0
    assert state.pending[0]["qty"] == 5
    assert not state.pending[0].get("sent")
    assert source.calls == []


# Repeated-name buy legs share a budget without shrinking the actual orders.
def test_common_buy_budget_counts_duplicate_legs_and_fee(tmp_path):
    rows = [intent(qty=4, identifier="one"), intent(qty=6, identifier="two")]
    traces, state, _ = send(tmp_path, broker(50), rows, Provider().provider, cost=25)
    assert traces[0]["all_pending_buy_spend"] == pytest.approx(100.25)
    assert traces[1]["buy_funding_fraction"] == pytest.approx(50 / 100.25)
    assert traces[0]["trade_fraction"] == pytest.approx(4 / 10.025)
    assert traces[1]["trade_fraction"] == pytest.approx(6 / 10.025)
    assert state.pending[0]["qty"] == 4
    assert state.pending[1]["qty"] == 6
    assert not state.pending[1].get("sent")
    assert (
        "REFUSED" in state.pending[1]["send_error"]
        or "cash" in state.pending[1]["send_error"]
    )


# The existing sender retries a refused original buy only after confirmed later cash.
def test_sale_cash_is_not_visible_before_flush_and_retry_is_unchanged(tmp_path):
    client = broker(50, holdings={"AAA": 5})
    rows = [
        intent(side="sell", identifier="sale"),
        intent("BBB", qty=10, identifier="buy"),
    ]
    source = Provider({1: 0.01, 3: -0.01})
    traces, state, _ = send(tmp_path, client, rows, source.provider)
    assert traces[1]["buying_power_budget"] == 50
    assert traces[1]["buy_funding_fraction"] == 0.5
    assert not state.pending[1].get("sent")
    client.flush(NOW + timedelta(minutes=15), {"AAA": 10})
    later = NOW + timedelta(minutes=15)
    client.observe(later, {"AAA": 10, "BBB": 10}, True)
    follow, final, _ = send(
        tmp_path, client, state.pending, source.provider, now=later, clock=1
    )
    assert follow[0]["buying_power_budget"] == 100
    assert final.pending[1]["sent"]["qty"] == 10
    assert client.ledger()["holdings"] == {}


# The shared final deadline bypasses the learned reader and remains authoritative.
def test_shared_terminal_deadline_bypasses_reader(tmp_path):
    final = NOW.replace(hour=15, minute=45)
    client, source = broker(now=final), Provider(0.01)
    traces, state, _ = send(
        tmp_path, client, [intent()], source.provider, now=final, clock=24
    )
    assert traces == []
    assert source.calls == []
    assert state.pending[0]["sent"]["qty"] == 5


# Missing other pending buy quotes do not artificially inflate a known buy's funding.
def test_missing_peer_buy_quote_blocks_common_budget(tmp_path):
    quotes = snapshot(prices={"AAA": 10})
    source = Provider()
    traces, _, _ = send(
        tmp_path,
        broker(),
        [intent(), intent("BBB", identifier="peer")],
        source.provider,
        quotes=quotes,
    )
    assert all(row["state"] == "unavailable" for row in traces)
    assert source.calls == []


# Covered whole sell quantity determines exposure without changing the saved intent.
def test_sell_exposure_is_capped_to_covered_whole_shares(tmp_path):
    client = broker(holdings={"AAA": 3})
    traces, state, _ = send(
        tmp_path, client, [intent(side="sell", qty=9)], Provider(0.01).provider
    )
    assert traces[0]["observed_qty"] == 3
    assert traces[0]["trade_fraction"] == pytest.approx(30 / 1030)
    assert state.pending[0]["qty"] == 9
    assert state.pending[0]["sent"]["qty"] == 3


# Unknown fresh equity prevents both provider calls and sender submissions.
def test_unknown_held_valuation_is_unavailable(tmp_path):
    client, source = broker(holdings={"BBB": 3}), Provider()
    client.observe(NOW, {"BBB": None, "AAA": 10}, True)
    traces, state, _ = send(tmp_path, client, [intent()], source.provider)
    assert traces[0]["state"] == "unavailable"
    assert source.calls == []
    assert not state.pending[0].get("sent")


# The frozen 15-minute calibration supplies no ordinary forecast for clock 23.
def test_unsupported_forecast_clock_stays_unavailable(tmp_path):
    late = NOW.replace(hour=15, minute=30)
    client, source = broker(now=late), Provider()
    traces, state, _ = send(
        tmp_path, client, [intent()], source.provider, now=late, clock=23
    )
    assert traces[0]["state"] == "unavailable"
    assert traces[0]["reason"] == "unsupported learned clock"
    assert source.calls == []
    assert not state.pending[0].get("sent")


# Invalid original symbol or date attestation cannot silently select another forecast.
def test_saved_provider_identity_mismatch_is_rejected():
    source, client = Provider(verify=True), broker()
    source.symbols = tuple(reversed(SYMBOLS))
    with pytest.raises(ValueError, match="attestation"):
        build_reader(
            source.provider,
            SYMBOLS,
            0,
            0,
            SESSION,
            NOW,
            snapshot(),
            [intent()],
            client,
            0,
            [],
        )


# Nonmatching horizons reject rather than falling back to the old price rule.
def test_wrong_horizon_is_not_a_one_percent_fallback(tmp_path):
    # Supply an explicitly invalid target domain without any learned estimator.
    def provider(day, clock, stock):
        return Distribution(
            -0.01, 0, np.array([0.0]), np.array([1.0]), "holding_return"
        )

    with pytest.raises(ValueError, match="horizon"):
        send(tmp_path, broker(), [intent()], provider)


# Incomplete date/clock and duplicate IDs cannot create a permissive reader.
@pytest.mark.parametrize("defect", ["clock", "date", "duplicate"])
def test_invalid_reader_contract(defect):
    session, clock, rows = SESSION, 0, [intent()]
    if defect == "clock":
        clock = 1
    elif defect == "date":
        session = date(2026, 8, 4)
    else:
        rows.append(intent())
    with pytest.raises(ValueError, match="clock|Clock|contract|identities"):
        build_reader(
            Provider().provider,
            SYMBOLS,
            0,
            clock,
            session,
            NOW,
            snapshot(),
            rows,
            broker(),
            0,
            [],
        )
