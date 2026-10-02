"""The `/4` board acts only at the measured level; the `/3` board is untouched.

The operator reads BUY as "place the buy in my own account now". So on a
record stamped with the active policy every row's `action` is the TIMED
decision and `strategy_action` stays the intent the charts draw:

- waiting for the level, before the first bar, on a non-session day and
  after the close: Hold, size 0, and the reason says what is planned and at
  what price;
- a 15-minute close at the level today (latched, even if the price has
  recovered since), or the close window: BUY / SELL / TRIM with the size;
- a name whose daily rejects its upper band (the executor's gate): Hold,
  "Buy blocked", and it takes no share of the cash;
- a quote or reading that cannot be traded keeps its blocker: timing only
  ever holds a trade back;
- the intent reads the record's close grade; the candle's re-grade is
  exposed as `grade_intraday` for the hover, and an intraday-only downgrade
  is not an exit.

And every `/3` board is identical to `main`'s (`board_v3_scenarios`).
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.market import decision_view, entry_timing
from backend.market.holdings import Holding
from backend.tests import board_v3_scenarios
from backend.tests.board_v3_scenarios import _inputs

POLICY = "graded-equal-weight/4"
EQUITY = 100000.0


# A `/4` record on the shared fixture: eleven names at 1/11, S0 at zero,
# every name's band flag recorded clear, and the clock moved to `when` (a
# New York instant on Monday 2026-09-14) with every piece of evidence fresh
# for it: the snapshot written at `when`, the latest completed bar the one
# that closed at or before `when`, quotes stamped `when`. Each quote gets an
# open `move` away from its last close (last = open x (1 + move)).
def v4(when=None, move=-0.005, until_rebalance=10):
    """Return (record, snapshot, quoted, now) for the timed `/4` board."""
    record, snapshot, quoted, now = _inputs()
    record["targets"] = {
        "policy": POLICY,
        "weights": {n: (0.0 if n == "S0" else 1 / 11) for n in record["grades"]},
    }
    record["paper"] = {"until_rebalance": until_rebalance}
    record["levels"] = {n: {"rejecting_band": False} for n in record["grades"]}
    now = when or now
    minutes = (now.minute // 15) * 15
    bar = now.replace(minute=minutes, second=0, microsecond=0) - timedelta(minutes=15)
    snapshot["as_of"] = now.isoformat()
    for q in snapshot["quotes"].values():
        q["bar"] = bar.astimezone(UTC).isoformat()
        q["open"] = q["last"] / (1.0 + move)
        q["as_of"] = now.isoformat()
    for q in quoted["quotes"].values():
        q["t"] = now.isoformat()
    return record, snapshot, quoted, now


# Monday 2026-09-14 at hour:minute New York time.
def at(hour, minute=0):
    """Return the aware instant."""
    return datetime(2026, 9, 14, hour, minute, tzinfo=entry_timing.NEW_YORK)


# Build the personal board for the inputs with the given extras.
def board(record, snapshot, quoted, now, held=(), cash=EQUITY, **kwargs):
    """Return the built board's rows."""
    return decision_view.build(
        record, list(held), EQUITY, snapshot, quoted, now, cash=cash, **kwargs
    )["rows"]


# Shares of `symbol` worth `weight` of the account at the snapshot's price.
def shares(snapshot, weight, symbol="S11"):
    """Return the share count."""
    return weight * EQUITY / snapshot["quotes"][symbol]["last"]


# The real latch, written by `entry_timing.update` from `snapshot` at `now`
# under `root`, as the API would load it.
def latched(root, snapshot, now):
    """Return today's latch document after latching `snapshot`."""
    entry_timing.update(root, snapshot, now)
    return entry_timing.load(root, now.astimezone(entry_timing.NEW_YORK).date())


# Waiting for the level: the target buy is a Hold of size 0 whose reason
# names the size, the level and the open; the intent is kept for the charts.
def test_waiting_is_a_hold_with_the_level_in_the_reason(tmp_path):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.005)
    row = board(
        record, snapshot, quoted, now, timing_latch=latched(tmp_path, snapshot, now)
    )["S11"]
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0.0
    assert row["strategy_action"] == "Buy"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11)
    assert row["executable"] is True
    assert row["timing"]["state"] == entry_timing.WAITING
    opened = snapshot["quotes"]["S11"]["open"]
    assert row["timing"]["level"] == pytest.approx(opened * 0.99)
    assert row["reason"].startswith(
        "Buy 9.1% planned: on a 15-minute close at or under $"
    )
    assert (
        f"(1% under today's open ${opened:,.2f}), else at market in the last 15 minutes"
        in row["reason"]
    )
    assert "Buy to 9.1% target (policy graded-equal-weight/4)" in row["reason"]
    assert row["structure_gate"] == decision_view.CLEAR


# A 15-minute close at the level: BUY 9.1%, and it stays a BUY after the
# price recovers above the level on a later candle (the latch holds it).
def test_a_triggered_level_is_a_buy_and_survives_the_recovery(tmp_path):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    latch = latched(tmp_path, snapshot, now)
    row = board(record, snapshot, quoted, now, timing_latch=latch)["S11"]
    assert row["action"] == "Buy"
    assert row["move_weight"] == pytest.approx(1 / 11, abs=1e-6)
    assert row["timing"]["state"] == entry_timing.TRIGGERED
    assert row["reason"].startswith("Buy now: the 10:30 AM ET 15-minute close $")
    # Two candles later the price is back above the level.
    record, snapshot, quoted, now = v4(at(11, 1), move=-0.015)
    for q in snapshot["quotes"].values():
        q["last"] = q["open"] * 1.002
    latch = latched(tmp_path, snapshot, now)
    row = board(record, snapshot, quoted, now, timing_latch=latch)["S11"]
    assert row["action"] == "Buy"
    assert row["move_weight"] == pytest.approx(1 / 11, abs=1e-6)
    assert row["timing"]["state"] == entry_timing.TRIGGERED
    assert row["timing"]["trigger_bar"] == "2026-09-14T14:15:00+00:00"


# A historical dip cannot authorize a new personal purchase above its entry ceiling.
def test_current_personal_entry_blocks_recovered_ask_and_keeps_original_signal(
    tmp_path,
):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    latch = latched(tmp_path, snapshot, now)
    record, snapshot, quoted, now = v4(at(11, 1), move=-0.015)
    price = snapshot["quotes"]["S11"]["open"] * 1.002
    snapshot["quotes"]["S11"]["last"] = price
    quoted["quotes"]["S11"].update(bp=price - 0.01, ap=price + 0.01)
    before = deepcopy((record, snapshot, quoted, latch))
    row = board(
        record, snapshot, quoted, now, timing_latch=latch, protect_entry_price=True
    )["S11"]
    assert row["action"] == "Hold"
    assert row["executable"] is False
    assert row["move_weight"] == 0
    assert row["strategy_action"] == "Buy"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11)
    assert row["grade"] == record["grades"]["S11"]["grade"]
    assert row["timing"]["state"] == entry_timing.TRIGGERED
    assert row["timing"]["trigger_bar"] == "2026-09-14T14:15:00+00:00"
    assert row["entry_guard"]["ask"] > row["entry_guard"]["limit_price"]
    assert "entry limit" in row["reason"]
    assert (record, snapshot, quoted, latch) == before


# A missed entry consumes no cash; returning inside the limit permits an entry.
def test_current_entry_cash_is_shared_only_by_names_still_inside_the_limit(tmp_path):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    for symbol, raw in quoted["quotes"].items():
        price = snapshot["quotes"][symbol]["last"]
        raw.update(bp=price - 0.01, ap=price + 0.01)
    latch = latched(tmp_path, snapshot, now)
    quoted["quotes"]["S11"].update(bp=110, ap=110.01)
    rows = board(
        record,
        snapshot,
        quoted,
        now,
        cash=10000,
        timing_latch=latch,
        protect_entry_price=True,
    )
    assert rows["S11"]["action"] == "Hold"
    assert rows["S11"]["move_weight"] == 0
    buys = [r for r in rows.values() if r["action"] == "Buy"]
    assert len(buys) == 10
    assert sum(r["move_weight"] * EQUITY for r in buys) == pytest.approx(10000)
    assert all(r["move_weight"] == pytest.approx(0.01) for r in buys)
    quoted["quotes"]["S11"].update(bp=99.99, ap=100.01)
    row = board(
        record, snapshot, quoted, now, timing_latch=latch, protect_entry_price=True
    )["S11"]
    assert row["action"] == "Buy"
    assert row["entry_guard"]["allowed"] is True
    assert row["reason"].startswith("Buy limit $")


# The close window with no trigger: BUY near the close, the market order the
# paper desk sends on the last candle (3:45 PM ET) named.
def test_the_close_window_is_a_buy(tmp_path):
    record, snapshot, quoted, now = v4(at(15, 31), move=-0.004)
    row = board(
        record, snapshot, quoted, now, timing_latch=latched(tmp_path, snapshot, now)
    )["S11"]
    assert row["action"] == "Buy"
    assert row["move_weight"] == pytest.approx(1 / 11, abs=1e-6)
    assert row["timing"]["state"] == entry_timing.CLOSE
    assert row["reason"].startswith("Buy near the close: no 15-minute close reached $")
    assert "a market order at 3:45 PM ET, in the last 15 minutes" in row["reason"]
    assert "market-on-close" not in row["reason"]


# A held name the record downgraded (close grade B, target zero) is the
# exit; it is a SELL of the whole position only when a close reaches 1%
# over the open, and a Hold that says so before that.
@pytest.mark.parametrize(("move", "expected"), [(0.012, "Sell"), (0.004, "Hold")])
def test_a_downgrade_sells_on_the_pop(tmp_path, move, expected):
    record, snapshot, quoted, now = v4(at(10, 31), move=move)
    record["grades"]["S11"]["grade"] = "B"
    record["targets"]["weights"]["S11"] = 0.0
    held = [Holding("S11", shares(snapshot, 0.05), 100.0, "2026-08-01")]
    row = board(
        record,
        snapshot,
        quoted,
        now,
        held=held,
        cash=0.0,
        timing_latch=latched(tmp_path, snapshot, now),
    )["S11"]
    assert row["strategy_action"] == "Sell"
    assert row["strategy_move_weight"] == pytest.approx(-0.05)
    assert row["action"] == expected
    assert row["timing"]["side"] == "sell"
    if expected == "Sell":
        assert row["move_weight"] == pytest.approx(-0.05)
        assert row["timing"]["state"] == entry_timing.TRIGGERED
        assert row["reason"].startswith("Sell now: the 10:30 AM ET 15-minute close $")
        assert "grade below A; close position" in row["reason"]
    else:
        assert row["move_weight"] == 0.0
        assert row["reason"].startswith(
            "Sell 5.0% planned: on a 15-minute close at or over $"
        )


# The executor's band gate: a name whose daily rejects its upper band is a
# Hold even when its level has triggered, says so, and leaves the cash to
# the names that can be bought (cash for exactly the other ten fills each).
def test_a_band_rejecting_name_is_held_and_takes_no_cash(tmp_path):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    record["levels"]["S11"]["rejecting_band"] = True
    rows = board(
        record,
        snapshot,
        quoted,
        now,
        cash=EQUITY * 10 / 11,
        timing_latch=latched(tmp_path, snapshot, now),
    )
    row = rows["S11"]
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0.0
    assert row["strategy_action"] == "Buy"
    assert row["structure_gate"] == decision_view.REJECTING
    assert row["executable"] is False
    assert row["blocker"] == "rejecting its upper band (executor's gate)"
    assert row["reason"] == (
        "Buy blocked: rejecting its upper band (executor's gate); "
        "Buy to 9.1% target (policy graded-equal-weight/4)"
    )
    others = [r for s, r in rows.items() if s not in ("S0", "S11")]
    assert all(r["action"] == "Buy" for r in others)
    for r in others:
        assert r["move_weight"] == pytest.approx(1 / 11, abs=1e-6)


# Before the opening bar is known the level cannot be priced yet: Hold, and
# the reason says the level is 1% under the open the first bar will set.
def test_before_the_opening_bar_is_a_hold():
    record, snapshot, quoted, now = v4(at(10, 1))
    for q in snapshot["quotes"].values():
        del q["open"]
    row = board(record, snapshot, quoted, now)["S11"]
    assert row["action"] == "Hold"
    assert row["timing"]["state"] == entry_timing.PRE_OPEN
    assert row["reason"].startswith(
        "Buy 9.1% planned: on a 15-minute close 1% or more under today's open "
        "(the 9:30 AM ET bar), else at market in the last 15 minutes"
    )


# After the close the session's decisions are over, even on evidence the
# board would otherwise call tradable.
def test_after_the_close_is_a_hold(tmp_path):
    record, snapshot, quoted, now = v4(at(16, 5), move=-0.015)
    row = board(
        record, snapshot, quoted, now, timing_latch=latched(tmp_path, snapshot, now)
    )["S11"]
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0.0
    assert row["timing"]["state"] == entry_timing.CLOSED
    assert row["reason"].startswith("Buy 9.1% planned: the session has closed")


# A weekend is no session: every row is a Hold and the timing says why.
def test_a_non_session_day_is_a_hold():
    record, snapshot, quoted, now = v4()
    saturday = datetime(2026, 9, 19, 11, tzinfo=entry_timing.NEW_YORK)
    rows = board(record, snapshot, quoted, saturday)
    assert all(r["action"] == "Hold" for r in rows.values())
    assert rows["S11"]["timing"]["state"] == entry_timing.PRE_OPEN
    assert rows["S11"]["timing"]["trading_day"] is False


# A triggered BUY on a quote that cannot be traded is still a Hold, and the
# reason names the blocker rather than the level.
def test_a_triggered_buy_on_an_unusable_quote_keeps_its_blocker(tmp_path):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    quoted["quotes"]["S11"]["t"] = (now - timedelta(seconds=31)).isoformat()
    row = board(
        record, snapshot, quoted, now, timing_latch=latched(tmp_path, snapshot, now)
    )["S11"]
    assert row["timing"]["state"] == entry_timing.TRIGGERED
    assert row["action"] == "Hold"
    assert row["executable"] is False
    assert row["move_weight"] == 0.0
    assert "buy not executable" in row["reason"]
    assert row["blocker"]


# Over target on the reset day is a trim: it waits for a close 1% over the
# open (TRIM needs a sell trigger), then reads as a Sell that keeps a target.
@pytest.mark.parametrize(("move", "expected"), [(0.004, "Hold"), (0.013, "Sell")])
def test_a_trim_waits_for_the_level_over_the_open(tmp_path, move, expected):
    record, snapshot, quoted, now = v4(at(10, 31), move=move, until_rebalance=0)
    held = [Holding("S11", shares(snapshot, 0.14), 100.0, "2026-08-01")]
    row = board(
        record,
        snapshot,
        quoted,
        now,
        held=held,
        cash=50000,
        timing_latch=latched(tmp_path, snapshot, now),
    )["S11"]
    assert row["strategy_action"] == "Sell"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11 - 0.14)
    assert row["action"] == expected
    assert row["target_weight"] > 0
    if expected == "Hold":
        assert row["reason"].startswith(
            "Trim 4.9% planned: on a 15-minute close at or over $"
        )
    else:
        assert row["move_weight"] == pytest.approx(1 / 11 - 0.14)
        assert row["reason"].startswith("Trim now: the 10:30 AM ET 15-minute close $")
        assert "Trim to 9.1% target (policy graded-equal-weight/4)" in row["reason"]


# The intent reads the record's close grade: a candle re-grade to B on a
# held name the record rates A+ is not an exit (the executor would not sell
# it), and both readings are on the row for the page.
def test_an_intraday_downgrade_is_not_a_v4_exit(tmp_path):
    from backend.market import holdings

    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    snapshot["technical"]["S11"] = {"now": 0.01, "close": 0.7, "stance": -1}
    assert (
        holdings.live_grades(record, snapshot["technical"])["S11"]["grade_live"] == "B"
    )
    held = [Holding("S11", shares(snapshot, 0.05), 100.0, "2026-08-01")]
    row = board(
        record,
        snapshot,
        quoted,
        now,
        held=held,
        timing_latch=latched(tmp_path, snapshot, now),
    )["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Buy"
    assert row["grade"] == "A+"
    assert row["grade_intraday"] == "B"


# A record without the band flag is not blocked, and the row says the gate
# was not recorded rather than implying it was checked.
def test_an_unrecorded_gate_is_not_a_block(tmp_path):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    del record["levels"]
    row = board(
        record, snapshot, quoted, now, timing_latch=latched(tmp_path, snapshot, now)
    )["S11"]
    assert row["structure_gate"] == decision_view.UNRECORDED
    assert row["action"] == "Buy"


# The `/4` payload says it is timed, and by what; the words stay three.
def test_the_v4_payload_names_its_timing(tmp_path):
    record, snapshot, quoted, now = v4(at(10, 31), move=-0.015)
    latch = latched(tmp_path, snapshot, now)
    built = decision_view.build(
        record, [], EQUITY, snapshot, quoted, now, cash=EQUITY, timing_latch=latch
    )
    assert built["timing"] == {
        "rule": "dip_or_close",
        "level": entry_timing.LEVEL,
        "session": "2026-09-14",
        "close_cutoff": at(15, 30).isoformat(),
        "moc_deadline": at(15, 50).isoformat(),
        "latched": True,
    }
    assert built["policy"].startswith("Nightly targets timed by the measured level")
    assert {r["action"] for r in built["rows"].values()} <= {"Buy", "Sell", "Hold"}
    for row in built["rows"].values():
        assert (row["move_weight"] == 0.0) is (row["action"] == "Hold")
    # Hold-intent rows carry no timing and the close grade.
    assert built["rows"]["S0"]["timing"] is None
    assert built["rows"]["S0"]["grade"] == "A+"


# Every `/3` board (no stamp, another policy's stamp, the research path) is
# the one `main` produced before the timing existed, and passing a latch -
# even one that would trigger every name - changes none of them.
def test_the_v3_board_is_identical_to_main(tmp_path):
    golden = board_v3_scenarios.golden(
        Path(board_v3_scenarios.__file__).parent / board_v3_scenarios.GOLDEN
    )
    rendered = board_v3_scenarios.render()
    assert sorted(rendered) == sorted(golden)
    for name in golden:
        assert rendered[name] == golden[name], name
    _, snapshot, _, now = v4(move=-0.05)
    latch = latched(tmp_path, snapshot, now)
    assert latch["symbols"]["S11"]["buy_trigger"] is not None
    with_latch = board_v3_scenarios.render({"timing_latch": latch})
    assert board_v3_scenarios.dumps(with_latch) == board_v3_scenarios.dumps(rendered)
    for name, built in rendered.items():
        assert "timing" not in built, name
        for row in built["rows"].values():
            assert "timing" not in row
            assert "structure_gate" not in row
