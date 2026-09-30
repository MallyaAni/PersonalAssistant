"""The paper account, the record and the board all follow `live_policy.ACTIVE`.

`live_policy` is the one place that says which allocation policy the paper
account runs: since 2026-09-29 `graded-equal-weight/5`, the equal-weight
book under a 25% cap. Its targets are the shadow ledger's decisions to the
byte, the record carries them for every graded name, the board sizes
against them, and a paper state planned under another policy rebalances
into them once - except a state planned under `/4`, which differs only in
the cap: that one keeps its book and clock, fills toward the new targets
through the redeploy, and is re-stamped `/5`.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import (
    event_risk,
    grading,
    intraday_orders,
    live_policy,
    paper,
    policy_v4,
    policy_v5,
    shadow_ledger,
)
from backend.cli import market_daily
from backend.tests.test_market_daily import _Broker, _report
from backend.tests.test_policy_v4 import _mask
from backend.tests.test_policy_v4 import _report as _wide_report


# The account and its shadow ask for the same book: identical weights on the
# same report, for every name, and the active policy is policy_v5, as a
# module and as a version.
def test_targets_match_the_shadow_ledgers_decision():
    report = _wide_report()
    assert live_policy.POLICY is policy_v5
    assert live_policy.ACTIVE == policy_v5.POLICY_VERSION == "graded-equal-weight/5"
    assert live_policy.targets(report) == shadow_ledger.decide(report)
    assert live_policy.targets(_report()) == shadow_ledger.decide(_report())


# The family: `/4` and `/5` by name, never by prefix, and the active policy
# is one of them. With no argument the question is about the active policy.
def test_the_equal_weight_family_is_named():
    assert live_policy.EQUAL_WEIGHT == (
        policy_v4.POLICY_VERSION,
        policy_v5.POLICY_VERSION,
    )
    assert live_policy.is_equal_weight()
    assert live_policy.is_equal_weight("graded-equal-weight/4")
    assert live_policy.is_equal_weight("graded-equal-weight/5")
    for other in ("graded-equal-weight/3", "graded-equal-weight/40", "", "x/5"):
        assert not live_policy.is_equal_weight(other), other


# The allocator the rules lines are priced with is the active policy's, row
# for row: /5's cap, not /4's.
def test_the_allocator_is_the_active_policys():
    report = _wide_report()
    mask = _mask()
    ours = live_policy.allocator(mask)
    capped = 0
    for t in range(len(report.panel.dates)):
        row = ours(report, report.panel, None, t)
        expected = policy_v5.allocator(mask)(report, report.panel, None, t)
        assert (row == expected).all(), t
        capped += int((row == policy_v5.HOLD_CAP).any())
    assert capped > 0, "the cap never bound: the check would be vacuous"


# The record block names every graded name, zero where the policy holds
# none, never the benchmark, weights in [0, 1] summing to at most one - the
# shape the board's decision view validates.
def test_record_targets_cover_every_graded_name():
    report = _wide_report()
    block = live_policy.record_targets(report)
    panel = report.panel
    assert block["policy"] == live_policy.ACTIVE
    assert set(block["weights"]) == {t for t in panel.tickers if t != panel.benchmark}
    assert all(
        0.0 <= w <= live_policy.POLICY.HOLD_CAP for w in block["weights"].values()
    )
    assert sum(block["weights"].values()) <= 1.0 + 1e-9
    held = {t: w for t, w in block["weights"].items() if w > 0}
    assert held == live_policy.targets(report)
    assert not live_policy.needs_rebalance(live_policy.ACTIVE)


# A cap change inside the equal-weight family moves the targets, not the
# book: a state stamped `/4` needs no forced rebalance under `/5`. The `/3`
# era (no stamp, or `/3`'s names) and anything unknown still do.
def test_needs_rebalance_only_outside_the_equal_weight_family():
    assert not live_policy.needs_rebalance("graded-equal-weight/5")
    assert not live_policy.needs_rebalance("graded-equal-weight/4")
    for stamp in (
        None,
        "",
        "graded-equal-weight/3",
        "cash-bounded-breakout-rotation/3",
        "graded-equal-weight/6",
        "graded-equal-weight/40",
    ):
        assert live_policy.needs_rebalance(stamp), stamp
    assert live_policy.same_book("graded-equal-weight/4")
    assert not live_policy.same_book(None)


# The exemption needs both ends in the family: were the account moved to a
# sizing policy, a `/4` or `/5` book would be forced into it like any other.
def test_the_family_exemption_needs_the_active_policy_in_it(monkeypatch):
    monkeypatch.setattr(live_policy, "ACTIVE", "some-sizing/9")
    assert not live_policy.is_equal_weight()
    assert live_policy.needs_rebalance("graded-equal-weight/4")
    assert live_policy.needs_rebalance("graded-equal-weight/5")
    assert not live_policy.needs_rebalance("some-sizing/9")


# The nightly record carries the active policy's targets beside the desk's
# `/3` book, and the curve block names the allocation policy and the
# executor's conventions separately.
def test_record_and_curve_block_name_the_active_policy():
    report = _report()
    record = market_daily.record(report)
    assert record["targets"]["policy"] == live_policy.ACTIVE
    assert set(record["targets"]["weights"]) == {"SNDK", "IREN"}
    # SNDK is the one A+ name: held at the cap, now a quarter of the book.
    assert record["targets"]["weights"]["SNDK"] == pytest.approx(
        live_policy.POLICY.HOLD_CAP
    )
    assert record["targets"]["weights"]["SNDK"] == pytest.approx(0.25)
    assert record["book"], "the /3 book stays on the record for reference"
    curve = market_daily.curve_block(report, None)
    if curve is not None:
        assert curve["strategy_policy"] == live_policy.ACTIVE
        assert curve["execution_policy"] == paper.POLICY_VERSION


# The board reads the active policy's weights as its book; a record from
# before the stamp keeps the book it has.
def test_board_sizes_against_the_active_targets():
    market_api = pytest.importorskip("backend.api.v1.market")
    old = {
        "grades": {"AAA": {"grade": "A"}},
        "book": [{"ticker": "AAA", "weight": 0.05}],
    }
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


# A broker for the forced-rebalance tests: a funded account holding nothing,
# so every target is a buy; every order it accepts fills at the reference
# price, so the rebalance clock is not rolled back by an unconfirmed
# rebalance. One broker across sessions, so yesterday's fills are found.
class _EmptyBroker:
    # Start with no orders on record.
    def __init__(self):
        self.orders = []

    # The account's value: all cash.
    def account(self):
        return SimpleNamespace(equity=100000, cash=100000)

    # Nothing held.
    def positions(self):
        return []

    # The market is shut, as it is at the nightly.
    def clock(self):
        return {"is_open": False}

    # Accept an order and report it filled at 100.
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
        # Closed for the nightly; the intraday leg's session opens it.
        is_open = False

        def clock(self):
            return {"is_open": self.is_open}

    # A next-open order.
    def submit_market_on_open(self, symbol, qty, side, client_order_id):
        return self._accept(symbol, qty, side, client_order_id)

    # A market-on-close order.
    def submit_market_on_close(self, symbol, qty, side, client_order_id):
        return self._accept(symbol, qty, side, client_order_id)

    # Every order this broker has seen.
    def orders_since(self, since):
        return self.orders

    # Cancelling is a no-op here.
    def cancel_orders(self, ids):
        return None
        # The intraday leg's in-session market order.
        def submit_market(self, symbol, qty, side, client_order_id):
            return self._accept(symbol, qty, side, client_order_id)

        def orders_since(self, since):
            return self.orders


# The ordinary-session calendar: no FOMC cycle, the calendar known.
def _no_event(monkeypatch):
    monkeypatch.setattr(
        event_risk,
        "decision",
        lambda panel: {
            "calendar_known": True,
            "factor": 1.0,
            "decision_date": "2026-09-16",
        },
    )


# A state planned under the `/3` era - no stamp, or a `/3` name - rebalances
# into the active policy's targets on its next plan, whatever the clock
# says; the saved state carries the stamp and the next session is not
# forced again.
@pytest.mark.parametrize(
    ("stamp", "said"),
    [
        (None, "unstamped (/3 era)"),
        ("graded-equal-weight/3", "graded-equal-weight/3"),
    ],
)
def test_a_v3_era_state_rebalances_once_into_the_active_policy(
    tmp_path, monkeypatch, capsys, stamp, said
):
    from backend.market import alpaca_trading

    broker = _EmptyBroker()
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: broker)
    _no_event(monkeypatch)
    # Rebalanced yesterday under the old policy: the clock alone would hold.
    paper.save_state(
        tmp_path,
        paper.PaperState(
            last_rebalance="2026-09-02",
            sessions_since_rebalance=1,
            policy_version=stamp,
        ),
    )
    report = _report()
    entry = market_daily.paper_trade(report, tmp_path, "2026-09-03", True)
    out = capsys.readouterr().out
    assert f"policy change: {said} -> graded-equal-weight/5" in out
    assert f"paper book ({live_policy.ACTIVE}; rebalance, forced tonight)" in out
    state = paper.load_state(tmp_path)
    assert state.policy_version == live_policy.ACTIVE == "graded-equal-weight/5"
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


# The switch night, as it will happen: a state stamped `/4`, rebalanced two
# sessions ago with SNDK (the one A+ name) at the 20% cap and 80% of the
# book in cash. Under `/5` there is no forced rebalance and no clock reset:
# the redeploy fills SNDK toward its new 25% target from the idle cash (50
# shares, the 5-point gap), and the saved state is re-stamped `/5`. Once
# that fills, SNDK sits at its target and the next session holds.
def test_a_v4_state_moves_to_v5_without_a_forced_rebalance(
    tmp_path, monkeypatch, capsys
):
    from backend.market import alpaca_trading

    broker = _Broker(cash=80_000.0, positions={"SNDK": 200})
    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: broker)
    _no_event(monkeypatch)
    paper.save_state(
        tmp_path,
        paper.PaperState(
            last_rebalance="2026-09-01",
            sessions_since_rebalance=1,
            policy_version="graded-equal-weight/4",
            rebalance_targets={"SNDK": 0.2},
        ),
    )
    report = _report()
    entry = market_daily.paper_trade(report, tmp_path, "2026-09-03", True)
    out = capsys.readouterr().out
    assert "policy change" not in out
    assert "forced tonight" not in out
    assert "paper book (graded-equal-weight/5; redeploy)" in out
    assert entry["plan"] == "redeploy"
    assert broker.sent == [("buy", "SNDK", 50)]
    assert [(o["symbol"], o["qty"], o["kind"]) for o in entry["orders"]] == [
        ("SNDK", 50, paper.REDEPLOY_KIND)
    ]
    state = paper.load_state(tmp_path)
    assert state.policy_version == "graded-equal-weight/5"
    # The reset clock is the account's own: nothing restarted it.
    assert state.last_rebalance == "2026-09-01"
    assert state.sessions_since_rebalance == 2
    assert state.rebalance_targets == {"SNDK": 0.2}
    # Filled overnight: 250 SNDK and 75,000 cash, SNDK at its 25% target.
    broker.held["SNDK"] = 250
    broker.cash = 75_000.0
    later = market_daily.paper_trade(report, tmp_path, "2026-09-04", True)
    out = capsys.readouterr().out
    assert "policy change" not in out
    assert later["orders"] == []
    assert later["plan"] == "hold"
    assert later["idle_cash_share"] == pytest.approx(0.75)
    assert paper.load_state(tmp_path).policy_version == "graded-equal-weight/5"


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
