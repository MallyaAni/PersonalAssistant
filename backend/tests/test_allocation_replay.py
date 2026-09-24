"""Independent synthetic acceptance for the research-only allocation adapter.

These cases exercise real account fills and independently replay their journals.
They fit no model, reread no study, and confer no historical or live readiness.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import funded_execution, planner, simulate
from backend.market.allocation_replay import AllocationInstruction, replay
from backend.market.panel import Panel
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot


# Build actual Panels with independently specified raw and adjusted observations.
def _panel(rows=6, *, closes=None, opens=None, tickers=("AAA", "BBB", "SPY", "QQQ")):
    prices = (
        np.full((rows, len(tickers)), 100.0)
        if closes is None
        else np.array(closes, dtype=float)
    )
    opening = prices.copy() if opens is None else np.array(opens, dtype=float)
    dates = np.arange("2024-01-02", "2024-06-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)][:rows]
    return Panel(
        dates,
        tickers,
        opening,
        prices + 1,
        prices - 1,
        prices.copy(),
        prices.copy(),
        np.full_like(prices, 1000),
        {},
        "SPY",
    )


# Declare one dated instruction per decision session without reading any future prices.
def _instructions(
    panel, *, first=0, stock_scale=1.0, spy_weight=0.0, qqq_weight=0.0, base=None
):
    return [
        AllocationInstruction(
            session=str(panel.dates[t]),
            information_through=str(panel.dates[t]),
            evidence_id=f"synthetic-observation-{t}",
            stock_scale=stock_scale,
            spy_weight=spy_weight,
            qqq_weight=qqq_weight,
            stock_weights=({"AAA": 1.0} if base is None else base)
            if t == first and stock_scale > 0
            else None,
        )
        for t in range(first, len(panel.dates) - 1)
    ]


# Construct the immutable journal from the public adjusted-price convention.
def _journal(panel, cost_bps=0.0):
    with np.errstate(all="ignore"):
        opening = panel.open * np.where(
            panel.close > 0, panel.adj_close / panel.close, np.nan
        )
    return ResearchJournal(
        panel.dates,
        panel.tickers,
        opening,
        panel.adj_close,
        run_id="allocation-adapter-synthetic",
        account_id="independent-fixture",
        policy_id="stock-index-cash-adapter/1-research",
        cost_bps=cost_bps,
        provenance={"evidence_basis": "synthetic-accounting-test"},
    )


# Check every account state and cost against the separately implemented journal replay.
def _checked(panel, instructions, *, cost_bps=0.0, start_equity=100.0, first=0):
    journal = _journal(panel, cost_bps)
    result = replay(
        panel,
        instructions,
        first=first,
        cost_bps=cost_bps,
        start_equity=start_equity,
        journal=journal,
    )
    proof = verify_snapshot(journal.snapshot())
    assert proof["ok"], proof["errors"]
    assert proof["accounting_verified"]
    assert result["execution_policy"] == "stock-index-cash-adapter/1-research"
    assert result["adoption_eligible"] is False
    assert proof["adoption_eligible"] is False
    np.testing.assert_array_equal(result["dates"], panel.dates[first:])
    np.testing.assert_allclose(
        result["nav"], [mark["nav"] for mark in proof["marks"]], rtol=1e-12, atol=1e-12
    )
    np.testing.assert_allclose(
        result["cash"],
        [mark["cash"] for mark in proof["marks"]],
        rtol=1e-12,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        result["positions"],
        [mark["positions"] for mark in proof["marks"]],
        rtol=1e-12,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        result["cash_fraction"], result["cash"] / result["nav"], rtol=1e-12, atol=1e-12
    )
    assert result["fees"][0] == 0
    assert result["turnover"][0] == 0
    assert sum(result["fees"]) == pytest.approx(proof["total_fees"], abs=1e-12)
    turnover = np.diff([mark["traded"] for mark in proof["marks"]]) / result["nav"][:-1]
    np.testing.assert_allclose(result["turnover"][1:], turnover, rtol=1e-12, atol=1e-12)
    assert result["terminal_pending"] == proof["terminal"]["pending"]
    batches = [
        event for event in journal.snapshot()["events"] if event["type"] == "fill_batch"
    ]
    assert all(
        event["phase"] == "open" and event["recycle_sells"] is False
        for event in batches
    )
    assert len(result["decisions"]) == len(instructions)
    for decision, instruction, execution in zip(
        result["decisions"], instructions, panel.dates[first + 1 :], strict=True
    ):
        assert decision["session"] == instruction.session
        assert decision["information_through"] == instruction.information_through
        assert decision["evidence_id"] == instruction.evidence_id
        assert decision["earliest_execution_session"] == str(execution)
        assert isinstance(decision["planned"], bool)
        if decision["planned"]:
            assert isinstance(decision["submitted_units"], list)
        else:
            assert decision["submitted_units"] is None
        assert bool(decision["triggers"]) is decision["planned"]
        assert isinstance(decision["reason"], str)
        assert decision["reason"]
    return result, journal


# Cover cash and each investable sleeve without quietly treating QQQ as risk-only.
@pytest.mark.parametrize(
    ("stock", "spy", "qqq", "expected"),
    [
        (1.0, 0.0, 0.0, [1, 0, 0, 0]),
        (0.0, 1.0, 0.0, [0, 0, 1, 0]),
        (0.0, 0.0, 1.0, [0, 0, 0, 1]),
        (0.0, 0.0, 0.0, [0, 0, 0, 0]),
    ],
)
def test_each_investable_mode_and_cash_is_a_real_account(stock, spy, qqq, expected):
    panel = _panel(3)
    instructions = _instructions(
        panel, stock_scale=stock, spy_weight=spy, qqq_weight=qqq
    )
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["positions"][-1], expected)
    assert result["cash"][-1] == (100 if not any(expected) else 0)
    np.testing.assert_array_equal(result["nav"], [100, 100, 100])


# An underfilled stock basket leaves extra cash rather than being normalized.
def test_mixed_sleeves_preserve_unscaled_underfilled_stock_composition():
    panel = _panel(3)
    instructions = _instructions(
        panel,
        base={"AAA": 0.5, "BBB": 0.25},
        stock_scale=0.4,
        spy_weight=0.3,
        qqq_weight=0.1,
    )
    result, _ = _checked(panel, instructions)
    np.testing.assert_allclose(result["positions"][-1], [0.2, 0.1, 0.3, 0.1])
    assert result["cash"][-1] == pytest.approx(30)
    np.testing.assert_array_equal(
        result["decisions"][0]["stock_weights"], [0.5, 0.25, 0, 0]
    )
    np.testing.assert_allclose(
        result["decisions"][0]["desired_weights"], [0.2, 0.1, 0.3, 0.1]
    )


# Stock scale multiplies the unscaled basket rather than reserving that much equity.
def test_underallocated_stock_basket_can_fill_remaining_equity_with_an_index():
    panel = _panel(3)
    instructions = _instructions(
        panel, base={"AAA": 0.2}, stock_scale=1.0, spy_weight=0.8
    )
    result, _ = _checked(panel, instructions)
    np.testing.assert_allclose(result["positions"][-1], [0.2, 0.0, 0.8, 0.0])
    assert result["cash"][-1] == pytest.approx(0, abs=1e-12)
    assert result["decisions"][0]["stock_scale"] == 1.0


# A larger later basket cannot silently overallocate an unchanged index sleeve.
def test_composition_update_revalidates_actual_total_target_weight():
    panel = _panel(3)
    instructions = _instructions(
        panel, base={"AAA": 0.2}, stock_scale=1.0, spy_weight=0.8
    )
    instructions[1] = replace(instructions[1], stock_weights={"AAA": 0.5})
    with pytest.raises(ValueError, match="stock|weight|target|equity"):
        replay(panel, instructions)


# Explicit exits sell holdings below both legacy suppression thresholds.
@pytest.mark.parametrize("weight", [0.001, 1e-10])
def test_zero_exposure_completely_exits_tiny_positions(weight):
    panel = _panel(4)
    instructions = _instructions(panel, base={"AAA": weight})
    instructions[1:] = [replace(row, stock_scale=0.0) for row in instructions[1:]]
    result, journal = _checked(panel, instructions, start_equity=1.0, cost_bps=10.0)
    assert result["positions"][1, 0] > 0
    np.testing.assert_array_equal(result["positions"][2:], np.zeros((2, 4)))
    assert result["terminal_pending"] == {}
    sells = [
        event
        for event in journal.snapshot()["events"]
        if event["type"] == "fill_batch" and event["gross_sells"] > 0
    ]
    assert len(sells) == 1
    assert sells[0]["positions_after"][0] == 0.0


# A base update while in cash restores the latest selection, not old holdings.
def test_cash_restoration_uses_latest_unscaled_composition():
    panel = _panel(6)
    instructions = _instructions(panel)
    instructions[1] = replace(instructions[1], stock_scale=0.0)
    instructions[2] = replace(
        instructions[2], stock_scale=0.0, stock_weights={"BBB": 1.0}
    )
    instructions[3] = replace(instructions[3], stock_scale=0.0)
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["positions"][1], [1, 0, 0, 0])
    np.testing.assert_array_equal(result["positions"][2:5], np.zeros((3, 4)))
    np.testing.assert_array_equal(result["positions"][5], [0, 1, 0, 0])
    np.testing.assert_array_equal(
        result["decisions"][-1]["stock_weights"], [0, 1, 0, 0]
    )
    assert result["decisions"][-1]["stock_composition_session"] == str(panel.dates[2])
    assert np.all(np.isfinite(result["nav"]))


# A stock basket may be declared during the initial cash period for later entry.
def test_initial_cash_can_preserve_an_explicit_stock_basket_for_later_entry():
    panel = _panel(4)
    instructions = _instructions(panel, stock_scale=0.0)
    instructions[0] = replace(instructions[0], stock_weights={"BBB": 1.0})
    instructions[2] = replace(instructions[2], stock_scale=1.0)
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["positions"][:3], np.zeros((3, 4)))
    np.testing.assert_array_equal(result["positions"][3], [0, 1, 0, 0])
    assert result["decisions"][-1]["stock_composition_session"] == str(panel.dates[0])


# An explicit empty update is a liquidation instruction; None is only preservation.
def test_empty_stock_update_is_not_confused_with_absent_update():
    panel = _panel(5)
    instructions = _instructions(panel)
    instructions[1] = replace(instructions[1], stock_weights={})
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["positions"][2:], np.zeros((3, 4)))
    assert result["cash"][-1] == 100
    assert result["decisions"][1]["planned"]
    assert not result["decisions"][2]["planned"]
    np.testing.assert_array_equal(
        result["decisions"][-1]["stock_weights"], [0, 0, 0, 0]
    )


# Repeated absolute partial exposure never compounds reductions.
def test_unchanged_half_exposure_does_not_repeatedly_halve_the_account():
    panel = _panel(5)
    instructions = _instructions(panel, stock_scale=0.5)
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["positions"][1:, 0], [0.5] * 4)
    np.testing.assert_array_equal(result["cash"][1:], [50] * 4)
    assert [row["planned"] for row in result["decisions"]] == [
        True,
        False,
        False,
        False,
    ]


# Price drift is not itself authorization to rebalance an unchanged instruction.
@pytest.mark.parametrize("explicit_rebalance", [False, True])
def test_only_explicit_rebalance_trades_unrequested_weight_drift(explicit_rebalance):
    closes = np.full((4, 4), 100.0)
    closes[1:, 0] = 200
    opens = closes.copy()
    opens[1, 0] = 100
    panel = _panel(4, closes=closes, opens=opens)
    instructions = _instructions(panel, stock_scale=0.5)
    instructions[1] = replace(instructions[1], rebalance=explicit_rebalance)
    result, _ = _checked(panel, instructions)
    assert result["positions"][-1, 0] == (0.375 if explicit_rebalance else 0.5)
    assert result["cash"][-1] == (75 if explicit_rebalance else 50)
    assert result["decisions"][1]["planned"] is explicit_rebalance
    assert not result["decisions"][2]["planned"]


# Close-time share counts must not shrink retroactively when the next open gaps.
def test_gap_cost_and_cash_budget_are_applied_at_execution_only():
    closes = np.full((3, 4), 100.0)
    closes[1:, 0] = 200
    panel = _panel(3, closes=closes)
    instructions = _instructions(panel)
    result, journal = _checked(panel, instructions, cost_bps=100.0)
    assert result["decisions"][0]["submitted_units"][0] == 1.0
    assert result["positions"][1, 0] == pytest.approx(100 / 202)
    assert result["nav"][1] == pytest.approx(100 / 1.01)
    assert result["fees"][1] == pytest.approx(100 / 101)
    assert result["turnover"][1] == pytest.approx(1 / 1.01)
    assert result["cash"][1] == pytest.approx(0, abs=1e-12)
    assert result["terminal_pending"] == {}
    assert not result["decisions"][1]["planned"]
    fills = [
        event for event in journal.snapshot()["events"] if event["type"] == "fill_batch"
    ]
    assert fills[0]["scale"] == pytest.approx(100 / 202)


# Multiple submitted buys share one funding scale while preserving relative quantities.
def test_competing_stock_and_index_buys_share_cash_proportionally():
    panel = _panel(3)
    panel.open[1] = [200, 100, 100, 300]
    instructions = _instructions(
        panel,
        base={"AAA": 0.5, "BBB": 0.5},
        stock_scale=0.5,
        spy_weight=0.25,
        qqq_weight=0.25,
    )
    result, journal = _checked(panel, instructions)
    np.testing.assert_allclose(result["decisions"][0]["submitted_units"], [0.25] * 4)
    np.testing.assert_allclose(result["positions"][1], [1 / 7] * 4)
    assert result["cash"][1] == pytest.approx(0, abs=1e-12)
    fills = [
        event for event in journal.snapshot()["events"] if event["type"] == "fill_batch"
    ]
    assert fills[0]["scale"] == pytest.approx(4 / 7)


# Rotations wait for credited sale cash before replanning their unfunded buys.
def test_stock_spy_qqq_cash_transitions_use_delayed_sale_funding():
    panel = _panel(7)
    instructions = _instructions(panel)
    instructions[1:3] = [
        replace(row, stock_scale=0.0, spy_weight=1.0) for row in instructions[1:3]
    ]
    instructions[3:5] = [
        replace(row, stock_scale=0.0, qqq_weight=1.0) for row in instructions[3:5]
    ]
    instructions[5] = replace(instructions[5], stock_scale=0.0)
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["cash"], [100, 0, 100, 0, 100, 0, 100])
    np.testing.assert_array_equal(
        result["positions"][[1, 3, 5]], [[1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    )
    np.testing.assert_array_equal(result["positions"][[2, 4, 6]], np.zeros((3, 4)))
    np.testing.assert_array_equal(result["turnover"], [0, 1, 1, 1, 1, 1, 1])
    assert all(row["planned"] for row in result["decisions"])
    assert result["terminal_pending"] == {}


# Charge each executed leg once while delayed sale funding carries net cash forward.
def test_rotation_fees_are_charged_on_actual_fills_not_unfunded_requests():
    panel = _panel(4)
    instructions = _instructions(panel)
    instructions[1:] = [
        replace(row, stock_scale=0.0, spy_weight=1.0) for row in instructions[1:]
    ]
    result, _ = _checked(panel, instructions, start_equity=101, cost_bps=100)
    np.testing.assert_allclose(result["cash"], [101, 0, 99, 0], atol=1e-12)
    np.testing.assert_allclose(result["fees"], [0, 1, 1, 99 / 101], atol=1e-12)
    assert result["positions"][-1, 2] == pytest.approx(99 / 101)
    assert result["nav"][-1] == pytest.approx(101 - sum(result["fees"]))


# Funding follow-ups resize from the new close rather than reuse old share counts.
def test_funding_retry_replans_after_prices_change():
    panel = _panel(4)
    panel.close[2:, 2] = 200
    panel.adj_close[2:, 2] = 200
    panel.open[2:, 2] = 200
    instructions = _instructions(panel)
    instructions[1:] = [
        replace(row, stock_scale=0.0, spy_weight=1.0) for row in instructions[1:]
    ]
    result, _ = _checked(panel, instructions)
    assert result["decisions"][1]["submitted_units"][2] == 1
    assert result["decisions"][2]["submitted_units"][2] == 0.5
    assert result["positions"][-1, 2] == 0.5


# A changed allocation supersedes the unfilled prior sleeve rather than reviving it.
def test_new_instruction_supersedes_rotation_retry():
    panel = _panel(4)
    instructions = _instructions(panel)
    instructions[1] = replace(instructions[1], stock_scale=0.0, spy_weight=1.0)
    instructions[2] = replace(instructions[2], stock_scale=0.0, qqq_weight=1.0)
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["positions"][-1], [0, 0, 0, 1])
    assert np.all(result["positions"][:, 2] == 0)
    assert result["terminal_pending"] == {}


# A fresh cash instruction cancels the prior rotation's need to buy anything.
def test_cash_instruction_supersedes_unfunded_index_retry():
    panel = _panel(4)
    instructions = _instructions(panel)
    instructions[1] = replace(instructions[1], stock_scale=0.0, spy_weight=1.0)
    instructions[2] = replace(instructions[2], stock_scale=0.0)
    result, _ = _checked(panel, instructions)
    np.testing.assert_array_equal(result["positions"][2:], np.zeros((2, 4)))
    np.testing.assert_array_equal(result["cash"][2:], [100, 100])
    assert result["terminal_pending"] == {}


# A terminal rotation retains cash and a retry marker without an invented fill.
def test_terminal_rotation_retains_pending_retry_and_actual_cash():
    panel = _panel(3)
    instructions = _instructions(panel)
    instructions[1] = replace(instructions[1], stock_scale=0.0, spy_weight=1.0)
    result, journal = _checked(panel, instructions)
    assert result["terminal_pending"]["retry"] is True
    assert result["terminal_pending"].get("submitted_units") is None
    np.testing.assert_array_equal(result["positions"][-1], np.zeros(4))
    assert result["cash"][-1] == 100
    assert (
        len(
            [
                event
                for event in journal.snapshot()["events"]
                if event["type"] == "fill_batch"
            ]
        )
        == 2
    )


# The journal must preserve held terminal assets without an artificial closing fee.
def test_terminal_held_positions_are_not_liquidated():
    panel = _panel(3)
    result, _ = _checked(panel, _instructions(panel), cost_bps=10.0)
    assert result["positions"][-1, 0] > 0
    assert result["fees"][-1] == 0
    assert result["turnover"][-1] == 0
    assert result["terminal_pending"] == {}


# Adjusted synthetic units remain stable across a raw split without a second credit.
def test_adjusted_prices_do_not_double_credit_raw_splits():
    prices = np.full((4, 4), 100.0)
    prices[2:, 0] = 50
    panel = _panel(4, closes=prices)
    panel.adj_close[:, 0] = 50
    result, _ = _checked(panel, _instructions(panel))
    np.testing.assert_array_equal(result["positions"][1:, 0], [2, 2, 2])
    np.testing.assert_array_equal(result["nav"], [100, 100, 100, 100])


# Empty portfolios need no stock definition and no observations for unheld assets.
def test_all_cash_allows_missing_unused_prices():
    panel = _panel(4)
    panel.open[:] = np.nan
    panel.close[:] = np.nan
    panel.adj_close[:] = np.nan
    result, _ = _checked(panel, _instructions(panel, stock_scale=0.0))
    np.testing.assert_array_equal(result["nav"], [100] * 4)
    np.testing.assert_array_equal(result["cash"], [100] * 4)
    np.testing.assert_array_equal(result["positions"], np.zeros((4, 4)))


# An unused opening print cannot invalidate a held position's otherwise complete close.
def test_missing_open_on_no_order_hold_day_is_not_a_fictitious_trade():
    panel = _panel(4)
    panel.open[2, 0] = np.nan
    result, _ = _checked(panel, _instructions(panel))
    np.testing.assert_array_equal(result["positions"][1:, 0], [1, 1, 1])
    assert not result["decisions"][1]["planned"]


# Missing required decision, execution, or held marks fail without a verified account.
@pytest.mark.parametrize(
    "boundary", ["decision_close", "execution_open", "held_close", "exit_open"]
)
def test_missing_required_price_fails_closed(boundary):
    panel = _panel(4)
    instructions = _instructions(panel)
    if boundary == "decision_close":
        panel.adj_close[0, 0] = np.nan
    elif boundary == "execution_open":
        panel.open[1, 0] = np.nan
    elif boundary == "held_close":
        panel.adj_close[2, 0] = np.nan
    else:
        instructions[1] = replace(instructions[1], stock_scale=0.0)
        panel.open[2, 0] = np.nan
    journal = _journal(panel)
    with pytest.raises(ValueError, match="price|valuation"):
        replay(panel, instructions, cost_bps=0.0, start_equity=100.0, journal=journal)
    assert not verify_snapshot(journal.snapshot())["ok"]


# Require the exact source grid without inferring omitted or shifted instructions.
@pytest.mark.parametrize(
    "malformation", ["missing", "extra", "reversed", "shifted", "duplicate"]
)
def test_instruction_calendar_must_exactly_match_decision_sessions(malformation):
    panel = _panel(4)
    instructions = _instructions(panel)
    if malformation == "missing":
        instructions.pop()
    elif malformation == "extra":
        instructions.append(replace(instructions[-1], session=str(panel.dates[-1])))
    elif malformation == "reversed":
        instructions.reverse()
    elif malformation == "shifted":
        instructions[0] = replace(instructions[0], session="2024-01-01")
    else:
        instructions[1] = replace(instructions[1], session=instructions[0].session)
    with pytest.raises(ValueError, match="instruction|calendar"):
        replay(panel, instructions)


# Refuse future or malformed availability declarations.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("information_through", "2024-01-03"),
        ("information_through", "2024-01-02T16:00:00"),
        ("information_through", "not-a-date"),
        ("evidence_id", ""),
        ("evidence_id", "   "),
    ],
)
def test_invalid_information_or_evidence_declarations_fail(field, value):
    panel = _panel(3)
    instructions = _instructions(panel)
    instructions[0] = replace(instructions[0], **{field: value})
    with pytest.raises(ValueError, match="information|evidence"):
        replay(panel, instructions)


# Preserve an earlier declared observation separately from its decision date.
def test_prior_information_date_is_preserved():
    panel = _panel(3)
    instructions = _instructions(panel)
    instructions[0] = replace(instructions[0], information_through="2024-01-01")
    result, _ = _checked(panel, instructions)
    assert result["decisions"][0]["information_through"] == "2024-01-01"


# Invalid sleeve and stock budgets are errors, not silently normalized portfolios.
@pytest.mark.parametrize(
    "changes",
    [
        {"stock_scale": -0.1},
        {"stock_scale": 1.1, "stock_weights": {}},
        {"spy_weight": 1.1, "stock_scale": 0.0},
        {"qqq_weight": 1.1, "stock_scale": 0.0},
        {"spy_weight": -0.1},
        {"qqq_weight": -0.1},
        {"stock_scale": float("nan")},
        {"spy_weight": float("inf")},
        {"stock_scale": 0.5, "spy_weight": 0.4, "qqq_weight": 0.2},
        {"stock_weights": {"AAA": -0.1}},
        {"stock_weights": {"AAA": float("nan")}},
        {"stock_weights": {"AAA": 0.7, "BBB": 0.4}},
        {"stock_weights": {"UNKNOWN": 1.0}},
        {"stock_weights": {"SPY": 1.0}},
        {"stock_weights": {"QQQ": 1.0}},
        {"stock_scale": 1.0, "spy_weight": 0.5},
    ],
)
def test_invalid_portfolio_instructions_fail(changes):
    panel = _panel(3)
    instructions = _instructions(panel)
    instructions[0] = replace(instructions[0], **changes)
    with pytest.raises(ValueError, match="stock|weight|scale|target|sleeve"):
        replay(panel, instructions)


# Stock risk cannot appear before an explicit stock composition exists.
@pytest.mark.parametrize("initial_stock", [False, True])
def test_stock_sleeve_requires_an_established_composition(initial_stock):
    panel = _panel(3)
    instructions = _instructions(panel, stock_scale=0.0)
    index = 0 if initial_stock else 1
    instructions[index] = replace(instructions[index], stock_scale=1.0)
    with pytest.raises(ValueError, match="stock.*composition"):
        replay(panel, instructions)


# An explicitly empty first stock composition is a valid cash request, not missing data.
def test_explicit_empty_initial_composition_is_valid():
    panel = _panel(3)
    result, _ = _checked(panel, _instructions(panel, base={}))
    np.testing.assert_array_equal(result["cash"], [100, 100, 100])


# Both named index assets must exist even when the current instruction holds only cash.
@pytest.mark.parametrize("missing", ["SPY", "QQQ"])
def test_both_index_columns_are_required(missing):
    panel = _panel(
        3,
        tickers=tuple(
            ticker for ticker in ("AAA", "BBB", "SPY", "QQQ") if ticker != missing
        ),
    )
    with pytest.raises(ValueError, match="SPY.*QQQ"):
        replay(panel, _instructions(panel, stock_scale=0.0))


# Account start, cost, and source offset must be finite and executable.
@pytest.mark.parametrize(
    "options",
    [
        {"first": -1},
        {"first": 2},
        {"start_equity": 0},
        {"start_equity": -1},
        {"start_equity": float("nan")},
        {"cost_bps": -1},
        {"cost_bps": 10000},
        {"cost_bps": float("inf")},
    ],
)
def test_invalid_account_parameters_fail(options):
    panel = _panel(3)
    with pytest.raises(ValueError, match="first|start_equity|cost_bps"):
        replay(panel, _instructions(panel), **options)


# Warmup observations precede the opening account without invented earlier holdings.
def test_later_account_start_uses_exact_instruction_subgrid():
    panel = _panel(5)
    instructions = _instructions(panel, first=2)
    result, journal = _checked(panel, instructions, first=2, start_equity=250)
    np.testing.assert_array_equal(result["dates"], panel.dates[2:])
    assert result["nav"][0] == 250
    assert result["cash"][0] == 250
    assert journal.snapshot()["events"][0]["session_index"] == 2


# Enabling the recorder must not change any returned arithmetic or decision content.
def test_optional_journal_does_not_change_results_or_mutate_inputs():
    panel = _panel(5)
    base = {"AAA": 0.6, "BBB": 0.4}
    instructions = _instructions(panel, base=base)
    instructions[1] = replace(instructions[1], stock_scale=0.0)
    original = copy.deepcopy(instructions)
    source = {
        name: getattr(panel, name).copy()
        for name in ("dates", "open", "close", "adj_close")
    }
    plain = replay(panel, instructions, cost_bps=10, start_equity=100)
    observed, _ = _checked(panel, instructions, cost_bps=10, start_equity=100)
    for name in (
        "dates",
        "nav",
        "cash",
        "cash_fraction",
        "positions",
        "fees",
        "turnover",
    ):
        np.testing.assert_array_equal(plain[name], observed[name])
    assert plain["decisions"] == observed["decisions"]
    assert plain["instruction_path"] == observed["instruction_path"]
    assert instructions == original
    assert base == {"AAA": 0.6, "BBB": 0.4}
    for name, values in source.items():
        np.testing.assert_array_equal(getattr(panel, name), values)


# Retain exact supplied instructions and their evidence in a hashed artifact.
def test_instruction_path_has_canonical_hash_and_preserves_optional_updates():
    panel = _panel(4)
    instructions = _instructions(panel, base={"AAA": 0.4})
    instructions[1] = replace(instructions[1], stock_weights={})
    result, journal = _checked(panel, instructions)
    path = result["instruction_path"]
    payload = path["payload"]
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    assert path["sha256"] == hashlib.sha256(encoded).hexdigest()
    assert payload["schema"] == "allocation-instructions/1"
    assert payload["sessions"] == [str(day) for day in panel.dates]
    assert payload["symbols"] == list(panel.tickers)
    assert payload["first"] == 0
    assert [row["stock_weights"] for row in payload["instructions"]] == [
        {"AAA": 0.4},
        {},
        None,
    ]
    # Metadata must retain the full declared row and path identity, not just a label.
    decisions = [
        event for event in journal.snapshot()["events"] if event["type"] == "decision"
    ]
    for event, row in zip(decisions, payload["instructions"], strict=True):
        assert row in event["metadata"].values()
        assert path["sha256"] in event["metadata"].values()


# Later input changes alter their hash but cannot change earlier decisions or NAV.
def test_future_instruction_and_price_changes_leave_prefix_unchanged():
    panel = _panel(6)
    instructions = _instructions(panel, stock_scale=0.5)
    original, _ = _checked(panel, instructions)
    changed = replace(
        panel,
        open=panel.open.copy(),
        close=panel.close.copy(),
        adj_close=panel.adj_close.copy(),
    )
    changed.open[4:, :] *= 7
    changed.close[4:, :] *= 7
    changed.adj_close[4:, :] *= 7
    later = list(instructions)
    later[3] = replace(later[3], stock_scale=0.0, qqq_weight=1.0)
    observed, _ = _checked(changed, later)
    assert (
        original["instruction_path"]["sha256"] != observed["instruction_path"]["sha256"]
    )
    for name in ("nav", "cash", "positions", "fees", "turnover"):
        np.testing.assert_array_equal(original[name][:4], observed[name][:4])
    for left, right in zip(
        original["decisions"][:3], observed["decisions"][:3], strict=True
    ):
        for key in (
            "session",
            "earliest_execution_session",
            "information_through",
            "evidence_id",
            "stock_scale",
            "spy_weight",
            "qqq_weight",
            "stock_weights",
            "desired_weights",
            "submitted_units",
            "planned",
            "triggers",
        ):
            assert left[key] == right[key]


# Fail if the adapter reaches a legacy planner or integrated policy loop.
def _legacy_call_forbidden(*args, **kwargs):
    raise AssertionError("research adapter used an incumbent planning/execution path")


# The adapter must remain separate from incumbent sizing, allocation, and trading loops.
def test_adapter_does_not_route_through_incumbent_planners(monkeypatch):
    monkeypatch.setattr(simulate, "run", _legacy_call_forbidden)
    monkeypatch.setattr(simulate._Book, "plan", _legacy_call_forbidden)
    monkeypatch.setattr(simulate._Book, "finish", _legacy_call_forbidden)
    monkeypatch.setattr(planner, "plan", _legacy_call_forbidden)
    monkeypatch.setattr(funded_execution, "plan_funded", _legacy_call_forbidden)
    panel = _panel(4)
    instructions = _instructions(panel, base={"AAA": 1e-10})
    instructions[1:] = [replace(row, stock_scale=0.0) for row in instructions[1:]]
    result, _ = _checked(panel, instructions, start_equity=1)
    np.testing.assert_array_equal(result["positions"][-1], np.zeros(4))
