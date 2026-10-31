"""The check that makes a stalled intraday board loud."""

import json
from datetime import UTC, datetime

import pytest

from backend.cli import market_intraday_health as health


# The market store the check writes its verdict under.
def _market(tmp_path):
    market = tmp_path / "data" / "market"
    market.mkdir(parents=True)
    return market


# The board's plan, as the balancer writes it.
def _plan(market, *, as_of="2026-11-02T14:45:00+00:00", session="2026-10-30"):
    desk = market / "desk"
    desk.mkdir(parents=True, exist_ok=True)
    (desk / "intraday.json").write_text(
        json.dumps({"as_of": as_of, "session": session, "top_buys": []})
    )


# A previous verdict, so the page cooldown has something to read.
def _previous(market, *, status="failed", last_page_at=None):
    desk = market / "desk"
    desk.mkdir(parents=True, exist_ok=True)
    (desk / "intraday-health.json").write_text(
        json.dumps({"status": status, "last_page_at": last_page_at})
    )


# 10:00 ET on Monday 2026-11-02, inside the regular session.
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def test_a_fresh_plan_is_green(tmp_path):
    market = _market(tmp_path)
    _plan(market)
    messages = []
    result = health.check(tmp_path, NOW, notify=messages.append)
    assert result["status"] == "ok"
    assert result["reasons"] == []
    assert messages == []
    written = json.loads((market / "desk" / "intraday-health.json").read_text())
    assert written["status"] == "ok"
    assert written["checks"]["plan_age_minutes"] == 15.0


def test_a_stale_plan_pages(tmp_path):
    market = _market(tmp_path)
    _plan(market, as_of="2026-11-02T14:00:00+00:00")
    messages = []
    result = health.check(tmp_path, NOW, notify=messages.append)
    assert result["status"] == "failed"
    assert "intraday plan is stale" in result["reasons"][0]
    assert messages
    assert "intraday board is stale" in messages[0]
    written = json.loads((market / "desk" / "intraday-health.json").read_text())
    assert written["status"] == "failed"
    assert written["checks"]["last_page_at"] == NOW.isoformat()


def test_a_missing_plan_pages(tmp_path):
    _market(tmp_path)
    result = health.check(tmp_path, NOW, notify=lambda _: None)
    assert result["status"] == "failed"
    assert "intraday plan missing" in result["reasons"]


def test_an_unreadable_plan_pages(tmp_path):
    market = _market(tmp_path)
    desk = market / "desk"
    desk.mkdir(parents=True, exist_ok=True)
    (desk / "intraday.json").write_text("not json")
    result = health.check(tmp_path, NOW, notify=lambda _: None)
    assert result["status"] == "failed"
    assert "intraday plan unreadable" in result["reasons"]


def test_a_plan_without_a_timezone_pages(tmp_path):
    market = _market(tmp_path)
    _plan(market, as_of="2026-11-02T14:45:00")
    result = health.check(tmp_path, NOW, notify=lambda _: None)
    assert result["status"] == "failed"
    assert "has no timezone" in result["reasons"][0]


def test_a_future_plan_pages(tmp_path):
    market = _market(tmp_path)
    _plan(market, as_of="2026-11-02T15:10:00+00:00")
    result = health.check(tmp_path, NOW, notify=lambda _: None)
    assert result["status"] == "failed"
    assert "is in the future" in result["reasons"][0]


def test_outside_the_session_is_green(tmp_path):
    market = _market(tmp_path)
    _plan(market, as_of="2026-11-02T14:00:00+00:00")
    messages = []
    close = datetime(2026, 11, 2, 21, 0, tzinfo=UTC)
    result = health.check(tmp_path, close, notify=messages.append)
    assert result["status"] == "ok"
    assert result["checks"]["session_open"] is False
    assert messages == []
    assert (market / "desk" / "intraday-health.json").exists()


def test_a_non_session_day_is_green(tmp_path):
    _market(tmp_path)
    saturday = datetime(2026, 10, 31, 16, 0, tzinfo=UTC)
    result = health.check(tmp_path, saturday, notify=lambda _: None)
    assert result["status"] == "ok"
    assert result["checks"]["session_open"] is False


def test_a_red_verdict_pages_again_after_the_cooldown(tmp_path):
    market = _market(tmp_path)
    _plan(market, as_of="2026-11-02T14:00:00+00:00")
    _previous(market, last_page_at="2026-11-02T13:00:00+00:00")
    messages = []
    result = health.check(tmp_path, NOW, notify=messages.append)
    assert result["status"] == "failed"
    assert len(messages) == 1
    assert result["checks"]["last_page_at"] == NOW.isoformat()


def test_a_red_verdict_is_quiet_inside_the_cooldown(tmp_path):
    market = _market(tmp_path)
    _plan(market, as_of="2026-11-02T14:00:00+00:00")
    _previous(market, last_page_at="2026-11-02T14:30:00+00:00")
    messages = []
    result = health.check(tmp_path, NOW, notify=messages.append)
    assert result["status"] == "failed"
    assert messages == []
    assert result["checks"]["last_page_at"] == "2026-11-02T14:30:00+00:00"


def test_a_green_verdict_then_red_pages(tmp_path):
    market = _market(tmp_path)
    _plan(market, as_of="2026-11-02T14:00:00+00:00")
    _previous(market, status="ok", last_page_at=None)
    messages = []
    result = health.check(tmp_path, NOW, notify=messages.append)
    assert result["status"] == "failed"
    assert len(messages) == 1
    assert result["checks"]["last_page_at"] == NOW.isoformat()


def test_a_naive_instant_is_refused(tmp_path):
    _market(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        health.check(
            tmp_path,
            datetime(2026, 11, 2, 15, 0),
            notify=lambda _: None,
        )
