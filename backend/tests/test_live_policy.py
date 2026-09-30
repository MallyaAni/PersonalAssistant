"""The paper account, the record and the board all follow `live_policy.ACTIVE`.

`live_policy` is the one place that says which allocation policy the paper
account runs. Its targets are the shadow ledger's decisions to the byte, the
record carries them for every graded name, the board sizes against them,
and a paper state planned under another policy rebalances into them once.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import (
    event_risk,
    grading,
    intraday_orders,
    live_policy,
    paper,
    policy_v4,
    shadow_ledger,
)
from backend.cli import market_daily
from backend.tests.test_market_daily import _report
from backend.tests.test_policy_v4 import _report as _wide_report


# The account and its shadow ask for the same book: identical weights on the
# same report, for every name, and the active version is policy_v4's.
def test_targets_match_the_shadow_ledgers_decision():
    report = _wide_report()
    assert live_policy.ACTIVE == policy_v4.POLICY_VERSION == "graded-equal-weight/4"
    assert live_policy.targets(report) == shadow_ledger.decide(report)
    assert live_policy.targets(_report()) == shadow_ledger.decide(_report())


# The record block names every graded name, zero where the policy holds
# none, never the benchmark, weights in [0, 1] summing to at most one - the
# shape the board's decision view validates.
def test_record_targets_cover_every_graded_name():
    report = _wide_report()
    block = live_policy.record_targets(report)
    panel = report.panel
    assert block["policy"] == live_policy.ACTIVE
    assert set(block["weights"]) == {t for t in panel.tickers if t != panel.benchmark}
    assert all(0.0 <= w <= policy_v4.HOLD_CAP for w in block["weights"].values())
    assert sum(block["weights"].values()) <= 1.0 + 1e-9
    held = {t: w for t, w in block["weights"].items() if w > 0}
    assert held == live_policy.targets(report)
    assert live_policy.needs_rebalance(None)
    assert live_policy.needs_rebalance("cash-bounded-breakout-rotation/3")
    assert not live_policy.needs_rebalance(live_policy.ACTIVE)


# The nightly record carries the active policy's targets beside the desk's
# `/3` book, and the curve block names the allocation policy and the
# executor's conventions separately.
def test_record_and_curve_block_name_the_active_policy():
    report = _report()
    record = market_daily.record(report)
    assert record["targets"]["policy"] == live_policy.ACTIVE
    assert set(record["targets"]["weights"]) == {"SNDK", "IREN"}
    assert record["targets"]["weights"]["SNDK"] == pytest.approx(policy_v4.HOLD_CAP)
    assert record["book"], "the /3 book stays on the record for reference"
    curve = market_daily.curve_block(report, None)
    if curve is not None:
        assert curve["strategy_policy"] == live_policy.ACTIVE
        assert curve["execution_policy"] == paper.POLICY_VERSION


# The board reads the active policy's weights as its book; a record from
# before the stamp keeps the book it has.
def test_board_sizes_against_the_active_targets():
    market_api = pytest.importorskip("backend.api.v1.market")
    old = {"grades": {"AAA": {"grade": "A"}}, "book": [{"ticker": "AAA", "weight": 0.05}]}
    assert market_api._with_active_targets(old) is old
    record = {
        **old,
        "targets": {"policy": live_policy.ACTIVE, "weights": {"AAA": 0.2, "BBB": 0.0}},
    }
    swapped = market_api._with_active_targets(record)
    assert swapped["book"] == [
        {"ticker": "AAA", "weight": 0.2, "grade": "A", "policy": live_policy.ACTIVE}
    ]
    assert record["book"][0]["weight"] == 0.05, "the record itself is untouched"


# A state planned under the `/3` era (no stamp) rebalances into the active
# policy's targets on its next plan, whatever the clock says; the saved
# state carries the stamp and the next session is not forced again.
def test_unstamped_state_rebalances_once_into_the_active_policy(tmp_path, monkeypatch, capsys):
    from backend.market import alpaca_trading

    class Broker:
        # A funded account holding nothing, so every target is a buy; every
        # order it accepts fills at the reference price, so the rebalance
        # clock is not rolled back by an unconfirmed rebalance.
        def __init__(self):
            self.orders = []

        def account(self):
            return SimpleNamespace(equity=100000, cash=100000)

        def positions(self):
            return []

        # Closed for the nightly; the intraday leg's session opens it.
        is_open = False

        def clock(self):
            return {"is_open": self.is_open}

        def _accept(self, symbol, qty, side, client_order_id):
            self.orders.append(
                {
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "qty": qty,
                    "side": side,
                    "status": "filled",
                    "filled_qty": qty,
                    "filled_avg_price": 100.0,
                }
            )
            return {"submitted_at": "2026-09-04T00:01:02Z", "time_in_force": "day"}

        def submit_market_on_open(self, symbol, qty, side, client_order_id):
            return self._accept(symbol, qty, side, client_order_id)

        def submit_market_on_close(self, symbol, qty, side, client_order_id):
            return self._accept(symbol, qty, side, client_order_id)

        # The intraday leg's in-session market order.
        def submit_market(self, symbol, qty, side, client_order_id):
            return self._accept(symbol, qty, side, client_order_id)

        def orders_since(self, since):
            return self.orders

        def cancel_orders(self, ids):
            return None

    broker = Broker()  # one broker across sessions, so yesterday's fills are found
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: broker)
    monkeypatch.setattr(
        event_risk,
        "decision",
        lambda panel: {"calendar_known": True, "factor": 1.0, "decision_date": "2026-09-16"},
    )
    # Rebalanced yesterday under the old policy: the clock alone would hold.
    paper.save_state(tmp_path, paper.PaperState(last_rebalance="2026-09-02", sessions_since_rebalance=1))
    report = _report()
    entry = market_daily.paper_trade(report, tmp_path, "2026-09-03", True)
    out = capsys.readouterr().out
    assert "policy change: unstamped (/3 era) -> graded-equal-weight/4" in out
    assert f"paper book ({live_policy.ACTIVE}; rebalance, forced tonight)" in out
    state = paper.load_state(tmp_path)
    assert state.policy_version == live_policy.ACTIVE
    assert state.last_rebalance == "2026-09-03"
    # The orders are the active policy's: SNDK is the one A+ name, so it is
    # bought at the cap and nothing else is. They are planned for the next
    # session on the board's rule and sent then by the intraday leg (here in
    # its close window), which fills them.
    bought = {o["symbol"] for o in entry["planned"] if o["side"] == "buy"}
    assert bought == {"SNDK"}
    assert entry["orders"] == []
    broker.is_open = True
    intraday_orders.send_due(
        tmp_path, {}, datetime(2026, 9, 4, 19, 35, tzinfo=UTC), lambda: broker
    )
    broker.is_open = False
    assert {o["symbol"] for o in broker.orders} == {"SNDK"}
    # Stamped now: the next session is an ordinary day, not a forced rebalance.
    market_daily.paper_trade(report, tmp_path, "2026-09-04", True)
    out = capsys.readouterr().out
    assert "policy change" not in out
    assert paper.load_state(tmp_path).last_rebalance == "2026-09-03"


# A session that cannot rebalance - here an FOMC cycle routes the plan
# through the event path - leaves the state unstamped, so the rebalance
# into the active policy is forced again on the next ordinary session.
def test_a_session_that_cannot_rebalance_keeps_the_old_stamp(tmp_path, monkeypatch, capsys):
    from backend.market import alpaca_trading

    class Broker:
        def account(self):
            return SimpleNamespace(equity=100000, cash=100000)

        def positions(self):
            return []

        def clock(self):
            return {"is_open": False}

        def submit_market_on_open(self, *args):
            return {"submitted_at": "2026-09-04T00:01:02Z", "time_in_force": "day"}

        def submit_market_on_close(self, *args):
            return {"submitted_at": "2026-09-04T00:01:02Z", "time_in_force": "day"}

        def orders_since(self, since):
            return []

        def cancel_orders(self, ids):
            return None

    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: Broker())
    monkeypatch.setattr(
        event_risk,
        "decision",
        lambda panel: {"calendar_known": True, "factor": event_risk.REDUCED, "decision_date": "2026-09-16"},
    )
    paper.save_state(tmp_path, paper.PaperState(last_rebalance="2026-09-02", sessions_since_rebalance=1))
    market_daily.paper_trade(_report(), tmp_path, "2026-09-03", True)
    out = capsys.readouterr().out
    assert "policy change" in out
    state = paper.load_state(tmp_path)
    assert state.policy_version is None
    assert state.last_rebalance == "2026-09-02"
