"""Edge cases in the funded paper allocation path, beyond the main suite.

These pin the lifecycle and explicit-exit boundary behaviors through the real
`paper.plan` with settlement and retry journeys: an explicitly empty stable
selection is preserved while pending orders block the day and after they
settle (no resurrected buys, and an excluded name is not resurrected by a
pending-blocked day); missing cash is reported as missing rather than a
fabricated 0.0; an explicitly excluded held name is exited on an ordinary day
even when the policy decision is unavailable; and the account equity is
validated before sizing (a non-finite or non-positive equity blocks rather
than raising).
"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import funded_execution, paper
from backend.agents.trading.desk.allocation import SPY
from backend.agents.trading.desk.paper_allocation import AllocationContext

ROWS = 220


# An exclusion survives disk persistence and a later full selection refresh.
def test_exclusion_survives_reload_and_scheduled_refresh(tmp_path):
    ctx = _context(desired={"AAA": 0.15, "BBB": 0.15}, excluded={"AAA"})
    _, state, _ = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        100000.0,
        {},
        _prices("AAA", "BBB", SPY),
        {},
        {},
        cash=100000.0,
        allocation_context=ctx,
    )
    paper.save_state(tmp_path, state)
    state = paper.load_state(tmp_path)
    orders, final, _ = paper.plan(
        "2026-09-07",
        state,
        100000.0,
        {},
        _prices("AAA", "BBB", SPY),
        {},
        {},
        cash=100000.0,
        force_rebalance=True,
        allocation_context=_context(
            session="2026-09-07", desired={"AAA": 0.15, "BBB": 0.15}
        ),
    )
    assert not any(o.symbol == "AAA" for o in orders)
    assert "AAA" not in final.allocation_state["stable_desired"]


# Paper uses the same exclude-before-fallback convention as the simulator.
def test_missing_evidence_does_not_overcut_retained_name_after_exit():
    ctx = _context(
        policy="vol_trend",
        n=100,
        desired={"AAA": 0.15, "BBB": 0.15},
        excluded={"AAA"},
        regime_cap=0.2,
        index_eligible=False,
    )
    orders, state, _ = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        100000.0,
        {"AAA": 150, "BBB": 150},
        _prices("AAA", "BBB", SPY),
        {},
        {},
        cash=70000.0,
        allocation_context=ctx,
    )
    assert [(o.symbol, o.side, o.qty) for o in orders] == [("AAA", "sell", 150)]
    panel = SimpleNamespace(
        tickers=ctx.tickers,
        dates=ctx.dates,
        adj_close=ctx.prices,
        benchmark=SPY,
        index=ctx.tickers.index,
    )
    simulated = funded_execution.daily_decision(
        None,
        panel,
        None,
        ctx.t,
        policy=ctx.policy,
        index_eligible=False,
        benchmark_prices={
            "dates": ctx.dates,
            SPY: ctx.prices[:, 3],
            "QQQ": ctx.prices[:, 4],
        },
        desired={"BBB": 0.15},
        held={"AAA": 150, "BBB": 150},
        prices=_prices("AAA", "BBB", SPY),
        equity=100000.0,
        regime_cap=0.2,
        event_cap=1.0,
        excluded_symbols={"AAA"},
    )
    assert state.allocation_state["plan"]["target"]["stocks"] == pytest.approx(
        sum(simulated.decision.desired_weights.values())
    )
    assert state.allocation_state["plan"]["target"]["cash"] == simulated.decision.cash


# A stale external NAV cannot inflate company sizing beyond the account ledger.
def test_sizing_and_display_share_actual_marked_nav():
    orders, state, _ = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        200000.0,
        {},
        _prices("AAA", "BBB", SPY),
        {},
        {},
        cash=100000.0,
        allocation_context=_context(desired={"AAA": 0.15}, index_eligible=False),
    )
    assert [(o.symbol, o.qty) for o in orders] == [("AAA", 150)]
    assert state.allocation_state["plan"]["projected"]["stocks"] == pytest.approx(
        15000.0 / 99985.0
    )


# An externally reported positive NAV does not fund an actually empty account.
def test_zero_marked_nav_blocks_without_raising():
    orders, state, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        100000.0,
        {},
        _prices("AAA", "BBB", SPY),
        {},
        {},
        cash=0.0,
        allocation_context=_context(desired={"AAA": 0.15}),
    )
    assert orders == []
    assert what == "allocation-blocked"
    assert "marked account NAV" in state.allocation_state["plan"]["reason"]


# A decision calendar that ends exactly at the session being planned.
def _ending_dates(session: str, n: int = ROWS) -> np.ndarray:
    """Return `n` consecutive datetime64[D] dates ending at `session`."""
    end = np.datetime64(session, "D")
    start = end - np.timedelta64(n - 1, "D")
    return start + np.arange(n).astype("timedelta64[D]")


# A funded context on a constant $100 matrix, with its own defaults so each
# test names only what it needs.
def _context(
    session="2026-09-04",
    policy="vol",
    index_eligible=True,
    desired=None,
    regime_cap=1.0,
    event_cap=1.0,
    cost_bps=10.0,
    excluded=frozenset(),
    n=ROWS,
):
    """Return a funded AllocationContext whose decision date is `session`."""
    return AllocationContext(
        policy=policy,
        index_eligible=index_eligible,
        dates=_ending_dates(session, n),
        prices=np.full((n, 5), 100.0),
        tickers=["AAA", "BBB", "CCC", SPY, "QQQ"],
        t=n - 1,
        regime_cap=regime_cap,
        event_cap=event_cap,
        desired_stock_weights=desired,
        cost_bps=cost_bps,
        excluded_symbols=excluded,
    )


# The prices a plan's held and buy names carry at $100.
def _prices(*symbols: str) -> dict[str, float]:
    """Return a $100 close for each given symbol."""
    return {symbol: 100.0 for symbol in symbols}


# Write the pending rows the nightly would for a plan's orders, and leave them
# open on the broker.
def _write_pending(state, orders, session):
    """Return a copy of `state` with `orders` written down, still working."""
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
    working = [
        {
            "client_order_id": o.client_order_id,
            "status": "new",
            "filled_qty": 0,
            "filled_avg_price": 0.0,
        }
        for o in orders
    ]
    return paper.apply_settlements(state, paper.settle(state.pending, working))


# Settle every pending order as filled at $100.
def _fill_pending(state):
    """Return the state with all pending orders reported filled at $100."""
    filled = [
        {
            "client_order_id": row["client_order_id"],
            "status": "filled",
            "filled_qty": int(row["qty"]),
            "filled_avg_price": 100.0,
        }
        for row in state.pending
    ]
    return paper.apply_settlements(state, paper.settle(state.pending, filled))


# A pending-blocked day persists the persisted stable selection - here an
# explicitly empty (all-cash) stock composition - not the caller's daily
# selection, and the retry after settlement stays all-cash with no stock buy.
def test_pending_block_preserves_empty_selection_and_retry_has_no_resurrected_buy():
    ctx_empty = _context(session="2026-09-04", desired={})
    orders1, s1, _what1 = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={"AAA": 150.0},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=85_000.0,
        allocation_context=ctx_empty,
    )
    assert s1.allocation_state["stable_desired"] == {}
    s1 = _write_pending(s1, orders1, "2026-09-04")
    assert s1.pending

    # A plain day whose caller passes a full selection is blocked by the
    # outstanding orders, and the empty selection is persisted, not replaced.
    ctx_full = _context(session="2026-09-07", desired={"AAA": 0.15, "BBB": 0.15})
    orders2, s2, what2 = paper.plan(
        "2026-09-07",
        s1,
        equity=100_000.0,
        held={"AAA": 150.0},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=85_000.0,
        allocation_context=ctx_full,
    )
    assert what2 == "allocation-blocked"
    assert orders2 == []
    assert s2.allocation_state["stable_desired"] == {}
    assert "2026-09-07" not in s2.sessions_seen

    # Once the orders settle, the retry still decides against the empty
    # selection: the caller's stocks are never resurrected into a buy.
    s2 = _fill_pending(s2)
    assert not s2.pending
    orders3, s3, what3 = paper.plan(
        "2026-09-07",
        s2,
        equity=100_000.0,
        held={"SPY": 849.0},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=15.1,
        allocation_context=ctx_full,
    )
    assert what3 != "allocation-blocked"
    assert "2026-09-07" in s3.sessions_seen
    assert s3.allocation_state["stable_desired"] == {}
    assert not any(o.symbol in ("AAA", "BBB") for o in orders3)


# An excluded name is removed from the persisted stable composition even on a
# day blocked by unresolved orders, so a later daily plan cannot resurrect it.
def test_pending_block_persists_exclusion_of_a_name():
    ctx_full = _context(session="2026-09-04", desired={"AAA": 0.15, "BBB": 0.15})
    orders1, s1, _what1 = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx_full,
    )
    assert s1.allocation_state["stable_desired"] == {"AAA": 0.15, "BBB": 0.15}
    s1 = _write_pending(s1, orders1, "2026-09-04")
    assert s1.pending

    # The blocked day persists the selection with the excluded name already
    # dropped, matching what the retry would decide against.
    ctx_exit = _context(
        session="2026-09-07",
        desired={"AAA": 0.15, "BBB": 0.15},
        excluded=frozenset({"BBB"}),
    )
    _orders2, s2, what2 = paper.plan(
        "2026-09-07",
        s1,
        equity=100_000.0,
        held={},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx_exit,
    )
    assert what2 == "allocation-blocked"
    assert s2.allocation_state["stable_desired"] == {"AAA": 0.15}


# A missing cash value is reported as missing (a null fraction), never
# fabricated as a 0.0 that would make the account look consistently cashed out.
def test_missing_cash_is_reported_as_missing_not_zero():
    ctx = _context(desired={"AAA": 0.15})
    _orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={"AAA": 100.0},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=None,
        allocation_context=ctx,
    )
    assert what == "allocation-blocked"
    payload = new.allocation_state["plan"]
    assert payload["current"]["cash"] is None
    assert payload["projected"]["cash"] is None
    assert payload["rows"]["CASH"]["current_weight"] is None
    assert payload["rows"]["CASH"]["projected_weight"] is None


# The same honesty holds on the pending-blocked path, which passes whatever
# cash it was given rather than forcing a 0.0.
def test_pending_block_with_missing_cash_reports_cash_as_missing():
    ctx_full = _context(session="2026-09-04", desired={"AAA": 0.15})
    orders1, s1, _what1 = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=100_000.0,
        allocation_context=ctx_full,
    )
    s1 = _write_pending(s1, orders1, "2026-09-04")
    assert s1.pending
    ctx_next = _context(session="2026-09-07", desired={"AAA": 0.15})
    _orders2, s2, what2 = paper.plan(
        "2026-09-07",
        s1,
        equity=100_000.0,
        held={},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=None,
        allocation_context=ctx_next,
    )
    assert what2 == "allocation-blocked"
    payload = s2.allocation_state["plan"]
    assert payload["current"]["cash"] is None
    assert payload["projected"]["cash"] is None


# An explicitly excluded held name is a mandatory exit on an ordinary day even
# when the policy evidence is missing: the vol_trend decision is unavailable
# without a 200-price trend, but the excluded name is still sold and labeled.
def test_excluded_held_name_is_exited_when_policy_evidence_missing():
    # 120 rows give complete volatility but no 200-price trend, so the
    # vol_trend decision is unavailable and its fallback would otherwise
    # retain the actual holdings - including the excluded BBB.
    ctx = _context(
        session="2026-09-04",
        policy="vol_trend",
        desired={"AAA": 0.15, "BBB": 0.15},
        excluded=frozenset({"BBB"}),
        n=120,
    )
    orders, new, what = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={"AAA": 100.0, "BBB": 100.0},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=80_000.0,
        allocation_context=ctx,
    )
    assert what == "allocation-unavailable"
    exit_order = [o for o in orders if o.symbol == "BBB" and o.side == "sell"]
    assert exit_order
    assert "explicit company exit" in exit_order[0].reason
    # The removal is persisted; only AAA remains in the composition.
    assert new.allocation_state["stable_desired"] == {"AAA": 0.15}


# After the missing-evidence exit, the remaining name is still there to recover
# into once the evidence is complete, and the exited name never returns.
def test_risk_recovery_after_missing_evidence_exit():
    ctx_exit = _context(
        session="2026-09-04",
        policy="vol_trend",
        desired={"AAA": 0.15, "BBB": 0.15},
        excluded=frozenset({"BBB"}),
        n=120,
    )
    orders1, s1, _what1 = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        equity=100_000.0,
        held={"AAA": 100.0, "BBB": 100.0},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=80_000.0,
        allocation_context=ctx_exit,
    )
    assert any(o.symbol == "BBB" and o.side == "sell" for o in orders1)
    s1 = _fill_pending(s1)
    assert not s1.pending

    # A later day with complete evidence: the persisted composition still holds
    # AAA only, so BBB is never bought back and AAA is retained.
    ctx_full = _context(
        session="2026-09-07",
        policy="vol_trend",
        desired={"AAA": 0.15, "BBB": 0.15},
    )
    orders2, s2, what2 = paper.plan(
        "2026-09-07",
        s1,
        equity=100_000.0,
        held={"AAA": 100.0},
        prices=_prices("AAA", "BBB", SPY),
        targets={},
        grades={},
        cash=70_000.0,
        allocation_context=ctx_full,
    )
    assert what2 == "allocation"
    assert s2.allocation_state["stable_desired"] == {"AAA": 0.15}
    assert not any(o.symbol == "BBB" and o.side == "buy" for o in orders2)


# The account equity is a sizing input: a non-finite or non-positive value is
# a blocked day, never sized against and never raised out of the funded path.
def test_invalid_equity_blocks_instead_of_raising():
    ctx = _context(desired={"AAA": 0.15})
    for equity in (0.0, -100.0, float("inf"), float("nan")):
        orders, new, what = paper.plan(
            "2026-09-04",
            paper.PaperState(),
            equity=equity,
            held={"AAA": 100.0},
            prices=_prices("AAA", "BBB", SPY),
            targets={},
            grades={},
            cash=80_000.0,
            allocation_context=ctx,
        )
        assert what == "allocation-blocked"
        assert orders == []
        assert "equity" in new.allocation_state["plan"]["reason"]
