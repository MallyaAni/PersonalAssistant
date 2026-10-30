"""The preflight and health checks that make a silent nightly loud."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk.paper import PaperState
from backend.cli import market_nightly_check as check
from backend.market import alpaca_trading


# The market store the checks write their verdict under.
def _market(tmp_path):
    market = tmp_path / "data" / "market"
    market.mkdir(parents=True)
    return market


# A broker whose account, positions and clock the test controls.
class _Broker:
    def __init__(self, *, is_open=False, equity=100.0, cash=50.0, positions=()):
        self.is_open = is_open
        self.equity = equity
        self.cash = cash
        self.held = list(positions)

    def clock(self):
        return {
            "is_open": self.is_open,
            "next_open": "2026-11-02T09:30:00-05:00",
            "next_close": "2026-11-02T16:00:00-05:00",
        }

    def account(self):
        return SimpleNamespace(equity=self.equity, cash=self.cash)

    def positions(self):
        return self.held


# One position, as the broker reports it.
def _position(symbol="AAA", qty=1.0, market_value=50.0):
    return SimpleNamespace(symbol=symbol, qty=qty, market_value=market_value)


# 19:30 ET on Friday 2026-10-30, the nightly's decision window.
NOW = datetime(2026, 10, 30, 23, 30, tzinfo=UTC)


# A state whose last book is today's and whose receipt is available.
def _healthy_state(**overrides):
    history = {
        "session": "2026-10-30",
        "written": "2026-10-30T23:49:00+00:00",
        "plan": "joint-funded",
        "refused": [],
    }
    history.update(overrides.pop("history", {}))
    receipt = {"status": "available", "reason": None}
    receipt.update(overrides.pop("receipt", {}))
    return PaperState(
        history=[history],
        allocation_state={"receipt": receipt},
        **overrides,
    )


# The health check reads the publication and log the nightly wrote.
def _publish(market, session="2026-10-30"):
    desk = market / "desk" / "strategy-recommendations"
    desk.mkdir(parents=True, exist_ok=True)
    (desk / "latest.json").write_text(json.dumps({"session": session}))


# A log whose last paper-book line is the one the health check reads.
def _log(tmp_path, *lines):
    path = tmp_path / "desk_daily.log"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_preflight_passes_and_writes_the_verdict(tmp_path):
    market = _market(tmp_path)
    messages = []
    result = check.preflight(
        tmp_path,
        NOW,
        client=_Broker(),
        admission=lambda: {"status": "ADMITTED"},
        notify=messages.append,
    )
    assert result["status"] == "ok"
    assert result["reasons"] == []
    assert messages == []
    written = json.loads((market / "desk" / "nightly-readiness.json").read_text())
    assert written["status"] == "ok"
    assert written["checks"]["admission"] == "ADMITTED"
    assert written["checks"]["market_clock"]["is_open"] is False


def test_preflight_fails_when_admission_is_not_admitted(tmp_path):
    _market(tmp_path)
    messages = []
    result = check.preflight(
        tmp_path,
        NOW,
        client=_Broker(),
        admission=lambda: {"status": "REFUSED"},
        notify=messages.append,
    )
    assert result["status"] == "failed"
    assert "trading admission REFUSED" in result["reasons"]
    assert messages
    assert "preflight failed" in messages[0]


def test_preflight_fails_when_the_broker_clock_says_open(tmp_path):
    _market(tmp_path)
    result = check.preflight(
        tmp_path,
        NOW,
        client=_Broker(is_open=True),
        admission=lambda: {"status": "ADMITTED"},
        notify=lambda _: None,
    )
    assert result["status"] == "failed"
    assert any("market open" in reason for reason in result["reasons"])


def test_preflight_fails_when_marks_do_not_reconcile(tmp_path):
    _market(tmp_path)
    result = check.preflight(
        tmp_path,
        NOW,
        client=_Broker(positions=[_position(market_value=60.0)]),
        admission=lambda: {"status": "ADMITTED"},
        notify=lambda _: None,
    )
    assert result["status"] == "failed"
    assert "funded account guard: inconsistent_account_equity" in result["reasons"]


def test_preflight_fails_when_the_broker_cannot_be_reached(tmp_path, monkeypatch):
    _market(tmp_path)

    def _refuse():
        raise alpaca_trading.AlpacaTradingError("no key")

    monkeypatch.setattr(alpaca_trading, "client_from_env", _refuse)
    result = check.preflight(
        tmp_path,
        NOW,
        admission=lambda: {"status": "ADMITTED"},
        notify=lambda _: None,
    )
    assert result["status"] == "failed"
    assert any("broker client unavailable" in reason for reason in result["reasons"])


def test_health_passes_on_a_written_book(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    messages = []
    result = check.health(
        tmp_path,
        NOW,
        log_path=_log(
            tmp_path,
            "paper book (grade-led-leader-weight/1; joint-funded), equity 100000",
        ),
        state=_healthy_state(),
        notify=messages.append,
    )
    assert result["status"] == "ok"
    assert result["reasons"] == []
    assert messages == []
    written = json.loads((market / "desk" / "nightly-health.json").read_text())
    assert written["status"] == "ok"


def test_health_fails_when_today_was_not_written(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    state = _healthy_state(history={"session": "2026-10-29"})
    result = check.health(
        tmp_path, NOW, log_path=None, state=state, notify=lambda _: None
    )
    assert result["status"] == "failed"
    assert "today's book was not written (last session 2026-10-29)" in result["reasons"]


def test_health_fails_on_an_unavailable_receipt(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    state = _healthy_state(
        receipt={"status": "unavailable", "reason": "inconsistent_account_equity"}
    )
    result = check.health(
        tmp_path, NOW, log_path=None, state=state, notify=lambda _: None
    )
    assert result["status"] == "failed"
    assert (
        "funded receipt unavailable: inconsistent_account_equity"
        in result["reasons"]
    )


def test_health_fails_on_the_unavailable_plan_note(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    state = _healthy_state(history={"plan": "joint-funded-unavailable"})
    result = check.health(
        tmp_path, NOW, log_path=None, state=state, notify=lambda _: None
    )
    assert result["status"] == "failed"
    assert "plan note joint-funded-unavailable" in result["reasons"]


def test_health_fails_on_a_not_traded_log_line(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    log = _log(
        tmp_path,
        "paper book: not traded "
        "(ValueError: Exact reviewed learned holding release required)",
    )
    result = check.health(
        tmp_path, NOW, log_path=log, state=_healthy_state(), notify=lambda _: None
    )
    assert result["status"] == "failed"
    assert any("not traded" in reason for reason in result["reasons"])


def test_health_reads_the_last_paper_book_line_only(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    log = _log(
        tmp_path,
        "paper book: not traded "
        "(ValueError: Exact reviewed learned holding release required)",
        "paper book (grade-led-leader-weight/1; joint-funded), equity 100000",
    )
    result = check.health(
        tmp_path, NOW, log_path=log, state=_healthy_state(), notify=lambda _: None
    )
    assert result["status"] == "ok"


def test_health_fails_on_refused_orders(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    state = _healthy_state(history={"refused": ["SELL SMCI: qty below one share"]})
    result = check.health(
        tmp_path, NOW, log_path=None, state=state, notify=lambda _: None
    )
    assert result["status"] == "failed"
    assert any("1 order(s) refused" in reason for reason in result["reasons"])


def test_health_fails_when_the_publication_is_missing(tmp_path):
    _market(tmp_path)
    result = check.health(
        tmp_path, NOW, log_path=None, state=_healthy_state(), notify=lambda _: None
    )
    assert result["status"] == "failed"
    assert "strategy publication missing" in result["reasons"]


def test_health_fails_when_the_publication_is_stale(tmp_path):
    market = _market(tmp_path)
    _publish(market, session="2026-10-29")
    result = check.health(
        tmp_path, NOW, log_path=None, state=_healthy_state(), notify=lambda _: None
    )
    assert result["status"] == "failed"
    assert "strategy publication is for 2026-10-29, not today" in result["reasons"]


def test_health_is_green_on_a_non_session_day(tmp_path):
    _market(tmp_path)
    saturday = datetime(2026, 10, 31, 16, 0, tzinfo=UTC)
    result = check.health(
        tmp_path,
        saturday,
        log_path=None,
        state=PaperState(),
        notify=lambda _: None,
    )
    assert result["status"] == "ok"
    assert result["checks"]["session_open"] is False


def test_health_reports_a_red_verdict_in_the_log(tmp_path):
    market = _market(tmp_path)
    _publish(market)
    state = _healthy_state(
        receipt={"status": "unavailable", "reason": "inconsistent_account_equity"}
    )
    result = check.health(
        tmp_path, NOW, log_path=None, state=state, notify=lambda _: None
    )
    assert result["status"] == "failed"
    written = json.loads((market / "desk" / "nightly-health.json").read_text())
    assert written["status"] == "failed"
    assert written["reasons"] == result["reasons"]


def test_a_naive_instant_is_refused(tmp_path):
    _market(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        check.health(
            tmp_path,
            datetime(2026, 10, 30, 23, 30),
            log_path=None,
            state=_healthy_state(),
            notify=lambda _: None,
        )
