"""Exercise execution evidence and the adopted-plan decision gates."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.market import decision_view, execution_quotes
from backend.tests.test_intraday_candidate import inputs


# Construct fresh quotes and a strategy due for its scheduled rebalance.
def setup():
    record, snapshot, _, _, now = inputs()
    record["paper"] = {"until_rebalance": 0}
    quoted = {
        "feed": "sip",
        "market_open": True,
        "quotes": {
            n: {"bp": 99.99, "ap": 100.01, "bs": 10, "as": 10, "t": now.isoformat()}
            for n in record["grades"]
        },
    }
    return record, snapshot, quoted, now


# Every missing quote or strategy gate blocks an otherwise eligible addition.
@pytest.mark.parametrize(
    "block",
    [
        None,
        "stale",
        "closed",
        "spread",
        "size",
        "future",
        "band",
        "fomc",
        "schedule",
        "timing",
        "technical",
    ],
)
def test_decision_requires_every_gate(block):
    record, snapshot, quoted, now = setup()
    quote = quoted["quotes"]["S11"]
    changes = {
        "stale": (quote, {"t": (now - timedelta(seconds=31)).isoformat()}),
        "future": (quote, {"t": (now + timedelta(seconds=1)).isoformat()}),
        "closed": (quoted, {"market_open": False}),
        "spread": (quote, {"ap": 102}),
        "size": (quote, {"bs": 0}),
        "band": (record, {"levels": {"S11": {"rejecting_band": True}}}),
        "fomc": (record, {"event_risk": {"execution_pending": True}}),
        "schedule": (record, {"paper": {"until_rebalance": 10}}),
        "timing": (record, {"paper": {}}),
        "technical": (snapshot, {"technical": {}}),
    }
    if block:
        target, replacement = changes[block]
        target.update(replacement)
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert (result["action"] == "Buy eligible") is (block is None)
    assert result["target_weight"] == 0.1


# A decision written on the evening of its own session is current, not
# "outdated" until the next session: the nightly record carries today's date.
def test_just_written_decision_is_current():
    record, snapshot, quoted, now = setup()
    record["session"] = "2026-09-14"
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert "Nightly decision outdated" not in result.get("reason", "")


# IEX is the only feed the account can read; its quotes pass the gate, labelled.
def test_iex_quote_passes_the_gate():
    record, snapshot, quoted, now = setup()
    quoted["feed"] = "iex"
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert result["action"] == "Buy eligible"
    assert result["quote"]["feed"] == "iex"
    assert result["quote"]["eligible"]


# A name with no recorded position cannot be labeled Hold when buying is ineligible.
@pytest.mark.parametrize(("shares", "expected"), [(0, "Wait"), (10, "Hold")])
def test_no_eligible_addition_distinguishes_unheld_names(shares, expected):
    _, _, _, now = setup()
    row = {
        "in_book": True,
        "until_rebalance": 0,
        "rebalance_due": True,
        "rejecting_band": False,
        "grade_live": "B",
        "shares": shares,
    }
    action, reason = decision_view.action_for_row(
        row,
        {"eligible": True, "reason": "Quote checks passed"},
        now + timedelta(seconds=20),
        False,
        True,
        0.1,
        0,
        now,
    )
    assert action == expected
    assert reason == "No eligible addition"


# Expired provider caches are checked by their quote time, not their fetch time.
def test_invalid_quotes_never_gain_eligibility():
    _, _, quoted, now = setup()
    raw = quoted["quotes"]["S11"]
    for replacement in ({"bp": float("nan")}, {"ap": 0}, {"ap": 90}, {"t": "unknown"}):
        assert not execution_quotes.describe({**raw, **replacement}, "sip", True, now)[
            "eligible"
        ]


# Feed fallback is explicit, cached and read-only; provider text is never returned.
def test_quote_access_falls_back_without_hiding_feed(monkeypatch):
    execution_quotes._cache.clear()
    monkeypatch.setattr(execution_quotes, "_sip_retry_at", 0)
    monkeypatch.setattr(execution_quotes.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(
        execution_quotes.alpaca_trading,
        "client_from_env",
        lambda: SimpleNamespace(clock=lambda: {"is_open": True}),
    )
    calls = []

    # Return a forbidden consolidated feed and an available single-exchange quote.
    def request(url, headers):
        calls.append(url)
        return (
            (403, b"private provider text")
            if "feed=sip" in url
            else (200, json.dumps({"quotes": {"AAPL": {"bp": 1}}}).encode())
        )

    result = execution_quotes.fetch(["AAPL"], request, lambda: 100)
    assert result["feed"] == "iex"
    assert result["market_open"]
    assert len(calls) == 2
    assert execution_quotes.fetch(["AAPL"], request, lambda: 101) == result
    assert len(calls) == 2
    assert "private" not in json.dumps(result)
    execution_quotes._cache.clear()
