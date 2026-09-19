"""Prove isolated capital, delayed fills, and immutable forward account records."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.market import board_paper

NOW = datetime(2026, 9, 14, 18, 30, tzinfo=UTC)


# Give the simulator explicit quote evidence with a bounded expiry.
def inputs(now, action="Buy", weight=0.1):
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
        decisions["rows"]["AAPL"]["action"] = "Hold"
    result = board_paper.transition(row, decisions, research, later)
    assert result["fills"] == []
    assert result["pending"] == {}
    assert result["cash"] == 1000


# Repeated collection of a candle cannot duplicate a journal record or a fill.
def test_observer_is_idempotent_and_uses_shared_planner(tmp_path, monkeypatch):
    board_paper.initialize(tmp_path, 1000, NOW - timedelta(minutes=15))
    decisions, research = inputs(NOW, action="Hold")
    monkeypatch.setattr(
        board_paper.desk_freshness, "describe", lambda snapshot, now: {"stale": False}
    )
    monkeypatch.setattr(
        board_paper.event_status, "for_planning", lambda record, root: record
    )
    monkeypatch.setattr(
        board_paper.decision_view, "build", lambda *args, **kwargs: decisions
    )
    first = board_paper.observe(tmp_path, {}, {}, research, NOW)
    second = board_paper.observe(tmp_path, {}, {}, research, NOW)
    assert first == second == board_paper.latest(tmp_path)
    assert first["decisions"]["AAPL"]["action"] == "Hold"
    assert first["cash"] == 1000
    assert len(list((tmp_path / "desk/board-paper").glob("*.json"))) == 2


# A held position crosses sessions using fresh actions even before today's close.
def test_overnight_position_marks_and_splits_once(tmp_path, monkeypatch):
    from backend.market.yahoo import CorporateAction, TickerHistory

    previous = NOW - timedelta(days=1)
    state = board_paper.initialize(tmp_path, 1000, previous)
    state.update(
        sequence=1,
        cash=900,
        positions={
            "AAPL": {
                "shares": 1,
                "entry_price": 100,
                "mark": 100,
                "entry_date": "2026-09-11",
            }
        },
        bar="old",
    )
    board_paper.append(tmp_path / "desk/board-paper", state)
    calls = []

    # Record a current provider observation whose daily bars still end yesterday.
    def fetch(symbol, start, end, **kwargs):
        calls.append(symbol)
        return TickerHistory(
            symbol,
            (),
            (
                CorporateAction(NOW.date(), "split", 2),
                CorporateAction(NOW.date(), "dividend", 1),
            ),
            previous.date(),
            NOW,
        )

    monkeypatch.setattr("backend.market.yahoo.fetch_history", fetch)
    decisions, research = inputs(NOW, action="Hold")
    snapshot = {
        "as_of": NOW.isoformat(),
        "quotes": {"AAPL": {"last": 40, "bar": research["bar"]}},
    }
    monkeypatch.setattr(
        board_paper.event_status, "for_planning", lambda record, root: record
    )
    monkeypatch.setattr(
        board_paper.decision_view, "build", lambda *args, **kwargs: decisions
    )
    result = board_paper.observe(tmp_path, {}, snapshot, research, NOW)
    assert result["equity"] == 982
    assert result["receivables"] == 2
    assert result["positions"]["AAPL"]["shares"] == 2
    assert result["positions"]["AAPL"]["entry_price"] == 50
    assert board_paper.latest(tmp_path) == result
    assert board_paper.observe(tmp_path, {}, snapshot, research, NOW) == result
    assert calls == ["AAPL"]


# Both trade directions follow the same experimental target used to size the fill.
@pytest.mark.parametrize(
    ("nightly", "target", "action"),
    [(0.10, 0.02, "Sell"), (0.03, 0.10, "Buy")],
)
def test_paper_direction_matches_selected_target(tmp_path, nightly, target, action):
    from backend.market import decision_view, holdings
    from backend.tests.test_decision_view import setup

    record, snapshot, quoted, now = setup()
    record["book"][0]["weight"] = nightly
    targets = {ticker: target if ticker == "S11" else 0 for ticker in record["grades"]}
    held = [holdings.Holding("S11", 60, 100, "2026-09-14")]
    decisions = decision_view.build(
        record, held, 100000, snapshot, quoted, now, targets
    )
    assert decisions["rows"]["S11"]["action"] == action
    state = board_paper.initialize(tmp_path, 100000, now - timedelta(minutes=15))
    state.update(
        cash=94000,
        positions={
            "S11": {
                "shares": 60,
                "mark": 100,
                "entry_price": 100,
                "entry_date": "2026-09-14",
            }
        },
        pending={"S11": {"action": action, "weight": target}},
    )
    research = {
        "status": "available",
        "targets": targets,
        "valid_until": (now + timedelta(minutes=15)).isoformat(),
    }
    result = board_paper.transition(state, decisions, research, now)
    board_paper.append(tmp_path / "desk/board-paper", result)
    saved = board_paper.latest(tmp_path)
    assert saved["fills"][0]["side"] == ("sell" if action == "Sell" else "buy")
    assert (saved["positions"]["S11"]["shares"] < 60) == (action == "Sell")


# A failed corporate-action provider cannot silently move or corrupt the ledger.
def test_overnight_provider_failure_preserves_ledger(tmp_path, monkeypatch):
    state = board_paper.initialize(tmp_path, 1000, NOW - timedelta(days=1))
    state.update(
        sequence=1,
        cash=900,
        positions={
            "AAPL": {
                "shares": 1,
                "mark": 100,
                "entry_price": 100,
                "entry_date": "2026-09-11",
            }
        },
        bar="old",
    )
    board_paper.append(tmp_path / "desk/board-paper", state)

    # Model an unavailable provider without issuing a network request.
    def fail(*args, **kwargs):
        raise ValueError("Provider unavailable")

    monkeypatch.setattr(board_paper.forward_actions, "current", fail)
    _, research = inputs(NOW)
    snapshot = {
        "as_of": NOW.isoformat(),
        "quotes": {"AAPL": {"last": 80, "bar": research["bar"]}},
    }
    with pytest.raises(ValueError, match="Provider unavailable"):
        board_paper.observe(tmp_path, {}, snapshot, research, NOW)
    assert board_paper.latest(tmp_path) == state
