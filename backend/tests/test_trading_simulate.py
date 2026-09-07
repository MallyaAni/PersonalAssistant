"""The full-rule simulation: the desk's own rules walked through history.

`simulate.run` is the only thing that measures the desk as it actually
trades, rather than measuring one ingredient. Everything it reports —
whether the grade multipliers earn their place, whether the regime's
exposure cut helps, whether an exit overlay is worth having — is only
worth reading if the walk itself is honest. These tests fix that: no
lookahead, the rebalance clock, the grade and regime multipliers, costs,
and what happens to the weight an exit frees.
"""

from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.agents.trading.desk.grading import Graded
from backend.agents.trading.desk.regime import RegimeState
from backend.market.panel import Panel

SESSIONS = 200
NAMES = 6  # five names plus the benchmark


def _panel(close: np.ndarray) -> Panel:
    rows, names = close.shape
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(rows)],
        dtype="datetime64[D]",
    )
    tickers = tuple(f"N{i}" for i in range(names - 1)) + ("SPY",)
    return Panel(
        dates=dates,
        tickers=tickers,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: () for t in tickers[:-1]},
        benchmark="SPY",
    )


def _state(exposure: float = 1.0, tightening: bool = False) -> RegimeState:
    return RegimeState(
        ai_participation=0.5,
        software_participation=0.5,
        participation_percentile=0.5,
        ai_vs_software_correlation=0.0,
        correlation_z=0.0,
        novelty_z=0.0,
        rotation_leader="ai",
        rotation_spread=0.0,
        ai_drawdown=0.0,
        selection_confidence=1.0,
        exposure=exposure,
        flags=(),
        tightening=tightening,
    )


def _report(close=None, grades=None, exposure=1.0, tightening=False):
    """A desk report over a quiet panel, with the grades handed in."""
    if close is None:
        rng = np.random.default_rng(7)
        steps = rng.normal(loc=0.0005, scale=0.01, size=(SESSIONS, NAMES))
        close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    panel = _panel(close)
    rows, names = close.shape
    if grades is None:
        grades = np.zeros((rows, names), dtype=int)
        grades[:, 0] = 3  # N0 is A+ throughout
        grades[:, 1] = 2  # N1 is A
        grades[:, 2] = 1  # N2 is B
    scores = grades.astype(float)
    graded = Graded(grades=grades, votes=scores.copy(), stances={})
    regime = SimpleNamespace(states=[_state(exposure, tightening)] * rows)
    return SimpleNamespace(
        panel=panel,
        graded=graded,
        scores=scores,
        regime=regime,
        sides={f"N{i}": "ai" for i in range(names - 1)},
        book=[],
    )


# Nothing the simulation reports may come from a session it had not seen.
# Change a name's price from session 120 onward and every return before 120
# must be identical to the penny, because the weights that earned them were
# decided from prices that did not change. Session 120's own return does
# change, since that is the real move being filled, and the sessions after
# it may too, because the sizing engine has now seen a more volatile name.
# That is the engine reacting to news, not reading it early.
def test_no_lookahead_in_the_fill():
    rng = np.random.default_rng(11)
    close = 100.0 * np.exp(
        np.cumsum(rng.normal(loc=0.0, scale=0.001, size=(SESSIONS, NAMES)), axis=0)
    )
    quiet = _report(close.copy())
    spiked = close.copy()
    spiked[120:, 0] *= 2.0  # N0 doubles overnight on session 120
    loud = _report(spiked)
    a = simulate.run(quiet, use_exits=False, rebalance=20)
    b = simulate.run(loud, use_exits=False, rebalance=20)
    differs = np.flatnonzero(
        ~np.isclose(np.nan_to_num(a.returns), np.nan_to_num(b.returns))
    )
    # Nothing before the jump moved, so nothing leaked backwards.
    assert differs.min() == 120
    assert np.allclose(np.nan_to_num(a.returns[:120]), np.nan_to_num(b.returns[:120]))
    # The weights carried into the jump were the same ones either way.
    assert np.allclose(a.invested[:120], b.invested[:120])


# The book is brought to target every `rebalance` sessions and left alone
# in between, so the count of rebalances follows from the clock alone.
@pytest.mark.parametrize("every", [5, 20, 60])
def test_the_rebalance_clock(every):
    report = _report()
    result = simulate.run(report, use_exits=False, rebalance=every)
    expected = len(range(0, SESSIONS - 1, every))
    assert result.rebalances == expected


# A better grade earns a bigger position: A+ is a full one, A three
# quarters, B a half, and C nothing at all.
def test_the_grade_sizes_the_position():
    report = _report()
    weights = simulate._engine_weights(report, 150, simulate.risk.BOOK_CONFIG)
    held = simulate.run(report, use_exits=False, rebalance=20)
    assert held.invested[150] > 0
    # N3 and N4 are graded C and are never held.
    for trade in held.trades:
        assert trade.ticker not in {"N3", "N4", "SPY"}
    # Among the names the engine wants, the A+ carries more than the B.
    a_plus, b_grade = report.panel.index("N0"), report.panel.index("N2")
    if weights[a_plus] > 0 and weights[b_grade] > 0:
        assert (
            weights[a_plus] * simulate.risk.SIZE_MULTIPLIER["A+"]
            > weights[b_grade] * simulate.risk.SIZE_MULTIPLIER["B"]
        )


# The regime's exposure scales the whole book, and an exposure of zero
# means the desk holds nothing and earns nothing.
#
# The halving is exact in what the desk asks for. What it ends up holding
# is not exactly half a session later: the fill happens at the open and
# `invested` is measured at the close, and the half-exposure book carries
# more cash, so the two drift apart between those two prices. The target
# is the deterministic thing, so that is what the exactness is asserted on.
def test_the_regime_scales_the_whole_book():
    config = simulate.risk.BOOK_CONFIG
    full_report, half_report = _report(exposure=1.0), _report(exposure=0.5)
    full_target = simulate._targets(full_report, full_report.panel, config, 140)
    half_target = simulate._targets(half_report, half_report.panel, config, 140)
    assert half_target.sum() == pytest.approx(full_target.sum() * 0.5, rel=1e-9)
    assert np.allclose(half_target, full_target * 0.5)

    full = simulate.run(_report(exposure=1.0), use_exits=False, rebalance=20)
    half = simulate.run(_report(exposure=0.5), use_exits=False, rebalance=20)
    flat = simulate.run(_report(exposure=0.0), use_exits=False, rebalance=20)
    assert flat.invested.max() == 0.0
    assert np.nan_to_num(flat.returns).sum() == 0.0
    # And the book that follows those targets holds about half as much.
    assert half.invested[141] == pytest.approx(full.invested[141] * 0.5, rel=0.05)


# While money is tightening the same names are held, weighted so the
# steadier ones take more of the book. The gross does not change.
def test_tightening_keeps_the_gross_and_moves_the_weight():
    calm = simulate.run(_report(tightening=False), use_exits=False, rebalance=20)
    tight = simulate.run(_report(tightening=True), use_exits=False, rebalance=20)
    assert tight.invested[150] == pytest.approx(calm.invested[150], rel=1e-6)


# Costs are charged on what moves, so a bigger cost can only lower the
# return, and a zero cost run is the ceiling.
def test_costs_only_subtract():
    free = simulate.run(_report(), use_exits=False, rebalance=20, cost_bps=0.0)
    dear = simulate.run(_report(), use_exits=False, rebalance=20, cost_bps=50.0)
    assert np.nan_to_num(dear.returns).sum() < np.nan_to_num(free.returns).sum()
    assert dear.stats()["annual"] < free.stats()["annual"]


# Every position that opens is eventually recorded as closed, with a reason
# a person can read, and the run ends with the open ones marked as such.
def test_every_position_is_accounted_for():
    result = simulate.run(_report(), use_exits=False, rebalance=20)
    assert result.trades
    assert all(t.reason for t in result.trades)
    still = [t for t in result.trades if t.reason == "still held"]
    assert still, "the run should end holding something"
    assert all(t.closed is None for t in still)
    assert all(t.grade in {"A+", "A", "B", "C"} for t in result.trades)


# An exit between rebalances either parks the freed weight as cash or
# spreads it over the names still held. `redeploy` is what decides, and
# the two must actually differ in the gross carried.
def test_redeploy_puts_the_freed_weight_back_to_work():
    report = _report()
    panel = report.panel
    rows, names = panel.adj_close.shape
    # The engine's usual concentration would leave one name held, and one
    # name leaving is the whole book leaving. Widen it so the freed weight
    # has somewhere to go.
    wide = replace(simulate.risk.BOOK_CONFIG, top_fraction=1.0)
    # An exit signal that fires once, on a held session that is not a
    # rebalance: the clock rebalances at 0, 20, ... 140, 160.
    signal = np.zeros((rows, names), dtype=bool)
    signal[155, 0] = True

    class _Stub:
        def __getitem__(self, key):
            return signal[key]

    original = (
        simulate.exit_analyst.evidence,
        simulate.exit_analyst.should_exit,
        simulate.exit_analyst.reason,
    )
    simulate.exit_analyst.evidence = lambda p: _Stub()
    simulate.exit_analyst.should_exit = lambda ev, t, c, entry: bool(ev[t, c])
    simulate.exit_analyst.reason = lambda ev, t, c: "the stub said so"
    try:
        cash = simulate.run(
            report, config=wide, use_exits=True, rebalance=20, redeploy=False
        )
        back = simulate.run(
            report, config=wide, use_exits=True, rebalance=20, redeploy=True
        )
    finally:
        (
            simulate.exit_analyst.evidence,
            simulate.exit_analyst.should_exit,
            simulate.exit_analyst.reason,
        ) = original
    # An exit named on session 155 is filled at 156's open, like every
    # other decision here, so 155 still shows the book that was held into
    # it and the difference appears the session after.
    assert cash.invested[155] == pytest.approx(back.invested[155], rel=1e-6)
    assert cash.invested[156] < back.invested[156]
    assert any(t.reason == "the stub said so" for t in cash.trades)


# The statistics come from the daily series and nothing else, so a series
# with no return has no Sharpe and a straight line has no drawdown.
def test_stats_read_the_daily_series():
    dates = np.array([date(2024, 1, 1)], dtype="datetime64[D]")
    empty = simulate.SimResult(dates, np.array([np.nan]), np.array([0.0]))
    assert np.isnan(empty.stats()["sharpe"])
    steady = simulate.SimResult(
        dates, np.full(300, 0.001), np.ones(300), [], rebalances=1
    )
    stats = steady.stats()
    assert stats["drawdown"] == pytest.approx(0.0)
    assert stats["annual"] == pytest.approx(0.252)
    assert stats["total"] > 0.34


# A decision is filled at the next open, so a gap between the session the
# decision was made on and that open belongs to whoever held the name
# overnight - never to a book that buys at the open.
#
# The first version of the simulator never read an opening price and
# applied close-to-close returns, so a name it decided to buy on Friday
# was paid Monday's gap. On news-driven names that is the whole move, and
# it is the part a real fill cannot have.
#
# The assertion is the position's own return and not a band around the
# book's. A threshold of "less than 5%" was the first attempt and it was
# worthless: a 7% position collecting a 20% gap moves the book 1.4%, which
# is under 5%, so the broken simulator passed the test written to catch
# it. The name is bought at 120 and never moves again, so the only honest
# number is zero.
def test_a_gap_before_the_fill_is_not_collected():
    rows, decide_at = 200, 160  # a rebalance session; the fill is at 161
    close = np.full((rows, NAMES), 100.0)
    rng = np.random.default_rng(5)
    close[:, 1:] = 100.0 * np.exp(
        np.cumsum(rng.normal(0, 0.008, (rows, NAMES - 1)), axis=0)
    )
    opens = close.copy()
    # N0 sits at 100, gaps to 120 overnight into the fill session, and does
    # nothing ever again: its open and close are 120 from then on.
    close[decide_at + 1 :, 0] = 120.0
    opens[decide_at + 1 :, 0] = 120.0

    grades = np.zeros((rows, NAMES), dtype=int)
    grades[:, 1:] = 1  # the rest of the book is only ever a B
    grades[decide_at:, 0] = 3  # N0 becomes the desk's best name here
    report = _report(close, grades=grades)
    report.panel = replace(report.panel, open=opens)
    result = simulate.run(report, use_exits=False, rebalance=20, cost_bps=0.0)

    bought = [t for t in result.trades if t.ticker == "N0"]
    assert bought, "N0 should have been bought once it was graded A+"
    # Bought at the gapped open of 120 and never moved: exactly nothing.
    # Filled at the previous close of 100 it would read +20%.
    assert bought[-1].ret == pytest.approx(0.0, abs=1e-9)
    assert bought[-1].opened == str(report.panel.dates[decide_at + 1])


# The quantity is decided at the price the decision could see, and the
# fill happens later at whatever the open turns out to be.
#
# Sizing at the opening price is a smaller error than collecting the gap
# and it is still an error: it spends exactly the target fraction however
# the price moved overnight, which no order can do. With a 10% target, a
# $100 close and a $120 open the paper planner submits 100 shares; the
# simulator used to buy 83.33.
def test_the_order_is_sized_at_the_decision_price():
    book = simulate._Book(
        3, equity=100_000.0, cost_bps=0.0, panel=None, report=None, stamps=[]
    )
    decision_prices = np.array([100.0, 100.0, np.nan])
    target = np.array([0.10, 0.0, 0.0])
    order = book.plan(target, decision_prices)
    assert order[0] == pytest.approx(100.0), "10% of 100,000 at 100 is 100 shares"

    # The fill happens at a different price and the share count does not
    # move to compensate: the order was already placed.
    book.settle(order, np.array([120.0, 120.0, np.nan]), session=0, reason="x")
    assert book.shares[0] == pytest.approx(100.0)
    # It cost what 100 shares cost at the open, not the planned notional.
    assert book.cash == pytest.approx(100_000.0 - 100.0 * 120.0)


# Between rebalances the book holds shares, so a winner's weight grows
# instead of being sold back to target every session.
#
# The first version held a weight vector, which silently rebalanced daily:
# a holding that quadrupled left the gross exactly where it started.
def test_a_winner_grows_between_rebalances():
    rows = 200
    close = np.full((rows, NAMES), 100.0)
    close[:, -1] = 100.0
    rng = np.random.default_rng(9)
    close = close * np.exp(np.cumsum(rng.normal(0, 0.005, (rows, NAMES)), axis=0))
    before = close.copy()
    close[160:, 0] = before[160:, 0] * 4.0
    report = _report(close)
    result = simulate.run(report, use_exits=False, rebalance=60, cost_bps=0.0)
    # Sessions 121 to 180 are one holding period (the rebalance decided at
    # 120 fills at 121, the next is decided at 180).
    assert result.invested[170] > result.invested[150], (
        "a holding that quadrupled should take up more of the book, not the "
        "same fraction of it"
    )


# The name cap survives the tightening tilt. The tilt renormalises to the
# same gross, which moves weight onto the calmest names; before the recap
# that carried one to 0.1626 against a 0.15 cap.
def test_the_tightening_tilt_respects_the_name_cap():
    rows = 260
    rng = np.random.default_rng(7)
    vols = np.linspace(0.002, 0.06, NAMES)
    steps = np.column_stack([rng.normal(0, v, rows) for v in vols])
    close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    report = _report(close, tightening=True)
    config = simulate.risk.BOOK_CONFIG
    for fraction in (0.1, 0.3, 0.6):
        wide = replace(config, top_fraction=fraction)
        weights = simulate._engine_weights(report, 240, wide)
        tilted = simulate._steepen(weights.copy(), report.panel, wide, 240)
        assert tilted.max() <= wide.name_cap + 1e-9, (
            f"the tilt carried a position to {tilted.max():.4f}, over the "
            f"{wide.name_cap} cap"
        )
        # And it does not quietly raise the gross to compensate.
        assert tilted.sum() <= weights.sum() + 1e-9
