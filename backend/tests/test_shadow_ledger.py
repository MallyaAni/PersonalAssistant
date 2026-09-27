"""The /4 shadow ledger: fills, cash, marks, idempotency and the frozen identity.

Three sessions on a two-name book whose prices are chosen by hand, so every
number the ledger writes can be checked with arithmetic: the first close
decides whole-share targets, the next open fills them at ten basis points
from cash that never goes negative, the close marks the book and the day's
return follows. Observing the same session twice appends nothing, and a
changed code identity without a declared migration refuses to continue.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import grading, policy_v4, regime, shadow_ledger
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NOW = datetime(2026, 9, 26, 23, 30, tzinfo=UTC)
# Sessions and the prices the journey is checked against.
SESSIONS = ("2026-09-24", "2026-09-25", "2026-09-28")
OPENS = {
    "AAA": (100.0, 102.0, 101.0),
    "BBB": (50.0, 49.0, 52.0),
    "SPY": (400.0, 401.0, 402.0),
}
CLOSES = {
    "AAA": (100.0, 104.0, 103.0),
    "BBB": (50.0, 48.0, 51.0),
    "SPY": (400.0, 402.0, 403.0),
}


# A desk report ending on session `k`, both names graded A+ unless `grades`
# says otherwise.
def _report(k: int, grades: dict | None = None) -> DeskReport:
    t, n = k + 1, 2
    tickers = ("AAA", "BBB", "SPY")
    dates = np.array([np.datetime64(s) for s in SESSIONS[:t]], dtype="datetime64[D]")
    close = np.array([[CLOSES[s][i] for s in tickers] for i in range(t)])
    opens = np.array([[OPENS[s][i] for s in tickers] for i in range(t)])
    panel = Panel(
        dates=dates,
        tickers=tickers,
        open=opens,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={"AAA": (AI_COMPUTE,), "BBB": (AI_COMPUTE,)},
        benchmark="SPY",
    )
    letters = {"AAA": "A+", "BBB": "A+", **(grades or {})}
    row = [grading.ORDINAL[letters[s]] if s != "SPY" else 0 for s in tickers]
    grade_matrix = np.array([row] * t)
    graded = grading.Graded(grade_matrix, grade_matrix.astype(float), {})
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView(
        [state] * t, Opinion("rotation", np.full((t, n + 1), np.nan))
    )
    return DeskReport(
        panel, {"AAA": "ai", "BBB": "ai"}, {}, view, graded, graded.as_scores(), []
    )


# The prices the nightly hands the ledger for session `k`.
def _prices(k: int) -> tuple[dict, dict]:
    return (
        {s: OPENS[s][k] for s in OPENS},
        {s: CLOSES[s][k] for s in CLOSES},
    )


# Observe session `k` into `root`.
def _observe(root, k: int, grades=None, migrations=None):
    opens, closes = _prices(k)
    return shadow_ledger.observe(
        root,
        _report(k, grades),
        opens,
        closes,
        SESSIONS[k],
        NOW + timedelta(days=k),
        migrations=migrations,
    )


# Session 1 decides, session 2 fills at the open and marks at the close,
# session 3 holds; every figure is checked by hand and the folder holds one
# whole row per transition.
def test_three_session_journey(tmp_path):
    first = _observe(tmp_path, 0)
    assert first["sequence"] == 1
    assert first["session"] == SESSIONS[0]
    assert first["cash"] == 100_000.0
    assert first["equity"] == 100_000.0
    assert first["return_1d"] is None
    assert first["fills"] == []
    # Two A+ names: 20% each, the rest cash. Sized at the first close.
    assert first["targets"] == {"AAA": pytest.approx(0.2), "BBB": pytest.approx(0.2)}
    assert first["pending"]["decided"] == SESSIONS[0]
    assert first["pending"]["orders"] == {"AAA": 200, "BBB": 400}

    second = _observe(tmp_path, 1)
    assert second["sequence"] == 2
    # Filled at the second open: 200 AAA at 102, 400 BBB at 49, 10 bp each.
    spent = 200 * 102.0 + 400 * 49.0
    fee = spent * 0.001
    assert second["cash"] == pytest.approx(100_000.0 - spent - fee)
    assert second["shares"] == {"AAA": 200, "BBB": 400}
    by_name = {f["ticker"]: f for f in second["fills"]}
    assert by_name["AAA"] == {
        "ticker": "AAA",
        "side": "buy",
        "shares": 200,
        "price": 102.0,
        "cost": pytest.approx(20.4),
    }
    assert by_name["BBB"]["shares"] == 400
    assert by_name["BBB"]["price"] == 49.0
    assert second["refusals"] == []
    # Marked at the second close: 200 * 104 + 400 * 48.
    equity = second["cash"] + 200 * 104.0 + 400 * 48.0
    assert second["equity"] == pytest.approx(equity)
    assert second["return_1d"] == pytest.approx(equity / 100_000.0 - 1.0)
    # The reset clock has not come round: the book holds, nothing pending.
    assert second["pending"] is None
    assert second["status"] == "Observed; holding"
    assert second["marks"] == {"AAA": 104.0, "BBB": 48.0}

    third = _observe(tmp_path, 2, grades={"BBB": "B"})
    assert third["sequence"] == 3
    assert third["fills"] == []
    assert third["shares"] == {"AAA": 200, "BBB": 400}
    assert third["cash"] == pytest.approx(second["cash"])
    assert third["equity"] == pytest.approx(third["cash"] + 200 * 103.0 + 400 * 51.0)
    assert third["return_1d"] == pytest.approx(third["equity"] / second["equity"] - 1.0)
    # The policy's view is still written on a holding session: BBB fell to B.
    assert third["targets"] == {"AAA": pytest.approx(0.2)}
    assert third["pending"] is None
    rows = sorted((tmp_path / "desk/shadow/graded-equal-weight-4").glob("*.json"))
    assert [p.name for p in rows] == [f"{i:08d}.json" for i in range(4)]
    for path in rows:
        row = json.loads(path.read_text(encoding="utf-8"))
        assert row["policy"] == policy_v4.POLICY_VERSION
        assert row["identity"] == shadow_ledger.identity()
        assert row["version"] == shadow_ledger.VERSION


# Observing a session already on the ledger returns the row and appends
# nothing; a session before the ledger's is refused.
def test_observing_the_same_session_twice_appends_nothing(tmp_path):
    _observe(tmp_path, 0)
    second = _observe(tmp_path, 1)
    folder = tmp_path / "desk/shadow/graded-equal-weight-4"
    before = sorted(p.name for p in folder.glob("*.json"))
    again = _observe(tmp_path, 1)
    assert again == second
    assert sorted(p.name for p in folder.glob("*.json")) == before
    with pytest.raises(ValueError, match="before the ledger"):
        _observe(tmp_path, 0)


# A cash-short basket is scaled down together to whole shares and the
# unpaid remainder is written down; cash never goes negative.
def test_a_cash_short_basket_is_scaled_and_recorded():
    cash, shares, fills, refusals = shadow_ledger._fill(
        1000.0,
        {"CCC": 5},
        {"AAA": 10, "BBB": 10, "CCC": 0},
        {"AAA": 100.0, "BBB": 50.0},
    )
    # CCC has no opening price: refused, still held. AAA and BBB want 1500
    # plus fees from 1000 cash: scaled to two thirds, floored.
    assert shares["CCC"] == 5
    assert any(r["ticker"] == "CCC" for r in refusals)
    assert shares["AAA"] == 6
    assert shares["BBB"] == 6
    assert cash >= 0
    unpaid = {r["ticker"]: r["shares"] for r in refusals if r["reason"] == "cash"}
    assert unpaid == {"AAA": 4, "BBB": 4}
    assert sum(f["cost"] for f in fills) == pytest.approx((600 + 300) * 0.001)


# Sells fill first and fund the same open's buys; a name sold out leaves
# the shares map.
def test_sells_fund_buys_and_a_full_exit_leaves_the_map():
    cash, shares, fills, refusals = shadow_ledger._fill(
        0.0, {"AAA": 10}, {"AAA": 0, "BBB": 9}, {"AAA": 100.0, "BBB": 100.0}
    )
    assert "AAA" not in shares
    assert shares["BBB"] == 9
    assert cash == pytest.approx(1000 * 0.999 - 900 * 1.001)
    assert refusals == []
    assert [f["side"] for f in fills] == ["sell", "buy"]


# A missed nightly cancels the pending orders instead of filling them at an
# open that has passed, and says so.
def test_a_missed_session_cancels_the_pending_orders(tmp_path):
    _observe(tmp_path, 0)
    row = _observe(tmp_path, 2)
    assert row["fills"] == []
    assert row["shares"] == {}
    assert row["cash"] == 100_000.0
    assert any("cancelled" in r["reason"] for r in row["refusals"])


# A held name whose close is missing fails closed rather than being marked.
def test_a_missing_held_mark_fails_closed(tmp_path):
    _observe(tmp_path, 0)
    opens, closes = _prices(1)
    del closes["BBB"]
    with pytest.raises(ValueError, match="held valuation unavailable: BBB"):
        shadow_ledger.observe(tmp_path, _report(1), opens, closes, SESSIONS[1], NOW)


# A changed code identity refuses to continue the ledger unless the
# continuation is declared; a declared one carries its provenance forward.
def test_a_changed_identity_without_a_declared_migration_raises(tmp_path, monkeypatch):
    _observe(tmp_path, 0)
    monkeypatch.setattr(shadow_ledger, "identity", lambda: "changed")
    with pytest.raises(ValueError, match="Frozen experiment changed"):
        _observe(tmp_path, 1, migrations=tmp_path / "none.json")
    declared = tmp_path / "migrations.json"
    declared.write_text(
        json.dumps([{"from": "stranger", "to": "changed", "reason": "no"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Frozen experiment changed"):
        _observe(tmp_path, 1, migrations=declared)
    previous = json.loads(
        (tmp_path / "desk/shadow/graded-equal-weight-4/00000001.json").read_text()
    )["identity"]
    declared.write_text(
        json.dumps([{"from": previous, "to": "changed", "reason": "docstring only"}]),
        encoding="utf-8",
    )
    row = _observe(tmp_path, 1, migrations=declared)
    assert row["identity"] == "changed"
    assert row["identity_from"] == previous
    assert row["migration"] == "docstring only"
    assert row["shares"] == {
        "AAA": 200,
        "BBB": 400,
    }
    # The ledger's own migrations file parses and the current code needs none.
    assert shadow_ledger.migration("x", "y") is None


# The identity hashes both source files: a change to either moves it.
def test_identity_covers_both_files(monkeypatch, tmp_path):
    before = shadow_ledger.identity()
    copy = tmp_path / "policy_v4.py"
    copy.write_text("# changed\n", encoding="utf-8")
    monkeypatch.setattr(policy_v4, "__file__", str(copy))
    assert shadow_ledger.identity() != before


# The receipt the record carries is small and names the sequence, the
# equity, the day's return and how many orders were decided.
def test_receipt_shape(tmp_path):
    row = _observe(tmp_path, 0)
    receipt = shadow_ledger.receipt(row)
    assert receipt == {
        "sequence": 1,
        "session": SESSIONS[0],
        "equity": 100_000.0,
        "return_1d": None,
        "orders_decided": 2,
        "fills": 0,
        "refusals": 0,
        "note": "Observed; targets reset",
    }


# `decide` reads the report's last session only and never wants the benchmark.
def test_decide_reads_the_last_session():
    report = _report(2, grades={"BBB": "C"})
    assert shadow_ledger.decide(report) == {"AAA": pytest.approx(0.2)}
    unpriced = replace(report.panel, close=report.panel.close.copy())
    unpriced.close[-1, 0] = np.nan
    assert shadow_ledger.decide(replace(report, panel=unpriced)) == {}
