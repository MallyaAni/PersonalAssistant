"""The profit-taking study: each rule on hand-built paths, the control's identity, the hook, the verdict, the command.

The control is `simulate.run` under the live options with the redeploy,
element for element; `midcycle_trims` off is byte-identical and on sells a
name the hook cut between resets. Each rule is driven by hand through the
allocator wrapper and the hook on small price paths: the run-up trim fires
at 1.5x and not below, the RSI and band trims fire at their thresholds and
restore below theirs, the dip add caps at the 20% hold limit and is paid
by the others, the forecast trim takes the worst decile and its stop exits
15% below the trim close. The trim statistics are checked on hand-built
actions, the verdict on a hand-built payload, and the command end to end on
the pit fixture with the price rules alone and with a synthetic forecast
file.
"""

from __future__ import annotations

import io
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import point_in_time, policy_v4, simulate
from backend.cli import market_pit_scorecard as sc
from backend.cli import market_profit_taking as cli
from backend.market import drawdown_forecast as df
from backend.market import midcycle_ew as me
from backend.market import profit_taking as pt
from backend.tests.test_market_pit_scorecard import (  # noqa: F401 - fixture
    _report,
    history,
)


# The restricted fixture report, its mask and the second-session start.
def _book(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    return report, restricted, mask, sc._since(report.panel, 1)


# A fake restricted report over a close panel, for driving a rule by hand.
def _fake(closes: np.ndarray, tickers=None):
    closes = np.asarray(closes, dtype=float)
    n = closes.shape[1]
    tickers = tickers or tuple(f"N{j}" for j in range(n))
    dates = np.datetime64("2020-01-01", "D") + np.arange(closes.shape[0])
    panel = SimpleNamespace(adj_close=closes, tickers=tickers, dates=dates)
    return SimpleNamespace(panel=panel)


# A base allocator returning a fixed weight for every name in `weights`.
def _base(weights):
    weights = np.asarray(weights, dtype=float)

    def allocate(report, panel, config, t):
        return weights.copy()

    return allocate


# Seven named trials: the control first, four price rules, two model rules
# that need the forecast; the rule parameters are the plan's.
def test_variants_are_registered_and_named():
    names = [v.name for v in pt.VARIANTS]
    assert len(names) == len(set(names)) == 7
    assert names[0] == pt.CONTROL == "ew-redeploy"
    assert pt.variant(pt.CONTROL).rule is None
    assert names[1:] == [
        "trim-runup-20",
        "trim-rsi",
        "trim-band",
        "dip-add",
        "trim-dd-forecast",
        "trim-dd-forecast-stop",
    ]
    runup = pt.variant("trim-runup-20")
    assert runup.rule == pt.RUNUP and runup.ratio == 1.5
    rsi = pt.variant("trim-rsi")
    assert (rsi.rule, rsi.fraction, rsi.on, rsi.off) == (pt.RSI, 0.5, 80.0, 60.0)
    band = pt.variant("trim-band")
    assert (band.rule, band.fraction, band.on, band.off) == (pt.BAND, 0.5, 3.0, 2.0)
    dip = pt.variant("dip-add")
    assert (dip.rule, dip.ratio, dip.on) == (pt.DIP, 1.5, -0.08)
    for name in ("trim-dd-forecast", "trim-dd-forecast-stop"):
        v = pt.variant(name)
        assert v.rule == pt.FORECAST and v.model and v.quantile == 0.1
    assert pt.variant("trim-dd-forecast").stop is None
    assert pt.variant("trim-dd-forecast-stop").stop == 0.15
    assert all(not v.model for v in pt.VARIANTS[:5])
    with pytest.raises(KeyError):
        pt.variant("nothing")
    chosen, skipped = pt.selected(None)
    assert [v.name for v in chosen] == names[:5]
    assert set(skipped) == {"trim-dd-forecast", "trim-dd-forecast-stop"}
    assert "--drawdown-forecasts" in skipped["trim-dd-forecast"]
    chosen, skipped = pt.selected(np.zeros((2, 2)))
    assert len(chosen) == 7 and skipped == {}


# The control's options are the scorecard's live options plus the redeploy
# and its buffer, and nothing else.
def test_control_options_are_live_plus_redeploy():
    panel = _report().panel
    expected = sc._live_options(panel)
    options = pt.control_options(panel)
    assert set(options) == set(expected) | {"midcycle_redeploy", "redeploy_buffer"}
    for key, value in expected.items():
        if key == "event_exposure":
            np.testing.assert_array_equal(options[key], value)
        else:
            assert options[key] == value, key
    assert options["midcycle_redeploy"] is True
    assert options["redeploy_buffer"] == simulate.REDEPLOY_BUFFER
    described = pt._describe({**options, "weight_filter": lambda t, w, p: w})
    assert described["event_exposure"] == "event_risk.live_path(panel)"
    assert described["weight_filter"] == "ProfitTaking.weight_filter"


# The control priced through `price` is `simulate.run` under the live
# options with `midcycle_redeploy=True`, element for element; a hook that
# changes nothing with `midcycle_trims` on is byte-identical too; the
# option is refused without the rule or without a hook.
def test_control_is_live_with_redeploy_and_the_hook_default_changes_nothing(history):
    report, restricted, mask, since = _book(history)
    live = sc._live_options(report.panel)
    plain = simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=policy_v4.allocator(mask),
        midcycle_redeploy=True,
        **live,
    )
    control = pt.price(restricted, mask, pt.variant(pt.CONTROL), since, 25.0)
    np.testing.assert_array_equal(control.curve.daily, plain.returns)
    assert control.trims == [] and control.resets == 0
    assert control.diagnostics["all"]["cash_share"] < 0.1
    identity = simulate.run(
        restricted,
        since=since,
        cost_bps=25.0,
        allocator=policy_v4.allocator(mask),
        midcycle_redeploy=True,
        weight_filter=lambda t, w, p: w,
        midcycle_trims=True,
        **live,
    )
    np.testing.assert_array_equal(identity.returns, plain.returns)
    assert identity.traded == plain.traded
    base = dict(since=since, cost_bps=25.0, allocator=policy_v4.allocator(mask))
    with pytest.raises(ValueError, match="midcycle_trims requires"):
        simulate.run(
            restricted, midcycle_trims=True, weight_filter=lambda t, w, p: w, **base
        )
    with pytest.raises(ValueError, match="midcycle_trims requires"):
        simulate.run(restricted, midcycle_trims=True, **{**live, **base})


# With `midcycle_trims` a hook that halves one held name on a mid-cycle
# session sells it: at the mark after the fill the name's weight is about
# half what the control holds and the book has the proceeds (cash, which
# the redeploy puts to work the session after). Without the option the same
# hook changes nothing, because the live plan ignores the hook mid-cycle.
def test_midcycle_trims_sells_what_the_hook_cut(history):
    report, restricted, mask, since = _book(history)
    live = sc._live_options(report.panel)
    panel = restricted.panel
    column = panel.tickers.index("AAA")
    # A mid-cycle session (the resets are at 1 and 21) whose next open is
    # not up, so the live green-open skip does not hold the sale back.
    session = next(
        s
        for s in range(5, 19)
        if panel.open[s + 1, column] <= panel.adj_close[s, column]
    )

    def halve(t, weights, prices):
        out = np.array(weights, dtype=float)
        if t == session:
            out[column] = out[column] / 2.0
        return out

    def run(**extra):
        ledger = me.Ledger()
        result = simulate.run(
            restricted,
            since=since,
            cost_bps=25.0,
            allocator=policy_v4.allocator(mask),
            midcycle_redeploy=True,
            journal=ledger,
            **extra,
            **live,
        )
        return result, ledger

    control, control_ledger = run()
    trimmed, trimmed_ledger = run(weight_filter=halve, midcycle_trims=True)
    ignored, _ = run(weight_filter=halve)
    np.testing.assert_array_equal(ignored.returns, control.returns)
    assert not np.array_equal(trimmed.returns, control.returns)

    # The name's weight at the mark of session s.
    def weight(ledger, s):
        cash, shares, nav, _ = ledger.marks[s]
        return shares[column] * panel.adj_close[s, column] / nav

    before = weight(control_ledger, session)
    assert weight(trimmed_ledger, session) == pytest.approx(before)
    after = weight(trimmed_ledger, session + 1)
    assert after == pytest.approx(weight(control_ledger, session + 1) / 2.0, rel=0.1)
    assert trimmed_ledger.marks[session + 1][0] > control_ledger.marks[session + 1][0]


# The indicators on hand-built paths: the RSI is NaN before fourteen
# changes, 100 on a straight rise and 0 on a straight fall, near 50 on an
# alternating path; the band z is NaN before the window and where the sigma
# is zero, and a spike after a flat stretch reads far above the band; the
# EMA gap is negative under the average and a sudden 20% fall reads well
# below -8%.
def test_indicators_by_hand():
    t = 40
    rise = 100.0 * 1.01 ** np.arange(t)
    fall = 100.0 / 1.01 ** np.arange(t)
    zigzag = 100.0 + np.where(np.arange(t) % 2 == 0, 1.0, -1.0)
    closes = np.column_stack([rise, fall, zigzag])
    rsi = pt.rsi(closes)
    assert np.isnan(rsi[:14]).all() and np.isfinite(rsi[14:]).all()
    assert rsi[20, 0] == pytest.approx(100.0)
    assert rsi[20, 1] == pytest.approx(0.0)
    assert 35.0 < rsi[20, 2] < 65.0
    flat = np.full((t, 2), 100.0)
    flat[30:, 0] = 130.0
    z = pt.band_sigma_z(flat)
    assert np.isnan(z[:19]).all()
    assert np.isnan(z[25, 1])  # zero sigma is not a reading
    assert z[30, 0] > 3.0  # one spike after nineteen flat closes
    assert z[38, 0] < 2.0  # inside the band once the spike is old news
    path = np.full((t, 1), 100.0)
    path[30:, 0] = 80.0
    gap = pt.ema_gap(path)
    assert np.isnan(gap[:20]).all()
    assert gap[29, 0] == pytest.approx(0.0)
    assert gap[30, 0] < -0.08
    # A single NaN close reads NaN on its two sessions and carries the
    # averages over the hole rather than poisoning the rest of the path.
    holed = rise.copy()
    holed[25] = np.nan
    r = pt.rsi(holed[:, None])[:, 0]
    assert np.isnan(r[25]) and np.isnan(r[26])
    assert r[27] == pytest.approx(100.0) and np.isfinite(r[27:]).all()


# The run-up trim: a held name at 1.5x its target is cut back to target
# and recorded; at 1.49x nothing happens; on a reset session (the hook sees
# the allocator's targets) nothing is trimmed; a name the policy no longer
# wants is left to the rotation.
def test_runup_trim_fires_at_the_threshold():
    closes = np.full((5, 3), 100.0)
    rule = pt.ProfitTaking(
        _base([0.2, 0.2, 0.0]), pt.variant("trim-runup-20"), _fake(closes)
    )
    np.testing.assert_allclose(rule.allocator(None, None, None, 0), [0.2, 0.2, 0.0])
    assert rule.resets == [0]
    out = rule.weight_filter(0, [0.2, 0.2, 0.0], closes[0])
    np.testing.assert_allclose(out, [0.2, 0.2, 0.0])
    out = rule.weight_filter(1, [0.298, 0.15, 0.1], closes[1])
    np.testing.assert_allclose(out, [0.298, 0.15, 0.1])
    assert rule.trims == []
    out = rule.weight_filter(2, [0.30, 0.15, 0.1], closes[2])
    np.testing.assert_allclose(out, [0.2, 0.15, 0.1])
    assert len(rule.trims) == 1
    trim = rule.trims[0]
    assert (trim.kind, trim.ticker, trim.index, trim.date) == (
        pt.TRIM,
        "N0",
        2,
        "2020-01-03",
    )
    assert trim.weight_before == pytest.approx(0.30)
    assert trim.weight_after == pytest.approx(0.20)
    assert trim.size == pytest.approx(0.10)
    assert trim.indicator == pytest.approx(1.5)
    # The mid-cycle allocator call after the hook is not a reset.
    rule.allocator(None, None, None, 2)
    assert rule.resets == [0]
    rule.resolve_forward(sessions=2)
    assert trim.forward == pytest.approx(0.0) and trim.rose is False
    assert rule.trims[0].as_dict()["kind"] == pt.TRIM


# The RSI trim: a straight run-up drives the RSI to 100, the name is halved
# (the hook cuts it, the allocator holds it at half) and the state persists
# across a reset; once the RSI is under 60 the state clears, a restore is
# recorded and the allocator's target is whole again.
def test_rsi_trim_and_restore():
    t = 80
    up = 100.0 * 1.01 ** np.arange(40)
    down = up[-1] / 1.01 ** np.arange(1, 41)
    closes = np.column_stack([np.concatenate([up, down]), np.full(t, 100.0)])
    rule = pt.ProfitTaking(_base([0.2, 0.2]), pt.variant("trim-rsi"), _fake(closes))
    rule.allocator(None, None, None, 0)
    for s in range(1, 14):  # no RSI reading yet: nothing fires
        out = rule.weight_filter(s, [0.2, 0.2], closes[s])
        np.testing.assert_allclose(out, [0.2, 0.2])
    assert rule.trims == []
    out = rule.weight_filter(14, [0.22, 0.2], closes[14])
    np.testing.assert_allclose(out, [0.1, 0.2])
    assert rule.state == {0: pt.TRIMMED}
    assert [tr.kind for tr in rule.trims] == [pt.TRIM]
    assert rule.trims[0].size == pytest.approx(0.12)
    assert rule.trims[0].indicator == pytest.approx(100.0)
    # The redeploy's targets and the next reset hold the name at half.
    np.testing.assert_allclose(rule.allocator(None, None, None, 14), [0.1, 0.2])
    np.testing.assert_allclose(rule.allocator(None, None, None, 21), [0.1, 0.2])
    assert rule.resets == [0, 21]
    # Still above 80 on the way up: no second trim record, the cut is held.
    for s in range(15, 40):
        out = rule.weight_filter(s, [0.11, 0.2], closes[s])
        np.testing.assert_allclose(out, [0.1, 0.2])
    assert len(rule.trims) == 1
    restored_at = None
    for s in range(40, t):
        rule.weight_filter(s, [0.1, 0.2], closes[s])
        if 0 not in rule.state:
            restored_at = s
            break
    assert restored_at is not None
    assert pt.rsi(closes)[restored_at, 0] < 60.0
    assert [tr.kind for tr in rule.trims] == [pt.TRIM, pt.RESTORE]
    np.testing.assert_allclose(
        rule.allocator(None, None, None, restored_at), [0.2, 0.2]
    )


# The band trim: a spike more than one sigma above the upper band halves
# the name; when the close is back inside the band the state clears; a
# name the policy drops loses its state with it.
def test_band_trim_and_restore():
    t = 60
    closes = np.full((t, 2), 100.0)
    closes[:30, 0] = 100.0 + 0.5 * np.sin(np.arange(30))
    closes[30:, 0] = 110.0
    rule = pt.ProfitTaking(_base([0.2, 0.2]), pt.variant("trim-band"), _fake(closes))
    rule.allocator(None, None, None, 0)
    for s in range(1, 30):
        rule.weight_filter(s, [0.2, 0.2], closes[s])
    assert rule.trims == []
    z = pt.band_sigma_z(closes)
    assert z[30, 0] > 3.0
    out = rule.weight_filter(30, [0.2, 0.2], closes[30])
    np.testing.assert_allclose(out, [0.1, 0.2])
    assert rule.state == {0: pt.TRIMMED}
    restored_at = None
    for s in range(31, t):
        rule.weight_filter(s, [0.1, 0.2], closes[s])
        if 0 not in rule.state:
            restored_at = s
            break
    assert restored_at is not None and z[restored_at, 0] < 2.0
    assert [tr.kind for tr in rule.trims] == [pt.TRIM, pt.RESTORE]
    # A trimmed name the policy no longer wants loses its state.
    rule.state[0] = pt.TRIMMED
    rule.base = _base([0.0, 0.2])
    rule.weight_filter(t - 1, [0.1, 0.2], closes[t - 1])
    assert rule.state == {}


# The dip add: a held name 8% under its EMA has its target raised to 1.5x,
# capped at the hold limit (0.15 x 1.5 = 0.225 -> 0.20), the others scaled
# pro rata in the allocator; mid-cycle the hook trims the others to pay
# for the raise beyond the spare cash and leaves the buy to the redeploy;
# the add clears at the next reset and does not re-arm until the name is
# back within 8% of its EMA; a name already above the raised target is not
# added to.
def test_dip_add_caps_at_the_hold_limit_and_restores_at_the_reset():
    t = 60
    closes = np.full((t, 4), 100.0)
    closes[30:, 0] = 85.0
    rule = pt.ProfitTaking(
        _base([0.15, 0.15, 0.15, 0.0]), pt.variant("dip-add"), _fake(closes)
    )
    rule.allocator(None, None, None, 0)
    for s in range(1, 30):
        np.testing.assert_allclose(
            rule.weight_filter(s, [0.15, 0.15, 0.15, 0.0], closes[s]),
            [0.15, 0.15, 0.15, 0.0],
        )
    assert rule.trims == []
    held = np.array([0.14, 0.15, 0.15, 0.0])  # 56% cash: the spare pays part
    out = rule.weight_filter(30, held, closes[30])
    assert rule.state == {0: pt.ADDED}
    add = rule.trims[-1]
    assert add.kind == pt.ADD and add.weight_after == pytest.approx(policy_v4.HOLD_CAP)
    assert add.size == pytest.approx(0.14 - 0.20)
    assert add.indicator < -0.08
    # The spare cash (1 - 0.44 - 0.02 = 0.54) covers the 0.06 raise: no trims.
    np.testing.assert_allclose(out, held)
    # With no spare cash the others pay pro rata.
    rule2 = pt.ProfitTaking(
        _base([0.15, 0.15, 0.15, 0.0]), pt.variant("dip-add"), _fake(closes)
    )
    rule2.allocator(None, None, None, 0)
    full = np.array([0.30, 0.35, 0.33, 0.0])
    out = rule2.weight_filter(30, full, closes[30])
    need = 0.0  # the name already holds more than the 0.20 cap: nothing to add
    assert rule2.state == {} and need == 0.0
    np.testing.assert_allclose(out, full)
    tight = np.array([0.15, 0.42, 0.41, 0.0])
    out = rule2.weight_filter(31, tight, closes[31])
    assert rule2.state == {0: pt.ADDED}
    raise_needed = 0.20 - 0.15
    pool = 0.42 + 0.41
    np.testing.assert_allclose(
        out,
        [0.15, 0.42 * (1 - raise_needed / pool), 0.41 * (1 - raise_needed / pool), 0.0],
    )
    # The allocator carries the raise with the others scaled pro rata.
    target = rule2.allocator(None, None, None, 31)
    np.testing.assert_allclose(target, [0.20, 0.125, 0.125, 0.0])
    assert target.sum() == pytest.approx(0.45)
    # The next reset restores the policy's targets and the add is cooling.
    target = rule2.allocator(None, None, None, 40)
    np.testing.assert_allclose(target, [0.15, 0.15, 0.15, 0.0])
    assert rule2.state == {} and rule2.cooling == {0}
    out = rule2.weight_filter(40, target, closes[40])
    np.testing.assert_allclose(out, target)
    assert rule2.state == {}  # still under the EMA: no re-arm
    # Back within 8% of the EMA: armed again, and a new dip adds again.
    closes2 = closes.copy()
    closes2[41:, 0] = 100.0
    rule2.closes = closes2
    rule2.indicator = pt.ema_gap(closes2)
    rule2.weight_filter(45, [0.15, 0.15, 0.15, 0.0], closes2[45])
    assert rule2.cooling == set()
    # A cap at exactly the target adds nothing: base 0.20 x 1.5 -> 0.20.
    rule3 = pt.ProfitTaking(
        _base([0.2, 0.2, 0.2, 0.0]), pt.variant("dip-add"), _fake(closes)
    )
    rule3.allocator(None, None, None, 0)
    out = rule3.weight_filter(30, [0.2, 0.2, 0.2, 0.0], closes[30])
    np.testing.assert_allclose(out, [0.2, 0.2, 0.2, 0.0])
    assert rule3.state == {} and rule3.trims == []


# The forecast trim: the worst decile of the day's A/A+ names by forecast
# drawdown (at least one name) is halved and restored once out of it; the
# names without a forecast or without a target are not ranked; the stop
# variant exits a trimmed name whose close falls 15% under the trim close,
# to zero in the allocator until the next reset; the rule refuses to run
# without a forecast or with one of the wrong shape.
def test_forecast_trim_restore_and_stop():
    t, n = 10, 6
    closes = np.full((t, n), 100.0)
    closes[3:, 0] = 84.0  # 16% under the trim close of session 1
    forecast = np.tile(-0.05 - 0.01 * np.arange(n), (t, 1))  # N4 the worst by default
    forecast[1, 0] = -0.30  # N0 is the worst on sessions 1-3
    forecast[2, 0] = -0.30
    forecast[3, 0] = -0.30
    forecast[4, 0] = -0.01  # out of the decile on session 4
    forecast[:, 5] = np.nan  # never scored
    base = [0.15, 0.15, 0.15, 0.15, 0.15, 0.0]
    held = [0.15, 0.15, 0.15, 0.15, 0.15, 0.0]
    rule = pt.ProfitTaking(
        _base(base), pt.variant("trim-dd-forecast"), _fake(closes), forecast
    )
    rule.allocator(None, None, None, 0)
    # Session 0 (a reset): the worst decile of five names is one name, N4;
    # N5 has no forecast and is never ranked.
    out = rule.weight_filter(0, held, closes[0])
    np.testing.assert_allclose(out, [0.15, 0.15, 0.15, 0.15, 0.075, 0.0])
    assert rule.state == {4: pt.TRIMMED}
    # Session 1: N0 is the worst; N4 leaves the decile and is restored.
    out = rule.weight_filter(1, held, closes[1])
    assert [tr.kind for tr in rule.trims] == [pt.TRIM, pt.TRIM, pt.RESTORE]
    rule.trims = rule.trims[1:2]
    np.testing.assert_allclose(out, [0.075, 0.15, 0.15, 0.15, 0.15, 0.0])
    assert rule.state == {0: pt.TRIMMED} and rule.trim_price == {0: 100.0}
    assert [tr.kind for tr in rule.trims][-1] == pt.TRIM
    np.testing.assert_allclose(
        rule.allocator(None, None, None, 1), [0.075, 0.15, 0.15, 0.15, 0.15, 0.0]
    )
    rule.weight_filter(2, [0.075, 0.15, 0.15, 0.15, 0.15, 0.0], closes[2])
    assert rule.state == {0: pt.TRIMMED}
    # No stop in this variant: the 16% fall on session 3 changes nothing.
    rule.weight_filter(3, [0.06, 0.15, 0.15, 0.15, 0.15, 0.0], closes[3])
    assert rule.state == {0: pt.TRIMMED}
    rule.weight_filter(4, [0.06, 0.15, 0.15, 0.15, 0.15, 0.0], closes[4])
    assert rule.state == {4: pt.TRIMMED}
    assert [tr.kind for tr in rule.trims[-2:]] == [pt.RESTORE, pt.TRIM]
    assert rule.trims[-2].ticker == "N0" and rule.trims[-1].ticker == "N4"
    np.testing.assert_allclose(
        rule.allocator(None, None, None, 4), [0.15, 0.15, 0.15, 0.15, 0.075, 0.0]
    )
    # The stop variant exits on session 3 and stays out until the reset.
    stop = pt.ProfitTaking(
        _base(base), pt.variant("trim-dd-forecast-stop"), _fake(closes), forecast
    )
    stop.allocator(None, None, None, 0)
    stop.weight_filter(0, held, closes[0])
    stop.weight_filter(1, held, closes[1])
    stop.weight_filter(2, [0.075, 0.15, 0.15, 0.15, 0.15, 0.0], closes[2])
    out = stop.weight_filter(3, [0.06, 0.15, 0.15, 0.15, 0.15, 0.0], closes[3])
    assert stop.state == {0: pt.STOPPED}
    assert out[0] == 0.0
    assert stop.trims[-1].kind == pt.STOP
    assert stop.trims[-1].indicator == pytest.approx(-0.16)
    np.testing.assert_allclose(stop.allocator(None, None, None, 3)[0], 0.0)
    stop.weight_filter(4, [0.0, 0.15, 0.15, 0.15, 0.15, 0.0], closes[4])
    assert stop.state[0] == pt.STOPPED  # out of the decile does not lift a stop
    assert stop.state[4] == pt.TRIMMED
    reset = stop.allocator(None, None, None, 5)  # the reset lifts the stop only
    np.testing.assert_allclose(reset, [0.15, 0.15, 0.15, 0.15, 0.075, 0.0])
    assert stop.state == {4: pt.TRIMMED}
    with pytest.raises(ValueError, match="needs the aligned drawdown forecast"):
        pt.ProfitTaking(_base(base), pt.variant("trim-dd-forecast"), _fake(closes))
    with pytest.raises(ValueError, match="aligned to the panel"):
        pt.ProfitTaking(
            _base(base), pt.variant("trim-dd-forecast"), _fake(closes), forecast[:, :2]
        )
    with pytest.raises(ValueError, match="unknown rule"):
        pt.ProfitTaking(_base(base), pt.Variant("odd", "odd"), _fake(closes))


# Every rule prices on the fixture under the control's options: the curve
# is on the control's sessions, the ledger has a cash share, and the
# forecast rules run with a synthetic forecast and are skipped without one.
def test_every_variant_prices_on_the_fixture(history):
    report, restricted, mask, since = _book(history)
    control = pt.price(restricted, mask, pt.variant(pt.CONTROL), since, 25.0)
    rng = np.random.default_rng(0)
    forecast = rng.normal(-0.1, 0.05, size=restricted.panel.adj_close.shape)
    for v in pt.VARIANTS[1:]:
        priced = pt.price(restricted, mask, v, since, 25.0, forecast=forecast)
        np.testing.assert_array_equal(priced.curve.dates, control.curve.dates)
        assert np.isfinite(priced.curve.daily[1:]).all()
        assert priced.resets > 10
        assert np.isfinite(priced.diagnostics["all"]["cash_share"])
        for trim in priced.trims:
            assert trim.kind in (pt.TRIM, pt.ADD, pt.STOP, pt.RESTORE)
            assert trim.date in set(str(d) for d in restricted.panel.dates)
    forecast_run = pt.price(
        restricted, mask, pt.variant("trim-dd-forecast"), since, 25.0, forecast=forecast
    )
    assert any(tr.kind == pt.TRIM for tr in forecast_run.trims)
    assert not np.array_equal(forecast_run.curve.daily, control.curve.daily)


# The trim statistics on hand-built actions: two offsets, a window of 252
# sessions; trims a year is the median count over offsets, the "sold too
# early" share counts trims and stops the name rose after among those
# resolved, the forward bp is size x forward in bp of equity, adds are
# read the other way round.
def test_trim_stats_by_hand():
    dates = np.datetime64("2021-01-01", "D") + np.arange(252)
    keep = np.ones(252, dtype=bool)

    def action(kind, day, size, forward):
        return pt.Trim(
            "X",
            0,
            kind,
            day,
            str(dates[day]),
            100.0,
            0.2,
            0.2 - size,
            size,
            0.0,
            forward,
            None if forward is None else forward > 0,
        )

    first = pt.Priced(
        sc.Curve("x", dates, np.zeros(252)),
        trims=[
            action(pt.TRIM, 10, 0.10, 0.05),
            action(pt.TRIM, 50, 0.06, -0.10),
            action(pt.STOP, 80, 0.08, 0.02),
            action(pt.RESTORE, 90, 0.0, None),
            action(pt.ADD, 120, -0.05, -0.04),
            action(pt.TRIM, 250, 0.04, None),
        ],
    )
    second = pt.Priced(
        sc.Curve("x", dates, np.zeros(252)), trims=[action(pt.TRIM, 5, 0.1, 0.1)]
    )
    stats = pt.trim_stats([first, second], [dates, dates], [keep, keep])
    assert stats["trims_per_year"] == pytest.approx(np.median([4.0, 1.0]))
    assert stats["adds_per_year"] == pytest.approx(np.median([1.0, 0.0]))
    assert stats["restores_per_year"] == pytest.approx(0.5)
    assert stats["stops_per_year"] == pytest.approx(0.5)
    assert stats["mean_trim_size"] == pytest.approx(
        np.mean([0.10, 0.06, 0.08, 0.04, 0.1])
    )
    assert stats["mean_add_size"] == pytest.approx(0.05)
    assert stats["too_early_rate"] == pytest.approx(3 / 4)
    assert stats["dip_continued_rate"] == pytest.approx(1.0)
    assert stats["median_forward_after_trim"] == pytest.approx(
        np.median([0.05, -0.1, 0.02, 0.1])
    )
    assert stats["trim_forward_bp"] == pytest.approx(
        np.mean([0.1 * 0.05, 0.06 * -0.1, 0.08 * 0.02, 0.1 * 0.1]) * 1e4
    )
    assert stats["trims_total"] == 5 and stats["trims_resolved"] == 4
    assert set(stats) == set(pt.TRIM_STATS)
    empty = pt.trim_stats(
        [pt.Priced(sc.Curve("x", dates, np.zeros(252)))], [dates], [keep]
    )
    assert empty["trims_per_year"] == 0.0 and math.isnan(empty["too_early_rate"])


# A payload with the given per-variant CAGRs and drawdowns per window, t
# statistics and reported differences at 25 bp.
def _payload(
    choosing,
    reported,
    t,
    reported_bp,
    dd_choosing=None,
    above=None,
    cash=None,
    skipped=None,
):
    rows, paired = [], []
    for name, cagr in choosing.items():
        for window, value, dd in (
            (pt.CHOOSING, cagr, (dd_choosing or {}).get(name, -0.30)),
            (pt.REPORTED, reported.get(name, 0.4), -0.20),
        ):
            rows.append(
                {
                    "line": name,
                    "cost_bps": 25.0,
                    "window": window,
                    "median_cagr": value,
                    "median_drawdown": dd,
                    "offsets": 20,
                    "offsets_above_control": (above or {}).get(name, 10),
                    "cash_share": (cash or {}).get(name, 0.05),
                    "trims_per_year": 3.0,
                    "too_early_rate": 0.6,
                }
            )
        if name != pt.CONTROL:
            paired.append(
                {
                    "line": name,
                    "against": pt.CONTROL,
                    "cost_bps": 25.0,
                    "window": pt.CHOOSING,
                    "mean_daily_bp": (cagr - choosing[pt.CONTROL]) * 1e4 / 252,
                    "hac_t": t.get(name, 0.0),
                }
            )
            paired.append(
                {
                    "line": name,
                    "against": pt.CONTROL,
                    "cost_bps": 25.0,
                    "window": pt.REPORTED,
                    "mean_daily_bp": reported_bp.get(name, 0.0),
                    "hac_t": 0.0,
                }
            )
    return {
        "costs_bps": [10.0, 25.0],
        "rows": rows,
        "paired": paired,
        "skipped": skipped or {},
    }


# The verdict's floors on a hand-built payload: +1.5 pt at t 2.5, not worse
# later and drawdown within 3 pt is ADOPT; the same at t 1.5 is RECORD; +0.8
# pt at t 3 is RECORD; +2 pt at t 3 but worse later is RECORD; a drawdown 4
# pt deeper is RECORD; a skipped model rule is SKIPPED; +2.1 pt on 18 of 20
# offsets at t 0.7 is CONSISTENT and still a RECORD; the trims' CAGR points
# are the whole gap.
def test_verdict_floors_skips_and_sign_test():
    names = [v.name for v in pt.VARIANTS if v.name != pt.CONTROL]
    choosing = {pt.CONTROL: 0.25, **{n: 0.25 for n in names}}
    choosing["trim-runup-20"] = 0.265  # +1.5, t 2.5: ADOPT
    choosing["trim-rsi"] = 0.265  # +1.5, t 1.5: RECORD
    choosing["trim-band"] = 0.258  # +0.8, t 3: RECORD
    choosing["dip-add"] = 0.271  # +2.1, t 0.7, 18/20 offsets: CONSISTENT
    t = {"trim-runup-20": 2.5, "trim-rsi": 1.5, "trim-band": 3.0, "dip-add": 0.7}
    above = {"dip-add": 18}
    skipped = {
        "trim-dd-forecast": "no forecast",
        "trim-dd-forecast-stop": "no forecast",
    }
    payload = _payload(
        choosing, {}, t, {n: 0.5 for n in names}, above=above, skipped=skipped
    )
    payload["rows"] = [r for r in payload["rows"] if r["line"] not in skipped]
    payload["paired"] = [p for p in payload["paired"] if p["line"] not in skipped]
    verdict = pt.verdict(payload)
    decisions = {k: v["decision"] for k, v in verdict["variants"].items()}
    assert decisions == {
        "trim-runup-20": pt.ADOPT,
        "trim-rsi": pt.RECORD,
        "trim-band": pt.RECORD,
        "dip-add": pt.RECORD,
        "trim-dd-forecast": pt.SKIPPED,
        "trim-dd-forecast-stop": pt.SKIPPED,
    }
    assert verdict["adopt"] == ["trim-runup-20"]
    assert verdict["record"] == ["trim-rsi", "trim-band", "dip-add"]
    assert verdict["skipped"] == ["trim-dd-forecast", "trim-dd-forecast-stop"]
    assert verdict["consistent"] == ["dip-add"]
    dip = verdict["variants"]["dip-add"]
    assert dip["reading"] == pt.CONSISTENT and dip["offsets_above_control"] == 18
    assert dip["trims_cagr_points"] == pytest.approx(2.1) == dip["choosing_points"]
    assert verdict["variants"]["trim-dd-forecast"]["skipped"] == "no forecast"
    assert verdict["variants"]["trim-runup-20"]["trims_per_year"] == 3.0
    assert "ADOPT (registered): trim-runup-20" in verdict["text"]
    assert "SKIPPED (no forecast file)" in verdict["text"]
    assert pt.CONSISTENT in verdict["text"] and "18/20 offsets" in verdict["text"]
    # Worse later, or a drawdown 4 pt deeper, fails the floors.
    later = pt.verdict(_payload(choosing, {}, t, {"trim-runup-20": -0.5}))
    assert later["variants"]["trim-runup-20"]["decision"] == pt.RECORD
    deeper = pt.verdict(
        _payload(
            choosing,
            {},
            t,
            {n: 0.5 for n in names},
            dd_choosing={"trim-runup-20": -0.34},
        )
    )
    assert deeper["variants"]["trim-runup-20"]["decision"] == pt.RECORD
    assert deeper["variants"]["trim-runup-20"]["drawdown_gap_points"][
        pt.CHOOSING
    ] == pytest.approx(-4.0)
    # The exposure reading: a variant 10% less invested than the control.
    cash = {pt.CONTROL: 0.02, "trim-rsi": 0.12}
    exposure = pt.verdict(_payload(choosing, {}, t, {n: 0.5 for n in names}, cash=cash))
    info = exposure["variants"]["trim-rsi"]
    assert info["invested_share"] == pytest.approx(0.88)
    assert info["exposure_adjusted_control_cagr"] == pytest.approx(0.25 * 0.88 / 0.98)
    # Nothing to adopt: the text says so. Without the control it is not measured.
    flat = pt.verdict(
        _payload({pt.CONTROL: 0.25, **{n: 0.25 for n in names}}, {}, {}, {})
    )
    assert flat["adopt"] == [] and "every priced rule is RECORD" in flat["text"]
    empty = pt.verdict({"costs_bps": [10.0], "rows": [], "paired": []})
    assert empty["cost_bps"] == 10.0 and empty["text"].startswith("not measured")


# The command end to end on the fixture: with the price rules alone the two
# model rules are skipped and the payload says so; with a synthetic
# forecast file every rule is priced, the file's coverage is recorded and
# the trims of the median offset are kept; a missing forecast file exits 1;
# `--json` prints the payload.
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
    target = tmp_path / "desk" / "profit_taking.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert (
        payload["study"] == pt.STUDY and payload["policy"] == policy_v4.POLICY_VERSION
    )
    assert payload["trials"] == 7 and len(payload["variants"]) == 7
    assert payload["ran"] == [v.name for v in pt.VARIANTS[:5]]
    assert set(payload["skipped"]) == {"trim-dd-forecast", "trim-dd-forecast-stop"}
    assert len(payload["rows"]) == 5 * 3 and payload["forecast_file"] is None
    assert payload["options"]["midcycle_redeploy"] is True
    assert payload["options"]["event_exposure"] == "event_risk.live_path(panel)"
    verdict = payload["verdict"]
    assert verdict["skipped"] == ["trim-dd-forecast", "trim-dd-forecast-stop"]
    assert set(verdict["variants"]) == {v.name for v in pt.VARIANTS} - {pt.CONTROL}
    text = out.getvalue()
    assert "profit-taking study for graded-equal-weight/4" in text
    assert "7 registered variants (5 priced)" in text
    assert "vs ctl" in text and "trims/y" in text and "early" in text
    assert "skipped:" in text and "trim-dd-forecast-stop: no drawdown forecast" in text
    assert "exposure reading" in text and "verdict:" in text
    # With a synthetic forecast file, every rule is priced.
    panel = _report().panel
    rng = np.random.default_rng(3)
    rows = [(t, d) for d in panel.dates for t in panel.tickers if t != "SPY"]
    forecasts = df.Forecasts(
        dates=np.array([d for _, d in rows], dtype="datetime64[D]"),
        tickers=np.array([t for t, _ in rows]),
        forecast=rng.normal(-0.1, 0.05, size=len(rows)),
        meta={"model": "synthetic"},
    )
    npz = tmp_path / "dd.npz"
    df.save_forecasts(npz, forecasts)
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
            "--drawdown-forecasts",
            str(npz),
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ran"] == [v.name for v in pt.VARIANTS] and payload["skipped"] == {}
    assert len(payload["rows"]) == 7 * 3
    assert payload["forecast_file"] == str(npz)
    assert payload["forecast_meta"] == {"model": "synthetic"}
    assert payload["forecast_coverage"] == pytest.approx(6 / 7)
    assert set(payload["trims"]) == {v.name for v in pt.VARIANTS}
    assert payload["trims"]["trim-dd-forecast"]
    assert payload["resets"]["trim-dd-forecast"] > 10
    assert payload["verdict"]["skipped"] == []
    text = out.getvalue()
    assert "7 registered variants (7 priced)" in text
    assert "largest trims at the median offset" in text
    assert "skipped:" not in text
    # A missing forecast file exits 1 before the desk runs.
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--membership",
            str(history),
            "--drawdown-forecasts",
            str(tmp_path / "none.npz"),
        ]
    )
    before = len(calls)
    assert cli.run(args, out, desk_run=fake_desk) == 1
    assert len(calls) == before and "not found" in out.getvalue()
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
