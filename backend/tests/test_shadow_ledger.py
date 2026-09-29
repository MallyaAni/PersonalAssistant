"""The policy shadow ledger: fills, cash, marks, idempotency and the frozen identity.

The ledger shadows the policy the paper account runs (`live_policy.POLICY`,
`graded-equal-weight/5` since 2026-09-29: every A/A+ name at equal weight
under a 25% cap). Three sessions on a two-name book whose prices are chosen
by hand, so every number the ledger writes can be checked with arithmetic:
the first close decides whole-share targets, the next open fills them at
ten basis points from cash that never goes negative, the close marks the
book and the day's return follows. Observing the same session twice appends
nothing, a changed code identity without a declared migration refuses to
continue, and the `/5` ledger lives in its own folder: it never reads or
writes the `/4` ledger's rows.
"""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.agents.trading.desk import (
    grading,
    live_policy,
    policy_v4,
    policy_v5,
    regime,
    shadow_ledger,
)
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NOW = datetime(2026, 9, 26, 23, 30, tzinfo=UTC)
# The shadowed policy's cap: two A+ names each get a quarter of the book.
CAP = 0.25
# Where the `/5` ledger writes, and where the `/4` ledger wrote.
V5_FOLDER = "desk/shadow/graded-equal-weight-5"
V4_FOLDER = "desk/shadow/graded-equal-weight-4"
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
    assert shadow_ledger.shadowed() is live_policy.POLICY is policy_v5
    assert policy_v5.HOLD_CAP == CAP
    first = _observe(tmp_path, 0)
    assert first["sequence"] == 1
    assert first["session"] == SESSIONS[0]
    assert first["cash"] == 100_000.0
    assert first["equity"] == 100_000.0
    assert first["return_1d"] is None
    assert first["fills"] == []
    # Two A+ names: a quarter each, the rest cash. Sized at the first close.
    assert first["targets"] == {"AAA": pytest.approx(CAP), "BBB": pytest.approx(CAP)}
    assert first["pending"]["decided"] == SESSIONS[0]
    assert first["pending"]["orders"] == {"AAA": 250, "BBB": 500}

    second = _observe(tmp_path, 1)
    assert second["sequence"] == 2
    # Filled at the second open: 250 AAA at 102, 500 BBB at 49, 10 bp each.
    spent = 250 * 102.0 + 500 * 49.0
    fee = spent * 0.001
    assert spent == 50_000.0
    assert second["cash"] == pytest.approx(100_000.0 - spent - fee)
    assert second["cash"] == pytest.approx(49_950.0)
    assert second["shares"] == {"AAA": 250, "BBB": 500}
    by_name = {f["ticker"]: f for f in second["fills"]}
    assert by_name["AAA"] == {
        "ticker": "AAA",
        "side": "buy",
        "shares": 250,
        "price": 102.0,
        "cost": pytest.approx(25.5),
    }
    assert by_name["BBB"]["shares"] == 500
    assert by_name["BBB"]["price"] == 49.0
    assert second["refusals"] == []
    # Marked at the second close: 250 * 104 + 500 * 48.
    equity = second["cash"] + 250 * 104.0 + 500 * 48.0
    assert second["equity"] == pytest.approx(equity)
    assert second["equity"] == pytest.approx(99_950.0)
    assert second["return_1d"] == pytest.approx(equity / 100_000.0 - 1.0)
    # The reset clock has not come round: the book holds, nothing pending.
    assert second["pending"] is None
    assert second["status"] == "Observed; holding"
    assert second["marks"] == {"AAA": 104.0, "BBB": 48.0}

    third = _observe(tmp_path, 2, grades={"BBB": "B"})
    assert third["sequence"] == 3
    assert third["fills"] == []
    assert third["shares"] == {"AAA": 250, "BBB": 500}
    assert third["cash"] == pytest.approx(second["cash"])
    assert third["equity"] == pytest.approx(third["cash"] + 250 * 103.0 + 500 * 51.0)
    assert third["return_1d"] == pytest.approx(third["equity"] / second["equity"] - 1.0)
    # The policy's view is still written on a holding session: BBB fell to B.
    assert third["targets"] == {"AAA": pytest.approx(CAP)}
    assert third["pending"] is None
    rows = sorted((tmp_path / V5_FOLDER).glob("*.json"))
    assert [p.name for p in rows] == [f"{i:08d}.json" for i in range(4)]
    for path in rows:
        row = json.loads(path.read_text(encoding="utf-8"))
        assert row["policy"] == live_policy.ACTIVE == "graded-equal-weight/5"
        assert row["identity"] == shadow_ledger.identity()
        assert row["version"] == shadow_ledger.VERSION
    # Nothing was written under the `/4` ledger's folder.
    assert not (tmp_path / V4_FOLDER).exists()


# Observing a session already on the ledger returns the row and appends
# nothing; a session before the ledger's is refused.
def test_observing_the_same_session_twice_appends_nothing(tmp_path):
    _observe(tmp_path, 0)
    second = _observe(tmp_path, 1)
    folder = tmp_path / V5_FOLDER
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
        (tmp_path / V5_FOLDER / "00000001.json").read_text()
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
        "AAA": 250,
        "BBB": 500,
    }
    # The ledger's own migrations file parses and the current code needs none.
    assert shadow_ledger.migration("x", "y") is None


# The identity hashes the shadowed policy's source and this ledger's, as
# whole files: a change to either moves it. It is `policy_v5.py`'s now, so
# `/4`'s frozen bytes no longer enter it.
def test_identity_covers_both_files(monkeypatch, tmp_path):
    before = shadow_ledger.identity()
    code = b"".join(
        Path(module.__file__).read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        for module in (policy_v5, shadow_ledger)
    )
    assert before == hashlib.sha256(code).hexdigest()
    elsewhere = tmp_path / "policy_v4.py"
    elsewhere.write_text("# changed\n", encoding="utf-8")
    monkeypatch.setattr(policy_v4, "__file__", str(elsewhere))
    assert shadow_ledger.identity() == before
    copy = tmp_path / "policy_v5.py"
    copy.write_text("# changed\n", encoding="utf-8")
    monkeypatch.setattr(policy_v5, "__file__", str(copy))
    assert shadow_ledger.identity() != before


# The `/5` ledger starts fresh in its own folder beside a `/4` ledger that
# already has rows - here one dated after tonight and holding shares, which
# a ledger that read it would either refuse or continue from. It does
# neither: sequence 1 is a fresh 100,000 account, and the `/4` rows are
# byte for byte what they were.
def test_a_v4_folder_is_not_read_by_the_v5_ledger(tmp_path):
    old = tmp_path / V4_FOLDER
    old.mkdir(parents=True)
    rows = {
        "00000000.json": {"sequence": 0, "session": None, "shares": {}},
        "00000001.json": {"sequence": 1, "session": "2026-09-28", "shares": {"AAA": 7}},
    }
    for name, row in rows.items():
        row = {
            **row,
            "version": shadow_ledger.VERSION,
            "policy": policy_v4.POLICY_VERSION,
            "identity": "the /4 ledger's identity",
            "cash": 99_000.0,
            "equity": 100_000.0,
        }
        (old / name).write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    assert shadow_ledger.folder(tmp_path) == tmp_path / V5_FOLDER
    assert shadow_ledger.folder(tmp_path, policy_v4.POLICY_VERSION) == old
    first = _observe(tmp_path, 0)
    assert first["sequence"] == 1
    assert first["policy"] == policy_v5.POLICY_VERSION
    assert first["cash"] == 100_000.0
    assert first["shares"] == {}
    assert first["pending"]["orders"] == {"AAA": 250, "BBB": 500}
    assert sorted(p.name for p in (tmp_path / V5_FOLDER).glob("*.json")) == [
        "00000000.json",
        "00000001.json",
    ]
    assert {p.name: p.read_bytes() for p in old.iterdir()} == before


# A folder whose rows name another policy is not continued: a `/4` row found
# where the `/5` ledger lives is refused, never re-labelled.
def test_rows_of_another_policy_are_refused(tmp_path):
    here = tmp_path / V5_FOLDER
    here.mkdir(parents=True)
    (here / "00000000.json").write_text(
        json.dumps(
            {
                "version": shadow_ledger.VERSION,
                "policy": policy_v4.POLICY_VERSION,
                "identity": shadow_ledger.identity(),
                "sequence": 0,
                "session": None,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Frozen experiment changed"):
        _observe(tmp_path, 0)


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
    assert shadow_ledger.decide(report) == {"AAA": pytest.approx(CAP)}
    unpriced = replace(report.panel, close=report.panel.close.copy())
    unpriced.close[-1, 0] = np.nan
    assert shadow_ledger.decide(replace(report, panel=unpriced)) == {}
