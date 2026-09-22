"""The funded-allocation paper path, exercised through the real paper.plan.

These tests call `paper.plan` with an `allocation_context` - the same public
function the nightly calls on the incumbent path - and drive the settlement
journal (`paper.settle` / `paper.apply_settlements`) between sessions, saving
and reading state in a temp directory exactly as the live state file is
written. Nothing here mocks the decision or the planner: the inputs are a real
price matrix and real holdings.

Scenarios pinned: the incumbent default path is unchanged; the first funded
plan persists the stable selection and serializes the allocation_plan payload
with adopted False; state survives save/load; a scheduled rebalance refreshes
the selection while a risk-only cut does not; a genuine company exit updates
composition at the next rebalance; an explicit `excluded_symbols` exit removes
a held name on an ordinary day, persists the removal with no resurrection
next daily plan, and leaves the remaining composition and its risk recovery
intact; the produced payload survives the shared allocation_view serializer
with current and projected as fractions of the account's own NAV; unresolved
pending orders block the next plan and are never duplicated; partial and
rejected fills are reconciled from actual holdings and cash; a missing held
price blocks explicitly; risk cuts carry priority metadata; buys are held to
whole shares and existing cash after fees; SPY is exempt from the name cap
only under explicit index eligibility; and legacy state JSON without the
allocation fields loads identically.
"""

import json
from dataclasses import asdict

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.agents.trading.desk.allocation import SPY
from backend.agents.trading.desk.paper_allocation import AllocationContext

ROWS = 220


# A decision calendar that ends exactly at the session being planned.
def _ending_dates(session: str, n: int = ROWS) -> np.ndarray:
    """Return `n` consecutive datetime64[D] dates ending at `session`."""
    end = np.datetime64(session, "D")
    start = end - np.timedelta64(n - 1, "D")
    return start + np.arange(n).astype("timedelta64[D]")


# A constant price matrix: zero volatility means no risk scaling, so the
# decision is the pure capped selection plus the SPY residual - deterministic
# whole-share quantities at a $100 price.


def _context(
    session="2026-09-04",
    policy="vol",
    index_eligible=True,
    desired=None,
    regime_cap=1.0,
    event_cap=1.0,
    cost_bps=10.0,
    dates=None,
    prices=None,
    tickers=None,
    t=None,
    excluded_symbols=frozenset(),
):
    """Return a funded AllocationContext whose decision date is `session`."""
    dates = dates if dates is not None else _ending_dates(session)
    prices = prices if prices is not None else np.full((ROWS, 5), 100.0)
    tickers = tickers if tickers is not None else ["AAA", "BBB", "CCC", SPY, "QQQ"]
    return AllocationContext(
        policy=policy,
        index_eligible=index_eligible,
        dates=dates,
        prices=prices,
        tickers=tickers,
        t=t if t is not None else len(dates) - 1,
        regime_cap=regime_cap,
        event_cap=event_cap,
        desired_stock_weights=(
            desired if desired is not None else {"AAA": 0.15, "BBB": 0.15}
        ),
        cost_bps=cost_bps,
        excluded_symbols=excluded_symbols,
    )


# Build the pending rows the nightly writes for a plan's orders.
def _pending_rows(state, orders, session):
    """Return the pending rows the nightly would write for `orders`."""
    state.pending = [
        {
            "client_order_id": o.client_order_id,
            "symbol": o.symbol,
            "side": o.side,
            "qty": int(o.qty),
            "session": session,
            "reason": o.reason,
        }
        for o in orders
    ]


# The broker report for a set of pending rows. A partial fill is reported as a
# terminal cancel (the outstanding quantity is not coming), which is how a
# concluded partial appears on the broker.
def _broker_fills(orders, partial=None, rejected=()):
    """Return a broker order list; `partial` maps id -> filled qty."""
    partial = partial or {}
    out = []
    for o in orders:
        if o.client_order_id in rejected:
            out.append(
                {
                    "client_order_id": o.client_order_id,
                    "status": "rejected",
                    "filled_qty": 0,
                    "filled_avg_price": 0.0,
                }
            )
        else:
            filled = partial.get(o.client_order_id, int(o.qty))
            out.append(
                {
                    "client_order_id": o.client_order_id,
                    "status": "filled" if filled >= int(o.qty) else "canceled",
                    "filled_qty": filled,
                    "filled_avg_price": 100.0,
                }
            )
    return out


# Run one funded day: plan, write pending, settle against the broker report,
# and fold the outcome back into the state and the actual holdings and cash.
def _day(
    session, state, equity, held, cash, ctx, partial=None, rejected=(), force=False
):
    """Return (orders, new state, updated held, updated cash, what)."""
    prices = {s: 100.0 for s in held} | {"AAA": 100.0, "BBB": 100.0, SPY: 100.0}
    orders, new, what = paper.plan(
        session,
        state,
        equity,
        held,
        prices,
        {},
        {},
        cash=cash,
        force_rebalance=force,
        allocation_context=ctx,
    )
    if orders:
        _pending_rows(new, orders, session)
        settled = paper.settle(new.pending, _broker_fills(orders, partial, rejected))
        new = paper.apply_settlements(new, settled)
        partial = partial or {}
        for o in orders:
            filled = partial.get(o.client_order_id, int(o.qty))
            if o.client_order_id in rejected:
                filled = 0
            if o.side == "buy":
                held[o.symbol] = held.get(o.symbol, 0.0) + filled
                cash -= filled * 100.0 * (1.0 + ctx.cost_bps / 1e4)
            else:
                held[o.symbol] = held.get(o.symbol, 0.0) - filled
                cash += filled * 100.0 * (1.0 - ctx.cost_bps / 1e4)
            if held[o.symbol] <= 0:
                del held[o.symbol]
    return orders, new, held, cash, what


# The incumbent path (no allocation_context) is byte-for-byte unchanged: the
# same first-rebalance plan, the same tuple shape, the same rebalance clock.
def test_incumbent_default_path_is_unchanged():
    state = paper.PaperState()
    orders, new, what = paper.plan(
        "2026-09-04",
        state,
        equity=100_000.0,
        held={"MU": 10.0},
        prices={"SNDK": 200.0, "PANW": 180.0, "MU": 150.0, "TINY": 10.0},
        targets={"SNDK": 0.076, "PANW": 0.063, "TINY": 0.001},
        grades={"SNDK": "A+", "PANW": "A+", "MU": "C", "TINY": "A"},
    )
    assert what == "rebalance"
    assert [(o.symbol, o.side, o.qty) for o in orders] == [
        ("MU", "sell", 10),
        ("SNDK", "buy", 38),
        ("PANW", "buy", 35),
    ]
    assert new.last_rebalance == "2026-09-04"
    assert new.allocation_state is None
    assert all(o.priority is None for o in orders)


# The first funded plan buys the capped selection plus the SPY residual in whole
# shares, persists the stable selection, and serializes an allocation_plan whose
# adopted flag defaults to False.
def test_first_funded_plan_persists_selection_and_payload():
    ctx = _context(index_eligible=True)
    orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert what == "allocation-rebalance"
    buys = {o.symbol: o.qty for o in orders if o.side == "buy"}
    # 15% of 100k at $100 = 150 shares each; the SPY residual rounds to 699
    # whole shares after the 10bps fee on the 100k spend.
    assert buys == {"AAA": 150, "BBB": 150, SPY: 699}
    assert all(o.qty == int(o.qty) for o in orders)
    assert new.allocation_state["stable_desired"] == {"AAA": 0.15, "BBB": 0.15}
    payload = new.allocation_state["plan"]
    assert payload["version"] == "portfolio-allocation-view/1"
    assert payload["status"] == "available"
    assert payload["adopted"] is False
    assert payload["policy"] == "vol"
    assert payload["target"]["stocks"] == 0.3
    assert payload["target"]["indexes"] == 0.7
    assert payload["current"]["cash"] == 1.0
    assert payload["rows"][SPY]["kind"] == "index"
    spy_cap = next(c for c in payload["capabilities"] if c["symbol"] == SPY)
    assert spy_cap["eligible"] is True
    assert new.last_rebalance == "2026-09-04"


# The persisted allocation state survives a save/read round-trip in a temp
# directory, exactly like the live state file.
def test_state_survives_save_and_load_in_temp_dir(tmp_path):
    ctx = _context()
    orders, new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    paper.save_state(tmp_path, new)
    loaded = paper.load_state(tmp_path)
    assert loaded.allocation_state == new.allocation_state
    assert loaded.allocation_state["stable_desired"] == {"AAA": 0.15, "BBB": 0.15}
    assert loaded.allocation_state["plan"]["status"] == "available"


# The snapshot includes the allocation_plan payload only on the funded path,
# and never rewrites an earlier session's history entry.
def test_snapshot_carries_allocation_plan_without_rewriting_history():
    ctx = _context()
    _orders, new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    entry1 = paper.snapshot(new, "2026-09-04", 100_000.0, 1.0, [])
    assert entry1["allocation_plan"]["status"] == "available"
    assert entry1["allocation_plan"]["adopted"] is False
    entry2 = paper.snapshot(new, "2026-09-07", 100_000.0, 1.0, [])
    assert [h["session"] for h in new.history] == ["2026-09-04", "2026-09-07"]
    assert "allocation_plan" in entry2


# A scheduled rebalance adopts the caller's fresh selection; between rebalances
# the persisted selection is what is decided against, so a caller change on a
# plain day is not adopted until the next rebalance.
def test_rebalance_refreshes_selection_and_daily_uses_persisted():
    ctx_full = _context(session="2026-09-04", desired={"AAA": 0.15, "BBB": 0.15})
    orders, s1, held, cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx_full
    )
    assert s1.allocation_state["stable_desired"] == {"AAA": 0.15, "BBB": 0.15}

    # A plain day whose caller selection differs must NOT adopt it - the stable
    # selection is refreshed only on a scheduled rebalance.
    ctx_changed = _context(session="2026-09-07", desired={"AAA": 0.15, "CCC": 0.15})
    orders2, s2, held, cash, what2 = _day(
        "2026-09-07", s1, 100_000.0, held, cash, ctx_changed
    )
    assert what2 == "allocation"
    assert s2.allocation_state["stable_desired"] == {"AAA": 0.15, "BBB": 0.15}
    # The persisted selection contains BBB, so CCC is never bought on a plain day.
    assert not any(o.symbol == "CCC" for o in orders2)

    # The next scheduled rebalance adopts the fresh selection, selling the
    # exited BBB. Its proceeds are NOT spendable the same day (no pending-sale
    # proceeds), so CCC is bought only once that cash has settled.
    forced = _context(session="2026-09-08", desired={"AAA": 0.15, "CCC": 0.15})
    cash_before_refresh = cash
    orders3, s3, held, cash, what3 = _day(
        "2026-09-08", s2, 100_000.0, held, cash, forced, force=True
    )
    assert what3 == "allocation-rebalance"
    assert s3.allocation_state["stable_desired"] == {"AAA": 0.15, "CCC": 0.15}
    assert any(o.symbol == "BBB" and o.side == "sell" for o in orders3)
    # Prior settled cap trims can leave spendable cash; this session's BBB
    # proceeds still cannot fund any part of the buy basket.
    assert (
        sum(o.qty * 100.0 * 1.001 for o in orders3 if o.side == "buy")
        <= cash_before_refresh + 1e-8
    )
    # Once the exit sale has settled, the cash is real and CCC is bought.
    orders4, s4, held, cash, what4 = _day(
        "2026-09-09",
        s3,
        100_000.0,
        held,
        cash,
        _context(session="2026-09-09", desired={"AAA": 0.15, "CCC": 0.15}),
    )
    assert what4 == "allocation"
    assert s4.allocation_state["stable_desired"] == {"AAA": 0.15, "CCC": 0.15}
    assert any(o.symbol == "CCC" and o.side == "buy" for o in orders4)


# A genuine company exit (a name leaving the caller's selection) updates the
# composition at the next rebalance: the name is dropped from the stable
# selection and sold.
def test_genuine_company_exit_updates_composition():
    ctx_full = _context(session="2026-09-04", desired={"AAA": 0.15, "BBB": 0.15})
    orders1, s1, held, cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx_full
    )
    # A rebalance day whose selection drops BBB is a genuine exit.
    ctx_exit = _context(session="2026-09-05", desired={"AAA": 0.15})
    orders2, s2, held, cash, what2 = _day(
        "2026-09-05", s1, 100_000.0, held, cash, ctx_exit, force=True
    )
    assert what2 == "allocation-rebalance"
    assert s2.allocation_state["stable_desired"] == {"AAA": 0.15}
    assert any(o.symbol == "BBB" and o.side == "sell" for o in orders2)


# A risk-only cut reduces exposure but never loses the names to re-enter: the
# stable selection is untouched and the sells carry risk-cut priority metadata.
def test_risk_only_cut_keeps_composition_and_marks_priority():
    ctx_full = _context(session="2026-09-04", desired={"AAA": 0.15, "BBB": 0.15})
    orders1, s1, held, cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx_full
    )
    ctx_cut = _context(
        session="2026-09-07", desired={"AAA": 0.15, "BBB": 0.15}, event_cap=0.2
    )
    orders2, s2, held, cash, what2 = _day(
        "2026-09-07", s1, 100_000.0, held, cash, ctx_cut
    )
    assert what2 == "allocation"
    assert s2.allocation_state["stable_desired"] == {"AAA": 0.15, "BBB": 0.15}
    cuts = [o for o in orders2 if o.side == "sell"]
    assert cuts
    for o in cuts:
        assert o.priority == "event cap"
        assert "risk reduction" in o.reason
    # After the cut settles, the names are still there to re-enter.
    ctx_full2 = _context(session="2026-09-08", desired={"AAA": 0.15, "BBB": 0.15})
    orders3, s3, held, cash, _what = _day(
        "2026-09-08", s2, 100_000.0, held, cash, ctx_full2
    )
    assert any(o.symbol in ("AAA", "BBB") and o.side == "buy" for o in orders3)


# Unresolved pending orders block the next plan explicitly, never duplicating
# them and never assuming a cancellation.
def test_unresolved_pending_orders_block_the_next_plan():
    ctx = _context()
    orders, new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert orders
    _pending_rows(new, orders, "2026-09-04")
    # The broker reports the day's orders still working, so they stay pending.
    working = [
        {
            "client_order_id": o.client_order_id,
            "status": "new",
            "filled_qty": 0,
            "filled_avg_price": 0.0,
        }
        for o in orders
    ]
    new = paper.apply_settlements(new, paper.settle(new.pending, working))
    assert new.pending  # still open
    orders2, s2, what2 = paper.plan(
        "2026-09-07",
        new,
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert what2 == "allocation-blocked"
    assert orders2 == []
    assert s2.allocation_state["plan"]["status"] == "blocked"
    assert "pending" in s2.allocation_state["plan"]["reason"]
    # The pending order ids are named, and no duplicate was created.
    assert s2.pending == new.pending


# Planning the same session twice submits nothing the second time, funded or not.
def test_same_session_is_never_planned_twice():
    ctx = _context()
    orders1, s1, _held, _cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx
    )
    again, same, why = paper.plan(
        "2026-09-04",
        s1,
        100_000.0,
        {},
        {"AAA": 100.0, "BBB": 100.0},
        {},
        {},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert again == []
    assert why == "already planned for this session"
    assert same is s1


# A partial fill is reconciled from the actual holdings and cash: the next plan
# sizes against what the broker actually delivered, not the written-down order.
def test_partial_fill_is_reconciled_from_actual_holdings():
    ctx = _context()
    orders, new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    _pending_rows(new, orders, "2026-09-04")
    # AAA half-fills at the open; the rest is still working.
    partial = {orders[0].client_order_id: 50}
    settled = paper.settle(new.pending, _broker_fills(orders, partial=partial))
    new = paper.apply_settlements(new, settled)
    held = {}
    cash = 100_000.0
    for o in orders:
        filled = partial.get(o.client_order_id, int(o.qty))
        held[o.symbol] = held.get(o.symbol, 0.0) + filled
        cash -= filled * 100.0 * (1.0 + ctx.cost_bps / 1e4)
    assert held["AAA"] == 50.0
    assert any(e["status"] == "partial" for e in new.journal)
    # The next plan still wants the rest of AAA and sizes from actual holdings.
    ctx_next = _context(session="2026-09-05")
    orders2, s2, what2 = paper.plan(
        "2026-09-05",
        new,
        equity=100_000.0,
        held=held,
        prices={"AAA": 100.0, "BBB": 100.0, SPY: 100.0},
        targets={},
        grades={},
        cash=cash,
        allocation_context=ctx_next,
    )
    assert what2 == "allocation"
    assert any(o.symbol == "AAA" and o.side == "buy" for o in orders2)
    # No duplicate: the partially-filled order id is already in the journal.
    assert not any(o.client_order_id == orders[0].client_order_id for o in orders2)


# A rejected order is retried from actual holdings: the journal records it dead
# and the next plan sizes the same move again from the unchanged holdings.
def test_rejected_order_is_retried():
    ctx = _context()
    orders, new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    _pending_rows(new, orders, "2026-09-04")
    rejected = {orders[1].client_order_id}
    settled = paper.settle(new.pending, _broker_fills(orders, rejected=rejected))
    new = paper.apply_settlements(new, settled)
    held = {}
    cash = 100_000.0
    for o in orders:
        if o.client_order_id in rejected:
            continue
        held[o.symbol] = held.get(o.symbol, 0.0) + int(o.qty)
        cash -= int(o.qty) * 100.0 * (1.0 + ctx.cost_bps / 1e4)
    assert "BBB" not in held
    assert any(e["status"] == "dead" for e in new.journal)
    # The next plan retries BBB from the actual cash on hand.
    ctx_next = _context(session="2026-09-05")
    orders2, s2, what2 = paper.plan(
        "2026-09-05",
        new,
        equity=100_000.0,
        held=held,
        prices={"AAA": 100.0, "BBB": 100.0, SPY: 100.0},
        targets={},
        grades={},
        cash=cash,
        allocation_context=ctx_next,
    )
    assert what2 == "allocation"
    assert any(o.symbol == "BBB" and o.side == "buy" for o in orders2)


# A held position with no usable price blocks the day explicitly, with no
# made-up allocation and no orders.
def test_missing_held_price_blocks_explicitly():
    dates = _ending_dates("2026-09-04")
    tickers = ["AAA", "BBB", SPY, "QQQ"]
    prices = np.full((ROWS, 4), 100.0)
    ctx = _context(session="2026-09-04", dates=dates, prices=prices, tickers=tickers)
    orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={"AAA": 100.0},
        prices={"AAA": 100.0, "BBB": 100.0, SPY: 100.0},
        targets={},
        grades={},
        cash=10_000.0,
        allocation_context=ctx,
    )
    # AAA is in the universe and priced - this sizes fine.
    assert orders
    assert any(o.symbol == "AAA" for o in orders)
    # Now AAA has no usable price anywhere: its row in the decision matrix is
    # not usable and no paper close is supplied, so the held name cannot be
    # valued and the day blocks explicitly.
    bad_prices = prices.copy()
    bad_prices[:, 0] = np.nan
    dates2 = _ending_dates("2026-09-05")
    ctx2 = _context(
        session="2026-09-05", dates=dates2, prices=bad_prices, tickers=tickers
    )
    orders2, new2, what2 = paper.plan(
        "2026-09-05",
        paper.PaperState(),
        equity=100_000.0,
        held={"AAA": 100.0},
        prices={"BBB": 100.0, SPY: 100.0},
        targets={},
        grades={},
        cash=10_000.0,
        allocation_context=ctx2,
    )
    assert what2 == "allocation-blocked"
    assert orders2 == []
    payload = new2.allocation_state["plan"]
    assert payload["status"] == "blocked"
    assert any("AAA" in message for message in payload["blocked"])
    # No made-up target for a day that could not size.
    assert payload["target"]["stocks"] is None
    assert payload["rows"]["AAA"]["current_weight"] is None


# A missing price for a held name not in the decision universe blocks too.
def test_held_name_outside_universe_blocks():
    ctx = _context()
    orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={"ZZZ": 100.0},
        prices={"ZZZ": 100.0, "AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=10_000.0,
        allocation_context=ctx,
    )
    assert what == "allocation-blocked"
    assert orders == []
    assert any("ZZZ" in message for message in new.allocation_state["plan"]["blocked"])


# A missing trend makes a vol_trend decision unavailable and the payload says
# so explicitly, instead of fabricating a target.
def test_unavailable_decision_reports_explicit_payload():
    n = 120  # complete volatility, no 200-price trend
    dates = _ending_dates("2026-09-04", n)
    tickers = ["AAA", "BBB", SPY, "QQQ"]
    prices = np.full((n, 4), 100.0)
    ctx = _context(
        session="2026-09-04",
        policy="vol_trend",
        dates=dates,
        prices=prices,
        tickers=tickers,
        t=n - 1,
    )
    orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert what == "allocation-unavailable"
    assert new.allocation_state["plan"]["status"] == "unavailable"
    assert any(
        "trend" in message for message in new.allocation_state["plan"]["missing"]
    )


# Buys are held to whole shares and to the cash actually on hand after fees.
def test_whole_shares_and_cash_respected_after_rounding():
    ctx = _context(cost_bps=50.0)
    orders, new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=50_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=30_000.0,
        allocation_context=ctx,
    )
    assert orders
    assert all(o.qty == int(o.qty) for o in orders)
    spend = sum(
        o.qty * 100.0 * (1.0 + ctx.cost_bps / 1e4) for o in orders if o.side == "buy"
    )
    assert spend <= 30_000.0 + 1e-6
    assert not any(o.side == "sell" for o in orders)


# SPY is exempt from the name cap only under explicit index eligibility; a
# stock is never sized above the cap.
def test_spy_exempt_from_name_cap_only_when_eligible():
    ctx = _context(index_eligible=True)
    orders, _new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    spy = next(o for o in orders if o.symbol == SPY)
    # 69.9% of equity, far above the 15% name cap, and whole shares carry it.
    assert spy.qty * 100.0 / 100_000.0 > 0.69

    not_eligible = _context(index_eligible=False)
    orders2, _new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=not_eligible,
    )
    assert not any(o.symbol == SPY for o in orders2)
    for o in orders2:
        assert o.side == "buy"
        assert o.qty * 100.0 / 100_000.0 <= paper.ENTRY_NAME_CAP + 1e-9


# The band-reversal buy blocker holds back buys for a rejecting name while
# sells and risk cuts pass regardless.
def test_band_reversal_holds_back_buys_not_risk_cuts():
    # index_eligible=False so cash stays on hand for a later buy.
    ctx_full = _context(
        session="2026-09-04", index_eligible=False, desired={"AAA": 0.05}
    )
    orders1, s1, held, cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx_full
    )
    assert held.get("AAA", 0.0) == 50.0
    assert cash > 90_000.0
    # A rebalance adopting BBB is blocked from buying it when its daily
    # rejects its upper Bollinger band; the AAA exit sell still goes.
    ctx_new = _context(
        session="2026-09-07", index_eligible=False, desired={"BBB": 0.05}
    )
    orders2, s2, what2 = paper.plan(
        "2026-09-07",
        s1,
        equity=100_000.0,
        held=held,
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=cash,
        force_rebalance=True,
        allocation_context=ctx_new,
        entry_blocked={"BBB"},
    )
    assert what2 == "allocation-rebalance"
    assert not any(o.symbol == "BBB" and o.side == "buy" for o in orders2)
    assert any(o.symbol == "AAA" and o.side == "sell" for o in orders2)
    assert any("BBB" in message for message in s2.allocation_state["plan"]["blocked"])
    # The stable selection still adopts the caller's names; only the buy is gated.
    assert s2.allocation_state["stable_desired"] == {"BBB": 0.05}


# Legacy state JSON without the allocation fields loads identically, and the
# funded path then populates them on the next plan.
def test_legacy_state_json_loads_without_allocation_fields(tmp_path):
    # 19 sessions since the last rebalance, so the next plan rebalances.
    legacy = paper.PaperState(last_rebalance="2026-08-01", sessions_since_rebalance=19)
    raw = json.dumps(asdict(legacy))
    state_path = tmp_path / "paper" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(raw, encoding="utf-8")
    loaded = paper.load_state(tmp_path)
    assert loaded.allocation_state is None
    assert loaded.last_rebalance == "2026-08-01"
    # The incumbent path treats the loaded legacy state exactly as before.
    orders, new, what = paper.plan(
        "2026-09-04",
        loaded,
        equity=100_000.0,
        held={},
        prices={"SNDK": 200.0},
        targets={"SNDK": 0.1},
        grades={"SNDK": "A+"},
    )
    assert what == "rebalance"
    assert [(o.symbol, o.side, o.qty) for o in orders] == [("SNDK", "buy", 50)]
    # And the funded path adopts the caller selection on a legacy state.
    ctx = _context()
    orders2, new2, what2 = paper.plan(
        "2026-09-04",
        loaded,
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert what2 == "allocation-rebalance"
    assert new2.allocation_state["stable_desired"] == {"AAA": 0.15, "BBB": 0.15}


# A fractional holding that whole shares cannot sell fully is reported as a
# blocked residual while the sellable whole shares still go.
def test_fractional_residual_after_whole_share_rounding_is_reported():
    # AAA is held but no longer in the selection, so it is exited; the 0.6-share
    # remainder that whole shares cannot sell is reported as blocked.
    ctx = _context(desired={"BBB": 0.15})
    orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={"AAA": 1.6},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert what == "allocation-blocked"
    assert any(o.symbol == "AAA" and o.side == "sell" and o.qty == 1 for o in orders)
    assert any("AAA" in message for message in new.allocation_state["plan"]["blocked"])


# A blocked attempt does not mark the session as planned, so once the pending
# orders resolve the same session is retried instead of being skipped.
def test_blocked_session_is_retryable_after_pending_resolves():
    ctx = _context(session="2026-09-04")
    orders, new, _what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    _pending_rows(new, orders, "2026-09-04")
    working = [
        {
            "client_order_id": o.client_order_id,
            "status": "new",
            "filled_qty": 0,
            "filled_avg_price": 0.0,
        }
        for o in orders
    ]
    new = paper.apply_settlements(new, paper.settle(new.pending, working))
    assert new.pending
    # The next session is blocked by the outstanding orders and not marked seen.
    ctx_next = _context(session="2026-09-07")
    orders2, s2, what2 = paper.plan(
        "2026-09-07",
        new,
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx_next,
    )
    assert what2 == "allocation-blocked"
    assert "2026-09-07" not in s2.sessions_seen
    # Once the orders settle, the same blocked session proceeds instead of
    # being reported as already planned.
    filled = [
        {
            "client_order_id": o.client_order_id,
            "status": "filled",
            "filled_qty": int(o.qty),
            "filled_avg_price": 100.0,
        }
        for o in orders
    ]
    s2 = paper.apply_settlements(s2, paper.settle(s2.pending, filled))
    assert not s2.pending
    orders3, s3, what3 = paper.plan(
        "2026-09-07",
        s2,
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx_next,
    )
    assert what3 != "allocation-blocked"
    assert "2026-09-07" in s3.sessions_seen


# A context whose decision date is in the future of the session it is used for
# is rejected: a later matrix mark must never value an earlier session.
def test_future_decision_context_is_rejected():
    dates = _ending_dates("2026-09-04")
    prices = np.full((ROWS, 5), 100.0)
    past = _context(session="2026-09-04", dates=dates, prices=prices)
    orders, _new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=past,
    )
    assert what == "allocation-rebalance"
    future_dates = np.datetime64("2026-09-04") + np.arange(ROWS).astype(
        "timedelta64[D]"
    )
    future = _context(dates=future_dates, prices=prices)
    orders2, new2, what2 = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=future,
    )
    assert what2 == "allocation-blocked"
    assert orders2 == []
    assert new2.allocation_state["plan"]["status"] == "blocked"


# An intentionally empty selection (a deliberate all-cash target) is preserved
# between rebalances and is not replaced by the caller's daily selection.
def test_explicit_empty_selection_is_preserved_between_rebalances():
    ctx_empty = _context(desired={})
    _orders, s1, what1 = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx_empty,
    )
    assert what1 == "allocation-rebalance"
    assert s1.allocation_state["stable_desired"] == {}
    # A plain day whose caller passes a full selection must not adopt it.
    ctx_full = _context(session="2026-09-07", desired={"AAA": 0.15})
    orders2, s2, what2 = paper.plan(
        "2026-09-07",
        s1,
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx_full,
    )
    assert what2 == "allocation"
    assert s2.allocation_state["stable_desired"] == {}
    assert not any(o.symbol == "AAA" and o.side == "buy" for o in orders2)


# An explicit excluded_symbols exit removes a held name on an ordinary day -
# not waiting for a scheduled rebalance - persists the removal so the next
# daily plan cannot resurrect it, and leaves the remaining composition alone.
def test_excluded_symbols_remove_held_name_on_ordinary_day():
    ctx_full = _context(session="2026-09-04", desired={"AAA": 0.15, "BBB": 0.15})
    orders1, s1, held, cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx_full
    )
    assert held.get("BBB", 0.0) > 0.0
    # An ordinary day whose caller selection still lists BBB, but whose context
    # names BBB as an explicit company exit. The name is dropped from the
    # stable composition before the decision and sold that same day.
    ctx_exit = _context(
        session="2026-09-07",
        desired={"AAA": 0.15, "BBB": 0.15},
        excluded_symbols=frozenset({"BBB"}),
    )
    orders2, s2, held, cash, what2 = _day(
        "2026-09-07", s1, 100_000.0, held, cash, ctx_exit
    )
    assert what2 == "allocation"
    assert any(o.symbol == "BBB" and o.side == "sell" for o in orders2)
    # The removal is persisted: BBB leaves the stable selection now, on the
    # ordinary day, and the remaining AAA composition is untouched.
    assert s2.allocation_state["stable_desired"] == {"AAA": 0.15}
    assert held.get("BBB", 0.0) == 0.0
    # The next daily plan - whose caller still lists BBB with no exclusion -
    # must not resurrect it: the persisted selection no longer has BBB.
    ctx_full2 = _context(session="2026-09-08", desired={"AAA": 0.15, "BBB": 0.15})
    orders3, s3, held, cash, what3 = _day(
        "2026-09-08", s2, 100_000.0, held, cash, ctx_full2
    )
    assert what3 == "allocation"
    assert s3.allocation_state["stable_desired"] == {"AAA": 0.15}
    assert not any(o.symbol == "BBB" and o.side == "buy" for o in orders3)


# A risk-only cut after an explicit exit keeps the remaining composition for
# re-entry: the persisted selection still holds the non-excluded names, and
# once the ceiling lifts they are bought back.
def test_excluded_symbols_keep_remaining_composition_for_risk_recovery():
    ctx_full = _context(session="2026-09-04", desired={"AAA": 0.15, "BBB": 0.15})
    orders1, s1, held, cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx_full
    )
    ctx_exit = _context(
        session="2026-09-07",
        desired={"AAA": 0.15, "BBB": 0.15},
        excluded_symbols=frozenset({"BBB"}),
    )
    _orders, s2, held, cash, _what = _day(
        "2026-09-07", s1, 100_000.0, held, cash, ctx_exit
    )
    assert s2.allocation_state["stable_desired"] == {"AAA": 0.15}
    # An event-cap risk cut on the remaining names: sells carry the binding
    # constraint and the composition is untouched, so AAA is there to re-enter.
    ctx_cut = _context(
        session="2026-09-08",
        desired={"AAA": 0.15, "BBB": 0.15},
        event_cap=0.2,
    )
    orders3, s3, held, cash, what3 = _day(
        "2026-09-08", s2, 100_000.0, held, cash, ctx_cut
    )
    assert what3 == "allocation"
    cuts = [o for o in orders3 if o.side == "sell"]
    assert cuts
    for o in cuts:
        assert o.priority == "event cap"
        assert "risk reduction" in o.reason
    assert s3.allocation_state["stable_desired"] == {"AAA": 0.15}
    # Once the ceiling lifts, AAA is bought back from the retained composition.
    ctx_full2 = _context(session="2026-09-09", desired={"AAA": 0.15, "BBB": 0.15})
    orders4, s4, held, cash, what4 = _day(
        "2026-09-09", s3, 100_000.0, held, cash, ctx_full2
    )
    assert what4 == "allocation"
    assert s4.allocation_state["stable_desired"] == {"AAA": 0.15}
    assert any(o.symbol == "AAA" and o.side == "buy" for o in orders4)
    assert not any(o.symbol == "BBB" for o in orders4)


# The produced allocation_plan survives the shared allocation_view serializer
# on an ordinary day with real holdings: current and projected are fractions
# of the account's own NAV (marked positions plus cash), so each bucket totals
# one and the rows agree with the buckets it claims to detail.
def test_funded_plan_payload_survives_allocation_view_serializer():
    from backend.market.allocation_view import serialize

    ctx = _context()
    orders1, s1, held, cash, _what = _day(
        "2026-09-04", paper.PaperState(), 100_000.0, {}, 100_000.0, ctx
    )
    assert held.get("AAA", 0.0) > 0.0
    held_before, cash_before = dict(held), cash
    orders2, s2, held, cash, what2 = _day(
        "2026-09-07", s1, 100_000.0, held, cash, _context(session="2026-09-07")
    )
    assert what2 == "allocation"
    payload = s2.allocation_state["plan"]
    # The projected stage is fractions of the post-fee NAV of the actual
    # filtered basket: cash after the basket's fees plus the remaining marked
    # positions. Recompute that NAV from the basket and assert the payload
    # carries exactly its fractions.
    price = {s: 100.0 for s in ("AAA", "BBB", SPY)}
    cost = ctx.cost_bps / 1e4
    cash_after = cash_before
    for o in orders2:
        if o.side == "buy":
            cash_after -= o.qty * price[o.symbol] * (1.0 + cost)
        else:
            cash_after += o.qty * price[o.symbol] * (1.0 - cost)
    remaining = dict(held_before)
    for o in orders2:
        remaining[o.symbol] = remaining.get(o.symbol, 0.0) + (
            o.qty if o.side == "buy" else -o.qty
        )
    remaining = {s: q for s, q in remaining.items() if q > 1e-9}
    nav = cash_after + sum(q * price[s] for s, q in remaining.items())
    assert nav > 0
    projected = payload["projected"]
    assert projected["cash"] == pytest.approx(cash_after / nav)
    assert projected["stocks"] + projected["indexes"] + projected[
        "cash"
    ] == pytest.approx(1.0, abs=1e-9)
    current = payload["current"]
    assert current["stocks"] + current["indexes"] + current["cash"] == pytest.approx(
        1.0, abs=1e-9
    )
    # The rows agree with the buckets they detail, and the whole payload
    # survives the shared serializer as an available preview.
    assert projected["stocks"] == pytest.approx(
        sum(
            r["projected_weight"]
            for r in payload["rows"].values()
            if r["kind"] == "stock"
        )
    )
    rendered = serialize(payload, session="2026-09-07")
    assert rendered["status"] == "available"
    assert rendered["projected"] == projected


# An explicit exit can also be expressed as a dict context, not only the
# dataclass, and its removal is normalized before the decision.
def test_excluded_symbols_work_through_a_dict_context():
    ctx = dict(
        policy="vol",
        index_eligible=True,
        dates=_ending_dates("2026-09-04"),
        prices=np.full((ROWS, 5), 100.0),
        tickers=["AAA", "BBB", "CCC", SPY, "QQQ"],
        t=ROWS - 1,
        regime_cap=1.0,
        event_cap=1.0,
        desired_stock_weights={"AAA": 0.15, "BBB": 0.15},
        cost_bps=10.0,
        excluded_symbols=["BBB"],
    )
    _orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 100.0},
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx,
    )
    assert what == "allocation-rebalance"
    # The exit is applied to the freshly adopted selection on the rebalance:
    # BBB never enters the persisted composition.
    assert new.allocation_state["stable_desired"] == {"AAA": 0.15}
    assert not any(o.symbol == "BBB" for o in _orders)
