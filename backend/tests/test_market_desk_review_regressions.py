"""Desk review acceptance paths with isolated broker traffic and persisted state."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import paper
from backend.agents.trading.desk.narrative import _cut
from backend.cli import market_balancer
from backend.market import alpaca_trading, live_quotes


# Freeze a regular-session observation without touching the system clock.
class Clock(datetime):
    # Give each decision the same current candle.
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 11, 14, 0, tzinfo=UTC)


# Exercise cancellation acknowledgement, restart, and terminal reconciliation.
@pytest.mark.parametrize(
    ("status", "filled", "expected"),
    [
        ("canceled", 0, "skipped"),
        ("canceled", 3, "skipped"),
        ("filled", 10, "filled"),
        ("pending_cancel", 3, "partial"),
    ],
)
def test_hold_intent_survives_restart_without_losing_fills(
    tmp_path, monkeypatch, status, filled, expected
):
    oid = "anios-test-sell-aaa"
    pending = [
        {
            "client_order_id": oid,
            "symbol": "AAA",
            "side": "sell",
            "qty": 10,
            "session": "2026-09-10",
        }
    ]
    paper.save_state(
        tmp_path,
        paper.PaperState(
            pending=pending,
            last_rebalance="2026-09-10",
            previous_rebalance="2026-08-10",
            unconfirmed_rebalance="2026-09-10",
        ),
    )
    calls = []

    # The broker acknowledges first and confirms only on a later reconciliation.
    def transport(method, url, headers, body):
        calls.append((method, url))
        if method == "DELETE":
            assert paper.load_state(tmp_path).pending[0]["hold_requested"]
            return 204, b""
        if "status=open" in url:
            return 200, json.dumps(
                [{"id": "broker-id", "client_order_id": oid}]
            ).encode()
        return 200, json.dumps({"status": "pending_cancel", "filled_qty": "0"}).encode()

    client = alpaca_trading.AlpacaTradingClient(
        "fixture", "fixture", transport=transport
    )
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: client)
    monkeypatch.setattr(market_balancer, "datetime", Clock)
    market_balancer._green_day_skip(
        tmp_path,
        {"actions": [{"ticker": "AAA", "last_close": 100}]},
        {"AAA": {"open": 102, "bar": "2026-09-11T13:45:00+00:00"}},
        tmp_path / "audit.log",
    )
    restored = paper.load_state(tmp_path)
    assert restored.pending
    assert not restored.journal
    assert calls[-1] == ("GET", client.base_url + "/orders/broker-id")
    settled = paper.settle(
        restored.pending,
        [
            {
                "client_order_id": oid,
                "status": status,
                "filled_qty": str(filled),
                "filled_avg_price": "101" if filled else None,
            }
        ],
    )
    paper.save_state(tmp_path, paper.apply_settlements(restored, settled))
    final = paper.load_state(tmp_path)
    assert final.journal[0]["status"] == expected
    assert final.journal[0]["filled_qty"] == filled
    assert final.journal[0]["filled_price"] == (101 if filled else 0)
    assert final.last_rebalance == "2026-09-10"
    assert bool(final.pending) == (status == "pending_cancel")
    assert (final.unconfirmed_rebalance is None) == (status != "pending_cancel")


# Ignore extended hours and missing opening candles in both seasons.
@pytest.mark.parametrize(("month", "hour"), [(9, 13), (12, 14)])
def test_quote_requires_the_regular_session_open(month, hour):
    # Make one timestamped bar whose price identifies its session.
    def bar(day, h, minute, price):
        return SimpleNamespace(
            start=datetime(2026, month, day, h, minute, tzinfo=UTC),
            open=price,
            high=price,
            low=price,
            close=price,
        )

    now = datetime(2026, month, 11, hour + 1, 0, tzinfo=UTC)
    regular = bar(11, hour, 30, 99)
    premarket = bar(11, hour - 1, 0, 102)
    previous = bar(10, hour, 30, 105)
    quote = live_quotes.quote_from_bars("AAA", [premarket, regular, previous], now)
    assert quote.open == 99
    assert (quote.high, quote.low) == (99, 99)
    assert live_quotes.quote_from_bars("AAA", [premarket, previous], now) is None
    assert live_quotes.quote_from_bars("AAA", [bar(11, hour, 45, 101)], now) is None


# Never turn punctuation outside the budget or a decimal into a sentence ending.
@pytest.mark.parametrize("limit", [0, 5, 30, 200, 700, 1600])
def test_narrative_bound_is_absolute(limit):
    for text in (
        "A" * (limit + 100) + ". More text.",
        "Price is 100.25 and the",
        "Unfinished; clause",
        "Done! Still unfinished",
    ):
        result = _cut(text, limit)
        assert len(result) <= limit
        assert not result or result.endswith((".", "!", "?"))
    assert _cut("Price is 100.25 and the", 13) == ""


# A stale, future, missing, or premarket candle cannot authorize a cancellation.
@pytest.mark.parametrize(
    "bar",
    [
        None,
        "2026-09-10T13:45:00+00:00",
        "2026-09-11T13:00:00+00:00",
        "2026-09-11T14:15:00+00:00",
    ],
)
def test_invalid_candle_does_not_change_state(tmp_path, monkeypatch, bar):
    state = paper.PaperState(
        pending=[
            {"client_order_id": "test", "symbol": "AAA", "side": "sell", "qty": 10}
        ]
    )
    paper.save_state(tmp_path, state)
    monkeypatch.setattr(market_balancer, "datetime", Clock)
    market_balancer._green_day_skip(
        tmp_path,
        {"actions": [{"ticker": "AAA", "last_close": 100}]},
        {"AAA": {"open": 102, "bar": bar}},
        tmp_path / "audit.log",
    )
    assert paper.load_state(tmp_path) == state


# A cache entry from another session must never supply today's opening price.
def test_quote_cache_is_scoped_to_the_requested_session():
    from datetime import date

    live_quotes.forget()
    calls = []

    # Give each requested session a different opening price.
    def fetch(symbol, start, end, headers=None):
        calls.append(start)
        return [
            SimpleNamespace(
                start=datetime(2026, 9, start.day, 13, 30, tzinfo=UTC),
                open=start.day,
                high=start.day,
                low=start.day,
                close=start.day,
            )
        ]

    try:
        for day in (10, 11):
            quote = live_quotes.quotes(
                ["AAA"],
                session=date(2026, 9, day),
                fetch=fetch,
                now=lambda: 0,
                clock=Clock.now,
            )["AAA"]
            assert quote.open == day
        assert len(calls) == 2
    finally:
        live_quotes.forget()
