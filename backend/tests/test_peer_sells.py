"""The S2 sector-aware sell rules, live: off by default, fail-safe, true on the board.

What has to hold, because the operator trades his own account by hand from
the board:

* with `SECTOR_SELLS` unset or `off`, the paper orders are bit for bit the
  board's `dip_or_close` orders, whatever peer data is on file;
* the peer group is the study's (`backend.market.peer_groups`), point in
  time: nothing after the decision session changes it;
* G1 holds a downgrade sell for the session when the peers' first-bar
  return beats sigma_g, G2 sends it at the close instead of on the pop when
  the peers are up more than 1%, G3 is G1 for trims and C exits only;
* every missing piece (no peer file, another session's file, no group,
  fewer than 3 of 5 peers priced, an exception) runs the control unchanged
  and says why in the log;
* the board keeps the SELL/TRIM word and size and adds one grey sentence of
  computed numbers only when the rule held or moved the sell.
"""

import json
import math
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper, peer_sells
from backend.cli import market_daily
from backend.market import deskrecord, entry_timing
from backend.market import peer_groups as pg

NY = ZoneInfo("America/New_York")
# Wednesday 2026-09-30, a regular session; its orders were decided Tuesday.
TODAY = date(2026, 9, 30)
DECIDED = "2026-09-29"
PEERS = ["P1", "P2", "P3", "P4", "P5"]
EXIT_B = "graded B; the desk wants the money elsewhere"


# An aware New York instant on TODAY.
def ny(hour: int, minute: int = 0) -> datetime:
    """Return TODAY at hour:minute in New York."""
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute, tzinfo=NY)


# One pending sell as the nightly writes it for the intraday leg.
def sell(symbol="AAA", qty=14, reason=EXIT_B, **extra) -> dict:
    """Return a pending sell planned on DECIDED for TODAY."""
    out = {
        "client_order_id": f"anios-{DECIDED}-sell-{symbol.lower()}-1",
        "symbol": symbol,
        "side": "sell",
        "qty": qty,
        "session": DECIDED,
        "reason": reason,
        "event_id": None,
        "priority": None,
        "execution_timing": intraday_orders.INTRADAY_TIMING,
        "execute_on": TODAY.isoformat(),
        "kind": None,
        "execution": {"reference_price": 100.0},
    }
    out.update(extra)
    return out


# Save a paper state whose pending rows are `rows`.
def save(root: Path, *rows: dict) -> None:
    """Write the paper state."""
    state = paper.PaperState()
    state.pending = [dict(r) for r in rows]
    paper.save_state(root, state)


# The peer file beside DECIDED's record: one name per (symbol, scope grade),
# all with the five peers P1..P5 at sigma_g, each peer closing at 100.
def peer_file(root: Path, names: dict[str, str], sigma=0.02, session=DECIDED):
    """Write a record and its sector-peers file; return the block."""
    folder = deskrecord.folder(root, session)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "desk.json").write_text("{}", encoding="utf-8")
    block = {
        "session": session,
        "names": {
            s: {
                "grade": g,
                "scope_grade": g,
                "member": True,
                "peers": list(PEERS),
                "corr": [0.9, 0.8, 0.7, 0.6, 0.5],
                "sigma_g": sigma,
            }
            for s, g in names.items()
        },
        "closes": {p: 100.0 for p in PEERS},
    }
    peer_sells.write(root, block, overwrite=True)
    return block


# Today's latch: each sold name opened at 100 with an optional sell trigger
# on the first bar, and each peer's first bar closing at `peer_close`
# (None leaves that peer without a first bar).
def latch(root: Path, names=("AAA",), peer_close=103.0, trigger=101.5, skip=()):
    """Write the entry-timing latch for TODAY."""
    symbols: dict[str, dict] = {}
    for symbol in names:
        symbols[symbol] = {
            "open": 100.0,
            "buy_level": 99.0,
            "sell_level": 101.0,
            "buy_trigger": None,
            "sell_trigger": None
            if trigger is None
            else {"bar": ny(9, 30).isoformat(), "price": trigger},
            "first_bar": {"close": trigger or 100.2, "high": 102.0},
        }
    for p in PEERS:
        symbols[p] = {"open": 100.0, "buy_trigger": None, "sell_trigger": None}
        if p not in skip and peer_close is not None:
            symbols[p]["first_bar"] = {"close": peer_close, "high": peer_close}
    path = entry_timing.latch_path(root, TODAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"session": TODAY.isoformat(), "symbols": symbols}), encoding="utf-8"
    )


# A paper broker, faked: clock open, the positions, what was sent.
class Broker:
    """Record every submission."""

    # The account's shares and an empty record of submissions.
    def __init__(self, held=None):
        self.held = held or {}
        self.sent: list[tuple] = []

    # The broker's clock.
    def clock(self):
        return {"is_open": True}

    # The account's positions.
    def positions(self):
        return [SimpleNamespace(symbol=s, qty=q) for s, q in self.held.items()]

    # No order placed earlier.
    def orders_since(self, since):
        return []

    # A market order now.
    def submit_market(self, symbol, qty, side, cid):
        self.sent.append(("market", side, symbol, qty, cid))
        return {"submitted_at": "2026-09-30T13:46:01Z", "time_in_force": "day"}

    # A market-on-close order.
    def submit_market_on_close(self, symbol, qty, side, cid):
        self.sent.append(("moc", side, symbol, qty, cid))
        return {"submitted_at": "2026-09-30T19:31:01Z", "time_in_force": "cls"}


# Run the executor on every candle from the first bar to the close window,
# under `mode` (None: SECTOR_SELLS unset); return the broker, the log lines
# and the saved state.
def run_day(root: Path, monkeypatch, mode: str | None, held=None):
    """Return (broker, lines, state) after a session of candles."""
    if mode is None:
        monkeypatch.delenv(peer_sells.ENV, raising=False)
    else:
        monkeypatch.setenv(peer_sells.ENV, mode)
    broker = Broker(held or {"AAA": 14})
    lines: list[str] = []
    for at in (ny(9, 46), ny(11, 1), ny(15, 31), ny(15, 51)):
        lines += intraday_orders.send_due(root, {}, at, lambda: broker)
    return broker, lines, paper.load_state(root)


# --- the shared peer group ------------------------------------------------------


# The registered constants, imported by the study and the desk from one place.
def test_the_registered_constants():
    assert (pg.K_PEERS, pg.CORR_SESSIONS, pg.PEER_SIGMA_SESSIONS) == (5, 60, 20)
    assert pg.MIN_PRICED_PEERS == 3
    assert math.log1p(0.01) == pg.CLOSE_THRESHOLD


# A synthetic book: the benchmark, two factor groups of five and a loner;
# returns the panel-like namespace and the (T, N) membership.
def book(length=120, seed=3):
    """Return (panel, membership)."""
    rng = np.random.default_rng(seed)
    tickers = (
        "SPY",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "B1",
        "B2",
        "B3",
        "B4",
        "B5",
        "Z",
    )
    m = rng.normal(0, 0.01, length)
    fa, fb = rng.normal(0, 0.01, length), rng.normal(0, 0.01, length)
    r = np.zeros((length, len(tickers)))
    r[:, 0] = m
    for j, t in enumerate(tickers[1:], start=1):
        factor = fa if t.startswith("A") else fb if t.startswith("B") else 0.0
        r[:, j] = m + factor + rng.normal(0, 0.004, length)
    closes = 100 * np.exp(np.cumsum(r, axis=0))
    panel = SimpleNamespace(
        dates=np.datetime64("2026-03-02") + np.arange(length),
        tickers=tickers,
        adj_close=closes,
        close=closes.copy(),
        benchmark="SPY",
    )
    return panel, np.ones((length, len(tickers)), dtype=bool)


# Truncate a panel-like namespace at session t (inclusive).
def upto(panel, t):
    """Return the panel through t."""
    return SimpleNamespace(
        dates=panel.dates[: t + 1],
        tickers=panel.tickers,
        adj_close=panel.adj_close[: t + 1],
        close=panel.close[: t + 1],
        benchmark=panel.benchmark,
    )


# The desk's one-session group is the study's full-panel group at that
# session, and prices after t never move t's group or sigma_g.
def test_the_desk_reads_the_studys_group_point_in_time():
    panel, member = book()
    t = 100
    letters = {x: "B" for x in panel.tickers}
    live = peer_sells.compute(upto(panel, t), member[: t + 1], letters)
    study = pg.peer_groups(panel.dates, panel.tickers, panel.adj_close, 0, member)
    j = panel.tickers.index("A1")
    assert live["session"] == str(panel.dates[t])
    assert live["names"]["A1"]["peers"] == [
        panel.tickers[p] for p in study.members[t, j]
    ]
    assert live["names"]["A1"]["sigma_g"] == study.sigma[t, j]
    assert set(live["names"]["A1"]["peers"]) == {"A2", "A3", "A4", "A5", "A6"}
    tampered = panel.adj_close.copy()
    tampered[t + 1 :] *= np.linspace(0.5, 3.0, len(tampered) - t - 1)[:, None]
    after = pg.peer_groups(panel.dates, panel.tickers, tampered, 0, member)
    assert np.array_equal(after.members[t], study.members[t])
    assert np.array_equal(after.sigma[t], study.sigma[t], equal_nan=True)
    assert "SPY" not in live["names"]
    assert all("SPY" not in e["peers"] for e in live["names"].values())
    assert live["closes"]["A2"] == panel.close[t, panel.tickers.index("A2")]


# A name outside the book at t is never anyone's peer and counts as C.
def test_a_non_member_is_no_peer_and_scopes_as_c():
    panel, member = book()
    member[:, panel.tickers.index("A2")] = False
    letters = {x: "A" for x in panel.tickers}
    live = peer_sells.compute(panel, member, letters)
    assert all("A2" not in e["peers"] for e in live["names"].values())
    assert live["names"]["A2"]["scope_grade"] == "C"
    assert live["names"]["A2"]["grade"] == "A"
    assert live["names"]["A1"]["scope_grade"] == "A"


# R_g needs three of five peers priced; the two triggers are strict.
def test_the_morning_and_the_triggers():
    assert pg.group_morning([0.01, None, float("nan"), 0.03]) == (None, 2)
    morning, priced = pg.group_morning([0.01, 0.02, 0.03, None, None])
    assert priced == 3
    assert morning == pytest.approx(0.02)
    assert bool(pg.defer_fires(0.021, 0.02))
    assert not bool(pg.defer_fires(0.02, 0.02))
    assert not bool(pg.defer_fires(float("nan"), 0.02))
    assert bool(pg.close_fires(math.log1p(0.01) + 1e-9))
    assert not bool(pg.close_fires(math.log1p(0.01)))


# --- the switch -------------------------------------------------------------------


# Unset is off; the four values; anything else is off with a reason.
def test_the_switch_defaults_off():
    assert peer_sells.SECTOR_SELLS == peer_sells.OFF
    assert peer_sells.mode({}) == ("off", None)
    assert peer_sells.mode({"SECTOR_SELLS": " G1 "}) == ("g1", None)
    for value in ("off", "g2", "g3"):
        assert peer_sells.mode({"SECTOR_SELLS": value}) == (value, None)
    mode, problem = peer_sells.mode({"SECTOR_SELLS": "on"})
    assert mode == "off"
    assert "not one of" in problem


# --- the executor -------------------------------------------------------------------


# Flag off: the same orders, the same state, whatever peer data is on file -
# and identical to a session with no peer data at all.
@pytest.mark.parametrize("value", [None, "off"])
def test_flag_off_is_the_control_bit_for_bit(tmp_path, monkeypatch, value):
    base = tmp_path / "base"
    save(base, sell("AAA"))
    latch(base)
    expected, base_lines, base_state = run_day(base, monkeypatch, None)
    with_data = tmp_path / "data"
    save(with_data, sell("AAA"))
    latch(with_data)
    peer_file(with_data, {"AAA": "B"})
    got, lines, state = run_day(with_data, monkeypatch, value)
    assert (
        got.sent
        == expected.sent
        == [("market", "sell", "AAA", 14, sell()["client_order_id"])]
    )
    assert lines == base_lines
    assert json.dumps(state.pending, sort_keys=True) == json.dumps(
        base_state.pending, sort_keys=True
    )
    assert peer_sells.ROW_KEY not in state.pending[0]


# G1 holds a B exit for the whole session when its peers opened above
# sigma_g, says so in the log, and the board keeps SELL with the note.
def test_g1_defers_a_downgrade_sell(tmp_path, monkeypatch):
    save(tmp_path, sell("AAA"))
    latch(tmp_path)
    peer_file(tmp_path, {"AAA": "B"})
    broker, lines, state = run_day(tmp_path, monkeypatch, "g1")
    assert broker.sent == []
    verdict = state.pending[0][peer_sells.ROW_KEY]
    assert verdict["action"] == peer_sells.DEFER
    assert verdict["morning"] == pytest.approx(math.log(1.03))
    assert verdict["priced"] == 5
    assert verdict["peers"] == PEERS
    assert lines[0].startswith("peer rule G1: sell 14 AAA DEFER")
    board = intraday_orders.board_orders(
        state,
        broker_orders=[],
        latch=entry_timing.load(tmp_path, TODAY),
        quotes={},
        held={"AAA": 14.0},
        prices={"AAA": 101.0},
        equity=10_000.0,
        now=ny(11, 5),
    )[0]
    assert board["action"] == "SELL"
    assert board["qty"] == 14
    assert board["state"] == intraday_orders.DEFERRED
    assert board["terminal"] is True
    assert board["note"] == (
        "Held: its peer group (P1, P2, P3, P4, P5) opened +3.0%, above its usual "
        "daily move 2.0%; sale re-planned tonight"
    )
    assert board["status"] == "Not sent today · re-planned tonight"
    assert board["when"] == "Today · not sent: held by the peer-group rule"


# G1 with the peers flat: a control verdict, and the order is the control's.
def test_g1_that_does_not_fire_is_the_control(tmp_path, monkeypatch):
    save(tmp_path, sell("AAA"))
    latch(tmp_path, peer_close=100.5)
    peer_file(tmp_path, {"AAA": "B"})
    broker, lines, state = run_day(tmp_path, monkeypatch, "g1")
    assert broker.sent == [("market", "sell", "AAA", 14, sell()["client_order_id"])]
    assert state.pending[0][peer_sells.ROW_KEY]["action"] == peer_sells.CONTROL
    assert peer_sells.board_note(state.pending[0]) is None


# G2 skips the first-bar pop and sends the control's own close-window order.
def test_g2_sells_at_the_close(tmp_path, monkeypatch):
    save(tmp_path, sell("AAA"))
    latch(tmp_path)
    peer_file(tmp_path, {"AAA": "C"})
    monkeypatch.setenv(peer_sells.ENV, "g2")
    broker = Broker({"AAA": 14})
    assert intraday_orders.send_due(tmp_path, {}, ny(9, 46), lambda: broker)[
        0
    ].startswith("peer rule G2: sell 14 AAA CLOSE")
    assert intraday_orders.send_due(tmp_path, {}, ny(14, 1), lambda: broker) == []
    state = paper.load_state(tmp_path)
    board = intraday_orders.board_orders(
        state,
        broker_orders=[],
        latch=entry_timing.load(tmp_path, TODAY),
        quotes={},
        held={"AAA": 14.0},
        prices={"AAA": 101.0},
        equity=10_000.0,
        now=ny(14, 5),
    )[0]
    assert board["action"] == "SELL"
    assert board["state"] == "waiting"
    assert board["status"] == "Waiting for the close (3:30 PM window)"
    assert board["note"] == (
        "Selling at the close: its peer group (P1, P2, P3, P4, P5) opened +3.0%"
    )
    assert board["when"] == "Today · at the close, not on the 1% pop (peer-group rule)"
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 31), lambda: broker)
    assert lines == ["sell 14 AAA (moc, triggered): sent"]
    assert broker.sent == [("moc", "sell", "AAA", 14, sell()["client_order_id"])]


# G2's threshold is 1%, not sigma_g: peers up 0.8% leave the pop rule alone.
def test_g2_below_one_percent_is_the_control(tmp_path, monkeypatch):
    save(tmp_path, sell("AAA"))
    latch(tmp_path, peer_close=100.8)
    peer_file(tmp_path, {"AAA": "B"}, sigma=0.001)
    broker, _, state = run_day(tmp_path, monkeypatch, "g2")
    assert broker.sent[0][0] == "market"
    assert state.pending[0][peer_sells.ROW_KEY]["action"] == peer_sells.CONTROL


# The scopes: G1/G2 judge only names below A; G3 judges trims (A/A+) and C
# exits and leaves a B exit to the control.
@pytest.mark.parametrize(
    ("mode", "grade", "held_back"),
    [
        ("g1", "B", True),
        ("g1", "C", True),
        ("g1", "A", False),
        ("g3", "B", False),
        ("g3", "C", True),
        ("g3", "A", True),
        ("g3", "A+", True),
    ],
)
def test_each_rules_scope(tmp_path, monkeypatch, mode, grade, held_back):
    reason = "rebalance to 0.05" if grade.startswith("A") else EXIT_B
    save(tmp_path, sell("AAA", reason=reason))
    latch(tmp_path)
    peer_file(tmp_path, {"AAA": grade})
    broker, _, state = run_day(tmp_path, monkeypatch, mode)
    assert (broker.sent == []) is held_back
    verdict = state.pending[0][peer_sells.ROW_KEY]
    assert (verdict["action"] == peer_sells.DEFER) is held_back
    if not held_back:
        assert verdict["reason"].startswith("out of scope")


# Event and priority sells are in no scope and are never judged.
def test_event_sells_are_never_judged(tmp_path, monkeypatch):
    row = sell("AAA", event_id="fomc-1")
    save(tmp_path, row)
    latch(tmp_path)
    peer_file(tmp_path, {"AAA": "B"})
    monkeypatch.setenv(peer_sells.ENV, "g1")
    intraday_orders.send_due(tmp_path, {}, ny(9, 46), lambda: Broker({"AAA": 14}))
    assert peer_sells.ROW_KEY not in paper.load_state(tmp_path).pending[0]


# Every missing piece runs the control and logs why.
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("no file", "no peer file for the 2026-09-29 decision"),
        ("other session", "the peer file is for 2026-09-28, the order for 2026-09-29"),
        ("not listed", "AAA is not in the 2026-09-29 peer file"),
        ("no group", "AAA had no peer group on 2026-09-29"),
        ("two priced", "only 2 of 5 peers' first bars on file (needs 3)"),
    ],
)
def test_fail_safes_run_the_control(tmp_path, monkeypatch, case, reason):
    save(tmp_path, sell("AAA"))
    latch(tmp_path, skip=("P1", "P2", "P3") if case == "two priced" else ())
    if case == "other session":
        peer_file(tmp_path, {"AAA": "B"}, session="2026-09-28")
        folder = deskrecord.folder(tmp_path, DECIDED)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / peer_sells.FILE).write_text(
            (deskrecord.folder(tmp_path, "2026-09-28") / peer_sells.FILE).read_text()
        )
    elif case == "not listed":
        peer_file(tmp_path, {"ZZZ": "B"})
    elif case == "no group":
        block = peer_file(tmp_path, {"AAA": "B"})
        block["names"]["AAA"].update(peers=[], corr=[], sigma_g=None)
        peer_sells.write(tmp_path, block, overwrite=True)
    elif case != "no file":
        peer_file(tmp_path, {"AAA": "B"})
    broker, lines, state = run_day(tmp_path, monkeypatch, "g1")
    assert broker.sent == [("market", "sell", "AAA", 14, sell()["client_order_id"])]
    verdict = state.pending[0][peer_sells.ROW_KEY]
    assert verdict["action"] == peer_sells.CONTROL
    assert verdict["reason"] == reason
    assert any(reason in line for line in lines)


# An exception while judging is a control verdict naming it, never a crash.
def test_an_exception_runs_the_control(tmp_path, monkeypatch):
    save(tmp_path, sell("AAA"))
    latch(tmp_path)
    peer_file(tmp_path, {"AAA": "B"})

    # A judge that fails.
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(peer_sells, "judge", broken)
    broker, lines, state = run_day(tmp_path, monkeypatch, "g1")
    assert broker.sent[0][:4] == ("market", "sell", "AAA", 14)
    assert state.pending[0][peer_sells.ROW_KEY]["reason"] == (
        "error while judging (RuntimeError: boom)"
    )


# An unknown switch value is off, and the log says so.
def test_an_unknown_switch_value_is_off_and_logged(tmp_path, monkeypatch):
    save(tmp_path, sell("AAA"))
    latch(tmp_path)
    peer_file(tmp_path, {"AAA": "B"})
    broker, lines, state = run_day(tmp_path, monkeypatch, "yes")
    assert broker.sent[0][:4] == ("market", "sell", "AAA", 14)
    assert peer_sells.ROW_KEY not in state.pending[0]
    assert any("SECTOR_SELLS='yes' is not one of" in line for line in lines)


# No verdict before the session's opening bar is known; one verdict per row.
def test_judged_once_and_never_before_the_open(tmp_path, monkeypatch):
    save(tmp_path, sell("AAA"))
    peer_file(tmp_path, {"AAA": "B"})
    monkeypatch.setenv(peer_sells.ENV, "g1")
    broker = Broker({"AAA": 14})
    assert intraday_orders.send_due(tmp_path, {}, ny(9, 31), lambda: broker) == []
    assert peer_sells.ROW_KEY not in paper.load_state(tmp_path).pending[0]
    latch(tmp_path)
    first = intraday_orders.send_due(tmp_path, {}, ny(9, 46), lambda: broker)
    assert len(first) == 1
    assert "DEFER" in first[0]
    latch(tmp_path, peer_close=100.0)
    assert intraday_orders.send_due(tmp_path, {}, ny(10, 1), lambda: broker) == []
    assert (
        paper.load_state(tmp_path).pending[0][peer_sells.ROW_KEY]["action"] == "defer"
    )


# --- the board's sentence ---------------------------------------------------------


# The note appears only for a held or close-only sell, with its own numbers;
# when the two numbers would print alike both go to two decimals.
def test_the_board_note_only_when_held():
    assert peer_sells.board_note(sell()) is None
    control = sell(peer_rule={"action": "control", "morning": 0.05})
    assert peer_sells.board_note(control) is None
    held = sell(
        peer_rule={
            "action": "defer",
            "peers": ["LITE", "GLW", "FN", "AAOI", "CIEN"],
            "morning": math.log1p(0.041),
            "sigma_g": 0.037,
        }
    )
    assert peer_sells.board_note(held) == (
        "Held: its peer group (LITE, GLW, FN, AAOI, CIEN) opened +4.1%, above its "
        "usual daily move 3.7%; sale re-planned tonight"
    )
    close = dict(held, peer_rule={**held["peer_rule"], "sigma_g": 0.0369})
    close["peer_rule"]["morning"] = math.log1p(0.0371)
    assert "opened +3.71%, above its usual daily move 3.69%" in peer_sells.board_note(
        close
    )
    moc = sell(
        peer_rule={"action": "close", "peers": PEERS, "morning": math.log1p(0.023)}
    )
    assert peer_sells.board_note(moc) == (
        "Selling at the close: its peer group (P1, P2, P3, P4, P5) opened +2.3%"
    )


# --- the nightly ------------------------------------------------------------------


# A held sell settles as missing (the rebalance re-plans), its journal entry
# keeps the verdict, and the record says what tonight did with it.
def test_the_nightly_replans_a_held_sell():
    state = paper.PaperState()
    held = sell("AAA", peer_rule={"action": "defer", "morning": 0.03})
    plain = sell("BBB")
    state.pending = [held, plain]
    settled = paper.settle(state.pending, [])
    after = paper.apply_settlements(state, settled)
    market_daily._keep_peer_verdicts(state, after)
    by = {e["symbol"]: e for e in after.journal}
    assert by["AAA"]["status"] == "missing"
    assert by["AAA"][peer_sells.ROW_KEY]["action"] == "defer"
    assert peer_sells.ROW_KEY not in by["BBB"]
    before = {r["client_order_id"]: r for r in state.pending}
    regraded = peer_sells.replanned(before, [], {"AAA": "A"})
    assert [(r["symbol"], r["outcome"]) for r in regraded] == [
        ("AAA", "not sold: regraded A")
    ]
    again = peer_sells.replanned(
        before, [SimpleNamespace(symbol="AAA", side="sell")], {"AAA": "B"}
    )
    assert again[0]["outcome"] == "sell planned again"
    other = peer_sells.replanned(before, [], {"AAA": "B"})
    assert other[0]["outcome"] == "not sold: tonight's plan has no sell of it"


# With the switch off and nothing held, the record gains nothing.
def test_the_off_record_is_unchanged(monkeypatch):
    monkeypatch.delenv(peer_sells.ENV, raising=False)
    assert market_daily._peer_replanned({"x": sell()}, [], {}) is None
    monkeypatch.setenv(peer_sells.ENV, "g1")
    block = market_daily._peer_replanned({}, [], {})
    assert block == {"mode": "g1", "problem": None, "replanned": []}


# The nightly writes the peer file beside the record from the report's own
# panel; a failure is printed and never raised.
def test_the_nightly_writes_the_peer_file(tmp_path, monkeypatch, capsys):
    panel, member = book()
    report = SimpleNamespace(
        panel=panel,
        graded=SimpleNamespace(letter=lambda t, column: "B"),
    )
    from backend.agents.trading.desk import point_in_time

    monkeypatch.setattr(point_in_time, "eligibility", lambda dates, tickers: member)
    session = str(panel.dates[-1])
    folder = deskrecord.folder(tmp_path, session)
    folder.mkdir(parents=True)
    (folder / "desk.json").write_text("{}", encoding="utf-8")
    market_daily._write_peer_groups(tmp_path, report)
    block = peer_sells.load(tmp_path, session)
    assert block["session"] == session
    assert len(block["names"]["B1"]["peers"]) == 5
    assert set(block["names"]["B1"]["peers"]) >= {"B2", "B3", "B4", "B5"}
    assert "peer groups: 12 of 12 names" in capsys.readouterr().out
    market_daily._write_peer_groups(tmp_path / "nowhere", report)
    assert "peer groups: not written (FileNotFoundError" in capsys.readouterr().out


# The backfill writes a recorded session's file from the store as of that
# session, with the record's own grades, and refuses a panel that runs past it.
def test_the_backfill_is_point_in_time(tmp_path, monkeypatch):
    from backend.agents.trading.desk import desk, point_in_time
    from backend.cli import market_peer_groups

    panel, member = book()
    session = str(panel.dates[100])
    calls = []

    # The store's book panel as of a date: through that date only.
    def book_panel(store, asof=None):
        calls.append(asof)
        t = int(np.flatnonzero(panel.dates == np.datetime64(asof, "D"))[0])
        return upto(panel, t), {}

    monkeypatch.setattr(desk, "book_panel", book_panel)
    monkeypatch.setattr(
        point_in_time, "eligibility", lambda dates, tickers: member[: len(dates)]
    )
    folder = deskrecord.folder(tmp_path, session)
    folder.mkdir(parents=True)
    (folder / "desk.json").write_text(
        json.dumps({"grades": {"A1": {"grade": "C"}, "A2": {"grade": "A"}}}),
        encoding="utf-8",
    )
    written = market_peer_groups.run(tmp_path)
    block = json.loads(written.read_text(encoding="utf-8"))
    assert calls == [date.fromisoformat(session)]
    assert block["session"] == session
    assert block["names"]["A1"]["scope_grade"] == "C"
    assert block["names"]["A2"]["scope_grade"] == "A"
    with pytest.raises(FileExistsError):
        market_peer_groups.run(tmp_path, session)
    monkeypatch.setattr(desk, "book_panel", lambda store, asof=None: (panel, {}))
    with pytest.raises(ValueError, match="not on"):
        market_peer_groups.run(tmp_path, session, overwrite=True)
