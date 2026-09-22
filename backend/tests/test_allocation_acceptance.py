"""Independent acceptance tests for the shared funded-allocation execution path.

Written from the PARALLEL contract's stable shared boundary, not by mirroring
the SIMULATOR/PAPER/API roles' own tests. The snapshot under test is root's
combined backend tree, now copied in as the dependency (hashes are the SHA-256
of the working tree at this edit):

  HEAD a86745115c827e8e1a60b92d3d77078f4a573e2b
  simulate.py         36ab2ad82f4831147b5aa9273935c217e109ed7ab5f063c8c92e3a9186a67ee1
  paper.py            20203bb838841621e0cac794911511ff0d4be9ccc8c4ff13d7ae795b7d1205f8
  funded_execution.py 7bfebb8ea14bf2edf374bbc9ba73df0c271d97a3e76641739af9685ac4c1cec4
  allocation.py       1a35cc5a18b75b20f179fd795ab27e8e1f5cc7233e3d65f5796f0ac7c05fc616
  planner.py          ad917b5344654087e12b25b55cf558d3f519d3955ee2f3191b58ae263d8d248c

These tests pin contract properties the roles' own tests do not: that the real
`_Book` conserves value up to fees (loss/fees conservation), that funded buys
never spend a same-day sale's proceeds (cash gaps), that a missing fill is
reported rather than fabricated, that a full or partial exit leaves the exact
shares and proceeds it filled at, that whole-share holdings never go short or
overdrawn, that a plan (a preview of the full candidate) is pure data that
places no orders by itself, and that a held name whose price goes missing
leaves the NAV unavailable rather than liquidating or fabricating a value.

Every test here asserts the CONTRACT behaviour, not the draft's. Four defects
of the seeded draft - index eligibility, the post-fee reference NAV, a blocked
plan's unavailable NAV, and benchmark `dates` validation - are fixed in the
integrated source: their checks now pass unmarked and their `xfail` markers are
removed. Two findings remain in the combined tree:

  - SPY partial cut (assigned to the SIMULATOR): with `index_eligible=False`
    and a held 400-share SPY position at desired weight 0.4 (200 shares), the
    integrated `plan_funded` sells all 400 instead of the 200-share cut the
    desired weight calls for. `False` must suppress only new SPY *buys*; risk
    cuts of held SPY stay the desk's hands and sell the excess, not everything.
    The assertion stays red until the simulator corrects it - it is deliberately
    NOT marked xfail so the defect remains a visible failure, not an expected
    one.
  - unavailable NAV on a missing held price is enforced at the funded
    `simulate.run` boundary (its explicit guards mark the session's NAV/returns
    unavailable), not at the private `_Book.equity` helper, whose priced-only
    valuation is the incumbent default path's frozen 2693-session behaviour.
    The funded journey test walks a real funded run with a held price that
    disappears and asserts the ledger keeps the actual shares, records no
    fictitious fill or liquidation, never shows a fabricated loss or recovery,
    and that a strict evaluation rejects the run's missing evaluated returns.

The API/paper adoption boundary (`portfolio_allocation` view,
`snapshot["allocation_plan"]`) is NOT implemented in this seed; the exact
required acceptance for it is documented in PARALLEL_ACCEPTANCE_HANDOFF.md
rather than mocked here.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import allocation, funded_execution, simulate
from backend.agents.trading.desk.allocation import QQQ, SPY, AllocationDecision
from backend.agents.trading.desk.funded_execution import plan_funded
from backend.agents.trading.desk.grading import Graded
from backend.agents.trading.desk.regime import RegimeState
from backend.agents.trading.desk.simulate import _Book
from backend.market.panel import Panel

COST_BPS = 10.0


# A decision that simply wants the given weights and claims full availability.
def _decision(desired_weights: dict[str, float]) -> AllocationDecision:
    """Return a valid vol_trend decision wanting exactly `desired_weights`."""
    return AllocationDecision(
        version="portfolio-allocation/vol_trend/1",
        as_of="2026-09-01",
        desired_weights=dict(desired_weights),
        cash=1.0,
        available=True,
        reasons=("no risk reduction required",),
        missing=(),
        volatility=None,
        binding="none",
    )


# A bare book with synthetic tickers T0..T(n-1), panel-free, for isolated fills.
def _book(cash: float, shares: list[float], cost_bps: float = COST_BPS) -> _Book:
    """Return a bare _Book holding exactly `shares` with `cash`."""
    book = _Book(len(shares), cash, cost_bps, None, None, None)
    book.shares = np.array(shares, dtype=float)
    return book


# --------------------------------------------------------------------------
# _Book conservation: loss/fees conservation
# --------------------------------------------------------------------------


# The account's value at the fill prices may change by exactly the fees paid,
# never by a rounding artifact, whichever way a basket moves. A losing sale is
# a realized loss the holder bears, not money the ledger invents or deletes.
def test_book_conserves_account_value_up_to_fees_across_random_baskets():
    rng = np.random.default_rng(11)
    for _ in range(400):
        n = int(rng.integers(1, 5))
        cash = float(rng.uniform(0.0, 300.0))
        book = _book(cash, rng.uniform(0.0, 3.0, n).tolist())
        # Some names have no usable price, so their holdings cannot move.
        prices = np.where(rng.random(n) < 0.15, np.nan, rng.uniform(1.0, 200.0, n))
        order = np.where(rng.random(n) < 0.2, np.nan, rng.uniform(0.0, 3.0, n))
        recycle = bool(rng.integers(0, 2))
        priced = np.nan_to_num(prices, nan=0.0)
        before = cash + float((book.shares * priced).sum())
        book._fill(order, prices, recycle_sells=recycle)
        after = book.cash + float((book.shares * priced).sum())
        # The only leak is the fee on the notional that actually traded.
        assert after == pytest.approx(before - book.traded * book.cost)
        assert book.cash >= -1e-9
        assert (book.shares >= -1e-9).all()


# A position bought at 100 and sold at the next open of 80 is a real loss: the
# ledger credits 80 net of fees and never pretends the decision close was paid.
def test_losing_exit_bears_the_loss_at_the_fill_price():
    book = _book(0.0, [1.0])  # one share bought at 100 on an earlier session
    plan = plan_funded(
        _decision({}),
        held={"T0": 1.0},
        prices={"T0": 100.0},
        equity=100.0,
        cash=0.0,
        cost_bps=COST_BPS,
    )
    book._fill(book.funded_order(plan), np.array([80.0]), recycle_sells=False)
    assert book.shares[0] == 0.0
    assert book.cash == pytest.approx(80.0 * (1.0 - COST_BPS / 1e4))


# One plan that exits T0 entirely and T1 partially leaves the exact shares and
# proceeds the fill produced, with the account conserved to the fees. The
# fixture is economically consistent: equity equals cash plus the valued
# holdings (20000 cash + 400 T0 at 100 + 400 T1 at 100 = 100000), so the
# weights and the dollars agree.
def test_partial_and_full_exit_in_one_plan_leave_the_filled_shares_and_cash():
    plan = plan_funded(
        _decision({"T1": 0.3}),
        held={"T0": 400.0, "T1": 400.0},
        prices={"T0": 100.0, "T1": 100.0},
        equity=100000.0,
        cash=20000.0,
        cost_bps=COST_BPS,
    )
    sides = {o.symbol: (o.side, o.qty) for o in plan.orders}
    assert sides == {"T0": ("sell", 400.0), "T1": ("sell", 100.0)}
    book = _book(20000.0, [400.0, 400.0])
    book._fill(book.funded_order(plan), np.array([100.0, 100.0]), recycle_sells=False)
    # T0 is gone (full exit); T1 kept the 300 shares the plan asked to keep.
    assert book.shares[0] == 0.0
    assert book.shares[1] == pytest.approx(300.0)
    # Cash is the pre-existing cash plus the net proceeds of both sales, the
    # 10 bps fee on the 50000 of notional that traded being the only leak.
    assert book.cash == pytest.approx(20000.0 + 50000.0 * (1.0 - COST_BPS / 1e4))
    assert book.equity(np.array([100.0, 100.0])) == pytest.approx(
        100000.0 - book.traded * book.cost
    )


# --------------------------------------------------------------------------
# Funded orders and cash gaps
# --------------------------------------------------------------------------


# A decision that sells a name and buys another with no pre-existing cash must
# not fund the buy from the same day's sale: the plan emits only the sell, and
# after the fill the new name holds nothing while the proceeds sit in cash.
def test_same_day_exit_never_funds_a_buy_without_preexisting_cash():
    plan = plan_funded(
        _decision({"T1": 0.5}),
        held={"T0": 1.0},
        prices={"T0": 100.0, "T1": 100.0},
        equity=100.0,
        cash=0.0,
        cost_bps=COST_BPS,
    )
    assert [(o.symbol, o.side) for o in plan.orders] == [("T0", "sell")]
    book = _book(0.0, [1.0, 0.0])
    book._fill(book.funded_order(plan), np.array([100.0, 100.0]), recycle_sells=False)
    assert book.shares[1] == 0.0
    assert book.cash == pytest.approx(100.0 * (1.0 - COST_BPS / 1e4))


# A funded buy is sized from the cash actually on hand, so the fill can never
# spend money the account does not have: cash stays nonnegative after fees.
def test_funded_buys_never_overdraw_cash_after_fees():
    plan = plan_funded(
        _decision({"T0": 1.0}),
        held={},
        prices={"T0": 100.0},
        equity=100.0,
        cash=40.0,
        cost_bps=COST_BPS,
    )
    # The plan wanted a full position but only 40 of cash exists.
    assert sum(o.qty * o.reference_price for o in plan.orders) <= 40.0
    book = _book(40.0, [0.0])
    book._fill(book.funded_order(plan), np.array([100.0]), recycle_sells=False)
    assert book.cash >= 0.0
    assert book.shares[0] * 100.0 <= 40.0


# A held name with no usable price blocks the whole plan: no order is placed,
# no executable is fabricated, and the reason names the missing valuation.
def test_held_name_without_a_price_blocks_without_orders_or_executable():
    plan = plan_funded(
        _decision({"T0": 0.5}),
        held={"T0": 1.0},
        prices={},
        equity=100.0,
        cash=50.0,
    )
    assert plan.orders == ()
    assert plan.executable == {}
    assert any("T0" in m for m in plan.blocked)


# A desired name with no price is reported missing and never filled: nothing
# is fabricated for it, and the rest of the plan still trades.
def test_desired_name_without_a_price_is_missing_not_fabricated():
    plan = plan_funded(
        _decision({"T0": 0.3, "T1": 0.3}),
        held={"T0": 0.0},
        prices={"T0": 100.0},
        equity=100.0,
        cash=60.0,
    )
    symbols = {o.symbol for o in plan.orders}
    assert "T1" not in symbols
    assert "T0" in symbols
    assert any("T1" in m and "no decision price" in m for m in plan.missing)


# --------------------------------------------------------------------------
# Whole-share holdings and index eligibility
# --------------------------------------------------------------------------


# Whole-share buys never round to zero, never exceed the cash on hand, and
# never create a position the account could not fund.
def test_whole_share_buy_rounds_to_zero_shares_when_unaffordable():
    plan = plan_funded(
        _decision({"T0": 0.5}),
        held={},
        prices={"T0": 100.0},
        equity=100.0,
        cash=10.0,
        whole_shares=True,
    )
    assert not any(o.side == "buy" for o in plan.orders)
    assert any("T0" in m and "zero shares" in m for m in plan.missing)
    assert plan.executable == {}


# SPY may be bought only when the caller declares explicit index eligibility;
# False must yield NO new SPY buy at all - in both continuous and whole-share
# modes - not merely cap it like a company name. The fixture uses the root
# reproduction: cash=equity=100000, SPY price 200, target 0.8, 10 bps, with
# enough capital that the eligible/ineligible outcomes are distinct. The
# integrated source enforces this (ineligible yields no new SPY buy), so the
# check passes unmarked.
def test_spy_requires_explicit_index_eligibility_for_any_new_buy():
    prices = {SPY: 200.0}
    for whole in (False, True):
        eligible = plan_funded(
            _decision({SPY: 0.8}),
            held={},
            prices=prices,
            equity=100000.0,
            cash=100000.0,
            whole_shares=whole,
            index_eligible=True,
        )
        ineligible = plan_funded(
            _decision({SPY: 0.8}),
            held={},
            prices=prices,
            equity=100000.0,
            cash=100000.0,
            whole_shares=whole,
            index_eligible=False,
        )
        eligible_buys = [
            o.qty for o in eligible.orders if o.side == "buy" and o.symbol == SPY
        ]
        ineligible_buys = [
            o.qty for o in ineligible.orders if o.side == "buy" and o.symbol == SPY
        ]
        assert eligible_buys, "explicit index eligibility must permit an SPY buy"
        assert not ineligible_buys, "no new SPY buy without index eligibility"


# Withholding index eligibility must not tie the desk's hands on risk: a
# decision that reduces a held SPY position still sells it, however small the
# cut, exactly like any other name. With held 400 and desired 0.4 (200 shares
# at equity 100000, price 200) the sell must be the 200-share excess, not the
# whole position. This is the SIMULATOR's unresolved partial-cut defect: the
# integrated `plan_funded` sells 400 when `index_eligible=False` because it
# drops ineligible SPY from the wanted set entirely, so the whole holding looks
# like excess. The assertion stays red until the simulator corrects it and is
# deliberately NOT marked xfail, so the defect remains a visible failure.
def test_risk_cut_sells_of_held_spy_are_permitted_without_index_eligibility():
    plan = plan_funded(
        _decision({SPY: 0.4}),
        held={SPY: 400.0},
        prices={SPY: 200.0},
        equity=100000.0,
        cash=20000.0,
        index_eligible=False,
    )
    spy_sells = [o.qty for o in plan.orders if o.side == "sell" and o.symbol == SPY]
    assert spy_sells == [200.0]


# --------------------------------------------------------------------------
# Projection: the post-fee reference NAV
# --------------------------------------------------------------------------


# The projected cash and the executable weights must be fractions of the
# post-fee reference NAV - the account value after the fill's fees have been
# paid - never of the pre-fee equity. With cash=equity=100000, a 0.4 target in
# a 100 stock and 10 bps, the 40000 buy costs 40 in fees: cash lands at 59960
# and the reference NAV at 99960, so the projected cash fraction is 59960/99960
# and the executable T0 weight 40000/99960. The integrated source references
# the post-fee NAV, so the check passes unmarked.
def test_projected_cash_uses_the_post_fee_reference_nav():
    plan = plan_funded(
        _decision({"T0": 0.4}),
        held={},
        prices={"T0": 100.0},
        equity=100000.0,
        cash=100000.0,
        cost_bps=COST_BPS,
    )
    buy = 0.4 * 100000.0
    fee = buy * COST_BPS / 1e4
    cash_after = 100000.0 - buy - fee
    nav_after = cash_after + buy
    assert plan.cash == pytest.approx(cash_after / nav_after)
    assert plan.executable["T0"] == pytest.approx(buy / nav_after)


# CASH is a display asset, never an order: it appears nowhere in the plan's
# orders, desired or executable. (The projected cash fraction itself is
# asserted against the post-fee reference NAV by the test above.)
def test_cash_is_a_display_asset_never_an_order():
    plan = plan_funded(
        _decision({"T0": 0.3}),
        held={"T0": 0.5},
        prices={"T0": 100.0},
        equity=100.0,
        cash=50.0,
    )
    for order in plan.orders:
        assert order.symbol != "CASH"
    assert "CASH" not in plan.desired
    assert "CASH" not in plan.executable


# --------------------------------------------------------------------------
# Unavailable NAV when a held valuation is missing
# --------------------------------------------------------------------------


# A blocked plan cannot be valued, so it must not emit a fabricated numeric
# projected cash (0.0 reads as "100% cash") as if the position were worthless:
# the projected NAV is unavailable. The integrated source reports `cash=None`
# on a blocked plan, so the check passes unmarked.
def test_blocked_plan_reports_unavailable_nav_not_a_fabricated_cash():
    plan = plan_funded(
        _decision({"T0": 0.5}),
        held={"T0": 1.0},
        prices={},
        equity=100.0,
        cash=50.0,
    )
    assert plan.blocked
    assert plan.cash is None


# A held name that loses its price mid-run must not be liquidated, filled at a
# made-up price, or turned into a fabricated loss and recovery: the optional
# funded path's guards keep the actual shares and mark the session's NAV and
# return explicitly unavailable. This is the public boundary the funded
# `simulate.run` enforces; the private `_Book.equity` helper keeps its
# priced-only default for the incumbent path (frozen 2693-session behaviour)
# and is deliberately not the boundary this contract pins.
def test_funded_run_keeps_shares_and_reports_unavailable_nav_on_missing_price():
    panel, report, benchmarks = _synthetic_run_inputs(missing_from=225)
    result = simulate.run(
        report,
        config=None,
        rebalance=20,
        cost_bps=10,
        use_exits=True,
        funded_allocation=True,
        allocation_policy="vol",
        index_eligible=True,
        benchmark_prices=benchmarks,
    )
    trace = result.trace
    assert trace is not None
    missing = [e for e in trace if e.get("unavailable")]
    assert missing, "the run must actually hold a name whose price goes missing"
    # Unavailable NAV: every session with a missing held price names the symbol
    # and the run's equity/return on the fill date are NaN - never a fabricated
    # number from valuing the position at zero.
    for entry in missing:
        assert "N0" in entry["unavailable"]
        assert entry["shares_before"].get("N0", 0.0) > 0
        fill_row = int(np.searchsorted(panel.dates, np.datetime64(entry["fill_date"])))
        assert np.isnan(result.equity[fill_row])
        assert np.isnan(result.returns[fill_row])
    # No fictitious liquidation, fill, loss or recovery: the held shares are
    # retained unchanged across every missing session, no N0 sell or fill is
    # recorded, and the actual shares are still held at the end of the run.
    kept = missing[0]["shares_before"]["N0"]
    for entry in missing:
        assert entry["shares_after"].get("N0", 0.0) == pytest.approx(kept)
        assert entry["deltas"].get("N0") is None
        assert "N0" not in entry["fills"]
    assert trace[-1]["shares_after"].get("N0", 0.0) == pytest.approx(kept)
    # Evaluation rejects missing evaluated returns: an evaluator that requires
    # every evaluated session to be finite (the fixed-run scorecard's own guard)
    # refuses this series rather than scoring a session it cannot value.
    evaluated = result.returns
    assert not np.isfinite(evaluated).all()
    with pytest.raises(ValueError, match="finite"):
        _reject_nonfinite_returns(evaluated)


# --------------------------------------------------------------------------
# Benchmark dates: the contract calendar
# --------------------------------------------------------------------------


# The contract benchmark context is {"dates", "SPY", "QQQ"} on the exact panel
# calendar, so a context whose dates do not match the calendar must be rejected
# (non-ascending or NaT dates are not a calendar). The integrated
# validate_benchmarks validates the dates against the panel calendar, so the
# check passes unmarked.
def test_benchmark_dates_must_match_the_panel_calendar():
    panel, report, benchmarks = _synthetic_run_inputs()
    reversed_dates = dict(benchmarks)
    reversed_dates["dates"] = np.array(benchmarks["dates"][::-1])
    with pytest.raises(ValueError, match="dates"):
        funded_execution.validate_benchmarks(panel, reversed_dates)


# A non-ascending decision calendar is a caller error at the pure decision's
# own boundary: the decision refuses to guess an order it cannot trust.
def test_allocation_decision_rejects_a_non_ascending_calendar():
    px, tickers = _price_matrix()
    dates = _dates(len(px))
    bad = dates.copy()
    bad[10] = bad[9]
    with pytest.raises(ValueError, match="strictly ascending"):
        allocation.decide(
            bad,
            px,
            tickers,
            20,
            desired={"AAA": 0.1},
            held={},
            regime_cap=1.0,
            event_cap=1.0,
            policy=allocation.POLICY_VOL,
        )


# The decision uses only rows through t, so changing or removing future price
# rows - a future gap, however large - cannot change an earlier decision.
def test_future_price_rows_do_not_change_an_earlier_decision():
    px, tickers = _price_matrix()
    dates = _dates(len(px))
    t = 60
    base = allocation.decide(
        dates,
        px,
        tickers,
        t,
        desired={"AAA": 0.3, "BBB": 0.2},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=allocation.POLICY_VOL,
    )
    future = px.copy()
    future[t + 1 :] = np.nan
    gapped = allocation.decide(
        dates,
        future,
        tickers,
        t,
        desired={"AAA": 0.3, "BBB": 0.2},
        held={},
        regime_cap=1.0,
        event_cap=1.0,
        policy=allocation.POLICY_VOL,
    )
    assert gapped.desired_weights == base.desired_weights
    assert gapped.available == base.available


# --------------------------------------------------------------------------
# Decision causality and the run-level trace
# --------------------------------------------------------------------------


# The funded walk decides on t's close and fills at t+1's open; every trace
# row must name the next session as its fill date, and every traded row must
# agree on the shares it moved and never carry negative cash or shares.
def test_funded_run_fills_at_the_next_open_and_conserves_every_session():
    panel, report, benchmarks = _synthetic_run_inputs()
    result = simulate.run(
        report,
        config=None,
        rebalance=20,
        cost_bps=10,
        use_exits=True,
        funded_allocation=True,
        allocation_policy="vol",
        index_eligible=True,
        benchmark_prices=benchmarks,
    )
    assert result.trace is not None
    traded = [e for e in result.trace if e["notional_traded"] > 0]
    assert traded, "the run must actually trade to be an acceptance path"
    for entry in result.trace:
        idx = int(np.searchsorted(panel.dates, np.datetime64(entry["decision_date"])))
        assert entry["fill_date"] == str(panel.dates[idx + 1])
        assert entry["cash_after"] >= -1e-9
        assert all(v >= -1e-9 for v in entry["shares_after"].values())
        for symbol, delta in entry["deltas"].items():
            before = entry["shares_before"].get(symbol, 0.0)
            after = entry["shares_after"].get(symbol, 0.0)
            assert delta == pytest.approx(after - before, abs=1e-9)
        sells = [s for s, d in entry["deltas"].items() if d < 0]
        buys = [s for s, d in entry["deltas"].items() if d > 0]
        if sells and not buys:
            # A sale-only day always credits the proceeds to cash.
            assert entry["cash_after"] >= entry["cash_before"] - 1e-9
        if buys and not sells:
            # A buy-only day may spend only cash already on hand.
            assert entry["cash_after"] <= entry["cash_before"] + 1e-9


# The run-level trace must record at least one full exit: a name that was held
# and is sold to zero, so the acceptance path exercises exits, not only buys
# and holds. When N0's grade drops to zero mid-run the daily decision stops
# wanting it and the walk sells it out completely; the symbol then appears in
# the trace union (held before, absent after).
def test_a_full_exit_appears_in_the_run_trace_union():
    panel, report, benchmarks = _synthetic_run_inputs()
    report.graded.grades[120:, 0] = 0
    report.scores = report.graded.grades.astype(float)
    result = simulate.run(
        report,
        config=None,
        rebalance=20,
        cost_bps=10,
        use_exits=True,
        funded_allocation=True,
        allocation_policy="vol",
        index_eligible=True,
        benchmark_prices=benchmarks,
    )
    assert result.trace is not None
    ever: set[str] = set()
    for entry in result.trace:
        ever |= set(entry["shares_before"]) | set(entry["shares_after"])
    final = {
        s
        for s in result.trace[-1]["shares_after"]
        if result.trace[-1]["shares_after"][s] > 0
    }
    assert ever - final, "the funded walk must fully exit a held name"
    full_exits = [
        (symbol, entry["decision_date"])
        for entry in result.trace
        for symbol in entry["shares_before"]
        if entry["deltas"].get(symbol, 0.0) < 0
        and entry["shares_after"].get(symbol, 0.0) <= 1e-12
    ]
    assert full_exits, "a full exit must appear in the trace union as a sell to zero"


# --------------------------------------------------------------------------
# Unadopted actions unchanged / preview cannot place orders
# --------------------------------------------------------------------------


# A FundedPlan is a pure preview of the full candidate: building it mutates
# neither the decision nor the caller's inputs, and no book changes until an
# explicit fill is requested. This proves plan_funded itself is pure data and
# places no orders by constructing it; it is NOT evidence that the paper
# account's full submission path never sends an order, which only a broker
# integration test can show.
def test_plan_funded_is_pure_and_a_preview_places_no_orders():
    held = {"T0": 1.0}
    prices = {"T0": 100.0}
    held_before, prices_before = dict(held), dict(prices)
    book = _book(50.0, [1.0])
    plan = plan_funded(
        _decision({"T0": 0.5}),
        held=held,
        prices=prices,
        equity=100.0,
        cash=50.0,
    )
    assert held == held_before
    assert prices == prices_before
    # Constructing the plan and reading its candidate did nothing to the book.
    assert book.cash == 50.0
    assert book.shares[0] == 1.0
    # The plan is data: no side effect, no order recorded anywhere.
    assert isinstance(plan.orders, tuple)
    book.funded_order(plan)
    assert book.cash == 50.0
    assert book.shares[0] == 1.0


# An index inside the desired stock composition is a caller error at the
# shared boundary; the decision rejects it rather than silently reshaping it.
def test_decision_rejects_an_index_in_desired():
    px, tickers = _price_matrix()
    for banned in (SPY, QQQ):
        with pytest.raises(ValueError, match="desired must be stock-only"):
            allocation.decide(
                _dates(len(px)),
                px,
                tickers,
                len(px) - 1,
                desired={banned: 0.1},
                held={},
                regime_cap=1.0,
                event_cap=1.0,
                policy=allocation.POLICY_VOL,
            )


# --------------------------------------------------------------------------
# Synthetic inputs shared by the run-level tests
# --------------------------------------------------------------------------


# A panel of six names plus SPY over 230 sessions, prices low enough that a
# unit account can actually buy fractional shares, plus a separate QQQ history.
# The benchmark context carries explicit dates on the contract's exact panel
# calendar ({"dates", "SPY", "QQQ"}).
def _synthetic_run_inputs(missing_from: int | None = None):
    """Return (panel, report, benchmark_prices) for a funded allocation run.

    `missing_from`, when set, removes N0's price from that row to the end of
    the panel (open/high/low/close/adj_close all NaN), so a funded walk can be
    driven through a held name whose valuation disappears.
    """
    rows, names = 230, 6
    rng = np.random.default_rng(3)
    steps = rng.normal(loc=0.0005, scale=0.01, size=(rows, names))
    close = 4.0 * np.exp(np.cumsum(steps, axis=0))
    if missing_from is not None:
        close[missing_from:, 0] = np.nan
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(rows)],
        dtype="datetime64[D]",
    )
    tickers = tuple(f"N{i}" for i in range(names - 1)) + ("SPY",)
    panel = Panel(
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
    grades = np.zeros((rows, names), dtype=int)
    grades[:, 0] = 3
    grades[:, 1] = 2
    grades[:, 2] = 1
    graded = Graded(grades=grades, votes=grades.astype(float).copy(), stances={})
    states = [
        RegimeState(
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
            exposure=1.0,
            flags=(),
            tightening=False,
        )
    ] * rows
    report = SimpleNamespace(
        panel=panel,
        graded=graded,
        scores=grades.astype(float),
        regime=SimpleNamespace(states=states),
        sides={f"N{i}": "ai" for i in range(names - 1)},
        book=[],
    )
    spy = close[:, names - 1]
    benchmarks = {
        "dates": dates,
        "SPY": spy.copy(),
        "QQQ": spy.copy() * 0.95,
    }
    return panel, report, benchmarks


# A 120-session rising-then-alternating price matrix for the pure decision.
def _price_matrix():
    """Return (T, N) prices and tickers with SPY and QQQ present."""
    n = 120
    pattern = np.where(np.arange(n - 1) % 2 == 0, 0.01, -0.01)
    out = np.empty((n, 4))
    for col in range(4):
        out[0, col] = 100.0
        for row in range(n - 1):
            out[row + 1, col] = out[row, col] * (1.0 + pattern[row])
    return out, ["AAA", "BBB", SPY, QQQ]


# Consecutive session dates for a decision horizon.
def _dates(n: int) -> np.ndarray:
    """Return `n` consecutive datetime64[D] session dates from 2020-01-01."""
    base = date(2020, 1, 1)
    return np.array([base + timedelta(days=i) for i in range(n)], dtype="datetime64[D]")


# The fixed-run evaluation's own guard, kept here so the acceptance path proves
# the property rather than quoting it: a candidate is only scored when every
# evaluated return is finite and above -100%, so a session that cannot be
# valued is rejected outright - never silently treated as a flat zero or a
# fabricated loss.
def _reject_nonfinite_returns(returns: np.ndarray) -> None:
    """Raise ValueError if any evaluated return is missing or below -100%."""
    values = np.asarray(returns, dtype=float)
    if not len(values) or not np.isfinite(values).all() or (values <= -1.0).any():
        raise ValueError("Every evaluated return must be finite and above -100%")
