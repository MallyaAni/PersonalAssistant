"""The display collector asks for a fresh entry observation only when it would help."""

import base64
import json
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from backend.market import strategy_entries, strategy_publication
from backend.services import current_opportunity_collector as module
from backend.services.current_opportunity_collector import CurrentOpportunityCollector

NOW = datetime.fromisoformat("2026-01-07T09:46:01-05:00")


def _value(rows, quotes):
    body = json.dumps({"quotes": quotes}).encode()
    return {
        "rows": rows,
        "quote_receipt": {"body_base64": base64.b64encode(body).decode()},
    }


def _quote(spread_bps, at=NOW):
    mid = 100.0
    half = mid * spread_bps / 2e4
    return {"bp": mid - half, "ap": mid + half, "bs": 40, "as": 40, "t": at.isoformat()}


@pytest.fixture
def collector(tmp_path):
    return CurrentOpportunityCollector(tmp_path, enabled=False)


def _decide(collector, rows, quotes, now=NOW):
    with (
        patch.object(strategy_publication, "read", return_value={"rows": {}}),
        patch.object(strategy_entries, "read", return_value=_value(rows, quotes)),
    ):
        return collector._pending_prices_now_quotable(now)


# A planned buy without an engine price, whose quote now passes, earns a
# fresh observation.
def test_reacquires_when_a_pending_plan_name_is_quotable(collector):
    rows = {"AAA": {"action": "Buy", "state": "unavailable", "quote_at": None}}
    assert _decide(collector, rows, {"AAA": _quote(10)}) is True


# A quote the engine would still refuse, or a name the plan does not trade,
# earns nothing.
@pytest.mark.parametrize(
    ("rows", "quotes"),
    [
        (
            {"AAA": {"action": "Buy", "state": "unavailable", "quote_at": None}},
            {"AAA": _quote(40)},
        ),
        ({"AAA": {"action": "Buy", "state": "unavailable", "quote_at": None}}, {}),
        (
            {"AAA": {"action": None, "state": "no_trade", "quote_at": None}},
            {"AAA": _quote(10)},
        ),
        (
            {"AAA": {"action": "Buy", "state": "execute", "quote_at": NOW.isoformat()}},
            {"AAA": _quote(10)},
        ),
    ],
)
def test_no_reacquire_without_a_quotable_pending_name(collector, rows, quotes):
    assert _decide(collector, rows, quotes) is False


# Fresh observations are rate limited and never requested at the end of a window.
def test_reacquire_is_rate_limited_and_respects_the_window(collector):
    rows = {"AAA": {"action": "Buy", "state": "unavailable", "quote_at": None}}
    collector._reacquired_at = time.monotonic()
    assert _decide(collector, rows, {"AAA": _quote(10)}) is False
    collector._reacquired_at = time.monotonic() - module.REACQUIRE_SECONDS - 1
    assert _decide(collector, rows, {"AAA": _quote(10)}) is True
    late = NOW.replace(minute=59, second=30)
    assert _decide(collector, rows, {"AAA": _quote(10, at=late)}, now=late) is False


# Outside a regular window, or when the latest observation cannot be read,
# nothing is scheduled.
def test_closed_or_unreadable_observation_schedules_nothing(collector):
    rows = {"AAA": {"action": "Buy", "state": "unavailable", "quote_at": None}}
    closed = NOW.replace(hour=20)
    assert _decide(collector, rows, {"AAA": _quote(10, at=closed)}, now=closed) is False
    with (
        patch.object(strategy_publication, "read", side_effect=ValueError("gone")),
    ):
        assert collector._pending_prices_now_quotable(NOW) is False


# The collect pass clears its cache so the next pass acquires a new observation.
def test_collect_pass_schedules_the_reacquire(tmp_path):
    collector = CurrentOpportunityCollector(tmp_path, enabled=False)
    collector._entry_cache["completed"] = "x"
    (tmp_path / strategy_publication.DIRECTORY).mkdir(parents=True)
    with (
        patch("backend.market.strategy_position_view.configured", return_value=False),
        patch("backend.market.strategy_entry_history.remember_latest"),
        patch.object(strategy_entries, "collect", return_value={"status": "collected"}),
        patch.object(
            CurrentOpportunityCollector,
            "_pending_prices_now_quotable",
            return_value=True,
        ),
    ):
        result = collector._collect_once()
    assert result["reacquire"] == "scheduled"
    assert collector._entry_cache == {}
    assert collector._reacquired_at is not None


# A fresh observation that cannot be acquired gives the window its previous
# one back.
def test_failed_reacquire_restores_the_previous_observation(tmp_path):
    collector = CurrentOpportunityCollector(tmp_path, enabled=False)
    collector._entry_cache.update({"completed": "x", "quotes": {}})
    (tmp_path / strategy_publication.DIRECTORY).mkdir(parents=True)
    outcomes = [
        {"status": "collected"},
        ValueError("acquire failed"),
        {"status": "collected"},
    ]

    def collect(root, cache):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            cache.clear()
            cache["failure"] = {"attempts": 1}
            raise outcome
        return outcome

    with (
        patch("backend.market.strategy_position_view.configured", return_value=False),
        patch("backend.market.strategy_entry_history.remember_latest"),
        patch.object(strategy_entries, "collect", side_effect=collect),
        patch.object(
            CurrentOpportunityCollector,
            "_pending_prices_now_quotable",
            return_value=True,
        ),
    ):
        assert collector._collect_once()["reacquire"] == "scheduled"
        assert collector._entry_cache == {}
        with pytest.raises(ValueError, match="acquire failed"):
            collector._collect_once()
        assert collector._entry_cache == {"completed": "x", "quotes": {}}
        assert collector._retained is None
