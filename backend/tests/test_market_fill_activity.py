"""Broker activity is execution evidence, not an inference from submissions."""

import json
from datetime import date

import pytest

from backend.market.alpaca_trading import AlpacaTradingClient


# Preserve fractional executions and never call a full page complete.
@pytest.mark.parametrize("count", [0, 2, 100])
def test_activity_reads_execution_date_and_marks_pagination(count):
    # Return broker executions independently of the original order date.
    def transport(method, url, headers, body):
        assert method == "GET"
        assert "/account/activities/FILL?date=2026-09-14&" in url
        assert body is None
        return 200, json.dumps(
            [
                {
                    "symbol": "AAPL",
                    "side": "buy",
                    "qty": "0.5",
                    "price": "200.25",
                    "transaction_time": "2026-09-14T13:32:00Z",
                    "order_id": "older-order",
                }
                for _ in range(count)
            ]
        ).encode()

    result = AlpacaTradingClient("test", "test", transport=transport).fill_activity(
        date(2026, 9, 14)
    )
    assert result["complete"] is (count < 100)
    assert len(result["fills"]) == count
    if count:
        assert result["fills"][0] == {
            "symbol": "AAPL",
            "side": "buy",
            "qty": 0.5,
            "price": 200.25,
            "filled_at": "2026-09-14T13:32:00Z",
        }
