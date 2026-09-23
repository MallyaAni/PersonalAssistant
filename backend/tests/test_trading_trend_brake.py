"""The trend brake shadow on the incumbent simulator.

The brake is a predeclared state machine over QQQ's own trend that holds
the book at half while the index is below its 200-session mean. These
tests fix the four things a shadow has to get right before its numbers
mean anything: off, it changes nothing; on, it turns at exactly the
thresholds the specification names and sits still in the hysteresis band;
it never reads a session it has not seen; and it refuses the combinations
that would measure a different book than was asked for.
"""

import numpy as np
import pytest

from backend.agents.trading.desk import simulate, trend_brake
from backend.tests.test_trading_simulate import NAMES, _report

ROWS = 320
ENTERS = 250  # the first close below 0.97 x the trailing mean
LEAVES = 271  # the first close above 1.02 x the trailing mean


# A QQQ path that sits on its own mean for 250 sessions, falls ten percent
# through the entry threshold, idles inside the hysteresis band and then
# jumps five percent through the exit threshold.
def _qqq() -> np.ndarray:
    qqq = np.full(ROWS, 100.0)
    qqq[ENTERS] = 90.0
    qqq[ENTERS + 1 : LEAVES] = 98.0
    qqq[LEAVES:] = 105.0
    return qqq


# The benchmark context the brake reads, on the panel's own calendar.
def _benchmarks(panel, qqq=None) -> dict:
    return {
        "dates": panel.dates,
        "SPY": np.full(ROWS, 100.0),
        "QQQ": _qqq() if qqq is None else qqq,
    }


# A fixed allocation, so the exposure the brake scales is known to the penny.
def _allocation(_report, _panel, _config, _t):
    weights = np.zeros(NAMES)
    weights[0] = 0.3
    weights[1] = 0.3
    return weights


# Off, the keyword is inert: every series is byte-identical to a run that
# never heard of it, under the bare rules and under the live policy, and
# the state it reports is all False.
@pytest.mark.parametrize("policy", [{}, simulate.LIVE_POLICY])
def test_the_brake_off_is_byte_identical(policy):
    report = _report()
    base = simulate.run(report, use_exits=False, **policy)
    off = simulate.run(report, use_exits=False, trend_brake=False, **policy)
    np.testing.assert_array_equal(base.equity, off.equity)
    np.testing.assert_array_equal(base.invested, off.invested)
    np.testing.assert_array_equal(base.returns, off.returns)
    assert base.traded == off.traded
    assert off.risk_off.shape == off.equity.shape
    assert not off.risk_off.any()
    assert base.risk_off is not None
    assert not base.risk_off.any()


# The state turns exactly where the specification says: on at the first
# close below 0.97 x the trailing 200-session mean, held through the closes
# inside the band, off at the first close above 1.02 x the mean, and never
# on before there are 200 sessions of history. The thresholds are checked
# against an independent reading of the trailing mean, not the module's.
def test_the_state_turns_at_the_thresholds_and_holds_in_the_band():
    qqq = _qqq()
    risk_off = trend_brake.risk_off_path(qqq)
    on = np.flatnonzero(risk_off)
    assert on.min() == ENTERS
    assert on.max() == LEAVES - 1
    assert risk_off[ENTERS:LEAVES].all()
    assert not risk_off[:ENTERS].any()
    assert not risk_off[LEAVES:].any()
    means = np.array([qqq[t - 199 : t + 1].mean() for t in range(199, ROWS)])
    closes = qqq[199:]
    below = np.flatnonzero(closes < 0.97 * means) + 199
    above = np.flatnonzero(closes > 1.02 * means) + 199
    assert below.min() == ENTERS
    assert above[above > ENTERS].min() == LEAVES
    # The band: every session held on is one the thresholds did not decide.
    inside = (closes >= 0.97 * means) & (closes <= 1.02 * means)
    assert inside[ENTERS + 1 - 199 : LEAVES - 199].all()


# While risk_off the book holds half of what the unbraked rules hold, and
# exactly what they hold outside; a rebalance inside the window sizes to
# the ceiling; and nothing moves between the two state changes.
def test_the_brake_halves_the_book_while_risk_off_and_restores_it():
    close = np.full((ROWS, NAMES), 100.0)
    report = _report(close)
    common = {"use_exits": False, "rebalance": 20, "allocator": _allocation}
    off = simulate.run(report, **common)
    on = simulate.run(
        report, **common, trend_brake=True, benchmark_prices=_benchmarks(report.panel)
    )
    np.testing.assert_array_equal(on.risk_off, trend_brake.risk_off_path(_qqq()))
    # Identical until the cut fills at the open after the first risk_off close.
    np.testing.assert_array_equal(on.equity[: ENTERS + 1], off.equity[: ENTERS + 1])
    np.testing.assert_array_equal(on.invested[: ENTERS + 1], off.invested[: ENTERS + 1])
    fills = np.arange(ENTERS, LEAVES) + 1
    np.testing.assert_allclose(on.invested[fills], 0.5 * off.invested[fills], atol=1e-3)
    assert np.allclose(off.invested[fills], 0.6, atol=1e-3)
    # The t=260 rebalance sits inside the window and sizes to the ceiling.
    assert on.rebalances == off.rebalances
    np.testing.assert_allclose(on.invested[fills], on.invested[fills[0]], atol=1e-3)
    # Restored from cash at the open after the first risk_on close, and
    # equal to the unbraked book from there on.
    np.testing.assert_allclose(
        on.invested[LEAVES + 1 :], off.invested[LEAVES + 1 :], atol=1e-3
    )
    assert on.traded > off.traded
    # The two state changes are the only sessions the brake trades on.
    moved = np.flatnonzero(~np.isclose(np.diff(on.invested), 0.0, atol=1e-3))
    assert set(moved.tolist()) == {0, ENTERS, LEAVES}


# The brake composes with the FOMC path as a minimum: a half-exposure event
# window inside the risk_off period asks for no less than the brake already
# holds, and one outside it cuts the book on its own.
def test_the_brake_and_the_event_path_compose_as_a_minimum():
    close = np.full((ROWS, NAMES), 100.0)
    report = _report(close)
    event = np.ones(ROWS)
    event[255:258] = 0.5  # inside the risk_off window
    event[300:303] = 0.5  # after it
    common = {"use_exits": False, "rebalance": 20, "allocator": _allocation}
    both = simulate.run(
        report,
        **common,
        event_exposure=event,
        trend_brake=True,
        benchmark_prices=_benchmarks(report.panel),
    )
    # Inside the window the event asks for the half the brake already
    # holds: one cut at 251, nothing further, restored at 272.
    assert np.allclose(both.invested[252:272], 0.3, atol=1e-3)
    assert np.allclose(both.invested[272:301], 0.6, atol=1e-3)
    # Outside it the event path cuts and restores the book on its own.
    assert np.allclose(both.invested[301:304], 0.3, atol=1e-3)
    assert np.allclose(both.invested[304:], 0.6, atol=1e-3)


# Every session's state is decided from that close and the ones before it,
# so a future that has not happened yet - a crash appended after the fact -
# leaves every earlier value exactly where it was, in the helper and in the
# result a run reports.
def test_the_state_never_reads_a_future_row():
    qqq = _qqq()
    full = trend_brake.risk_off_path(qqq)
    for k in (150, 199, 200, 251, 262, 272, 300):
        np.testing.assert_array_equal(trend_brake.risk_off_path(qqq[:k]), full[:k])
    crashed = np.r_[qqq, np.full(60, 50.0)]
    np.testing.assert_array_equal(trend_brake.risk_off_path(crashed)[:ROWS], full)
    # And through the simulator: the run over the shorter history reports
    # the same states as the first rows of the run over the longer one.
    close = np.full((ROWS, NAMES), 100.0)
    short = _report(close[:262])
    result = simulate.run(
        short,
        use_exits=False,
        rebalance=20,
        allocator=_allocation,
        trend_brake=True,
        benchmark_prices={
            "dates": short.panel.dates,
            "SPY": np.full(262, 100.0),
            "QQQ": qqq[:262],
        },
    )
    np.testing.assert_array_equal(result.risk_off, full[:262])


# The brake runs under the live policy: the account that sells at the close
# and skips a green open still takes the cut and the restoration as
# next-open orders, and reports the same state.
def test_the_brake_runs_under_the_live_policy():
    close = np.full((ROWS, NAMES), 100.0)
    report = _report(close)
    common = {"use_exits": False, "rebalance": 20, "allocator": _allocation}
    off = simulate.run(report, **common, **simulate.LIVE_POLICY)
    on = simulate.run(
        report,
        **common,
        **simulate.LIVE_POLICY,
        trend_brake=True,
        benchmark_prices=_benchmarks(report.panel),
    )
    np.testing.assert_array_equal(on.risk_off, trend_brake.risk_off_path(_qqq()))
    np.testing.assert_array_equal(on.equity[: ENTERS + 1], off.equity[: ENTERS + 1])
    assert on.invested[ENTERS + 1] == pytest.approx(
        0.5 * off.invested[ENTERS + 1], abs=1e-3
    )
    assert on.invested[LEAVES + 1] == pytest.approx(off.invested[LEAVES + 1], abs=1e-3)


# The combinations that would measure a different book than asked for are
# refused: no benchmark context, no QQQ in it, a calendar that is not the
# panel's, the funded path that has its own trend ceiling, and a scale
# that is not a fraction of the book.
def test_the_brake_refuses_the_wrong_inputs():
    close = np.full((ROWS, NAMES), 100.0)
    report = _report(close)
    benchmarks = _benchmarks(report.panel)
    with pytest.raises(ValueError, match="benchmark_prices"):
        simulate.run(report, use_exits=False, trend_brake=True)
    with pytest.raises(ValueError, match="QQQ"):
        simulate.run(
            report,
            use_exits=False,
            trend_brake=True,
            benchmark_prices={"dates": report.panel.dates, "SPY": benchmarks["SPY"]},
        )
    shifted = dict(benchmarks, dates=report.panel.dates + np.timedelta64(1, "D"))
    with pytest.raises(ValueError, match="calendar"):
        simulate.run(
            report, use_exits=False, trend_brake=True, benchmark_prices=shifted
        )
    short = dict(benchmarks, QQQ=benchmarks["QQQ"][:-1])
    with pytest.raises(ValueError, match="aligned"):
        simulate.run(report, use_exits=False, trend_brake=True, benchmark_prices=short)
    with pytest.raises(ValueError, match="trend_brake"):
        simulate.run(
            report,
            trend_brake=True,
            funded_allocation=True,
            benchmark_prices=benchmarks,
        )
    with pytest.raises(ValueError, match="brake_scale"):
        simulate.run(
            report,
            use_exits=False,
            trend_brake=True,
            brake_scale=0.0,
            benchmark_prices=benchmarks,
        )


# While the brake holds the book down, the mid-cycle policy's buys must not
# spend the cash the cut released, while its sells still go through. The
# shared policy is stubbed to ask for one buy and one sell every session, so
# the test reads the brake's own gate rather than the band signal: off, the
# buy is taken; on and inside the braked window, only the sell is; after the
# brake lifts, the buy is taken again.
def test_the_brake_pauses_mid_cycle_buys_but_not_sells(monkeypatch):
    close = np.full((ROWS, NAMES), 100.0)
    report = _report(close)
    asked: list[int] = []

    # A stand-in for the shared rotation-and-entry policy: sell a tenth of
    # name 0 and buy 0.01 shares of name 2, every mid-cycle session.
    def _policy(book, _report, t, *_args, **_kwargs):
        asked.append(t)
        wanted = book.shares.copy()
        wanted[0] *= 0.9
        wanted[2] += 0.01
        return wanted

    monkeypatch.setattr(simulate, "_live_midcycle", _policy)
    common = {"use_exits": False, "rebalance": 20, "allocator": _allocation}
    off = simulate.run(report, **common, **simulate.LIVE_POLICY)
    on = simulate.run(
        report,
        **common,
        **simulate.LIVE_POLICY,
        trend_brake=True,
        benchmark_prices=_benchmarks(report.panel),
    )
    assert asked  # the stub was consulted
    # Off: name 2 is bought on ordinary sessions, so it appears as a trade.
    assert any(tr.ticker == "N2" for tr in off.trades)
    # On: inside the braked window no N2 position is opened, but name 0
    # keeps being trimmed - the invested fraction falls between the cut and
    # the restoration instead of being refilled from the released cash.
    opened_n2 = [tr.opened for tr in on.trades if tr.ticker == "N2"]
    window = {str(d) for d in report.panel.dates[ENTERS + 1 : LEAVES + 1]}
    assert not (set(opened_n2) & window)
    assert on.invested[LEAVES - 1] < on.invested[ENTERS + 2]
    assert on.invested[LEAVES - 1] < 0.5 * off.invested[ENTERS + 2] + 1e-6
    # After the brake lifts, the buy side of the policy resumes.
    assert any(o > str(report.panel.dates[LEAVES]) for o in opened_n2)
