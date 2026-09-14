"""Prove isolated capital, delayed fills, and immutable forward account records."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.market import board_paper

NOW = datetime(2026, 9, 14, 18, 30, tzinfo=UTC)


# Give the simulator explicit quote evidence with a bounded expiry.
def inputs(now, action="Buy eligible", weight=0.1):
    quote = {
        "eligible": True,
        "at": now.isoformat(),
        "bid": 99,
        "ask": 100,
        "bid_size": 100,
        "ask_size": 100,
    }
    decisions = {
        "rows": {
            "AAPL": {
                "action": action,
                "quote": quote,
                "valid_until": (now + timedelta(seconds=30)).isoformat(),
            }
        }
    }
    research = {
        "status": "available",
        "targets": {"AAPL": weight},
        "valid_until": (now + timedelta(minutes=15)).isoformat(),
        "bar": (now - timedelta(minutes=15)).isoformat(),
    }
    return decisions, research


# Initialize in cash without resetting an existing run or another account.
def test_new_account_is_cash_and_preserves_other_accounts(tmp_path):
    other = tmp_path / "paper/state.json"
    other.parent.mkdir()
    other.write_text('"original"')
    row = board_paper.initialize(tmp_path, 1000, NOW)
    assert board_paper.latest(tmp_path) == row
    assert row["cash"] == row["equity"] == 1000
    assert row["positions"] == {}
    with pytest.raises(ValueError, match="already exists"):
        board_paper.initialize(tmp_path, 2000)
    assert other.read_text() == '"original"'
    assert len(list((tmp_path / "desk/board-paper").glob("*.json"))) == 1


# A signal cannot fill itself; the next quote pays spread and added slippage in cash.
def test_delayed_fill_and_cash_debit_are_persisted_together(tmp_path):
    row = board_paper.initialize(tmp_path, 1000, NOW - timedelta(minutes=15))
    decisions, research = inputs(NOW, weight=0.5)
    first = board_paper.transition(row, decisions, research, NOW)
    assert first["fills"] == []
    board_paper.append(tmp_path / "desk/board-paper", first)
    later = NOW + timedelta(minutes=15)
    decisions, research = inputs(later, weight=0.5)
    second = board_paper.transition(first, decisions, research, later)
    board_paper.append(tmp_path / "desk/board-paper", second)
    saved = board_paper.latest(tmp_path)
    assert saved["positions"]["AAPL"]["shares"] == 4
    assert saved["fills"][0]["price"] == pytest.approx(100.1)
    assert saved["cash"] == pytest.approx(599.6)
    assert saved["equity"] == pytest.approx(995.6)
    assert len(list((tmp_path / "desk/board-paper").glob("*.json"))) == 3


# A changed gate cancels the intent instead of manufacturing a profitable fill.
@pytest.mark.parametrize("blocked", ["pause", "quote", "expired", "wait"])
def test_revalidation_blocks_previous_intent(tmp_path, blocked):
    row = board_paper.initialize(tmp_path, 1000, NOW)
    decisions, research = inputs(NOW)
    row = board_paper.transition(row, decisions, research, NOW)
    later = NOW + timedelta(minutes=15)
    decisions, research = inputs(later)
    if blocked == "pause":
        research["event_paused"] = True
    elif blocked == "quote":
        decisions["rows"]["AAPL"]["quote"]["eligible"] = False
    elif blocked == "expired":
        research["valid_until"] = NOW.isoformat()
    else:
        decisions["rows"]["AAPL"]["action"] = "Wait"
    result = board_paper.transition(row, decisions, research, later)
    assert result["fills"] == []
    assert result["pending"] == {}
    assert result["cash"] == 1000


# Repeated collection of a candle cannot duplicate a journal record or a fill.
def test_observer_is_idempotent_and_uses_shared_planner(tmp_path, monkeypatch):
    board_paper.initialize(tmp_path, 1000, NOW - timedelta(minutes=15))
    decisions, research = inputs(NOW, action="Wait")
    monkeypatch.setattr(
        board_paper.desk_freshness, "describe", lambda snapshot, now: {"stale": False}
    )
    monkeypatch.setattr(
        board_paper.event_status, "for_planning", lambda record, root: record
    )
    monkeypatch.setattr(board_paper.decision_view, "build", lambda *args: decisions)
    first = board_paper.observe(tmp_path, {}, {}, research, NOW)
    second = board_paper.observe(tmp_path, {}, {}, research, NOW)
    assert first == second == board_paper.latest(tmp_path)
    assert first["decisions"]["AAPL"]["action"] == "Wait"
    assert first["cash"] == 1000
    assert len(list((tmp_path / "desk/board-paper").glob("*.json"))) == 2
