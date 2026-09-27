"""The mid-cycle study prices its registered variants, its options are honest and the defaults change nothing.

On the pit scorecard's synthetic report (six names, SPY, 320 sessions, a
dated membership file) with grades that flicker - two names fall to B for
a stretch and one is B before it is A+ - every variant runs; "live" is
`simulate.run` with the scorecard's live options element for element, and
the new `midcycle_entries` / `midcycle_sweep` defaults are byte-identical
to a run that never names them, with or without the ledger attached. The
entry modes and the sweep are checked by hand on small inputs, the
diagnostics on a hand-built ledger, the verdict on a hand-built payload,
and the command end to end.
"""

import io
import json
import math
from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import (
    grading,
    paper,
    point_in_time,
    policy_v4,
    simulate,
)
from backend.cli import market_midcycle_ew as cli
from backend.cli import market_pit_scorecard as sc
from backend.market import midcycle_ew as me
from backend.market.session_anatomy import json_ready
from backend.tests.test_market_pit_scorecard import (  # noqa: F401 - fixture
    _report,
    history,
)

B = grading.ORDINAL["B"]


# The synthetic report with grades that move between rebalances: BBB is B
# on sessions 25-44 and 130-149, CCC is B until session 70, DDD is B on
# 200-214. Every other grade is A+, as the scorecard's fixture has it.
def _flicker_report():
    report = _report()
    grades = report.graded.grades.copy()
    grades[25:45, 1] = B
    grades[130:150, 1] = B
    grades[:70, 2] = B
    grades[200:215, 3] = B
    return replace(report, graded=replace(report.graded, grades=grades))


# The restricted flicker report, its mask and the second-session start.
def _book(history):
    report = _flicker_report()
    restricted, mask = point_in_time.point_in_time(report, history)
    return report, restricted, mask, sc._since(report.panel, 1)


# Ten named variants: the two anchors first, mc-off with the rule off, four
# modifications of the entry leg whose modes the simulator knows, then the
# four follow-on trials - three redeploy variants with the rule on and the
# reset top-up with it off - appended after the first six, which are
# unchanged.
def test_variants_are_registered_and_named():
    names = [v.name for v in me.VARIANTS]
    assert len(names) == len(set(names)) == 10
    assert names[:2] == [me.MC_OFF, me.LIVE]
    assert me.variant(me.MC_OFF).live_midcycle is False
    assert me.variant(me.LIVE) == me.Variant(me.LIVE, note=me.variant(me.LIVE).note)
    for v in me.VARIANTS[2:6]:
        assert v.live_midcycle is True
        assert v.entries in simulate.MIDCYCLE_ENTRIES
        assert v.entries != simulate.MIDCYCLE_BREAKOUT or v.sweep
        assert not v.redeploy and v.exits and not v.reset_topup
    assert {v.entries for v in me.VARIANTS} == set(simulate.MIDCYCLE_ENTRIES)
    assert (
        names[6:]
        == [v.name for v in me.FOLLOW_ON]
        == [
            "mc-redeploy",
            "mc-redeploy-nobuffer",
            "mc-redeploy-no-exits",
            "reset-full-invest",
        ]
    )
    redeploy = me.variant("mc-redeploy")
    assert redeploy.redeploy and redeploy.buffer == simulate.REDEPLOY_BUFFER == 0.02
    assert redeploy.exits and redeploy.entries == simulate.MIDCYCLE_BREAKOUT
    assert me.variant("mc-redeploy-nobuffer").buffer == 0.0
    assert me.variant("mc-redeploy-no-exits").exits is False
    full = me.variant("reset-full-invest")
    assert full.live_midcycle is False and full.reset_topup and full.buffer == 0.0
    with pytest.raises(KeyError):
        me.variant("nothing")
    # `selected` adds the anchors to a `--only` list and refuses an unknown name.
    assert [v.name for v in me.selected(["mc-redeploy"])] == [
        me.MC_OFF,
        me.LIVE,
        "mc-redeploy",
    ]
    assert me.selected(None) == me.VARIANTS
    with pytest.raises(KeyError):
        me.selected(["mc-redeploy", "nothing"])


# "live" is `_live_options` plus the mid-cycle defaults; mc-off turns the
# rule off and carries no mid-cycle keys; every other variant with the rule
# on changes exactly its own mid-cycle keys; reset-full-invest is mc-off
# plus the top-up and its buffer.
def test_options_are_the_live_policy_with_the_midcycle_keys_alone_changed():
    panel = _report().panel
    expected = sc._live_options(panel)
    live = me.options_for(me.variant(me.LIVE), panel)
    midcycle_keys = {
        "midcycle_entries",
        "midcycle_sweep",
        "midcycle_redeploy",
        "redeploy_buffer",
        "midcycle_exits",
    }
    assert set(live) == set(expected) | midcycle_keys
    for key, value in expected.items():
        if key == "event_exposure":
            np.testing.assert_array_equal(live[key], value)
        else:
            assert live[key] == value, key
    assert live["midcycle_entries"] == simulate.MIDCYCLE_BREAKOUT
    assert live["midcycle_sweep"] is False
    assert live["midcycle_redeploy"] is False and live["midcycle_exits"] is True
    assert live["redeploy_buffer"] == simulate.REDEPLOY_BUFFER
    off = me.options_for(me.variant(me.MC_OFF), panel)
    assert off["live_midcycle"] is False and not (midcycle_keys & set(off))
    assert "reset_topup" not in off
    assert {
        k
        for k in expected
        if k != "live_midcycle"
        and not isinstance(expected[k], np.ndarray)
        and off[k] != expected[k]
    } == set()
    changes = {
        "mc-target-size": {"midcycle_entries"},
        "mc-no-idle-cash": {"midcycle_sweep"},
        "mc-new-grades-only": {"midcycle_entries"},
        "mc-exit-only": {"midcycle_entries"},
        "mc-redeploy": {"midcycle_redeploy"},
        "mc-redeploy-nobuffer": {"midcycle_redeploy", "redeploy_buffer"},
        "mc-redeploy-no-exits": {"midcycle_redeploy", "midcycle_exits"},
    }
    for v in me.VARIANTS[2:]:
        if not v.live_midcycle:
            continue
        options = me.options_for(v, panel)
        changed = {
            k
            for k in live
            if not isinstance(live[k], np.ndarray) and options[k] != live[k]
        }
        assert changed == changes[v.name], v.name
        assert options["live_midcycle"] is True
    full = me.options_for(me.variant("reset-full-invest"), panel)
    assert full["live_midcycle"] is False and full["reset_topup"] is True
    assert full["redeploy_buffer"] == 0.0
    assert not (midcycle_keys - {"redeploy_buffer"}) & set(full)
    described = me._describe(live)
    assert described["event_exposure"] == "event_risk.live_path(panel)"


# Naming the defaults changes nothing, byte for byte, and neither does the
# ledger: the live curve is the same with and without either.
def test_defaults_and_ledger_are_byte_identical(history):
    report, restricted, mask, since = _book(history)
    live = sc._live_options(report.panel)
    plain = simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=policy_v4.allocator(mask),
        **live,
    )
    named = simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=policy_v4.allocator(mask),
        midcycle_entries=simulate.MIDCYCLE_BREAKOUT,
        midcycle_sweep=False,
        midcycle_redeploy=False,
        redeploy_buffer=simulate.REDEPLOY_BUFFER,
        midcycle_exits=True,
        reset_topup=False,
        **live,
    )
    np.testing.assert_array_equal(plain.returns, named.returns)
    assert plain.traded == named.traded
    priced = me.price(restricted, mask, me.variant(me.LIVE), since, 25.0)
    np.testing.assert_array_equal(plain.returns, priced.curve.daily)
    assert priced.diagnostics["all"]["exits_per_year"] > 0
    # The same with the rule off: naming the top-up's default changes nothing.
    off = {**live, "live_midcycle": False}
    plain_off = simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=policy_v4.allocator(mask),
        **off,
    )
    named_off = simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=policy_v4.allocator(mask),
        reset_topup=False,
        redeploy_buffer=0.0,
        **off,
    )
    np.testing.assert_array_equal(plain_off.returns, named_off.returns)
    assert plain_off.traded == named_off.traded


# The simulator refuses an unknown mode and a variant without the rule it modifies.
def test_simulator_refuses_bad_midcycle_options(history):
    report, restricted, mask, since = _book(history)
    base = dict(
        since=since, cost_bps=25.0, allocator=policy_v4.allocator(mask), use_exits=False
    )
    with pytest.raises(ValueError, match="midcycle_entries must be one of"):
        simulate.run(restricted, live_midcycle=True, midcycle_entries="odd", **base)
    with pytest.raises(ValueError, match="require live_midcycle"):
        simulate.run(restricted, midcycle_entries="target", **base)
    with pytest.raises(ValueError, match="require live_midcycle"):
        simulate.run(restricted, midcycle_sweep=True, **base)
    with pytest.raises(ValueError, match="require live_midcycle"):
        simulate.run(restricted, midcycle_redeploy=True, **base)
    with pytest.raises(ValueError, match="require live_midcycle"):
        simulate.run(restricted, midcycle_exits=False, **base)
    with pytest.raises(ValueError, match="reset_topup is for a book without"):
        simulate.run(
            restricted, live_midcycle=True, exit_at_close=True, reset_topup=True, **base
        )
    with pytest.raises(ValueError, match="redeploy_buffer"):
        simulate.run(restricted, redeploy_buffer=1.0, **base)
    with pytest.raises(ValueError, match="redeploy_buffer"):
        simulate.run(restricted, redeploy_buffer=float("nan"), **base)


# The entry modes by hand. Prices 100 everywhere, equity 1000, AAA held at
# 10% and BBB unheld; both graded A+; only BBB breaks out. "target" sizes
# BBB straight to its 20% target and gives AAA (no breakout) nothing;
# "new-grade" ignores the band and opens BBB because the rebalance did not
# hold it, but not AAA (held) nor CCC (held at the rebalance); "none" is
# empty; a blocked or downgraded name never enters.
def test_variant_entry_orders_by_hand():
    prices = {"AAA": 100.0, "BBB": 100.0, "CCC": 100.0, "DDD": 100.0}
    reserved = {"AAA": 1.0}
    grades = {"AAA": "A+", "BBB": "A+", "CCC": "A+", "DDD": "B"}
    bands = {"AAA": 0.5, "BBB": 1.5, "CCC": 1.5, "DDD": 1.5}
    today = {"AAA": 0.2, "BBB": 0.2, "CCC": 0.2, "DDD": 0.2}
    at_rebalance = {"AAA": 0.25, "CCC": 0.25}
    args = (
        bands,
        reserved,
        prices,
        1000.0,
        grades,
        {},
        set(),
        today,
        at_rebalance,
        "s",
        paper.PaperState(),
    )
    target = simulate._variant_entry_orders("target", *args)
    assert {(o.symbol, round(o.qty, 6)) for o in target} == {("BBB", 2.0), ("CCC", 2.0)}
    assert all(o.side == "buy" for o in target)
    new = simulate._variant_entry_orders("new-grade", *args)
    assert [(o.symbol, round(o.qty, 6)) for o in new] == [("BBB", 2.0)]
    assert simulate._variant_entry_orders("none", *args) == []
    blocked = simulate._variant_entry_orders(
        "target",
        bands,
        reserved,
        prices,
        1000.0,
        grades,
        {},
        {"BBB"},
        today,
        at_rebalance,
        "s",
        paper.PaperState(),
    )
    assert [o.symbol for o in blocked] == ["CCC"]
    # A held name above its target gets no top-up; one below it is topped
    # up to the target, not by entry_size.
    topped = simulate._variant_entry_orders(
        "target",
        {"AAA": 1.5},
        {"AAA": 1.5},
        {"AAA": 100.0},
        1000.0,
        {"AAA": "A+"},
        {},
        set(),
        {"AAA": 0.2},
        {},
        "s",
        paper.PaperState(),
    )
    assert [(o.symbol, round(o.qty, 6)) for o in topped] == [("AAA", 0.5)]
    with pytest.raises(ValueError):
        simulate._variant_entry_orders("odd", *args)


# The sweep by hand: equity 1000, two held names at 30% each, the policy
# would hold 80% today, cash 400. The spare beyond the policy's 20% idle is
# 200, split pro rata (equal here) and capped at max(paper cap, target):
# 100 each. With no spare beyond the idle share there is nothing to sweep;
# a downgraded or blocked name takes nothing.
def test_sweep_orders_by_hand():
    prices = {"AAA": 100.0, "BBB": 100.0}
    reserved = {"AAA": 3.0, "BBB": 3.0}
    grades = {"AAA": "A+", "BBB": "A+"}
    today = {"AAA": 0.4, "BBB": 0.4}
    out = simulate._sweep_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {},
        set(),
        today,
        400.0,
        "s",
        paper.PaperState(),
    )
    assert {(o.symbol, round(o.qty, 6)) for o in out} == {("AAA", 1.0), ("BBB", 1.0)}
    none = simulate._sweep_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {},
        set(),
        today,
        200.0,
        "s",
        paper.PaperState(),
    )
    assert none == []
    only = simulate._sweep_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {"BBB": "grade rotation"},
        set(),
        today,
        400.0,
        "s",
        paper.PaperState(),
    )
    assert [(o.symbol, round(o.qty, 6)) for o in only] == [("AAA", 1.0)]
    # Cash a planned buy already spends is not swept twice, and the planned
    # buy counts toward the name's cap: AAA at 40% after its buy has no room,
    # so BBB alone takes its pro-rata share (3/7 of the 100 spare).
    planned = [paper.PaperOrder("AAA", "buy", 1.0, "x")]
    less = simulate._sweep_orders(
        planned,
        reserved,
        prices,
        1000.0,
        grades,
        {},
        set(),
        today,
        400.0,
        "s",
        paper.PaperState(),
    )
    assert {(o.symbol, round(o.qty, 6)) for o in less} == {("BBB", round(3 / 7, 6))}


# The redeploy by hand: equity 1000, AAA held at 10% and BBB at 30%, both
# targeted at 40% today, cash 600. Beyond the 2% buffer 580 is spare; the
# shortfalls are 300 and 100, so both are filled in full (400 spare needed)
# and 180 stays in cash. With cash 220 the 200 spare is split pro rata to
# the shortfall, 150 and 50. A buffer of 0 spends the last dollar. A name
# graded in since the reset (CCC, target 40% today, none at the reset,
# unheld) is a taker; a downgraded or rotating name, or one held at the
# reset and unheld now, is not. A planned buy counts toward the name's
# target and is not spent twice; there is no band gate and no 15% cap.
def test_redeploy_orders_by_hand():
    prices = {"AAA": 100.0, "BBB": 100.0, "CCC": 100.0}
    reserved = {"AAA": 1.0, "BBB": 3.0}
    grades = {"AAA": "A+", "BBB": "A+", "CCC": "A+"}
    today = {"AAA": 0.4, "BBB": 0.4}
    args = (prices, 1000.0, grades, {}, today, {}, 600.0, 0.02, "s")
    full = simulate._redeploy_orders([], reserved, *args, paper.PaperState())
    assert {(o.symbol, round(o.qty, 6)) for o in full} == {("AAA", 3.0), ("BBB", 1.0)}
    part = simulate._redeploy_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {},
        today,
        {},
        220.0,
        0.02,
        "s",
        paper.PaperState(),
    )
    assert {(o.symbol, round(o.qty, 6)) for o in part} == {("AAA", 1.5), ("BBB", 0.5)}
    none = simulate._redeploy_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {},
        today,
        {},
        20.0,
        0.02,
        "s",
        paper.PaperState(),
    )
    assert none == []
    last_dollar = simulate._redeploy_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {},
        today,
        {},
        20.0,
        0.0,
        "s",
        paper.PaperState(),
    )
    assert {(o.symbol, round(o.qty, 6)) for o in last_dollar} == {
        ("AAA", 0.15),
        ("BBB", 0.05),
    }
    # A name graded in since the reset enters toward its target; at 45% above
    # the 15% paper cap it is still filled (no cap but the target's own).
    new = simulate._redeploy_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {},
        {**today, "CCC": 0.45},
        {"AAA": 0.4},
        1000.0,
        0.0,
        "s",
        paper.PaperState(),
    )
    assert {(o.symbol, round(o.qty, 6)) for o in new} == {
        ("AAA", 3.0),
        ("BBB", 1.0),
        ("CCC", 4.5),
    }
    # Held at the reset, unheld now and not in the book: not a taker.
    held_then = simulate._redeploy_orders(
        [],
        reserved,
        prices,
        1000.0,
        grades,
        {},
        {**today, "CCC": 0.4},
        {"CCC": 0.4},
        1000.0,
        0.0,
        "s",
        paper.PaperState(),
    )
    assert {o.symbol for o in held_then} == {"AAA", "BBB"}
    downgraded = simulate._redeploy_orders(
        [],
        reserved,
        prices,
        1000.0,
        {**grades, "AAA": "B"},
        {"BBB": "grade rotation"},
        today,
        {},
        600.0,
        0.02,
        "s",
        paper.PaperState(),
    )
    assert downgraded == []
    planned = [paper.PaperOrder("AAA", "buy", 2.0, "x")]
    after = simulate._redeploy_orders(
        planned,
        reserved,
        prices,
        1000.0,
        grades,
        {},
        today,
        {},
        600.0,
        0.02,
        "s",
        paper.PaperState(),
    )
    # 380 spare after the planned 200; shortfalls 100 (AAA) and 100 (BBB).
    assert {(o.symbol, round(o.qty, 6)) for o in after} == {("AAA", 1.0), ("BBB", 1.0)}
    assert all(o.reason.startswith("redeploy") for o in after)


# The variants on the flicker book: exit-only opens nothing between
# rebalances yet still rotates out of downgrades; new-grades-only opens CCC
# on a mid-cycle fill once it is graded A+ (session 70, between the resets
# at 61 and 81) at the policy's target weight, and every such entry is still
# held at the next rebalance; the sweep holds no more cash than live; every
# variant is a curve on the same sessions.
def test_variants_behave_on_the_flicker_book(history):
    report, restricted, mask, since = _book(history)
    priced = {v.name: me.price(restricted, mask, v, since, 25.0) for v in me.VARIANTS}
    live = priced[me.LIVE]
    for p in priced.values():
        np.testing.assert_array_equal(p.curve.dates, live.curve.dates)
    d = {name: p.diagnostics["all"] for name, p in priced.items()}
    assert d[me.MC_OFF]["exits_per_year"] == 0 and d[me.MC_OFF]["entries_per_year"] == 0
    assert d[me.LIVE]["exits_per_year"] > 0
    assert d["mc-exit-only"]["entries_per_year"] == 0
    assert d["mc-exit-only"]["exits_per_year"] == d[me.LIVE]["exits_per_year"]
    assert d["mc-new-grades-only"]["entries_per_year"] > 0
    assert d["mc-new-grades-only"]["entries_held_at_rebalance"] == 1.0
    assert 0.1 < d["mc-new-grades-only"]["entry_weight"] <= policy_v4.HOLD_CAP + 1e-9
    assert d["mc-no-idle-cash"]["cash_share"] <= d[me.LIVE]["cash_share"]
    assert d["mc-no-idle-cash"]["midcycle_turnover"] > d[me.LIVE]["midcycle_turnover"]
    # The redeploy holds less cash than live and than the sweep, and beyond
    # the allocator's own idle share (the 20% cap on four names) it holds
    # nothing but its buffer once the cash it found is placed; without the
    # buffer less still; the no-exits variant never exits between resets
    # while the redeploy variants exit as often as live.
    idle = d[me.MC_OFF]["idle_target_share"]
    assert 0.05 < idle < 0.25
    assert d["mc-redeploy"]["cash_share"] < d["mc-no-idle-cash"]["cash_share"]
    assert d["mc-redeploy"]["cash_share"] < d[me.LIVE]["cash_share"]
    assert d["mc-redeploy-nobuffer"]["cash_share"] <= d["mc-redeploy"]["cash_share"]
    assert d["mc-redeploy-nobuffer"]["cash_share"] < idle + 0.03
    assert d["mc-redeploy-no-exits"]["exits_per_year"] == 0
    assert d["mc-redeploy"]["exits_per_year"] == d[me.LIVE]["exits_per_year"]
    assert d["mc-redeploy"]["midcycle_turnover"] > d[me.LIVE]["midcycle_turnover"]
    # The reset top-up: no mid-cycle entries or exits, like mc-off; less cash
    # than mc-off after the reset, and its trades count as the rebalance's.
    full = d["reset-full-invest"]
    assert full["exits_per_year"] == 0 and full["entries_per_year"] == 0
    assert full["cash_share_post_reset"] < d[me.MC_OFF]["cash_share_post_reset"]
    # With the top-up the post-reset cash is at most the allocator's own
    # idle share at the reset (the 20% cap on four names, none on five),
    # give or take the drift between the close the order was sized at and
    # the fills; without it mc-off holds more - the retry's 15% cap under a
    # 20% target and the buy-at-open, sell-at-close reset leave the rest idle.
    assert full["cash_share_post_reset"] <= full["idle_target_at_reset"] + 0.01
    assert d[me.MC_OFF]["cash_share_post_reset"] > full["cash_share_post_reset"] + 0.01
    assert full["cash_share"] < d[me.MC_OFF]["cash_share"]
    assert full["midcycle_turnover"] == 0
    assert full["rebalance_turnover"] > d[me.MC_OFF]["rebalance_turnover"]
    # The FOMC path is 1 throughout this synthetic history, so the unpaused
    # cash share is the cash share.
    assert d[me.LIVE]["cash_share_unpaused"] == pytest.approx(d[me.LIVE]["cash_share"])
    # CCC (column 2) is opened between the rebalances at 61 and 81 under
    # new-grades-only: the ledger shows it unheld at 70 and held by 81.
    ledger = me.Ledger()
    simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=policy_v4.allocator(mask),
        journal=ledger,
        **me.options_for(me.variant("mc-new-grades-only"), report.panel),
    )
    assert ledger.marks[70][1][2] == 0 and ledger.marks[81][1][2] > 0
    assert ledger.kinds[61] == me.REBALANCE and ledger.kinds[70] == me.MIDCYCLE
    opened = [
        s
        for s in range(71, 82)
        if ledger.marks[s][1][2] > 0 and ledger.marks[s - 1][1][2] == 0
    ]
    assert opened and ledger.kinds[opened[0] - 1] == me.MIDCYCLE


# The diagnostics on a hand-built ledger: two names, a rebalance at 0 and
# 4, mid-cycle plans at 1-3 and 5. Name 1 is opened on the fill of 2 (a
# mid-cycle entry, weight 0.20) and still held at the rebalance decision
# 4; name 0 leaves on the fill of 3 (a mid-cycle exit) and is bought back
# at the rebalance fill 5. Turnover is split by the kind that traded.
def test_diagnostics_on_a_hand_built_ledger():
    ledger = me.Ledger()
    dates = np.arange("2020-01-01", "2020-01-08", dtype="datetime64[D]")
    closes = np.full((7, 2), 100.0)
    ledger.assert_inputs(dates, ("AAA", "BBB"), closes, closes, 10.0)
    for s, kind in (
        (0, me.REBALANCE),
        (1, me.MIDCYCLE),
        (2, me.MIDCYCLE),
        (3, me.MIDCYCLE),
        (4, me.REBALANCE),
        (5, me.MIDCYCLE),
    ):
        meta = {"scheduled": kind == me.REBALANCE}
        assert ledger.decision(s, None, None, "r", meta) == s
        assert ledger.kinds[s] == kind
    assert ledger.decision(6, None, None, "r", {"event_scale": 0.5}) == 6
    assert ledger.kinds[6] == me.EVENT
    marks = [
        (0, 1000.0, [0.0, 0.0], 1000.0, 0.0),
        (1, 200.0, [8.0, 0.0], 1000.0, 800.0),  # rebalance fill
        (2, 200.0, [8.0, 0.0], 1000.0, 800.0),  # nothing
        (3, 0.0, [8.0, 2.0], 1000.0, 1000.0),  # mid-cycle entry BBB at 20% (fill of 2)
        (4, 800.0, [0.0, 2.0], 1000.0, 1800.0),  # mid-cycle exit AAA (fill of 3)
        (5, 0.0, [8.0, 2.0], 1000.0, 2600.0),  # rebalance fill: AAA bought back
        (6, 0.0, [8.0, 2.0], 1000.0, 2600.0),
    ]
    for s, cash, shares, nav, traded in marks:
        ledger.mark(s, cash, np.array(shares), nav, traded)
    out = me.diagnostics(ledger, None, None)
    years = 6 / 252.0
    assert out["sessions"] == 6
    assert out["midcycle_turnover"] == pytest.approx((200.0 + 800.0) / 1000.0 / years)
    assert out["rebalance_turnover"] == pytest.approx((800.0 + 800.0) / 1000.0 / years)
    assert out["entries_per_year"] == pytest.approx(1 / years)
    assert out["exits_per_year"] == pytest.approx(1 / years)
    assert out["entry_weight"] == pytest.approx(0.2)
    assert out["entries_held_at_rebalance"] == 1.0
    assert out["exits_rebought_at_rebalance"] == 1.0
    assert out["cash_share"] == pytest.approx(np.mean([0.2, 0.2, 0.0, 0.8, 0.0, 0.0]))
    assert out["midcycle_cash_share"] == pytest.approx(np.mean([0.2, 0.0, 0.8, 0.0]))
    # A window with no fills reports NaNs and zero sessions; an empty ledger too.
    empty = me.diagnostics(ledger, np.datetime64("2021-01-01").astype(object), None)
    assert empty["sessions"] == 0 and math.isnan(empty["entries_per_year"])
    assert me.diagnostics(me.Ledger(), None, None)["sessions"] == 0


# The payload holds every variant on every window at every cost with the
# diagnostics on each row, pairs every variant against live and against
# mc-off, and refuses nothing on this book.
def test_run_variants_payload(history):
    report, restricted, mask, _since = _book(history)
    payload = me.run_variants(report, restricted, mask, None, 2, (10.0, 25.0))
    names = {v.name for v in me.VARIANTS}
    assert payload["study"] == me.STUDY and payload["trials"] == 10
    assert payload["refused"] == {} and payload["ran"] == [v.name for v in me.VARIANTS]
    assert payload["selected"] == payload["ran"]
    assert payload["follow_on"] == [v.name for v in me.FOLLOW_ON]
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["diagnostics"] == list(me.DIAGNOSTICS)
    assert {r["line"] for r in payload["rows"]} == names
    assert len(payload["rows"]) == 10 * len(sc.WINDOWS) * 2
    for row in payload["rows"]:
        assert row["offsets"] == 2
        assert {
            "median_cagr",
            "median_drawdown",
            "offsets_above_live",
            "sessions",
        } <= set(row)
        assert set(me.DIAGNOSTICS) <= set(row)
    assert all(
        r["offsets_above_live"] == 0 for r in payload["rows"] if r["line"] == me.LIVE
    )
    pairs = {(p["line"], p["against"]) for p in payload["paired"]}
    assert pairs == {(n, me.LIVE) for n in names - {me.LIVE}} | {
        (n, me.MC_OFF) for n in names - {me.MC_OFF}
    }
    for p in payload["paired"]:
        assert {"mean_daily_bp", "hac_t", "psr", "sessions"} <= set(p)
    described = {v["name"]: v for v in payload["variants"]}
    assert (
        described[me.MC_OFF]["entries"] is None
        and described[me.MC_OFF]["options"]["live_midcycle"] is False
    )
    assert described["mc-target-size"]["options"]["midcycle_entries"] == "target"
    assert (
        described[me.LIVE]["options"]["event_exposure"] == "event_risk.live_path(panel)"
    )
    assert described["mc-redeploy"]["follow_on"] is True
    assert described["mc-redeploy"]["options"]["midcycle_redeploy"] is True
    assert described["mc-redeploy"]["buffer"] == 0.02
    assert described["mc-redeploy-no-exits"]["options"]["midcycle_exits"] is False
    assert described["reset-full-invest"]["options"]["reset_topup"] is True
    assert described["reset-full-invest"]["redeploy"] is None
    assert described[me.LIVE]["follow_on"] is False
    assert described[me.LIVE]["buffer"] is None


# `only` prices the named variants and the anchors alone; `merge_payload`
# folds that run into an earlier full payload, keeping the earlier rows of
# the lines it did not price and replacing those it did, and the merged
# verdict reads every variant. A payload from another study, or another
# offset count, is refused.
def test_only_and_merge(history):
    report, restricted, mask, _since = _book(history)
    earlier = me.run_variants(
        report,
        restricted,
        mask,
        None,
        2,
        (25.0,),
        only=[v.name for v in me.VARIANTS[:6]],
    )
    assert earlier["ran"] == [v.name for v in me.VARIANTS[:6]]
    assert {r["line"] for r in earlier["rows"]} == set(earlier["ran"])
    later = me.run_variants(
        report,
        restricted,
        mask,
        None,
        2,
        (25.0,),
        only=["mc-redeploy", "reset-full-invest"],
    )
    assert later["ran"] == [me.MC_OFF, me.LIVE, "mc-redeploy", "reset-full-invest"]
    assert later["selected"] == later["ran"]
    assert {p["line"] for p in later["paired"]} == {
        me.MC_OFF,
        me.LIVE,
        "mc-redeploy",
        "reset-full-invest",
    }
    merged = me.merge_payload(json.loads(json.dumps(json_ready(earlier))), later)
    assert merged["ran"] == [v.name for v in me.VARIANTS[:6]] + [
        "mc-redeploy",
        "reset-full-invest",
    ]
    assert {r["line"] for r in merged["rows"]} == set(merged["ran"])
    assert len(merged["rows"]) == 8 * len(sc.WINDOWS)
    assert merged["merged"]["kept"] == [v.name for v in me.VARIANTS[2:6]]
    assert merged["merged"]["repriced"] == later["ran"]
    # The anchors' rows are this run's and agree with the earlier run's.
    for line in me.ANCHORS:
        old = [r for r in earlier["rows"] if r["line"] == line]
        new = [r for r in merged["rows"] if r["line"] == line]
        assert [r["median_cagr"] for r in old] == pytest.approx(
            [r["median_cagr"] for r in new]
        )
    assert len([r for r in merged["rows"] if r["line"] == me.LIVE]) == len(sc.WINDOWS)
    verdict = me.verdict(merged)
    assert set(verdict["variants"]) == {v.name for v in me.VARIANTS} - {me.LIVE}
    assert verdict["variants"]["mc-target-size"]["measured"] is True
    assert verdict["variants"]["mc-redeploy"]["measured"] is True
    assert verdict["variants"]["mc-redeploy-nobuffer"]["measured"] is False
    with pytest.raises(ValueError, match="cannot merge: offsets"):
        me.merge_payload({**earlier, "offsets": 3}, later)
    with pytest.raises(ValueError, match="cannot merge: study"):
        me.merge_payload({**earlier, "study": "other"}, later)


# A variant `simulate.run` refuses is recorded with its reason and left out
# of the rows; the rest still run.
def test_refused_variant_is_recorded(history, monkeypatch):
    report, restricted, mask, _since = _book(history)
    broken = me.Variant(
        "mc-broken", live_midcycle=False, entries="target", note="off but modified"
    )
    original = me.options_for

    # `options_for` drops the mid-cycle keys when the rule is off, so the
    # refusal has to be forced through: the rule off with an entry mode named.

    def options_for(v, panel):
        if v.name == "mc-broken":
            return {
                **sc._live_options(panel),
                "live_midcycle": False,
                "midcycle_entries": "target",
            }
        return original(v, panel)

    monkeypatch.setattr(me, "options_for", options_for)
    monkeypatch.setattr(me, "VARIANTS", me.VARIANTS + (broken,))
    payload = me.run_variants(report, restricted, mask, None, 1, (10.0,))
    assert payload["trials"] == 11
    assert "require live_midcycle" in payload["refused"]["mc-broken"]
    assert "mc-broken" not in {r["line"] for r in payload["rows"]}
    assert "mc-broken" not in payload["ran"] and me.LIVE in payload["ran"]
    verdict = me.verdict(payload)
    assert verdict["variants"]["mc-broken"]["measured"] is False
    assert verdict["variants"]["mc-broken"]["decision"] == me.RECORD


# A payload with the given per-variant CAGRs and drawdowns per window, t
# statistics and reported differences at 25 bp.
def _payload(
    choosing,
    reported,
    t,
    reported_bp,
    dd_choosing=None,
    dd_reported=None,
    above=None,
    cash=None,
):
    rows, paired = [], []
    for name, cagr in choosing.items():
        rows.append(
            {
                "line": name,
                "cost_bps": 25.0,
                "window": me.CHOOSING,
                "median_cagr": cagr,
                "median_drawdown": (dd_choosing or {}).get(name, -0.30),
                "offsets": 20,
                "offsets_above_live": (above or {}).get(name, 10),
                "cash_share": (cash or {}).get(name, 0.2),
            }
        )
        rows.append(
            {
                "line": name,
                "cost_bps": 25.0,
                "window": me.REPORTED,
                "median_cagr": reported.get(name, 0.4),
                "median_drawdown": (dd_reported or {}).get(name, -0.20),
                "offsets": 20,
                "offsets_above_live": (above or {}).get(name, 10),
                "cash_share": (cash or {}).get(name, 0.2),
            }
        )
        if name != me.LIVE:
            paired.append(
                {
                    "line": name,
                    "against": me.LIVE,
                    "cost_bps": 25.0,
                    "window": me.CHOOSING,
                    "mean_daily_bp": (cagr - choosing[me.LIVE]) * 1e4 / 252,
                    "hac_t": t.get(name, 0.0),
                }
            )
            paired.append(
                {
                    "line": name,
                    "against": me.LIVE,
                    "cost_bps": 25.0,
                    "window": me.REPORTED,
                    "mean_daily_bp": reported_bp.get(name, 0.0),
                    "hac_t": 0.0,
                }
            )
    return {"costs_bps": [10.0, 25.0], "rows": rows, "paired": paired, "refused": {}}


# The verdict's floors on a hand-built payload: +1.5 pt at t 2.5, not worse
# later and drawdown within 3 pt is ADOPT; the same with t 1.5 is RECORD;
# +0.8 pt at t 3 is RECORD; +2 pt at t 3 but worse later is RECORD; +2 pt
# at t 3 with a drawdown 4 pt deeper on either window is RECORD; a variant
# that costs points is RECORD with a negative effect.
def test_verdict_floors():
    names = [v.name for v in me.VARIANTS if v.name != me.LIVE]
    choosing = {me.LIVE: 0.232, **{n: 0.232 for n in names}}
    choosing["mc-target-size"] = 0.247  # +1.5, t 2.5: ADOPT
    choosing["mc-no-idle-cash"] = 0.247  # +1.5, t 1.5: RECORD
    choosing["mc-new-grades-only"] = 0.240  # +0.8: RECORD
    choosing["mc-exit-only"] = 0.252  # +2.0, worse later: RECORD
    choosing[me.MC_OFF] = 0.278  # +4.6, t 0.5: RECORD (the ablation's number)
    t = {
        "mc-target-size": 2.5,
        "mc-no-idle-cash": 1.5,
        "mc-new-grades-only": 3.0,
        "mc-exit-only": 3.0,
        me.MC_OFF: 0.5,
    }
    reported_bp = {n: 0.5 for n in names}
    reported_bp["mc-exit-only"] = -0.5
    verdict = me.verdict(_payload(choosing, {}, t, reported_bp))
    decisions = {k: v["decision"] for k, v in verdict["variants"].items()}
    follow_on = {v.name: me.RECORD for v in me.FOLLOW_ON}
    assert decisions == {
        "mc-target-size": me.ADOPT,
        "mc-no-idle-cash": me.RECORD,
        "mc-new-grades-only": me.RECORD,
        "mc-exit-only": me.RECORD,
        me.MC_OFF: me.RECORD,
        **follow_on,
    }
    assert verdict["adopt"] == ["mc-target-size"] and len(verdict["record"]) == 8
    assert verdict["consistent"] == []
    assert verdict["variants"]["mc-redeploy"]["follow_on"] is True
    assert verdict["variants"]["mc-exit-only"]["passes_choosing"] is True
    assert verdict["variants"]["mc-exit-only"]["not_worse_reported"] is False
    assert verdict["variants"][me.MC_OFF]["anchor"] is True
    assert verdict["variants"]["mc-target-size"]["choosing_points"] == pytest.approx(
        1.5
    )
    assert "ADOPT (registered): mc-target-size" in verdict["text"]
    # The drawdown floor: 4 pt deeper on the choosing window fails it, 2 pt does not.
    deeper = me.verdict(
        _payload(choosing, {}, t, reported_bp, dd_choosing={"mc-target-size": -0.34})
    )
    assert deeper["variants"]["mc-target-size"]["decision"] == me.RECORD
    assert deeper["variants"]["mc-target-size"]["drawdown_within"] is False
    assert deeper["variants"]["mc-target-size"]["drawdown_gap_points"][
        me.CHOOSING
    ] == pytest.approx(-4.0)
    later = me.verdict(
        _payload(choosing, {}, t, reported_bp, dd_reported={"mc-target-size": -0.24})
    )
    assert later["variants"]["mc-target-size"]["decision"] == me.RECORD
    shallow = me.verdict(
        _payload(choosing, {}, t, reported_bp, dd_choosing={"mc-target-size": -0.32})
    )
    assert shallow["variants"]["mc-target-size"]["decision"] == me.ADOPT
    # Nothing to adopt: the text says so. Without live it is not measured.
    flat = me.verdict(
        _payload({me.LIVE: 0.232, **{n: 0.232 for n in names}}, {}, {}, {})
    )
    assert flat["adopt"] == [] and "every variant is RECORD" in flat["text"]
    empty = me.verdict(
        {"costs_bps": [10.0], "rows": [], "paired": [], "refused": {"live": "x"}}
    )
    assert empty["cost_bps"] == 10.0 and empty["text"].startswith("not measured")


# The second reading. Live earns 23.2% holding 22% cash (78% invested);
# mc-redeploy earns 25.3% holding 8% cash (92% invested). Live scaled to
# 92% invested would earn 23.2 x 92/78 = 27.4%, so the exposure-adjusted
# gain is -2.1 pt: the variant earned less than its extra exposure alone
# explains. On the sign test, +2.1 pt on 18 of 20 offsets at t 0.7 is
# CONSISTENT, floor not cleared by daily t - still a RECORD, never an ADOPT;
# on 17 offsets, or at +1.9 pt, it is a plain RECORD; an ADOPT is read as
# ADOPT whatever the offsets say.
def test_verdict_exposure_reading_and_sign_test():
    names = [v.name for v in me.VARIANTS if v.name != me.LIVE]
    choosing = {me.LIVE: 0.232, **{n: 0.232 for n in names}}
    choosing["mc-redeploy"] = 0.253
    choosing["mc-redeploy-nobuffer"] = 0.253
    choosing["mc-redeploy-no-exits"] = 0.251
    choosing["mc-target-size"] = 0.247
    t = {"mc-redeploy": 0.7, "mc-target-size": 2.5}
    above = {"mc-redeploy": 18, "mc-redeploy-nobuffer": 17, "mc-redeploy-no-exits": 18}
    cash = {me.LIVE: 0.22, "mc-redeploy": 0.08, "mc-redeploy-no-exits": 0.22}
    verdict = me.verdict(
        _payload(choosing, {}, t, {n: 0.5 for n in names}, above=above, cash=cash)
    )
    info = verdict["variants"]["mc-redeploy"]
    assert info["decision"] == me.RECORD and info["consistent"] is True
    assert info["reading"] == me.CONSISTENT
    assert info["invested_share"] == pytest.approx(0.92)
    assert info["live_invested_share"] == pytest.approx(0.78)
    assert info["exposure_adjusted_live_cagr"] == pytest.approx(0.232 * 0.92 / 0.78)
    assert info["exposure_adjusted_points"] == pytest.approx(
        (0.253 - 0.232 * 0.92 / 0.78) * 100
    )
    assert info["offsets_above_live"] == 18 and info["offsets"] == 20
    assert verdict["variants"]["mc-redeploy-nobuffer"]["reading"] == me.RECORD
    assert verdict["variants"]["mc-redeploy-no-exits"]["reading"] == me.RECORD
    assert verdict["variants"]["mc-target-size"]["reading"] == me.ADOPT
    assert verdict["variants"]["mc-target-size"]["consistent"] is False
    assert verdict["consistent"] == ["mc-redeploy"]
    assert verdict["floors"]["consistent_share"] == 0.9
    assert me.CONSISTENT in verdict["text"]
    assert "18/20 offsets above live" in verdict["text"]
    assert "exposure-adjusted" in verdict["text"]
    # A variant with the same cash share as live has no exposure adjustment.
    same = verdict["variants"]["mc-redeploy-no-exits"]
    assert same["exposure_adjusted_points"] == pytest.approx(same["choosing_points"])


# The command end to end on the flicker book: the file, the payload shape,
# the trial count, the diagnostics table and the verdict; `--json` prints it.
def test_cli_end_to_end(history, tmp_path):
    calls = []

    def fake_desk(store):
        calls.append(str(store.root))
        return _flicker_report()

    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--offsets",
            "2",
            "--costs",
            "25",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    assert calls == [str(tmp_path)]
    target = tmp_path / "desk" / "midcycle_ew.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert (
        payload["study"] == me.STUDY and payload["policy"] == policy_v4.POLICY_VERSION
    )
    assert payload["trials"] == 10 and len(payload["variants"]) == 10
    assert payload["offsets"] == 2 and payload["costs_bps"] == [25.0]
    assert len(payload["rows"]) == 10 * 3 and payload["refused"] == {}
    assert payload["membership_history"] == str(history)
    verdict = payload["verdict"]
    assert verdict["cost_bps"] == 25.0
    assert set(verdict["variants"]) == {v.name for v in me.VARIANTS} - {me.LIVE}
    assert all(
        v["decision"] in (me.ADOPT, me.RECORD) for v in verdict["variants"].values()
    )
    text = out.getvalue()
    assert "mid-cycle rule study for graded-equal-weight/4" in text
    assert "10 registered variants" in text
    assert "mc-new-grades-only" in text and "vs mc-off" in text
    assert "diagnostics" in text and "held@rb" in text
    assert "where the cash is" in text and "idle tgt" in text
    assert "exposure reading" in text and "exp-adj pt" in text
    assert "reset-full-invest" in text
    assert "verdict:" in text
    # `--only` with `--merge` folds the follow-on into the file just written:
    # the earlier rows of the lines not repriced are kept, the file is the
    # merged payload, and the text says what was kept and repriced.
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--offsets",
            "2",
            "--costs",
            "25",
            "--only",
            "mc-redeploy",
            "--merge",
            str(target),
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["ran"] == [v.name for v in me.VARIANTS]
    assert merged["selected"] == [me.MC_OFF, me.LIVE, "mc-redeploy"]
    assert merged["merged"]["repriced"] == [me.MC_OFF, me.LIVE, "mc-redeploy"]
    assert len(merged["merged"]["kept"]) == 7
    assert len(merged["rows"]) == 10 * 3
    assert set(merged["verdict"]["variants"]) == {v.name for v in me.VARIANTS} - {
        me.LIVE
    }
    text = out.getvalue()
    assert "merged with the earlier payload" in text
    assert "repriced mc-off, live, mc-redeploy" in text
    # A foreign payload is refused before anything is priced.
    foreign = tmp_path / "other.json"
    foreign.write_text(json.dumps({"study": "other"}), encoding="utf-8")
    args = cli.build_parser().parse_args(
        ["--root", str(tmp_path), "--membership", str(history), "--merge", str(foreign)]
    )
    with pytest.raises(SystemExit):
        cli.run(args, io.StringIO(), desk_run=fake_desk)
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--offsets",
            "1",
            "--costs",
            "10",
            "--json",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    printed = json.loads(out.getvalue())
    assert printed["offsets"] == 1 and printed["verdict"]["cost_bps"] == 10.0
