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


# Six named variants: the two anchors first, mc-off with the rule off, and
# four modifications of the entry leg whose modes the simulator knows.
def test_variants_are_registered_and_named():
    names = [v.name for v in me.VARIANTS]
    assert len(names) == len(set(names)) == 6
    assert names[:2] == [me.MC_OFF, me.LIVE]
    assert me.variant(me.MC_OFF).live_midcycle is False
    assert me.variant(me.LIVE) == me.Variant(me.LIVE, note=me.variant(me.LIVE).note)
    for v in me.VARIANTS[2:]:
        assert v.live_midcycle is True
        assert v.entries in simulate.MIDCYCLE_ENTRIES
        assert v.entries != simulate.MIDCYCLE_BREAKOUT or v.sweep
    assert {v.entries for v in me.VARIANTS} == set(simulate.MIDCYCLE_ENTRIES)
    with pytest.raises(KeyError):
        me.variant("nothing")


# "live" is `_live_options` plus the mid-cycle defaults; mc-off turns the
# rule off and carries no mid-cycle keys; every other variant changes
# exactly its own mid-cycle key.
def test_options_are_the_live_policy_with_the_midcycle_keys_alone_changed():
    panel = _report().panel
    expected = sc._live_options(panel)
    live = me.options_for(me.variant(me.LIVE), panel)
    assert set(live) == set(expected) | {"midcycle_entries", "midcycle_sweep"}
    for key, value in expected.items():
        if key == "event_exposure":
            np.testing.assert_array_equal(live[key], value)
        else:
            assert live[key] == value, key
    assert live["midcycle_entries"] == simulate.MIDCYCLE_BREAKOUT
    assert live["midcycle_sweep"] is False
    off = me.options_for(me.variant(me.MC_OFF), panel)
    assert off["live_midcycle"] is False and "midcycle_entries" not in off
    assert {
        k
        for k in expected
        if k != "live_midcycle"
        and not isinstance(expected[k], np.ndarray)
        and off[k] != expected[k]
    } == set()
    for v in me.VARIANTS[2:]:
        options = me.options_for(v, panel)
        changed = {
            k
            for k in live
            if not isinstance(live[k], np.ndarray) and options[k] != live[k]
        }
        assert changed == ({"midcycle_sweep"} if v.sweep else {"midcycle_entries"}), (
            v.name
        )
        assert options["live_midcycle"] is True
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
        **live,
    )
    np.testing.assert_array_equal(plain.returns, named.returns)
    assert plain.traded == named.traded
    priced = me.price(restricted, mask, me.variant(me.LIVE), since, 25.0)
    np.testing.assert_array_equal(plain.returns, priced.curve.daily)
    assert priced.diagnostics["all"]["exits_per_year"] > 0


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
    assert payload["study"] == me.STUDY and payload["trials"] == 6
    assert payload["refused"] == {} and payload["ran"] == [v.name for v in me.VARIANTS]
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["diagnostics"] == list(me.DIAGNOSTICS)
    assert {r["line"] for r in payload["rows"]} == names
    assert len(payload["rows"]) == 6 * len(sc.WINDOWS) * 2
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
    assert payload["trials"] == 7
    assert "require live_midcycle" in payload["refused"]["mc-broken"]
    assert "mc-broken" not in {r["line"] for r in payload["rows"]}
    assert "mc-broken" not in payload["ran"] and me.LIVE in payload["ran"]
    verdict = me.verdict(payload)
    assert verdict["variants"]["mc-broken"]["measured"] is False
    assert verdict["variants"]["mc-broken"]["decision"] == me.RECORD


# A payload with the given per-variant CAGRs and drawdowns per window, t
# statistics and reported differences at 25 bp.
def _payload(choosing, reported, t, reported_bp, dd_choosing=None, dd_reported=None):
    rows, paired = [], []
    for name, cagr in choosing.items():
        rows.append(
            {
                "line": name,
                "cost_bps": 25.0,
                "window": me.CHOOSING,
                "median_cagr": cagr,
                "median_drawdown": (dd_choosing or {}).get(name, -0.30),
            }
        )
        rows.append(
            {
                "line": name,
                "cost_bps": 25.0,
                "window": me.REPORTED,
                "median_cagr": reported.get(name, 0.4),
                "median_drawdown": (dd_reported or {}).get(name, -0.20),
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
    assert decisions == {
        "mc-target-size": me.ADOPT,
        "mc-no-idle-cash": me.RECORD,
        "mc-new-grades-only": me.RECORD,
        "mc-exit-only": me.RECORD,
        me.MC_OFF: me.RECORD,
    }
    assert verdict["adopt"] == ["mc-target-size"] and len(verdict["record"]) == 4
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
    assert payload["trials"] == 6 and len(payload["variants"]) == 6
    assert payload["offsets"] == 2 and payload["costs_bps"] == [25.0]
    assert len(payload["rows"]) == 6 * 3 and payload["refused"] == {}
    assert payload["membership_history"] == str(history)
    verdict = payload["verdict"]
    assert verdict["cost_bps"] == 25.0
    assert set(verdict["variants"]) == {v.name for v in me.VARIANTS} - {me.LIVE}
    assert all(
        v["decision"] in (me.ADOPT, me.RECORD) for v in verdict["variants"].values()
    )
    text = out.getvalue()
    assert "mid-cycle rule study for graded-equal-weight/4" in text
    assert "6 registered variants" in text
    assert "mc-new-grades-only" in text and "vs mc-off" in text
    assert "diagnostics" in text and "held@rb" in text
    assert "verdict:" in text
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
