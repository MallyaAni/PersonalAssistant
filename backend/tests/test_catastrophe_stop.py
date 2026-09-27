"""The catastrophe stop fires at its threshold, cools down, and reads its verdict honestly.

On a hand-built price path the stop sells on the first close through the
threshold and not above it; after a trigger the wrapped allocator refuses
the name until a rebalance has excluded it; the trailing stop fires on a
run-up-then-fall where the entry stop does not; the control is
`simulate.run` under the plain options element for element; `simulate.run`
with `weight_filter=None` is byte-identical to a call without the argument;
the verdict applies its floors on hand-built payloads; and the command runs
end to end on the pit scorecard's synthetic book.
"""

import dataclasses
import io
import json
import math

import numpy as np
import pytest

from backend.agents.trading.desk import paper, point_in_time, policy_v4, simulate
from backend.cli import market_catastrophe_stop as cli
from backend.cli import market_pit_scorecard as sc
from backend.market import catastrophe_stop as cs
from backend.tests.test_market_pit_scorecard import (  # noqa: F401 - fixture
    _report,
    history,
)

STOPS = tuple(v for v in cs.VARIANTS if v.mode != cs.NONE)


# A stop around a constant allocator on a two-name panel with the given
# closes for the first name (the second flat at 100) and SPY flat.
def _stop(
    mode: str, threshold: float | None, closes_a: list[float]
) -> cs.CatastropheStop:
    base = _report().panel
    rows = len(closes_a)
    close = np.full((rows, 3), 100.0)
    close[:, 0] = closes_a
    panel = dataclasses.replace(
        base,
        dates=base.dates[:rows],
        tickers=("AAA", "BBB", "SPY"),
        open=close.copy(),
        high=close * 1.01,
        low=close * 0.99,
        close=close.copy(),
        adj_close=close.copy(),
        volume=np.full_like(close, 1e6),
        themes={"AAA": base.themes["AAA"], "BBB": base.themes["BBB"]},
    )

    def allocate(report, panel, config, t):
        return np.array([0.5, 0.5, 0.0])

    return cs.CatastropheStop(allocate, mode, threshold, panel)


# The variant set is fixed and named: the control first, then three
# thresholds from entry and three from peak, every name unique.
def test_variants_are_registered_and_named():
    names = [v.name for v in cs.VARIANTS]
    assert len(names) == len(set(names)) == 7
    assert names[0] == cs.NONE and cs.variant(cs.NONE).threshold is None
    assert [(v.mode, v.threshold) for v in STOPS] == [
        (cs.ENTRY, 0.40),
        (cs.ENTRY, 0.50),
        (cs.ENTRY, 0.60),
        (cs.PEAK, 0.40),
        (cs.PEAK, 0.50),
        (cs.PEAK, 0.60),
    ]
    with pytest.raises(KeyError):
        cs.variant("nothing")
    with pytest.raises(ValueError):
        _stop("sideways", 0.4, [100.0])
    with pytest.raises(ValueError):
        _stop(cs.ENTRY, 1.5, [100.0])
    with pytest.raises(ValueError):
        _stop(cs.NONE, 0.4, [100.0])


# The entry stop fires on the first close strictly below entry * (1 -
# threshold) and not on a close at or above it; the trigger records the
# entry session and price, the trigger session and price and the drawdown;
# the name's target is zero from that session on while it stays blocked.
def test_entry_stop_fires_at_the_threshold_and_not_above_it():
    closes = [100.0, 80.0, 60.0, 59.0, 70.0]
    stop = _stop(cs.ENTRY, 0.40, closes)
    held = np.array([0.5, 0.5, 0.0])
    outs = [stop.weight_filter(t, held, stop.panel.adj_close[t]) for t in range(3)]
    # Entry at 100 on session 0; 60 is exactly the threshold and does not fire.
    assert all(out[0] == 0.5 for out in outs) and stop.triggers == []
    fired = stop.weight_filter(3, held, stop.panel.adj_close[3])
    assert fired[0] == 0.0 and fired[1] == 0.5
    assert len(stop.triggers) == 1
    tr = stop.triggers[0]
    assert (tr.ticker, tr.entry_index, tr.entry_price) == ("AAA", 0, 100.0)
    assert (tr.trigger_index, tr.trigger_price) == (3, 59.0)
    assert tr.entry_date == str(stop.panel.dates[0])
    assert tr.trigger_date == str(stop.panel.dates[3])
    assert tr.drawdown == pytest.approx(-0.41) and tr.drawdown_from_entry == tr.drawdown
    assert tr.drawdown_from_peak == pytest.approx(-0.41)
    # The book still carries the name until the sale fills: the next
    # session's target is forced to zero again without a second trigger.
    again = stop.weight_filter(4, held, stop.panel.adj_close[4])
    assert again[0] == 0.0 and len(stop.triggers) == 1
    # The recovery reading: 70 > 59 on the session after the trigger.
    stop.resolve_recoveries(sessions=60)
    assert tr.recovered is True and tr.recovery_sessions == 1
    # The recorded weights carry the post-stop target.
    assert stop.weights[3, 0] == 0.0 and stop.weights[2, 0] == 0.5


# After a trigger the wrapped allocator forces the name to zero at the next
# rebalance that wants it; once a rebalance has excluded it (the mask
# dropped the name for one full cycle), the following rebalance that wants
# it may have it, and the name is tracked afresh from that entry.
def test_cooldown_prevents_immediate_reentry():
    closes = [100.0, 50.0, 55.0, 55.0, 55.0, 55.0]
    stop = _stop(cs.ENTRY, 0.40, closes)
    held = np.array([0.5, 0.5, 0.0])
    stop.weight_filter(0, held, stop.panel.adj_close[0])
    out = stop.weight_filter(1, held, stop.panel.adj_close[1])
    assert out[0] == 0.0 and len(stop.triggers) == 1 and stop.blocked == {0: False}
    # The base allocator still wants AAA at the next rebalance: refused.
    target = stop.allocator(None, stop.panel, None, 2)
    assert target[0] == 0.0 and target[1] == 0.5 and stop.blocked == {0: False}
    filtered = stop.weight_filter(2, target, stop.panel.adj_close[2])
    assert filtered[0] == 0.0 and len(stop.triggers) == 1
    # The mask excludes AAA for a cycle: the block is marked served.
    stop.base = lambda report, panel, config, t: np.array([0.0, 1.0, 0.0])
    target = stop.allocator(None, stop.panel, None, 3)
    assert target[0] == 0.0 and stop.blocked == {0: True}
    stop.weight_filter(3, target, stop.panel.adj_close[3])
    # The mask wants it back: allowed, and the entry is the new session.
    stop.base = lambda report, panel, config, t: np.array([0.5, 0.5, 0.0])
    target = stop.allocator(None, stop.panel, None, 4)
    assert target[0] == 0.5 and stop.blocked == {}
    stop.weight_filter(4, target, stop.panel.adj_close[4])
    assert stop.entry_index[0] == 4 and stop.entry_price[0] == 55.0
    assert stop.rebalances == [2, 3, 4]


# On a run-up then a fall, the trailing stop fires where the entry stop does
# not: 100 to 200 to 115 is 42.5% off the peak and 15% above entry. The
# control never fires and never blocks.
def test_trailing_and_entry_differ_on_a_run_up_then_fall():
    closes = [100.0, 150.0, 200.0, 160.0, 115.0]
    held = np.array([0.5, 0.5, 0.0])
    peak = _stop(cs.PEAK, 0.40, closes)
    entry = _stop(cs.ENTRY, 0.40, closes)
    none = _stop(cs.NONE, None, closes)
    for t in range(5):
        p = peak.weight_filter(t, held, peak.panel.adj_close[t])
        e = entry.weight_filter(t, held, entry.panel.adj_close[t])
        n = none.weight_filter(t, held, none.panel.adj_close[t])
        np.testing.assert_array_equal(e, held)
        np.testing.assert_array_equal(n, held)
        assert p[0] == (0.0 if t == 4 else 0.5)
    assert entry.triggers == [] and none.triggers == [] and none.blocked == {}
    assert len(peak.triggers) == 1
    tr = peak.triggers[0]
    assert tr.peak_price == 200.0 and tr.trigger_price == 115.0
    assert tr.drawdown == pytest.approx(-0.425) and tr.drawdown == tr.drawdown_from_peak
    assert tr.drawdown_from_entry == pytest.approx(0.15)
    # The control tracks the peak too, so a later variant reads the same path.
    assert none.peak[0] == 200.0 and none.entry_price[0] == 100.0
    # With the panel ending inside the recovery window, an unrecovered
    # trigger is unresolved rather than counted a false alarm.
    peak.resolve_recoveries(sessions=60)
    assert tr.recovered is None
    # The worst single-name day is the weight times the fall from 200 to 160.
    loss = peak.name_loss()
    assert loss[3] == pytest.approx(0.5 * (160.0 / 200.0 - 1.0))
    assert loss[1] == 0.0 and math.isnan(loss[0])


# The stop runs inside `simulate.run` on a book where one name collapses:
# the stop variant sells it and its curve departs from the control's from
# the fill session on; the trigger names the collapse; the control holds.
def test_stop_runs_inside_simulate_on_a_collapsing_name(history):
    report = _report()
    panel = report.panel
    close = panel.adj_close.copy()
    # AAA loses 70% over sessions 60-70 and stays there.
    fall = np.linspace(1.0, 0.3, 11)
    close[60:71, 0] = close[59, 0] * fall
    close[71:, 0] = close[59, 0] * 0.3
    panel = dataclasses.replace(
        panel, open=close.copy(), close=close.copy(), adj_close=close.copy()
    )
    report = dataclasses.replace(report, panel=panel)
    restricted, mask = point_in_time.point_in_time(report, history)
    since = sc._since(panel, 1)
    control = cs.price(restricted, mask, cs.variant(cs.NONE), since, 10.0)
    stopped = cs.price(restricted, mask, cs.variant("entry-40"), since, 10.0)
    assert control.triggers == []
    aaa = [tr for tr in stopped.triggers if tr.ticker == "AAA"]
    assert len(aaa) == 1
    tr = aaa[0]
    assert 60 <= tr.trigger_index <= 70 and tr.drawdown < -0.40
    a, b = control.curve.daily, stopped.curve.daily
    differs = (a != b) & ~(np.isnan(a) & np.isnan(b))
    first = np.flatnonzero(differs)
    # Identical through the trigger session, different from the fill on.
    assert (
        first.size
        and control.curve.dates[first[0]] == panel.dates[tr.trigger_index + 1]
    )
    # The stop's worst single-name day is no worse than the control's.
    assert np.nanmin(stopped.name_loss.daily) >= np.nanmin(control.name_loss.daily)
    # The control's returns are `simulate.run` under the ablation's plain options.
    direct = simulate.run(
        restricted,
        since=since,
        cost_bps=10.0,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        allocator=policy_v4.allocator(mask),
    )
    np.testing.assert_array_equal(control.curve.daily, direct.returns)


# The control reproduces `simulate.run` under the plain options element for
# element on the pit fixture, and every variant runs.
def test_none_reproduces_plain_simulate(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    since = sc._since(report.panel, 1)
    for v in cs.VARIANTS:
        run = cs.price(restricted, mask, v, since, 10.0)
        assert run.curve.label == v.name
        assert len(run.curve.dates) == len(run.curve.daily) == len(run.name_loss.daily)
    control = cs.price(restricted, mask, cs.variant(cs.NONE), since, 10.0)
    direct = simulate.run(
        restricted,
        since=since,
        cost_bps=10.0,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        allocator=policy_v4.allocator(mask),
    )
    np.testing.assert_array_equal(control.curve.dates, direct.dates)
    np.testing.assert_array_equal(control.curve.daily, direct.returns)
    assert control.triggers == []


# `simulate.run` with `weight_filter=None` is identical to a call without
# the argument on the pit fixture, under the plain and the live options; a
# pass-through filter is identical too; the funded path refuses the hook;
# a filter returning the wrong shape is refused.
def test_weight_filter_none_is_byte_identical(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    since = sc._since(report.panel, 1)
    for options in (
        dict(use_exits=False, rebalance=paper.REBALANCE_EVERY),
        sc._live_options(report.panel),
        dict(use_exits=True),
    ):
        without = simulate.run(
            restricted,
            since=since,
            cost_bps=10.0,
            allocator=policy_v4.allocator(mask),
            **options,
        )
        with_none = simulate.run(
            restricted,
            since=since,
            cost_bps=10.0,
            allocator=policy_v4.allocator(mask),
            weight_filter=None,
            **options,
        )
        seen = []

        def passthrough(t, target, prices):
            seen.append(int(t))
            return target

        with_pass = simulate.run(
            restricted,
            since=since,
            cost_bps=10.0,
            allocator=policy_v4.allocator(mask),
            weight_filter=passthrough,
            **options,
        )
        for other in (with_none, with_pass):
            np.testing.assert_array_equal(without.dates, other.dates)
            np.testing.assert_array_equal(without.returns, other.returns)
            np.testing.assert_array_equal(without.equity, other.equity)
            np.testing.assert_array_equal(without.invested, other.invested)
            np.testing.assert_array_equal(without.top_weight, other.top_weight)
            assert len(without.trades) == len(other.trades)
            for x, y in zip(without.trades, other.trades, strict=True):
                assert (x.ticker, x.opened, x.closed, x.grade, x.reason) == (
                    y.ticker,
                    y.opened,
                    y.closed,
                    y.grade,
                    y.reason,
                )
                np.testing.assert_array_equal([x.weight, x.ret], [y.weight, y.ret])
            assert without.rebalances == other.rebalances
            assert without.traded == other.traded
        assert seen
    with pytest.raises(ValueError, match="one weight per name"):
        simulate.run(
            restricted,
            since=since,
            use_exits=False,
            allocator=policy_v4.allocator(mask),
            weight_filter=lambda t, target, prices: target[:2],
        )
    with pytest.raises(ValueError, match="weight_filter"):
        simulate.run(
            restricted,
            since=since,
            funded_allocation=True,
            benchmark_prices={},
            weight_filter=lambda t, target, prices: target,
        )


# The payload holds every variant on every window at every cost with the
# trial's own fields, pairs every stop against the control, and keeps the
# median offset's triggers at the verdict cost.
def test_run_variants_payload(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    payload = cs.run_variants(report, restricted, mask, None, 2, (10.0, 25.0))
    names = {v.name for v in cs.VARIANTS}
    assert payload["study"] == "catastrophe_stop" and payload["trials"] == 7
    assert payload["ran"] == [v.name for v in cs.VARIANTS]
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["options"] == dict(
        use_exits=False, rebalance=paper.REBALANCE_EVERY, redeploy=False
    )
    assert {r["line"] for r in payload["rows"]} == names
    assert len(payload["rows"]) == 7 * len(sc.WINDOWS) * 2
    for row in payload["rows"]:
        assert row["offsets"] == 2
        assert {
            "median_cagr",
            "median_drawdown",
            "worst_name_day",
            "triggers_per_year",
            "false_alarm_rate",
            "triggers_total",
            "offsets_above_control",
            "sessions",
        } <= set(row)
        assert not row["worst_name_day"] > 0
    control_rows = [r for r in payload["rows"] if r["line"] == cs.NONE]
    assert all(r["offsets_above_control"] == 0 for r in control_rows)
    assert all(
        r["triggers_total"] == 0 and r["triggers_per_year"] == 0 for r in control_rows
    )
    pairs = {(p["line"], p["against"]) for p in payload["paired"]}
    assert pairs == {(n, cs.NONE) for n in names - {cs.NONE}}
    for p in payload["paired"]:
        assert {"mean_daily_bp", "hac_t", "psr", "sessions"} <= set(p)
    assert set(payload["triggers"]) == names and payload["triggers"][cs.NONE] == []
    verdict = cs.verdict(payload)
    assert set(verdict["stops"]) == {v.name for v in STOPS}
    assert all(
        s["decision"] in (cs.ADOPT, cs.RECORD) for s in verdict["stops"].values()
    )


# A payload with the given per-variant choosing-window numbers and reported
# paired differences at 25 bp.
def _payload(
    cagr: dict[str, float],
    drawdown: dict[str, float],
    worst: dict[str, float],
    reported_bp: dict[str, float],
):
    rows, paired = [], []
    for name in cagr:
        rows.append(
            {
                "line": name,
                "cost_bps": 25.0,
                "window": cs.CHOOSING,
                "median_cagr": cagr[name],
                "median_drawdown": drawdown[name],
                "worst_name_day": worst[name],
                "triggers_per_year": 0.0 if name == cs.NONE else 1.5,
                "false_alarm_rate": math.nan if name == cs.NONE else 0.4,
            }
        )
        rows.append(
            {"line": name, "cost_bps": 25.0, "window": cs.REPORTED, "median_cagr": 0.1}
        )
        if name != cs.NONE:
            for window, bp in (
                (cs.CHOOSING, 0.0),
                (cs.REPORTED, reported_bp.get(name, 0.0)),
            ):
                paired.append(
                    {
                        "line": name,
                        "against": cs.NONE,
                        "cost_bps": 25.0,
                        "window": window,
                        "mean_daily_bp": bp,
                        "hac_t": 0.0,
                    }
                )
    return {"costs_bps": [10.0, 25.0], "rows": rows, "paired": paired}


# The verdict's floors on hand-built payloads: a stop costing 0.3 points
# that saves 4 drawdown points is ADOPT; one costing 0.3 points that cuts
# the worst day by 30% with no drawdown saving is ADOPT; one costing 1.0
# point that saves 5 points is RECORD (cost); one costing nothing that saves
# 1 point and 10% is RECORD (no benefit); one that would adopt but is worse
# on 2024-2026 is RECORD; the premium is points per drawdown point saved.
def test_verdict_rules_on_hand_built_payloads():
    stops = [v.name for v in STOPS]
    cagr = {cs.NONE: 0.277}
    dd = {cs.NONE: -0.40}
    worst = {cs.NONE: -0.04}
    reported = {}
    for name in stops:
        cagr[name], dd[name], worst[name] = 0.277, -0.40, -0.04
    cagr["entry-40"], dd["entry-40"] = 0.274, -0.36  # -0.3 pt, 4 pt saved: ADOPT
    cagr["entry-50"], worst["entry-50"] = 0.274, -0.028  # -0.3 pt, 30% worst cut: ADOPT
    cagr["entry-60"], dd["entry-60"] = (
        0.267,
        -0.35,
    )  # -1.0 pt, 5 pt saved: RECORD (cost)
    cagr["peak-40"], dd["peak-40"], worst["peak-40"] = (
        0.277,
        -0.39,
        -0.036,
    )  # RECORD (no benefit)
    cagr["peak-50"], dd["peak-50"] = (
        0.280,
        -0.36,
    )  # +0.3 pt, 4 pt saved, worse later: RECORD
    reported["peak-50"] = -0.4
    verdict = cs.verdict(_payload(cagr, dd, worst, reported))
    assert verdict["cost_bps"] == 25.0
    decisions = {k: v["decision"] for k, v in verdict["stops"].items()}
    assert decisions["entry-40"] == cs.ADOPT
    assert decisions["entry-50"] == cs.ADOPT
    assert decisions["entry-60"] == cs.RECORD
    assert decisions["peak-40"] == cs.RECORD
    assert decisions["peak-50"] == cs.RECORD
    assert decisions["peak-60"] == cs.RECORD
    e40 = verdict["stops"]["entry-40"]
    assert e40["choosing_points"] == pytest.approx(-0.3)
    assert e40["drawdown_points_saved"] == pytest.approx(4.0)
    assert e40["insurance_premium"] == pytest.approx(0.075)
    assert e40["affordable"] and e40["saves"] and e40["not_worse_reported"]
    e50 = verdict["stops"]["entry-50"]
    assert e50["worst_name_day_cut"] == pytest.approx(0.30)
    assert math.isnan(e50["insurance_premium"])
    e60 = verdict["stops"]["entry-60"]
    assert e60["affordable"] is False and e60["saves"] is True
    assert e60["insurance_premium"] == pytest.approx(0.2)
    p40 = verdict["stops"]["peak-40"]
    assert p40["affordable"] is True and p40["saves"] is False
    assert p40["worst_name_day_cut"] == pytest.approx(0.10)
    p50 = verdict["stops"]["peak-50"]
    assert p50["affordable"] and p50["saves"] and p50["not_worse_reported"] is False
    assert math.isnan(p50["insurance_premium"])  # nothing given up
    assert verdict["adopt"] == ["entry-40", "entry-50"]
    assert len(verdict["record"]) == 4
    assert "ADOPT (registered): entry-40, entry-50" in verdict["text"]
    assert "control 27.7% CAGR" in verdict["text"]
    # Nothing to adopt: the text says so.
    flat = cs.verdict(
        _payload(
            {cs.NONE: 0.277, **{n: 0.277 for n in stops}},
            {cs.NONE: -0.4, **{n: -0.4 for n in stops}},
            {cs.NONE: -0.04, **{n: -0.04 for n in stops}},
            {},
        )
    )
    assert flat["adopt"] == [] and "every stop is RECORD" in flat["text"]
    # Without 25 bp the verdict reads the largest cost; without a control it
    # is not measured.
    empty = cs.verdict({"costs_bps": [10.0], "rows": [], "paired": []})
    assert empty["cost_bps"] == 10.0 and empty["text"].startswith("not measured")
    assert math.isnan(empty["control_cagr"])


# The command end to end on the synthetic book: the file, the payload
# shape, the trial count, the verdict and trigger sections; `--json` prints
# the payload.
def test_cli_end_to_end(history, tmp_path):
    calls = []

    def fake_desk(store):
        calls.append(str(store.root))
        return _report()

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
    target = tmp_path / "desk" / "catastrophe_stop.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == "catastrophe_stop"
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["trials"] == 7 and len(payload["variants"]) == 7
    assert payload["offsets"] == 2 and payload["costs_bps"] == [25.0]
    assert len(payload["rows"]) == 7 * 3
    assert set(payload["windows"]) == {"2016-2023", "2024-2026", "all"}
    assert payload["membership_history"] == str(history)
    assert payload["recovery_sessions"] == cs.RECOVERY_SESSIONS
    verdict = payload["verdict"]
    assert verdict["cost_bps"] == 25.0
    assert set(verdict["stops"]) == {v.name for v in STOPS}
    assert verdict["text"].startswith("2016-2023 at 25 bp") or verdict[
        "text"
    ].startswith("not measured")
    text = out.getvalue()
    assert "catastrophe stop for graded-equal-weight/4" in text
    assert "7 registered variants" in text
    assert "entry-40" in text and "peak-60" in text
    assert "verdict:" in text and "deepest" in text and "triggers" in text
    # The trigger table orders the deepest first.
    top = cli.top_triggers(payload)
    assert len(top) <= cli.TOP_TRIGGERS
    assert all(
        a["drawdown"] <= b["drawdown"] for a, b in zip(top, top[1:], strict=False)
    )
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
